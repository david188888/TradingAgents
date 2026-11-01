"""Consumer-neutral evidence_v1 execution and durable recovery."""

from __future__ import annotations

import json
import math
import time
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace

import requests

from tradingagents.dataflows.budgeted_transport import BudgetedSession
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.search_sources import SearchEvidenceSources
from tradingagents.dataflows.tushare_price_history import PriceHistoryQualificationError
from tradingagents.execution.budget import BudgetBucket, BudgetConflictError, BudgetExhausted
from tradingagents.execution.config_identity import (
    SemanticConfigError,
    native_effective_config,
)
from tradingagents.execution.insight_model import InsightModelCaller
from tradingagents.execution.models import (
    AnalysisCancelled,
    AnalysisRequest,
    AnalysisResult,
    CancellationToken,
)
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.execution.search_budget import SEARCH_BUDGET_POLICY
from tradingagents.llm_clients.chatgpt_policy import (
    CHATGPT_REQUEST_POLICY,
    validate_reasoning_effort,
)
from tradingagents.llm_clients.task_effort import task_effort_overrides
from tradingagents.observability.events import RunEventDraft
from tradingagents.observability.roles import (
    role_instance_id,
    roles_for_profile,
)
from tradingagents.research.native_versions import (
    COMPANY_RESEARCH_POLICY,
    INSIGHT_POLICY,
    INSIGHT_WORKFLOW_VERSION,
    REPORT_DELIVERY_POLICY,
    SEARCH_RESEARCH_POLICY,
    STRUCTURED_FINANCIAL_POLICY,
)
from tradingagents.runtime.research_checkpoint import (
    ResearchCheckpointConflict,
    ResearchJournal,
    load_checkpoint,
)

WORKFLOW_VERSION = INSIGHT_WORKFLOW_VERSION
# New Web studies persist this value; saved requests without it keep the 300s identity.
NEW_STUDY_TIMEOUT_SECONDS = 900


def native_identity(request):
    """Freeze the current source, model, transport and Insight policies."""
    from tradingagents.llm_clients.structured_output import STRUCTURED_OUTPUT_POLICY
    from tradingagents.research.native_versions import FINANCIAL_DETAIL_POLICY

    subscription = request.effective_config.get("llm_provider") == "chatgpt"
    if subscription:
        validate_reasoning_effort(request.effective_config.get("openai_reasoning_effort"))
    return {
        **request.profile_identity(),
        "workflow_version": WORKFLOW_VERSION,
        "ticker": request.ticker,
        "mode": request.mode,
        "cutoff": request.analysis_date,
        "config": native_effective_config(request.effective_config, WORKFLOW_VERSION),
        **({"chatgpt_request_policy": CHATGPT_REQUEST_POLICY} if subscription else {}),
        "structured_output_policy": STRUCTURED_OUTPUT_POLICY,
        "search_research_policy": {**deepcopy(SEARCH_RESEARCH_POLICY),
            "enabled": request.effective_config.get("evidence_search_enabled", True)},
        "search_budget_policy": deepcopy(SEARCH_BUDGET_POLICY),
        "active_timeout_seconds": request.effective_config.get("evidence_timeout_seconds", 300),
        "structured_financial_policy": STRUCTURED_FINANCIAL_POLICY,
        "financial_detail_policy": FINANCIAL_DETAIL_POLICY,
        "company_research_policy": COMPANY_RESEARCH_POLICY,
        "report_delivery_policy": REPORT_DELIVERY_POLICY,
        "insight_policy": INSIGHT_POLICY,
        "insight_budget_policy": {"structured_repair": 8, "basic_model_attempts": 20, "model_attempts": 29},
        "insight_context_policy": "compact-saved-evidence-v1",
    }


@dataclass(frozen=True)
class NativeResumeGuard:
    require_existing: bool = True


def validate_native_resume(store, run_id, request):
    state = load_checkpoint(store, run_id)
    if state is None or state["identity"].get("workflow_version") != WORKFLOW_VERSION:
        raise ResearchCheckpointConflict("unsupported or missing research checkpoint")
    if state["identity"] != native_identity(request):
        raise ResearchCheckpointConflict("research checkpoint incompatible")
    if "native_seed" in state:
        seed = load_native_seed_from_state(state)
        if (seed.run_id, seed.ticker, seed.mode, seed.analysis_date.isoformat()) != (
                run_id, request.ticker, request.mode, request.analysis_date):
            raise ResearchCheckpointConflict("research seed identity mismatch")
    if "native_publication_candidate" in state:
        from tradingagents.research.insight_report import parse_insight_report
        record = parse_insight_report(state["native_publication_candidate"])
        if ((record.run_id, record.ticker, record.analysis_date.isoformat()) != (
                run_id, request.ticker, request.analysis_date)
                or state.get("insight.report") != state["native_publication_candidate"]):
            raise ResearchCheckpointConflict("insight checkpoint identity mismatch")
    if state.get("publication_authorized") and "native_publication_candidate" not in state:
        raise ResearchCheckpointConflict("research authorization has no candidate")


def load_native_seed_from_state(state):
    from tradingagents.agents.schemas._evidence_record import EvidenceRecord
    seed = EvidenceRecord.model_validate(state["native_seed"])
    if seed.construction != "native":
        raise ResearchCheckpointConflict("research seed contains retired model output")
    return seed


def load_native_seed(ledger):
    return load_native_seed_from_state(ledger.journal.state) if "native_seed" in ledger.journal.state else None


class NativeRunner:
    def __init__(
        self, observer, *, sources_factory=None, caller_factory=None, chatgpt_auth=None, search_session_factory=requests.Session
    ):
        self.chatgpt_auth = chatgpt_auth
        self.search_session_factory = search_session_factory
        self.observer, self.sources_factory, self.caller_factory = (
            observer,
            sources_factory,
            caller_factory or InsightModelCaller,
        )
        if chatgpt_auth is not None and caller_factory is None:
            from functools import partial
            self.caller_factory = partial(InsightModelCaller, chatgpt_auth=chatgpt_auth)

    def _stage(self, journal, key, status):
        with journal.lock:
            events = self.observer.store.read_events(self.observer.run_id)
            actor = "native." + key
            previous = next(
                (
                    e.payload["new_status"]
                    for e in reversed(events)
                    if e.type == "role.status_changed" and e.actor_id == actor
                ),
                "pending",
            )
            if previous == status:
                return
            role = next(item for item in roles_for_profile("evidence_v1", workflow_version=journal.state["identity"].get("workflow_version"), focus_requested=True) if item.actor_id == actor)
            journal.put("native_stages", {**journal.state.get("native_stages", {}), key: status})
            self.observer.emit(
                RunEventDraft(
                    self.observer.run_id,
                    "role.status_changed",
                    {
                        "role_instance_id": role_instance_id(self.observer.run_id, actor),
                        "previous_status": previous,
                        "new_status": status,
                        "reason": "native_durable_frontier",
                    },
                    actor_id=actor,
                    node_id=role.node_id,
                    team_id=role.team_id,
                    status=status,
                    parent_event_id=journal.last_event.event_id,
                )
            )

    def run(self, request, **kwargs):
        with ExitStack() as resources:
            return self._run(request, _resources=resources, **kwargs)

    def _run(
        self,
        request: AnalysisRequest,
        *,
        cancellation_token=None,
        checkpoint_guard=None,
        publication_authorizer=None,
        _resources,
        **_kwargs,
    ):
        if request.research_profile != "evidence_v1" or request.evidence_policy is None:
            raise ValueError("unsupported native request")
        request = replace(request, effective_config=deepcopy(dict(request.effective_config)))
        try:
            task_effort_overrides(request.effective_config)
            timeout = float(request.effective_config.get("evidence_timeout_seconds", 300))
        except (ValueError, TypeError, OverflowError) as exc:
            raise SemanticConfigError("invalid native execution configuration") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise SemanticConfigError("native timeout must be positive")
        deadline = time.monotonic() + timeout
        token = cancellation_token or CancellationToken()

        def active():
            token.raise_if_cancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError("native active deadline exceeded")

        def cancelled():
            return token.is_cancelled or time.monotonic() >= deadline

        run_id = self.observer.run_id
        resume = isinstance(checkpoint_guard, NativeResumeGuard)
        if resume:
            validate_native_resume(self.observer.store, run_id, request)
        journal = ResearchJournal(self.observer, native_identity(request), require_existing=resume)
        coordinator = None
        from tradingagents.execution.search_budget import SearchBudget
        from tradingagents.execution.search_coordinator import SearchCoordinator
        search_session = self.search_session_factory()
        if callable(getattr(search_session, 'close', None)):
            _resources.callback(search_session.close)
        search_budget = SearchBudget(journal.ledger, ensure_active=active,
            run_remaining=lambda: deadline-time.monotonic())
        coordinator = SearchCoordinator(search_session, search_budget, journal)
        seed = load_native_seed(journal.ledger)
        if seed is None:
            active()
            self._stage(journal, "evidence", "running")

            def fetch(key, operation):
                active()
                logical = "native.data." + key
                saved = journal.ledger.cached_result(logical)
                if saved is not None:
                    if "error" in saved:
                        if saved["error"] in {"ResearchCheckpointConflict", "BudgetConflictError", "BudgetExhausted", "AnalysisCancelled", "TimeoutError"}:
                            raise ResearchCheckpointConflict("saved source control failure cannot become provider fallback")
                        if saved.get("source_error_code"):
                            raise NativeSourceUnavailable(saved["source_error_code"])
                        raise ValueError(saved["error"])
                    # Exact JSON text survives RFC8785 numeric normalization.
                    return json.loads(saved["value_json"])
                if any(
                    item.logical_call_id == logical and item.dispatched_at is not None
                    for item in journal.ledger.records()
                ):
                    raise ValueError("native_source_response_unknown")
                grant = journal.ledger.reserve_or_raise(
                    BudgetBucket.DATA_CAPABILITY_CALLS,
                    stage="native.evidence",
                    logical_call_id=logical,
                )
                journal.ledger.mark_dispatched(grant)
                try:
                    value = operation()
                    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
                except Exception as exc:
                    if journal.failed or isinstance(exc, (
                        ResearchCheckpointConflict, BudgetConflictError, BudgetExhausted,
                        AnalysisCancelled, TimeoutError,
                    )):
                        raise
                    error = {"error": type(exc).__name__}
                    if isinstance(exc, (NativeSourceUnavailable, PriceHistoryQualificationError)):
                        error["source_error_code"] = exc.code
                    elif isinstance(exc, (requests.RequestException, ChinaDataUnavailableError)):
                        error["source_error_code"] = "source_transport_unavailable"
                    journal.ledger.record_result(logical, error)
                    journal.ledger.settle(grant, ok=False, usage_available=False)
                    raise
                journal.ledger.record_result(logical, {"value_json": encoded})
                journal.ledger.settle(grant, ok=True, usage_available=False)
                active()
                return value

            source_fields = {**vars(request), "collection_policy": request.evidence_policy.collector_policy()}
            source_fields.pop("research_question", None)
            source_fields["effective_config"] = {
                key: value for key, value in request.effective_config.items()
                if key != "research_question"
            }
            source_fields["company_research_policy"] = journal.state["identity"].get("company_research_policy")
            source_fields["report_delivery_policy"] = journal.state["identity"].get("report_delivery_policy")
            source_fields["financial_detail_policy"] = journal.state["identity"].get("financial_detail_policy")
            source_request = SimpleNamespace(**source_fields)
            with BudgetedSession(
                journal.ledger, active, lambda: deadline - time.monotonic()
            ) as session:
                factory = self.sources_factory or SearchEvidenceSources
                collector = factory(source_request, run_id, session, fetch, coordinator)
                seed, context = collector.collect()
            capabilities = getattr(collector, "source_admission", ())
            journal.put("native_source_admission", [cap.model_dump(mode="json") for cap in capabilities])
            active()
            from tradingagents.agents.schemas._evidence_record import EvidenceRecord
            if not isinstance(seed, EvidenceRecord):
                raise ValueError("collector must return a current evidence record")
            if (seed.run_id, seed.ticker, seed.mode, seed.analysis_date.isoformat()) != (
                run_id,
                request.ticker,
                request.mode,
                request.analysis_date,
            ):
                raise ResearchCheckpointConflict("native seed does not match request identity")
            journal.put("native_seed", seed.model_dump(mode="json"))
            self._stage(journal, "evidence", "completed")

        from tradingagents.graph.insight_research import run_insight_research
        from tradingagents.research.insights import build_insight_catalog
        from tradingagents.research.native_policy import fact_views
        factory = self.caller_factory
        delegate = factory(effective_config=request.effective_config, run_id=run_id, ledger=journal.ledger,
            cancelled=lambda: token.is_cancelled, deadline=lambda: deadline)
        catalogs = {role: build_insight_catalog(seed, facts=facts)
            for role, facts in fact_views(seed, valuation=True).items()}
        search_record = seed

        def supplement_insights(questions, round_id):
            nonlocal search_record
            from tradingagents.execution.insight_search import collect_insight_supplement
            search_record, result = collect_insight_supplement(search_record, questions,
                coordinator=coordinator, ledger=journal.ledger, round_id=round_id)
            return result

        record = run_insight_research(run_id=run_id, ticker=request.ticker, analysis_date=seed.analysis_date,
            catalogs=catalogs, caller=delegate, journal=journal, ensure_active=active, focus_question=request.research_question,
            company_basics=seed.company_basics, foundation_catalog=build_insight_catalog(seed, facts=tuple(
                f for f in seed.claims if seed.company_basics and f.claim_id in {v.claim_id for v in (
                    *seed.company_basics.introduction, *seed.company_basics.fundamentals, *seed.company_basics.quantitative)})),
            on_stage=lambda role, status: self._stage(journal, role, status),
            supplement=supplement_insights if coordinator is not None and journal.state['identity'].get('search_research_policy', {}).get('enabled') is not False else None,
            source_gaps=tuple(item for item in seed.limitations if item.startswith('global_gap:') or item.startswith('global_coverage:') and not item.endswith(':available'))
                + tuple('search_gap:' + g.gap_id for g in seed.search_gaps))
        active()
        if publication_authorizer is None:
            raise ValueError('native publication requires a lifecycle authorizer')
        entered = False

        def authorize_insight(value):
            nonlocal entered
            publication_authorizer(value)
            entered = True

        publish_native_record(self.observer, record=record, ledger=journal.ledger,
            publication_authorizer=authorize_insight)
        if not entered:
            authorize_insight(journal)
        return AnalysisResult({'research_profile': 'evidence_v1',
            'native_research_record': record.model_dump(mode='json')}, 'research_only')
