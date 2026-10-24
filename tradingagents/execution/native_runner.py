"""Consumer-neutral evidence_v1 execution and durable recovery."""

from __future__ import annotations

import json
import math
import time
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from types import SimpleNamespace

import requests

from tradingagents.dataflows.catalyst_sources import CatalystSources
from tradingagents.dataflows.catalyst_transport import BudgetedSession
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.minimum_sources import MinimumEvidenceSources
from tradingagents.dataflows.native_disclosures import DisclosureSources
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.native_sources import NativeSources
from tradingagents.dataflows.native_valuation import ValuationSources
from tradingagents.dataflows.search_sources import SearchEvidenceSources
from tradingagents.dataflows.tushare_price_history import PriceHistoryQualificationError
from tradingagents.execution.budget import BudgetBucket, BudgetConflictError, BudgetExhausted
from tradingagents.execution.config_identity import (
    SemanticConfigError,
    native_effective_config,
)
from tradingagents.execution.models import (
    AnalysisCancelled,
    AnalysisRequest,
    AnalysisResult,
    CancellationToken,
)
from tradingagents.execution.native_focus import execute_focus_response
from tradingagents.execution.native_focus_publication import publish_focus_response
from tradingagents.execution.native_model import NativeModelCaller
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.execution.search_budget import SEARCH_BUDGET_POLICY
from tradingagents.execution.search_reviews import run_search_reviews
from tradingagents.graph.native_research import load_native_seed, run_native_research
from tradingagents.llm_clients.chatgpt_policy import (
    CHATGPT_REQUEST_POLICY,
    validate_reasoning_effort,
)
from tradingagents.llm_clients.task_effort import task_effort_overrides
from tradingagents.observability.canonical import canonical_sha256 as config_sha256
from tradingagents.observability.events import RunEventDraft
from tradingagents.observability.roles import (
    role_instance_id,
    roles_for_profile,
)
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_versions import (
    COMPANY_RESEARCH_POLICY,
    FOCUS_BUDGET_POLICY,
    FOCUS_WORKFLOW_VERSION,
    NUMERIC_NARRATIVE_POLICY,
    REPORT_DELIVERY_POLICY,
    SEARCH_RESEARCH_POLICY,
    SEARCH_WORKFLOW_VERSION,
    SPECIALIST_REFERENCE_POLICY,
    STRUCTURED_FINANCIAL_POLICY,
    UNIFIED_BUDGET_POLICY,
    UNIFIED_WORKFLOW_VERSION,
)
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    CatalystJournal,
    load_checkpoint,
)

VALUATION_WORKFLOW_VERSION = "evidence-production-v4"
MINIMUM_WORKFLOW_VERSION = "evidence-production-v5"
WORKFLOW_VERSION = SEARCH_WORKFLOW_VERSION
DISCLOSURE_WORKFLOW_VERSION = "evidence-production-v3"
PUBLIC_WORKFLOW_VERSION = "evidence-production-v2"
LEGACY_WORKFLOW_VERSION = "evidence-production-v1"


def native_identity(request, *, workflow_version=None, model_retry_policy=True, specialist_reference_policy=True, company_research_policy=True, report_delivery_policy=True, numeric_narrative_policy=True, chatgpt_request_policy=True, structured_financial_policy=True, factual_premise_policy=True, financial_detail_policy=True, challenge_check_policy=True):
    workflow_version = workflow_version or WORKFLOW_VERSION
    from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
    from tradingagents.agents.schemas._factual_premise import FACTUAL_PREMISE_POLICY
    from tradingagents.execution.native_retry import MODEL_RETRY_POLICY
    from tradingagents.research.native_versions import FINANCIAL_DETAIL_POLICY
    subscription_policy = chatgpt_request_policy and request.effective_config.get("llm_provider") == "chatgpt"
    if subscription_policy:
        validate_reasoning_effort(request.effective_config.get("openai_reasoning_effort"))
    return {
        **request.profile_identity(),
        "workflow_version": workflow_version,
        "ticker": request.ticker,
        "mode": request.mode,
        "cutoff": request.analysis_date,
        "holding_context": asdict(request.holding_context) if request.holding_context else None,
        "config": native_effective_config(request.effective_config, workflow_version),
        **({"chatgpt_request_policy": CHATGPT_REQUEST_POLICY} if subscription_policy else {}),
        **({'search_research_policy': {**deepcopy(SEARCH_RESEARCH_POLICY),
                'enabled': request.effective_config.get('evidence_search_enabled', True)},
            'search_budget_policy': deepcopy(SEARCH_BUDGET_POLICY)}
           if workflow_version == SEARCH_WORKFLOW_VERSION else {}),
        "active_timeout_seconds": request.effective_config.get("evidence_timeout_seconds", 300),
        **({"factual_premise_policy": FACTUAL_PREMISE_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and numeric_narrative_policy and factual_premise_policy else {}),
        **({"structured_financial_policy": STRUCTURED_FINANCIAL_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and structured_financial_policy else {}),
        **({"financial_detail_policy": FINANCIAL_DETAIL_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and financial_detail_policy else {}),
        **({"challenge_check_policy": CHALLENGE_CHECK_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and challenge_check_policy else {}),
        **({"numeric_narrative_policy": NUMERIC_NARRATIVE_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and numeric_narrative_policy else {}),
        **({"company_research_policy": COMPANY_RESEARCH_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and company_research_policy else {}),
        **({"report_delivery_policy": REPORT_DELIVERY_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and report_delivery_policy else {}),
        **({"specialist_reference_policy": SPECIALIST_REFERENCE_POLICY}
           if workflow_version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and specialist_reference_policy else {}),
        **({"focus_budget_policy": dict(UNIFIED_BUDGET_POLICY if workflow_version == UNIFIED_WORKFLOW_VERSION else FOCUS_BUDGET_POLICY)} if workflow_version in {FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION} else {}),
        **({"model_retry_policy": deepcopy(MODEL_RETRY_POLICY)}
           if workflow_version in {FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} and model_retry_policy else {}),
    }


@dataclass(frozen=True)
class NativeResumeGuard:
    require_existing: bool = True


def validate_native_resume(store, run_id, request):
    if request.research_profile != "evidence_v1":
        raise CatalystCheckpointConflict("native resume profile mismatch")
    state = load_checkpoint(store, run_id)
    version = state["identity"].get("workflow_version") if state is not None else None
    retry_policy = state is not None and "model_retry_policy" in state["identity"]
    reference_policy = state is not None and "specialist_reference_policy" in state["identity"]
    company_policy = state is not None and "company_research_policy" in state["identity"]
    report_policy = state is not None and "report_delivery_policy" in state["identity"]
    numeric_policy = state is not None and "numeric_narrative_policy" in state["identity"]
    chatgpt_policy = state is not None and "chatgpt_request_policy" in state["identity"]
    premise_policy = state is not None and "factual_premise_policy" in state["identity"]
    structured_policy = state is not None and "structured_financial_policy" in state["identity"]
    detail_policy = state is not None and "financial_detail_policy" in state["identity"]
    challenge_policy = state is not None and "challenge_check_policy" in state["identity"]
    if version not in {SEARCH_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, VALUATION_WORKFLOW_VERSION, DISCLOSURE_WORKFLOW_VERSION, PUBLIC_WORKFLOW_VERSION, LEGACY_WORKFLOW_VERSION} or state["identity"] != native_identity(request, workflow_version=version, model_retry_policy=retry_policy, specialist_reference_policy=reference_policy, company_research_policy=company_policy, report_delivery_policy=report_policy, numeric_narrative_policy=numeric_policy, chatgpt_request_policy=chatgpt_policy, structured_financial_policy=structured_policy, factual_premise_policy=premise_policy, financial_detail_policy=detail_policy, challenge_check_policy=challenge_policy):
        raise CatalystCheckpointConflict("native checkpoint missing or incompatible")
    from tradingagents.research.record_codec import parse_research_record

    for key in ("native_seed", "native_publication_candidate"):
        if key in state:
            record = parse_research_record(state[key])
            from tradingagents.research.numeric_integration import validate_record_numeric
            validate_record_numeric(record, state["identity"])
            if (record.run_id, record.ticker, record.mode, record.analysis_date.isoformat()) != (
                run_id,
                request.ticker,
                request.mode,
                request.analysis_date,
            ):
                raise CatalystCheckpointConflict("native checkpoint record identity mismatch")
            if record.construction != "native":
                raise CatalystCheckpointConflict("native checkpoint construction mismatch")
            if key == "native_seed" and record.dialogue is not None:
                raise CatalystCheckpointConflict("native seed contains dialogue")
            if key == "native_publication_candidate":
                from tradingagents.research.native_versions import validate_assessment_version
                try:
                    validate_assessment_version(record, version)
                except (ValueError, AttributeError):
                    raise CatalystCheckpointConflict("native checkpoint assessment version mismatch") from None
    if state.get("publication_authorized") and "native_publication_candidate" not in state:
        raise CatalystCheckpointConflict("native authorization has no candidate")


class NativeRunner:
    def __init__(
        self, observer, *, sources_factory=None, caller_factory=NativeModelCaller, chatgpt_auth=None, search_session_factory=requests.Session
    ):
        self.search_session_factory = search_session_factory
        self.observer, self.sources_factory, self.caller_factory = (
            observer,
            sources_factory,
            caller_factory,
        )
        if chatgpt_auth is not None and caller_factory is NativeModelCaller:
            from functools import partial
            self.caller_factory = partial(NativeModelCaller, chatgpt_auth=chatgpt_auth)

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
        version = load_checkpoint(self.observer.store, run_id)["identity"]["workflow_version"] if resume else WORKFLOW_VERSION
        retry_policy = not resume or "model_retry_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        reference_policy = not resume or "specialist_reference_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        company_policy = not resume or "company_research_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        report_policy = not resume or "report_delivery_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        numeric_policy = not resume or "numeric_narrative_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        chatgpt_policy = not resume or "chatgpt_request_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        premise_policy = not resume or "factual_premise_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        structured_policy = not resume or "structured_financial_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        detail_policy = not resume or "financial_detail_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        challenge_policy = not resume or "challenge_check_policy" in load_checkpoint(self.observer.store, run_id)["identity"]
        journal = CatalystJournal(self.observer, native_identity(request, workflow_version=version,
            model_retry_policy=retry_policy, specialist_reference_policy=reference_policy, company_research_policy=company_policy, report_delivery_policy=report_policy,
            numeric_narrative_policy=numeric_policy, chatgpt_request_policy=chatgpt_policy, structured_financial_policy=structured_policy, factual_premise_policy=premise_policy,
            financial_detail_policy=detail_policy, challenge_check_policy=challenge_policy), require_existing=resume)
        if journal.state["identity"].get("numeric_narrative_policy") is not None:
            with self.observer.store.lock_for(run_id):
                snapshot = self.observer.store.read_snapshot(run_id)
                metadata = dict(snapshot.metadata or {})
                marker = metadata.get("numeric_narrative_policy")
                if marker not in {None, NUMERIC_NARRATIVE_POLICY}:
                    raise CatalystCheckpointConflict("native numeric snapshot identity mismatch")
                if marker is None:
                    metadata["numeric_narrative_policy"] = NUMERIC_NARRATIVE_POLICY
                    self.observer.store.write_snapshot_atomic(replace(snapshot, metadata=metadata))
        coordinator = None
        if version == SEARCH_WORKFLOW_VERSION:
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
                        if saved["error"] in {"CatalystCheckpointConflict", "BudgetConflictError", "BudgetExhausted", "AnalysisCancelled", "TimeoutError"}:
                            raise CatalystCheckpointConflict("saved source control failure cannot become provider fallback")
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
                        CatalystCheckpointConflict, BudgetConflictError, BudgetExhausted,
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

            source_fields = {**vars(request), "catalyst_policy": request.evidence_policy.collector_policy()}
            if version in {FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION}:
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
                factory = self.sources_factory or {
                    LEGACY_WORKFLOW_VERSION: CatalystSources,
                    PUBLIC_WORKFLOW_VERSION: NativeSources,
                    DISCLOSURE_WORKFLOW_VERSION: DisclosureSources,
                    VALUATION_WORKFLOW_VERSION: ValuationSources,
                    MINIMUM_WORKFLOW_VERSION: MinimumEvidenceSources,
                    FOCUS_WORKFLOW_VERSION: MinimumEvidenceSources,
                    UNIFIED_WORKFLOW_VERSION: MinimumEvidenceSources,
                    SEARCH_WORKFLOW_VERSION: SearchEvidenceSources,
                }[version]
                collector = factory(source_request, run_id, session, fetch, coordinator) if version == SEARCH_WORKFLOW_VERSION else factory(source_request, run_id, session, fetch)
                draft, context = collector.collect()
            capabilities = getattr(collector, 'source_admission', ()) if version == SEARCH_WORKFLOW_VERSION else draft.capabilities
            journal.put("native_source_admission", [cap.model_dump(mode="json") for cap in capabilities])
            active()
            if version == SEARCH_WORKFLOW_VERSION:
                from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
                if not isinstance(draft, ResearchRecordV2):
                    raise ValueError('V8 collector must return a native V2 record')
                seed = draft
            else:
                holding = request.holding_context
                seed = build_native_record(
                    draft,
                    context,
                    mode=request.mode,
                    original_thesis=holding.original_thesis if holding else None,
                    holding_facts_as_of=holding.facts_as_of if holding else None,
                    include_coverage=version in {DISCLOSURE_WORKFLOW_VERSION, VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
                    include_valuation=version in {VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
                    include_minimum=version in {MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
                    include_basics=journal.state["identity"].get("report_delivery_policy") == REPORT_DELIVERY_POLICY,
                    include_structured_financial=journal.state["identity"].get("structured_financial_policy") == STRUCTURED_FINANCIAL_POLICY,
                )
            if (seed.run_id, seed.ticker, seed.mode, seed.analysis_date.isoformat()) != (
                run_id,
                request.ticker,
                request.mode,
                request.analysis_date,
            ):
                raise CatalystCheckpointConflict("native seed does not match request identity")
            if journal.state["identity"].get("numeric_narrative_policy") is not None:
                from tradingagents.research.numeric_integration import attach_numeric_attribution
                seed = attach_numeric_attribution(seed, journal)
            journal.put("native_seed", seed.model_dump(mode="json"))
            self._stage(journal, "evidence", "completed")
        delegate = self.caller_factory(
            effective_config=request.effective_config,
            run_id=run_id,
            ledger=journal.ledger,
            cancelled=(lambda: token.is_cancelled) if version in {FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION} else cancelled,
            deadline=lambda: deadline,
        )
        runner = self

        class ProgressCaller:
            def recover_cached(self, stage, context):
                recover = getattr(delegate, "recover_cached", None)
                return recover(stage, context) if callable(recover) else None

            def __call__(self, stage, context):
                if not stage.startswith("search_review."):
                    runner._stage(journal, stage, "running")
                try:
                    value = delegate(stage, context)
                except Exception:
                    if not journal.failed and not stage.startswith("search_review."):
                        runner._stage(journal, stage, "failed")
                    raise
                if not stage.startswith("search_review."):
                    runner._stage(journal, stage, "completed")
                return value

        record = run_native_research(
            seed,
            caller=ProgressCaller(),
            ledger=journal.ledger,
            research_question=request.research_question,
            cancelled=cancelled,
            scoped=version in {DISCLOSURE_WORKFLOW_VERSION, VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
            valuation=version in {VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
            minimum=version in {MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
            independent=version in {FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
            unified=version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION},
            supplement=(lambda current, gaps: run_search_reviews(
                current, gaps, coordinator=coordinator, caller=ProgressCaller(), ledger=journal.ledger, cancelled=cancelled))
                if coordinator is not None else None,
        )
        active()
        focus_response = None
        if version in {FOCUS_WORKFLOW_VERSION, UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION}:
            focus_response = execute_focus_response(
                record, request.research_question, ledger=journal.ledger, caller=ProgressCaller(),
                cancelled=lambda: token.is_cancelled, deadline=lambda: deadline,
                output_language=str(request.effective_config.get("output_language", "Chinese")),
                model_policy_sha256=config_sha256(native_effective_config(request.effective_config, version)),
            )
            token.raise_if_cancelled()
            if focus_response is not None:
                dispatched = any(r.logical_call_id == "native.focus_response" and r.dispatched_at is not None
                                 for r in journal.ledger.records())
                self._stage(journal, "focus_response", "completed" if focus_response.status == "available"
                            else "failed" if dispatched else "skipped")
        # Cached proposals close interrupted roles; stages lacking qualified
        # inputs remain skipped. A completed run never leaves an open role.
        for role in roles_for_profile("evidence_v1", workflow_version=version, focus_requested=bool(request.research_question)):
            key = role.node_id
            if key == "focus_response":
                continue
            if key == "evidence" or journal.ledger.cached_result("native." + key) is not None:
                self._stage(journal, key, "completed")
            elif journal.state.get("native_stages", {}).get(key) not in {"completed", "failed"}:
                self._stage(journal, key, "skipped")
        if publication_authorizer is None:
            raise ValueError("native publication requires a lifecycle authorizer")
        lifecycle_entered = False

        def authorize(value):
            nonlocal lifecycle_entered
            publication_authorizer(value)
            lifecycle_entered = True

        base_artifact = publish_native_record(
            self.observer, record=record, ledger=journal.ledger, publication_authorizer=authorize
        )
        if not lifecycle_entered:
            # A verified artifact replay is read-only in the publisher. The
            # resumed consumer must still arbitrate its new lifecycle with cancel.
            authorize(journal)
        if focus_response is not None:
            publish_focus_response(self.observer, record=record, response=focus_response,
                                   ledger=journal.ledger, base_artifact_id=base_artifact)
        return AnalysisResult(
            {
                "research_profile": "evidence_v1",
                "native_research_record": record.model_dump(mode="json"),
            },
            "research_only",
        )
