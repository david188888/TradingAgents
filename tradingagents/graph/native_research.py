"""Evidence → hypotheses → one challenge → bounded checks → synthesis.

This shared kernel has no profile, HTTP retrieval, model SDK or Web dependency.
Callers supply a facts-only V0 and the run's existing durable ledger.
"""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV1,
    SpecialistProposalV1,
    SynthesisProposalV1,
)
from tradingagents.agents.schemas._research_assessment import (
    ChallengeAssessmentV1,
    DimensionAssessmentV1,
    ResearchAssessmentV1,
)
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import VerificationPlanV1, canonical_sha256
from tradingagents.execution.budget import AttemptPhase, BudgetBucket, BudgetLimitHit
from tradingagents.execution.verification_executor import execute_verification
from tradingagents.research.native_policy import (
    QUESTIONS,
    ROLE_ORDER,
    dimension_policy,
    fact_views,
    gate_dimensions,
)
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    DurableBudgetLedger,
)

WORKFLOW_VERSION = "native-research-kernel-v1"


def _bound_put(journal, key, value):
    with journal.lock:
        if key in journal.state and journal.state[key] != value:
            raise CatalystCheckpointConflict("native research frontier changed")
        if key not in journal.state:
            journal.put(key, value)


def _call(stage, context, schema, *, caller, ledger, cancelled, reservation=None):
    logical = "native." + stage
    _bound_put(ledger.journal, logical + ".input", {"sha256": canonical_sha256(context)})
    cached = ledger.cached_result(logical)
    if cached is not None:
        return schema.model_validate_json(json.dumps(cached["proposal"]))
    recover = getattr(caller, "recover_cached", None)
    if callable(recover):
        saved = recover(stage, context)
        if saved is not None:
            proposal = schema.model_validate_json(json.dumps(saved, allow_nan=False))
            ledger.record_result(logical, {"proposal": proposal.model_dump(mode="json")})
            return proposal
    attempts = [item for item in ledger.records() if item.logical_call_id == logical]
    if any(item.phase != AttemptPhase.RESERVED and item.dispatched_at is not None for item in attempts):
        # A lost response remains billed and unknown. Resuming cannot invent a
        # second model decision for the same immutable stage.
        return None
    token = reservation or ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage=logical, logical_call_id=logical)
    if isinstance(token, BudgetLimitHit):
        return None
    if cancelled():
        ledger.release(token, reason="native_cancelled_before_dispatch")
        return None
    ledger.mark_dispatched(token)
    try:
        value = caller(stage, context)
        if isinstance(value, BaseModel):
            value = value.model_dump_json()
        elif not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, allow_nan=False)
        proposal = schema.model_validate_json(value)
    except CatalystCheckpointConflict:
        raise
    except Exception:
        if ledger.journal.failed:
            raise
        ledger.settle(token, ok=False, detail="native_stage_invalid_or_unavailable")
        return None
    ledger.record_result(logical, {"proposal": proposal.model_dump(mode="json")})
    ledger.settle(token, ok=True, detail="native_stage_validated")
    return proposal


def _validated(record, **updates):
    return ResearchRecordV1.model_validate({**record.model_dump(mode="json"), **updates})


def load_native_seed(ledger: DurableBudgetLedger) -> ResearchRecordV1 | None:
    """Recover the exact V0 instead of rehashing normalized provider numbers.

    RunStore uses RFC 8785 (2.0 becomes 2). Source families use the provider's
    original JSON representation. The saved source-content strings in V0 keep
    their exact bytes; rebuilding that record from normalized raw context can
    therefore change provenance. Reading this seed never retrieves anything.
    """
    if not isinstance(ledger, DurableBudgetLedger) or ledger.journal.ledger is not ledger:
        raise ValueError("native seed recovery requires the run's durable ledger")
    with ledger.journal.lock:
        if ledger.journal.failed:
            raise CatalystCheckpointConflict("native seed persistence failed")
        saved = ledger.journal.state.get("native_seed")
        if saved is None:
            return None
        try:
            record = ResearchRecordV1.model_validate(saved)
        except Exception:
            raise CatalystCheckpointConflict("native seed invalid") from None
        identity = ledger.journal.state.get("native_input")
        if record.run_id != ledger.run_id or (identity is not None
                and identity.get("seed_sha256") != canonical_sha256(record)):
            raise CatalystCheckpointConflict("native seed identity mismatch")
        if (record.construction != "native" or len(record.snapshots) != 1 or record.hypotheses
                or record.challenges or record.verifications or record.assessment
                or any(claim.kind != "fact" for claim in record.claims)):
            raise CatalystCheckpointConflict("native seed is not a facts-only V0")
        return record


def run_native_research(seed: ResearchRecordV1, *, caller: Callable,
                        ledger: DurableBudgetLedger, research_question: str | None = None,
                        cancelled: Callable[[], bool] = lambda: False,
                        concurrency: int = 2) -> ResearchRecordV1:
    seed = ResearchRecordV1.model_validate_json(seed.model_dump_json())
    if (seed.construction != "native" or len(seed.snapshots) != 1 or seed.hypotheses
            or seed.challenges or seed.verifications or seed.assessment
            or any(claim.kind != "fact" for claim in seed.claims)):
        raise ValueError("native workflow requires a facts-only V0")
    if (not isinstance(ledger, DurableBudgetLedger) or ledger.run_id != seed.run_id
            or ledger.journal.ledger is not ledger):
        raise ValueError("native workflow requires the run's durable ledger")
    if concurrency not in (1, 2):
        raise ValueError("native specialist concurrency is bounded at two")
    sources = {source.evidence_id: source for source in seed.evidence}
    if any(sources[key].availability != "available" or sources[key].content is None
           or sources[key].usable_as_of is None for fact in seed.claims for key in fact.evidence_ids):
        raise ValueError("native facts require qualified saved source content")
    question = research_question if research_question is not None else QUESTIONS[seed.mode]
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 400:
        raise ValueError("research question must contain 1..400 characters")
    identity = {"workflow_version": WORKFLOW_VERSION, "seed_sha256": canonical_sha256(seed),
                "research_question": question}
    _bound_put(ledger.journal, "native_seed", seed.model_dump(mode="json"))
    _bound_put(ledger.journal, "native_input", identity)
    cached_final = ledger.cached_result("native.output")
    if cached_final is not None:
        if cached_final["identity"] != identity:
            raise CatalystCheckpointConflict("native output identity mismatch")
        return ResearchRecordV1.model_validate(cached_final["record"])
    views = fact_views(seed)
    contexts, reservations = {}, {}
    for role in ROLE_ORDER:
        facts = views[role]
        if not facts:
            continue
        source_ids = {key for fact in facts for key in fact.evidence_ids}
        contexts[role] = {"mode": seed.mode, "question": question,
            "input_snapshot_id": seed.snapshots[0].snapshot_id,
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "sources": [item.model_dump(mode="json") for item in seed.evidence if item.evidence_id in source_ids],
            "metrics": [item.model_dump(mode="json") for item in seed.metrics
                        if set(item.input_evidence_ids) <= source_ids] if role == "market_context" else [],
            "instruction": "只提出证据绑定的假设、必要与失效条件、替代解释。不得创造事实。"}
        logical = "native." + role
        if ledger.cached_result(logical) is None and not any(
            item.logical_call_id == logical and item.dispatched_at is not None for item in ledger.records()
        ):
            # Stable reservation order before fan-out: the last budget unit
            # cannot be won by thread timing.
            reservations[role] = ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage=logical, logical_call_id=logical)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {role: pool.submit(_call, role, context, SpecialistProposalV1,
            caller=caller, ledger=ledger, cancelled=cancelled, reservation=reservations.get(role))
            for role, context in contexts.items()}
        proposals = {role: pending[role].result() for role in ROLE_ORDER if role in pending}
    claims = list(seed.model_dump(mode="json")["claims"])
    hypotheses, conditions, limits = [], {}, list(seed.limitations)
    facts_by_id = {item.claim_id: item for item in seed.claims}
    for role in ROLE_ORDER:
        proposal = proposals.get(role)
        if proposal is None:
            if role in contexts:
                limits.append("native_stage_unavailable:" + role)
            continue
        allowed = {item.claim_id for item in views[role]}
        for index, item in enumerate(proposal.hypotheses):
            if not set(item.supporting_fact_ids) <= allowed:
                raise ValueError("specialist hypothesis references facts outside its view")
            hid = "h." + canonical_sha256({"input": identity, "role": role, "index": index,
                                           "proposal": item.model_dump(mode="json")})
            cid = "i." + hid[2:]
            evidence_ids = tuple(dict.fromkeys(key for fact_id in item.supporting_fact_ids
                                for key in facts_by_id[fact_id].evidence_ids))
            claims.append({"claim_id": cid, "kind": "inference", "statement": item.statement,
                           "evidence_ids": evidence_ids, "supporting_fact_ids": item.supporting_fact_ids})
            hypotheses.append({"hypothesis_id": hid, "claim_id": cid, "input_snapshot_id": seed.snapshots[0].snapshot_id,
                "origin": "hypothesis_stage", "assumptions": [c.text for c in item.conditions if c.condition_role == "necessary"],
                "invalidation_conditions": [c.text for c in item.conditions if c.condition_role == "invalidation"],
                "limitations": ["alternative_explanation:" + item.alternative_explanation]})
            for condition in item.conditions:
                check = condition.check
                if check is not None:
                    if check.kind == "financial":
                        operands = (check.current,) if check.base is None else (check.current, check.base)
                        if any(operand.evidence_id not in evidence_ids for operand in operands):
                            raise ValueError("condition references evidence outside its hypothesis")
                    else:
                        metric = next((m for m in seed.metrics if m.metric_id == check.metric_id), None)
                        if metric is None or not set(metric.input_evidence_ids) <= set(evidence_ids):
                            raise ValueError("condition references a metric outside its hypothesis")
                bound = {"hypothesis_id": hid, "input_snapshot_id": seed.snapshots[0].snapshot_id,
                         **condition.model_dump(mode="json")}
                conditions["condition." + canonical_sha256(bound)] = bound
        limits.extend("specialist_unknown:" + item for item in proposal.unknowns)
    current = _validated(seed, claims=claims, hypotheses=hypotheses, limitations=limits)
    _bound_put(ledger.journal, "native_conditions", conditions)
    # Opaque IDs and no author role/order metadata: challenge the claim rather
    # than its named producer. Each condition remains immutable and bound.
    critic_context = {"mode": seed.mode, "question": question,
        "record": {**current.model_dump(mode="json"),
            "claims": sorted(current.model_dump(mode="json")["claims"], key=lambda item: item["claim_id"]),
            "hypotheses": sorted(hypotheses, key=lambda item: item["hypothesis_id"])}, "conditions": conditions,
        "instruction": "检验假设的证据与替代解释；明确材料可返回零挑战；只引用给定假设和条件，不强制看多或看空。"}
    critique = _call("challenge", critic_context, ChallengesProposalV1, caller=caller,
                     ledger=ledger, cancelled=cancelled) if hypotheses else ChallengesProposalV1()
    challenges, tasks = [], []
    hypothesis_map = {item.hypothesis_id: item for item in current.hypotheses}
    if critique is None:
        limits.append("native_stage_unavailable:challenge")
    else:
        for index, item in enumerate(critique.challenges):
            if item.hypothesis_id not in hypothesis_map:
                raise ValueError("challenge references an unknown hypothesis")
            target = hypothesis_map[item.hypothesis_id]
            bound = conditions.get(item.condition_id) if item.condition_id else None
            if item.condition_id and (bound is None or bound["hypothesis_id"] != item.hypothesis_id):
                raise ValueError("challenge selected a condition from another hypothesis")
            challenge_id = "c." + canonical_sha256({"input": identity, "index": index, "challenge": item.model_dump(mode="json")})
            challenges.append({"challenge_id": challenge_id, "target_claim_ids": [target.claim_id],
                "statement": item.statement, "severity": item.severity, "risk_type": item.risk_type,
                "proposed_test": item.proposed_test})
            if bound and bound["check"] is not None:
                tasks.append({"task_id": "t." + challenge_id[2:], "challenge_id": challenge_id,
                    "hypothesis_id": item.hypothesis_id, "condition_role": bound["condition_role"],
                    "condition_text": bound["text"], "check": bound["check"]})
    current = _validated(current, challenges=challenges, limitations=list(dict.fromkeys(limits)))
    plan = VerificationPlanV1.model_validate_json(json.dumps({
        "run_id": seed.run_id, "ticker": seed.ticker, "mode": seed.mode,
        "analysis_date": seed.analysis_date.isoformat(), "input_snapshot_id": seed.snapshots[0].snapshot_id,
        "tasks": tasks}))
    execution = execute_verification(current, plan, ledger=ledger, cancelled=cancelled)
    current = execution.record
    synthesis = _call("synthesis", {"mode": seed.mode, "question": question,
        "record": current.model_dump(mode="json"), "verification": execution.model_dump(mode="json"),
        "dimension_policy": dimension_policy(current),
        "instruction": "核查仅证明条件；不能据此关闭经济假设挑战。按dimension_policy顺序输出维度，所有挑战保留unresolved。"},
        SynthesisProposalV1, caller=caller, ledger=ledger, cancelled=cancelled) if seed.claims else None
    if synthesis is None:
        limits.append("native_synthesis_unavailable")
        dimensions = tuple(DimensionAssessmentV1(dimension=name, status="unresolved", judgement="证据或综合环节不足。",
                            limitations=(reason,)) for name, (_, reason) in dimension_policy(current).items())
        judgement, next_check, keys, primary = "资料或综合环节不足，暂不能形成完整研究判断。", "补齐缺失资料并重新核查。", (), None
        challenge_assessments = tuple(ChallengeAssessmentV1(challenge_id=item.challenge_id,
                                     rationale="未完成对整体假设的核查。") for item in current.challenges)
    else:
        dimensions = gate_dimensions(current, synthesis.dimensions)
        judgement, next_check, keys, primary = synthesis.judgement, synthesis.next_check, synthesis.key_claim_ids, synthesis.primary_challenge_id
        challenge_assessments = synthesis.challenge_assessments
        critical_ids = {item.challenge_id for item in current.challenges if item.severity == "critical"}
        if critical_ids and primary not in critical_ids:
            primary = next(item.challenge_id for item in current.challenges if item.severity == "critical")
    complete = (synthesis is not None and not any(item.status == "unresolved" for item in dimensions)
                and not any(item.startswith("native_stage_unavailable:") for item in limits))
    assessment = ResearchAssessmentV1(input_snapshot_id=current.snapshots[-1].snapshot_id,
        research_question=question, judgement=judgement, dimensions=dimensions, key_claim_ids=keys,
        primary_challenge_id=primary, next_check=next_check, challenge_assessments=challenge_assessments,
        completeness="complete" if complete else "partial",
        quality="PASS" if complete and not current.challenges else "LOW_CONFIDENCE",
        forward_window_calendar_days=84 if seed.mode == "catalyst_research" else None,
        limitations=tuple(dict.fromkeys(limits)))
    output = _validated(current, assessment=assessment.model_dump(mode="json"), limitations=list(dict.fromkeys(limits)))
    ledger.record_result("native.output", {"identity": identity, "record": output.model_dump(mode="json")})
    return output
