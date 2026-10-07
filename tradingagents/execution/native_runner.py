"""Consumer-neutral evidence_v1 execution and durable recovery."""

from __future__ import annotations

import json
import math
import time
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
from tradingagents.dataflows.tushare_price_history import PriceHistoryQualificationError
from tradingagents.execution.budget import BudgetBucket, BudgetConflictError, BudgetExhausted
from tradingagents.execution.config_identity import prepare_effective_config
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
from tradingagents.graph.native_research import load_native_seed, run_native_research
from tradingagents.llm_clients.task_effort import task_effort_overrides
from tradingagents.observability.canonical import canonical_sha256 as config_sha256
from tradingagents.observability.events import RunEventDraft
from tradingagents.observability.roles import (
    FOCUS_ROLE,
    NATIVE_ROLE_REGISTRY,
    role_instance_id,
    roles_for_profile,
)
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_versions import FOCUS_BUDGET_POLICY, FOCUS_WORKFLOW_VERSION
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    CatalystJournal,
    load_checkpoint,
)

VALUATION_WORKFLOW_VERSION = "evidence-production-v4"
MINIMUM_WORKFLOW_VERSION = "evidence-production-v5"
WORKFLOW_VERSION = FOCUS_WORKFLOW_VERSION
DISCLOSURE_WORKFLOW_VERSION = "evidence-production-v3"
PUBLIC_WORKFLOW_VERSION = "evidence-production-v2"
LEGACY_WORKFLOW_VERSION = "evidence-production-v1"


def native_identity(request, *, workflow_version=WORKFLOW_VERSION):
    return {
        **request.profile_identity(),
        "workflow_version": workflow_version,
        "ticker": request.ticker,
        "mode": request.mode,
        "cutoff": request.analysis_date,
        "holding_context": asdict(request.holding_context) if request.holding_context else None,
        "config": prepare_effective_config(request.effective_config),
        "active_timeout_seconds": request.effective_config.get("evidence_timeout_seconds", 300),
        **({"focus_budget_policy": dict(FOCUS_BUDGET_POLICY)} if workflow_version == FOCUS_WORKFLOW_VERSION else {}),
    }


@dataclass(frozen=True)
class NativeResumeGuard:
    require_existing: bool = True


def validate_native_resume(store, run_id, request):
    if request.research_profile != "evidence_v1":
        raise CatalystCheckpointConflict("native resume profile mismatch")
    state = load_checkpoint(store, run_id)
    version = state["identity"].get("workflow_version") if state is not None else None
    if version not in {FOCUS_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, VALUATION_WORKFLOW_VERSION, DISCLOSURE_WORKFLOW_VERSION, PUBLIC_WORKFLOW_VERSION, LEGACY_WORKFLOW_VERSION} or state["identity"] != native_identity(request, workflow_version=version):
        raise CatalystCheckpointConflict("native checkpoint missing or incompatible")
    from tradingagents.agents.schemas._research_record import ResearchRecordV1

    for key in ("native_seed", "native_publication_candidate"):
        if key in state:
            record = ResearchRecordV1.model_validate(state[key])
            if (record.run_id, record.ticker, record.mode, record.analysis_date.isoformat()) != (
                run_id,
                request.ticker,
                request.mode,
                request.analysis_date,
            ):
                raise CatalystCheckpointConflict("native checkpoint record identity mismatch")
            if record.construction != "native":
                raise CatalystCheckpointConflict("native checkpoint construction mismatch")
    if state.get("publication_authorized") and "native_publication_candidate" not in state:
        raise CatalystCheckpointConflict("native authorization has no candidate")


class NativeRunner:
    def __init__(
        self, observer, *, sources_factory=None, caller_factory=NativeModelCaller
    ):
        self.observer, self.sources_factory, self.caller_factory = (
            observer,
            sources_factory,
            caller_factory,
        )

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
            role = next(item for item in (*NATIVE_ROLE_REGISTRY, FOCUS_ROLE) if item.actor_id == actor)
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

    def run(
        self,
        request: AnalysisRequest,
        *,
        cancellation_token=None,
        checkpoint_guard=None,
        publication_authorizer=None,
        **_kwargs,
    ):
        if request.research_profile != "evidence_v1" or request.evidence_policy is None:
            raise ValueError("unsupported native request")
        request = replace(request, effective_config=deepcopy(dict(request.effective_config)))
        task_effort_overrides(request.effective_config)
        timeout = float(request.effective_config.get("evidence_timeout_seconds", 300))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("native timeout must be positive")
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
        journal = CatalystJournal(self.observer, native_identity(request, workflow_version=version), require_existing=resume)
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
            if version == FOCUS_WORKFLOW_VERSION:
                source_fields.pop("research_question", None)
                source_fields["effective_config"] = {
                    key: value for key, value in request.effective_config.items()
                    if key != "research_question"
                }
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
                }[version]
                draft, context = factory(
                    source_request, run_id, session, fetch
                ).collect()
            journal.put("native_source_admission", [cap.model_dump(mode="json") for cap in draft.capabilities])
            active()
            holding = request.holding_context
            seed = build_native_record(
                draft,
                context,
                mode=request.mode,
                original_thesis=holding.original_thesis if holding else None,
                holding_facts_as_of=holding.facts_as_of if holding else None,
                include_coverage=version in {DISCLOSURE_WORKFLOW_VERSION, VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION},
                include_valuation=version in {VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION},
                include_minimum=version in {MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION},
            )
            if (seed.run_id, seed.ticker, seed.mode, seed.analysis_date.isoformat()) != (
                run_id,
                request.ticker,
                request.mode,
                request.analysis_date,
            ):
                raise CatalystCheckpointConflict("native seed does not match request identity")
            journal.put("native_seed", seed.model_dump(mode="json"))
            self._stage(journal, "evidence", "completed")
        delegate = self.caller_factory(
            effective_config=request.effective_config,
            run_id=run_id,
            ledger=journal.ledger,
            cancelled=(lambda: token.is_cancelled) if version == FOCUS_WORKFLOW_VERSION else cancelled,
            deadline=lambda: deadline,
        )
        runner = self

        class ProgressCaller:
            def recover_cached(self, stage, context):
                recover = getattr(delegate, "recover_cached", None)
                return recover(stage, context) if callable(recover) else None

            def __call__(self, stage, context):
                runner._stage(journal, stage, "running")
                try:
                    value = delegate(stage, context)
                except Exception:
                    if not journal.failed:
                        runner._stage(journal, stage, "failed")
                    raise
                runner._stage(journal, stage, "completed")
                return value

        record = run_native_research(
            seed,
            caller=ProgressCaller(),
            ledger=journal.ledger,
            research_question=request.research_question,
            cancelled=cancelled,
            scoped=version in {DISCLOSURE_WORKFLOW_VERSION, VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION},
            valuation=version in {VALUATION_WORKFLOW_VERSION, MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION},
            minimum=version in {MINIMUM_WORKFLOW_VERSION, FOCUS_WORKFLOW_VERSION},
            independent=version == FOCUS_WORKFLOW_VERSION,
        )
        active()
        focus_response = None
        if version == FOCUS_WORKFLOW_VERSION:
            focus_response = execute_focus_response(
                record, request.research_question, ledger=journal.ledger, caller=ProgressCaller(),
                cancelled=lambda: token.is_cancelled, deadline=lambda: deadline,
                output_language=str(request.effective_config.get("output_language", "Chinese")),
                model_policy_sha256=config_sha256(prepare_effective_config(request.effective_config)),
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
