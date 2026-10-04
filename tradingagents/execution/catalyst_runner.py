"""Consumer-neutral production adapter for the bounded catalyst workflow."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, datetime, time as calendar_time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas import CatalystResearchCase, Challenge, SpecialistFinding
from tradingagents.dataflows.catalyst_sources import CatalystSources
from tradingagents.dataflows.catalyst_transport import BudgetedSession
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.config_identity import prepare_effective_config
from tradingagents.execution.models import (
    AnalysisRequest,
    AnalysisResult,
    CancellationToken,
)
from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.graph.catalyst_workflow import (
    CatalystRunRequest,
    _invoke_budgeted,
    global_model_slots,
    run_catalyst_research,
)
from tradingagents.llm_clients import create_llm_client
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs
from tradingagents.llm_clients.task_effort import task_effort_overrides
from tradingagents.research.evidence_freeze import (
    ROLE_ORDER,
    FrozenEvidenceDraft,
    build_specialist_view,
)
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    CatalystJournal,
    load_checkpoint,
)

WORKFLOW_VERSION = "catalyst-production-v1"


def catalyst_identity(request: AnalysisRequest) -> dict[str, Any]:
    return {
        **request.profile_identity(), "workflow_version": WORKFLOW_VERSION,
        "ticker": request.ticker, "cutoff": request.analysis_date,
        "config": prepare_effective_config(request.effective_config),
        "active_timeout_seconds": request.effective_config.get("catalyst_timeout_seconds", 300),
    }


@dataclass(frozen=True)
class CatalystResumeGuard:
    require_existing: bool = True


def validate_catalyst_resume(store: Any, run_id: str, request: AnalysisRequest) -> None:
    state = load_checkpoint(store, run_id)
    if state is None or state["identity"] != catalyst_identity(request):
        raise CatalystCheckpointConflict("catalyst checkpoint missing or incompatible")
    if "draft" in state:
        draft = FrozenEvidenceDraft.model_validate(state["draft"])
        if (draft.run_id, draft.ticker, draft.cutoff, draft.policy_version) != (run_id, request.ticker, request.analysis_date, request.catalyst_policy.policy_version):
            raise CatalystCheckpointConflict("catalyst evidence identity mismatch")
        if not isinstance(state.get("evidence_context"), dict):
            raise CatalystCheckpointConflict("catalyst evidence context missing")
    if "candidate" in state:
        case = CatalystResearchCase.model_validate(state["candidate"])
        if (case.run_id, case.ticker, case.research_question, case.evidence_policy) != (run_id, request.ticker, request.research_question, request.catalyst_policy.policy_version):
            raise CatalystCheckpointConflict("catalyst candidate identity mismatch")
        if "as_of" not in state or case.as_of != datetime.fromisoformat(state["as_of"]):
            raise CatalystCheckpointConflict("catalyst candidate cutoff mismatch")
    elif state.get("publication_authorized"):
        raise CatalystCheckpointConflict("catalyst authorization has no candidate")


class ProductionModelCaller:
    def __init__(self, request, draft, context, journal, ensure_active, remaining):
        self.request, self.draft, self.context = request, draft, context
        self.config = deepcopy(dict(request.effective_config))
        task_effort_overrides(self.config)
        self.journal, self.ensure_active, self.remaining = journal, ensure_active, remaining

    def __call__(self, *, role: str, prompt: str) -> dict[str, Any]:
        self.ensure_active()
        logical = f"specialist.{role}" if role in ROLE_ORDER else "refutation" if role == "independent_refutation" else role
        if role in ROLE_ORDER:
            view = build_specialist_view(self.draft, role)
            prompt += "\nCITABLE EVIDENCE (only these IDs are permitted):\n" + json.dumps({
                eid: self.context[eid] for eid in view.citable_evidence_ids if eid in self.context
            }, ensure_ascii=False)
            shape = {"findings": [SpecialistFinding.model_json_schema()]}
        elif role == "independent_refutation":
            shape = {"challenges": [Challenge.model_json_schema()]}
        else:
            shape = {
                "judgement": "text <= 160 characters", "priority": "verify_first|keep_watching|defer_research|insufficient_information",
                "primary_catalyst_event_id": "existing event ID or null",
                "key_evidence_finding_ids": [], "key_question": "text <= 160 characters",
                "key_question_finding_ids": [], "key_question_challenge_ids": [],
                "next_check": "text <= 160 characters", "next_check_finding_ids": [],
                "critical_limitations": [], "dispositions": [], "rationale": "text",
            }
            from tradingagents.agents.schemas import ChallengeDisposition
            shape["dispositions"] = [ChallengeDisposition.model_json_schema()]
            prompt += "\nEVENT IDS: " + json.dumps([e.event_id for e in self.draft.events])
        prompt += "\nReturn one JSON object only, no Markdown. Shape/schema:\n" + json.dumps(shape, ensure_ascii=False)
        prompt += f"\nrun_id={self.draft.run_id}; output language={self.request.effective_config.get('output_language', 'Chinese')}. User research question: {self.request.research_question or '(none)'}"
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        with self.journal.lock:
            prior = self.journal.state.setdefault("prompts", {}).get(logical)
            if prior is not None and prior != digest:
                raise CatalystCheckpointConflict("catalyst prompt changed during resume")
            self.journal.state["prompts"][logical] = digest
            self.journal.persist()
        response = self._invoke(role, prompt)
        usage = getattr(response, "usage_metadata", None)
        try:
            value = self._parse(role, response)
        except (ValueError, TypeError, KeyError):
            # Exactly one structural repair, charged before dispatch by the same ledger.
            value = _invoke_budgeted(
                ledger=self.journal.ledger, bucket=BudgetBucket.STRUCTURED_REPAIR,
                stage=logical, logical_call_id=logical + ".repair",
                run=lambda: self._repair(role, prompt),
            )
        if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
            value["usage"] = {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]}
        return value

    def _repair(self, role, prompt):
        response = self._invoke(role, prompt + "\nYour previous response failed JSON/schema validation. Return a valid object respecting the schema, IDs and required fields.")
        return self._parse(role, response)

    def _invoke(self, role, prompt):
        self.ensure_active()
        extra_slot = role not in ROLE_ORDER
        if extra_slot:
            while not global_model_slots().acquire(timeout=0.1):
                self.ensure_active()
        try:
            self.ensure_active()
            config = self.config
            kwargs = provider_llm_kwargs(config, task="catalyst." + role)
            kwargs.update(max_retries=0, timeout=max(0.01, self.remaining()))
            client = create_llm_client(
                provider=config["llm_provider"],
                model=config["deep_think_llm"] if role == "synthesis" else config["quick_think_llm"],
                base_url=config.get("backend_url"), **kwargs,
            )
            response = client.get_llm().invoke(prompt)
            self.ensure_active()
            return response
        finally:
            if extra_slot:
                global_model_slots().release()

    def _parse(self, role, response):
        from tradingagents.llm_clients.base_client import normalize_content
        value = json.loads(normalize_content(response).content)
        if not isinstance(value, dict):
            raise ValueError("model response must be an object")
        if role in ROLE_ORDER:
            raw = value["findings"]
            if not isinstance(raw, list) or len(raw) > 6:
                raise ValueError("invalid findings envelope")
            view = build_specialist_view(self.draft, role)
            findings = []
            for index, item in enumerate(raw):
                item = {**item, "run_id": self.draft.run_id, "role": role}
                item.setdefault("finding_id", f"f.{role}.i{index}")
                finding = SpecialistFinding.model_validate(item)
                if set(finding.evidence_ids) - set(view.citable_evidence_ids):
                    raise ValueError("finding cites inaccessible evidence")
                if set(finding.event_ids) - {e.event_id for e in view.events}:
                    raise ValueError("finding cites inaccessible events")
                findings.append(finding.model_dump(mode="json"))
            value["findings"] = findings
        elif role == "independent_refutation":
            if not isinstance(value["challenges"], list) or len(value["challenges"]) > 3:
                raise ValueError("invalid challenges envelope")
            value["challenges"] = [Challenge.model_validate({
                **item, "run_id": self.draft.run_id, "challenge_id": item.get("challenge_id", f"ch.i{index}"),
            }).model_dump(mode="json") for index, item in enumerate(value["challenges"])]
        else:
            for key in ("judgement", "priority", "key_question", "next_check"):
                if not isinstance(value[key], str) or not value[key].strip():
                    raise ValueError("invalid synthesis envelope")
            for key in ("dispositions", "critical_limitations", "key_evidence_finding_ids"):
                if not isinstance(value.get(key, []), list):
                    raise ValueError("invalid synthesis collection")
        return value


class CatalystRunner:
    def __init__(self, observer: Any, *, sources_factory=CatalystSources, caller_factory=ProductionModelCaller):
        self.observer, self.sources_factory, self.caller_factory = observer, sources_factory, caller_factory

    def run(self, request: AnalysisRequest, *, cancellation_token: CancellationToken | None = None,
            checkpoint_guard=None, publication_authorizer: Callable | None = None, **_kwargs) -> AnalysisResult:
        if request.research_profile != "catalyst_v1" or request.mode != "company_research" or request.asset_type != "stock":
            raise ValueError("unsupported catalyst request")
        request = replace(request, effective_config=deepcopy(dict(request.effective_config)))
        task_effort_overrides(request.effective_config)
        timeout = float(request.effective_config.get("catalyst_timeout_seconds", 300))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("catalyst timeout must be positive")
        deadline = time.monotonic() + timeout
        token = cancellation_token or CancellationToken()

        def active():
            token.raise_if_cancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError("catalyst active deadline exceeded")

        def cancelled():
            return token.is_cancelled or time.monotonic() >= deadline

        run_id = self.observer.run_id
        if isinstance(checkpoint_guard, CatalystResumeGuard):
            validate_catalyst_resume(self.observer.store, run_id, request)
        journal = CatalystJournal(self.observer, catalyst_identity(request), require_existing=isinstance(checkpoint_guard, CatalystResumeGuard))
        if "candidate" in journal.state:
            case = CatalystResearchCase.model_validate(journal.state["candidate"])
        else:
            active()
            if "draft" not in journal.state:
                journal.stage("evidence", "running")

                def fetch(key, operation):
                    active()
                    cached = journal.state.get("source_results", {}).get(key)
                    if cached is not None:
                        if "error" in cached:
                            raise ValueError(cached["error"])
                        return cached["value"]
                    grant = journal.ledger.reserve_or_raise(BudgetBucket.DATA_CAPABILITY_CALLS, stage="evidence", logical_call_id="data." + key)
                    journal.ledger.mark_dispatched(grant)
                    try:
                        value = operation()
                        active()
                    except Exception as exc:
                        journal.ledger.settle(grant, ok=False, usage_available=False)
                        journal.state.setdefault("source_results", {})[key] = {"error": type(exc).__name__}
                        journal.persist()
                        raise
                    journal.state.setdefault("source_results", {})[key] = {"value": value}
                    journal.persist()
                    journal.ledger.settle(grant, ok=True, usage_available=False)
                    return value

                with BudgetedSession(journal.ledger, active, lambda: deadline-time.monotonic()) as session:
                    draft, context = self.sources_factory(request, run_id, session, fetch).collect()
                active()
                # One atomic frontier contains both the immutable draft and its citable payloads.
                with journal.lock:
                    journal.state.update(draft=draft.model_dump(mode="json"), evidence_context=context)
                    journal.stage("evidence", "completed")
            draft = FrozenEvidenceDraft.model_validate(journal.state["draft"])
            caller = self.caller_factory(request, draft, journal.state["evidence_context"], journal, active, lambda: deadline-time.monotonic())
            as_of = min(datetime.now(timezone.utc), datetime.combine(date.fromisoformat(request.analysis_date), calendar_time.max, ZoneInfo("Asia/Shanghai")))
            # Stable cutoff timestamp is saved once so replay cannot change public bytes.
            if "as_of" not in journal.state:
                journal.put("as_of", as_of.isoformat())
            result = run_catalyst_research(
                CatalystRunRequest(run_id, request.ticker, datetime.fromisoformat(journal.state["as_of"]), request.research_question or ""),
                draft, caller=caller, ledger=journal.ledger, cancel=cancelled, authorised=False,
            )
            active()
            if journal.failed:
                raise CatalystCheckpointConflict("catalyst persistence failed")
            case = result.case.model_copy(update={"source_sequence": journal.last_event.sequence})
            journal.put("candidate", case.model_dump(mode="json"))
        if publication_authorizer is None:
            raise ValueError("catalyst publication requires a lifecycle authorizer")
        published = [event for event in self.observer.store.read_events(run_id)
            if event.type == "artifact.written" and event.status == "committed"
            and event.payload.get("public_contract") == "catalyst-research-case-v1"]
        for event in published:
            try:
                prior = CatalystResearchCase.model_validate_json(
                    self.observer.store.read_artifact(run_id, event.payload["artifact_id"]))
            except Exception as exc:
                raise CatalystCheckpointConflict("existing catalyst public artifact is corrupt") from exc
            if prior != case:
                raise CatalystCheckpointConflict("same catalyst public task has different content")
        # The consumer arbitrates cancellation and this durable authorization under its lifecycle lock.
        active()
        publication_authorizer(journal)
        barrier = journal.last_event
        promote_derived_public_artifact(
            self.observer, contract="catalyst-research-case-v1", value=case,
            graph_task_id="catalyst.final", checkpoint_event_id=barrier.event_id,
            committed_sequence=barrier.sequence,
            promoted={("catalyst.final", "catalyst-research-case-v1")} if published else set(),
        )
        from tradingagents.execution.record_publisher import promote_research_record
        from tradingagents.research.record_assembly import record_from_catalyst
        promote_research_record(
            self.observer,
            build=lambda: record_from_catalyst(case, journal.state.get("evidence_context", {})),
            graph_task_id="catalyst.final", checkpoint_event_id=barrier.event_id,
            committed_sequence=barrier.sequence, promoted=set(),
        )
        return AnalysisResult({"research_profile": "catalyst_v1", "catalyst_case": case.model_dump(mode="json")}, "research_only")
