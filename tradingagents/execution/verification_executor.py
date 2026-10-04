"""One bounded, durable verification round on an existing run's budget.

This is a programmatic substrate. Compatibility production graphs still do
not produce the native hypotheses required here; their migration is separate.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from tradingagents.agents.schemas._research_record import (
    ResearchRecordV1,
    SourceContentV1,
    SourceEvidenceV1,
    VerificationRecordV1,
    make_evidence_snapshot,
)
from tradingagents.agents.schemas._verification_plan import (
    FinancialConditionV1,
    VerificationPlanV1,
    canonical_sha256,
)
from tradingagents.execution.budget import (
    BudgetBucket,
    BudgetLimitHit,
)
from tradingagents.research.verification_tools import VerificationToolResultV1, evaluate_condition
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    DurableBudgetLedger,
)


class VerificationTaskOutcomeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str
    state: Literal["completed", "budget_refused", "cancelled", "unknown"]
    executed_at: datetime | None = None
    result: VerificationToolResultV1 | None = None

    @model_validator(mode="after")
    def no_fabricated_execution(self):
        if self.state == "completed":
            if self.executed_at is None or self.executed_at.tzinfo is None or self.result is None:
                raise ValueError("completed verification requires a timestamp and result")
        elif self.executed_at is not None or self.result is not None:
            raise ValueError("unexecuted task cannot claim a verification result")
        return self


class VerificationExecutionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["verification-execution-v1"] = "verification-execution-v1"
    plan_sha256: str
    input_record_sha256: str
    output_record_sha256: str
    record: ResearchRecordV1
    outcomes: tuple[VerificationTaskOutcomeV1, ...]

    @model_validator(mode="after")
    def output_integrity(self):
        if canonical_sha256(self.record) != self.output_record_sha256:
            raise ValueError("verification output hash mismatch")
        return self


def _validate_bindings(record: ResearchRecordV1, plan: VerificationPlanV1) -> None:
    if (
        (plan.run_id, plan.ticker, plan.mode, plan.analysis_date, plan.input_snapshot_id)
        != (
            record.run_id,
            record.ticker,
            record.mode,
            record.analysis_date.isoformat(),
            record.snapshots[0].snapshot_id,
        )
        or record.construction != "native"
        or len(record.snapshots) != 1
        or record.verifications
    ):
        raise ValueError("verification requires matching identity and an unverified V0 record")
    hypotheses = {item.hypothesis_id: item for item in record.hypotheses}
    challenges = {item.challenge_id: item for item in record.challenges}
    for task in plan.tasks:
        hypothesis = hypotheses.get(task.hypothesis_id)
        challenge = challenges.get(task.challenge_id)
        if (
            hypothesis is None
            or hypothesis.origin != "hypothesis_stage"
            or hypothesis.input_snapshot_id != plan.input_snapshot_id
        ):
            raise ValueError("verification requires a native V0 hypothesis")
        if challenge is None or challenge.target_claim_ids != (hypothesis.claim_id,):
            raise ValueError("verification challenge must target exactly its hypothesis")
        conditions = (
            hypothesis.assumptions
            if task.condition_role == "necessary"
            else hypothesis.invalidation_conditions
        )
        if task.condition_text not in conditions:
            raise ValueError("verification condition must match its saved hypothesis")
        if isinstance(task.check, FinancialConditionV1):
            operands = (
                (task.check.current,)
                if task.check.base is None
                else (task.check.current, task.check.base)
            )
            if any(item.evidence_id not in record.snapshots[0].evidence_ids for item in operands):
                raise ValueError("verification operands must be in V0")
        elif task.check.metric_id not in {item.metric_id for item in record.metrics}:
            raise ValueError("verification metric must be in the frozen record")


def _prior_dispatch(ledger, logical_id):
    return any(
        item.logical_call_id == logical_id and item.dispatched_at is not None
        for item in ledger.records()
    )


def _local_settle(ledger, reservations, *, ok: bool, duration_ms=0):
    for reservation in reservations:
        ledger.settle(
            reservation,
            ok=ok,
            input_tokens=0,
            output_tokens=0,
            usage_available=True,
            duration_ms=duration_ms,
            detail="local_verification_no_http_or_model",
        )


def _authorize_round(ledger, logical_id):
    if _prior_dispatch(ledger, logical_id):
        return True
    reservation = ledger.reserve(
        BudgetBucket.SUPPLEMENT_ROUNDS, stage="verification", logical_call_id=logical_id
    )
    if isinstance(reservation, BudgetLimitHit):
        return False
    ledger.mark_dispatched(reservation)
    _local_settle(ledger, [reservation], ok=True)
    return True


def _task_outcome(record, task, logical_id, *, ledger, identity_sha256, cancelled):
    cached = ledger.cached_result(logical_id)
    if cached is not None:
        if cached.get("identity_sha256") != identity_sha256 or cached.get(
            "task_sha256"
        ) != canonical_sha256(task):
            raise CatalystCheckpointConflict("verification task cache identity mismatch")
        outcome = VerificationTaskOutcomeV1.model_validate(cached["outcome"])
        if outcome.task_id != task.task_id:
            raise CatalystCheckpointConflict("verification task cache target mismatch")
        return outcome
    if _prior_dispatch(ledger, logical_id):
        # A durable dispatch without a durable result is never silently retried.
        return VerificationTaskOutcomeV1(task_id=task.task_id, state="unknown")
    if cancelled():
        return VerificationTaskOutcomeV1(task_id=task.task_id, state="cancelled")
    reservations = []
    for bucket in (BudgetBucket.SUPPLEMENT_CAPABILITIES, BudgetBucket.DATA_CAPABILITY_CALLS):
        reservation = ledger.reserve(bucket, stage="verification", logical_call_id=logical_id)
        if isinstance(reservation, BudgetLimitHit):
            for granted in reservations:
                ledger.release(granted, reason="verification_companion_budget_refused")
            return VerificationTaskOutcomeV1(task_id=task.task_id, state="budget_refused")
        reservations.append(reservation)
    if cancelled():
        for granted in reservations:
            ledger.release(granted, reason="verification_cancelled_before_dispatch")
        return VerificationTaskOutcomeV1(task_id=task.task_id, state="cancelled")
    for granted in reservations:
        ledger.mark_dispatched(granted)
    executed_at = datetime.now(timezone.utc)
    started = monotonic()
    try:
        result = evaluate_condition(record, task)
    except Exception:
        # Provider-shaped exception messages and local paths must not leak.
        result = VerificationToolResultV1(status="unavailable", reason="tool_failed")
    outcome = VerificationTaskOutcomeV1(
        task_id=task.task_id, state="completed", executed_at=executed_at, result=result
    )
    ledger.record_result(
        logical_id,
        {
            "identity_sha256": identity_sha256,
            "task_sha256": canonical_sha256(task),
            "outcome": outcome.model_dump(mode="json"),
        },
    )
    # Saving before settlement permits replay if the process dies here. The
    # original ledger conservatively charges any unsettled dispatched attempt.
    _local_settle(
        ledger,
        reservations,
        ok=result.status != "unavailable",
        duration_ms=int((monotonic() - started) * 1000),
    )
    return outcome


def _build_record(record, plan, outcomes, plan_sha256):
    evidence = list(record.evidence)
    executions = []
    tasks = {task.task_id: task for task in plan.tasks}
    for outcome in outcomes:
        if outcome.state != "completed":
            continue
        task = tasks[outcome.task_id]
        result = outcome.result
        evidence_ids = ()
        if result.calculation is not None:
            text = json.dumps(
                result.calculation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            sources = [item for item in record.evidence if item.evidence_id in result.evidence_ids]
            if not sources or any(item.usable_as_of is None for item in sources):
                raise ValueError("verification derivation lacks qualified inputs")
            evidence_id = "verification." + canonical_sha256(
                {"plan": plan_sha256, "task": task.task_id}
            )
            families = {item.source_family_id for item in sources}
            evidence.append(
                SourceEvidenceV1(
                    evidence_id=evidence_id,
                    source_name="code.numeric_predicate.v1",
                    source_kind="derived",
                    source_family_id=next(iter(families)) if len(families) == 1 else None,
                    availability="available",
                    usable_as_of=max(item.usable_as_of for item in sources),
                    captured_at=outcome.executed_at,
                    content=SourceContentV1(
                        kind="source_fields",
                        text=text,
                        locator_label="已保存条件核查与输入血缘",
                        content_sha256=canonical_content_hash(text),
                    ),
                    limitations=(
                        "derived_not_an_independent_source",
                        "predicate_only_not_hypothesis_resolution",
                    ),
                )
            )
            evidence_ids = (*result.evidence_ids, evidence_id)
        if result.reason == "predicate_evaluated":
            label = (
                ("必要条件满足" if result.predicate_met else "必要条件不满足")
                if task.condition_role == "necessary"
                else ("失效条件触发" if result.predicate_met else "失效条件未触发，仍不能证明假设")
            )
            summary = f"{label}；计算值 {result.value} {task.check.predicate.unit}。仅核查指定条件，不证明整条假设。"
        else:
            summary = f"指定条件无法核查（{result.reason}）；保持未解决。"
        executions.append(
            {
                "verification_id": "check."
                + canonical_sha256({"plan": plan_sha256, "task": task.task_id}),
                "challenge_id": task.challenge_id,
                "input_snapshot_id": plan.input_snapshot_id,
                "method": "calculation",
                "status": result.status,
                "evidence_ids": evidence_ids,
                "executed_at": outcome.executed_at,
                "result": summary,
                "scope": "predicate_only",
                "hypothesis_id": task.hypothesis_id,
                "plan_sha256": plan_sha256,
                "condition_role": task.condition_role,
                "condition_text": task.condition_text,
            }
        )
    payload = record.model_dump(mode="json")
    if executions:
        v1 = make_evidence_snapshot(
            tuple(evidence), version=1, parent_snapshot_id=plan.input_snapshot_id
        )
        payload["evidence"] = [item.model_dump(mode="json") for item in evidence]
        payload["snapshots"].append(v1.model_dump(mode="json"))
        payload["verifications"] = [
            VerificationRecordV1(**item, output_snapshot_id=v1.snapshot_id).model_dump(mode="json")
            for item in executions
        ]
    limits = list(record.limitations)
    if plan.tasks:
        limits.append("numeric_condition_translation_not_economic_sufficiency")
    limits.extend(
        f"verification.{item.task_id}.{item.state}"
        for item in outcomes
        if item.state != "completed"
    )
    payload["limitations"] = list(dict.fromkeys(limits))
    return ResearchRecordV1.model_validate(payload)


def canonical_content_hash(text):
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def execute_verification(
    record: ResearchRecordV1,
    plan: VerificationPlanV1,
    *,
    ledger: DurableBudgetLedger,
    cancelled: Callable[[], bool] = lambda: False,
) -> VerificationExecutionV1:
    """Execute once, or read the saved result, using the caller's durable ledger.

    The same input V0 and plan must be supplied on replay. Output V1 is not a
    new verification input. An output is terminal even when cancelled/refused;
    a later native producer must explicitly handle unresolved checks.
    """
    # Revalidate copies: nested containers can have been mutated despite frozen
    # model settings, and model_copy(update=...) does not validate its updates.
    record = ResearchRecordV1.model_validate_json(record.model_dump_json())
    plan = VerificationPlanV1.model_validate_json(plan.model_dump_json())
    _validate_bindings(record, plan)
    if (
        not isinstance(ledger, DurableBudgetLedger)
        or ledger.run_id != record.run_id
        or ledger.journal.ledger is not ledger
    ):
        raise ValueError("verification requires this run's existing durable ledger")
    journal = ledger.journal
    with journal.lock:
        if journal.failed:
            raise CatalystCheckpointConflict("verification persistence failed")
        plan_sha256, input_sha256 = canonical_sha256(plan), canonical_sha256(record)
        frontier = {
            "plan_sha256": plan_sha256,
            "input_record_sha256": input_sha256,
            "plan": plan.model_dump(mode="json"),
            "record": record.model_dump(mode="json"),
        }
        prior = journal.state.get("verification_input")
        if prior is not None and prior != frontier:
            raise CatalystCheckpointConflict("verification input or plan changed")
        if prior is None:
            journal.put("verification_input", frontier)
        identity_sha256 = canonical_sha256(frontier)
        cached = ledger.cached_result("verification.output")
        if cached is not None:
            if cached.get("identity_sha256") != identity_sha256:
                raise CatalystCheckpointConflict("verification output identity mismatch")
            output = VerificationExecutionV1.model_validate(cached["output"])
            if output.plan_sha256 != plan_sha256 or output.input_record_sha256 != input_sha256:
                raise CatalystCheckpointConflict("verification output binding mismatch")
            return output
        priorities = {
            item.challenge_id: {"critical": 0, "material": 1, "minor": 2}[item.severity]
            for item in record.challenges
        }
        tasks = sorted(plan.tasks, key=lambda task: (priorities[task.challenge_id], task.task_id))
        round_id = "verification.round." + identity_sha256
        # Cancellation forbids new work, but must not discard a prior round's
        # completed cache or uncertain dispatch. _task_outcome reads both before
        # checking cancellation, so existing authorization is replayed first.
        round_allowed = bool(tasks) and (
            _prior_dispatch(ledger, round_id)
            or (not cancelled() and _authorize_round(ledger, round_id))
        )
        outcomes = []
        for task in tasks:
            if round_allowed:
                outcome = _task_outcome(
                    record,
                    task,
                    "verification.task." + canonical_sha256(task),
                    ledger=ledger,
                    identity_sha256=identity_sha256,
                    cancelled=cancelled,
                )
            else:
                outcome = VerificationTaskOutcomeV1(
                    task_id=task.task_id, state="cancelled" if cancelled() else "budget_refused"
                )
            outcomes.append(outcome)
        output_record = _build_record(record, plan, outcomes, plan_sha256)
        output = VerificationExecutionV1(
            plan_sha256=plan_sha256,
            input_record_sha256=input_sha256,
            output_record_sha256=canonical_sha256(output_record),
            record=output_record,
            outcomes=tuple(outcomes),
        )
        ledger.record_result(
            "verification.output",
            {"identity_sha256": identity_sha256, "output": output.model_dump(mode="json")},
        )
        return output
