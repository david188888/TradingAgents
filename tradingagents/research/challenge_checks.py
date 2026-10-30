"""Pure classification and binding over V0; no fetch, dispatch or model calls."""

import json
from decimal import Decimal

from tradingagents.agents.schemas._challenge_verification import (
    CHALLENGE_CHECK_POLICY,
    ChallengeInputAvailabilityV1,
    ChallengeTestV1,
)
from tradingagents.agents.schemas._verification_plan import (
    VERIFIABLE_FIELDS,
    ChallengeVerificationTaskV1,
    FinancialOperandV1,
    VerificationPlanV2,
    canonical_sha256,
)

SUPPORTED_OPERATIONS = frozenset({"value", "difference", "growth"})
SAVED_METRIC_NAMES = frozenset({
    "annualized_volatility", "historical_var_95", "historical_es_95",
    "max_drawdown", "atr_14", "beta",
})


class ChallengeValidationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def parse_challenge_items(value):
    """Only the closed array shape is shared; invalid item prose is discarded."""
    from tradingagents.agents.schemas._native_stage import ChallengesProposalV3
    if (not isinstance(value, dict) or value.keys() != {"challenges"}
            or not isinstance(value["challenges"], list) or len(value["challenges"]) > 3):
        raise ValueError("challenge envelope shape invalid")
    accepted, indices, rejections = [], [], []
    for index, item in enumerate(value["challenges"]):
        try:
            proposal = ChallengesProposalV3.model_validate_json(json.dumps({"challenges": [item]}, allow_nan=False))
        except (ValueError, TypeError):
            rejections.append({"index": index, "code": "challenge_schema_invalid"})
        else:
            indices.append(index)
            accepted.append(proposal.challenges[0])
    return ChallengesProposalV3(challenges=tuple(accepted)), indices, rejections


def challenge_test(proposal):
    return ChallengeTestV1.model_validate_json(proposal.model_dump_json(
        include=set(ChallengeTestV1.model_fields)))


def check_scope(record, test):
    """New facts belong to the challenge, never retroactively to the hypothesis."""
    from tradingagents.research.verification_tools import _qualified_source, _Unavailable
    baseline = set(record.snapshots[0].evidence_ids)
    facts = {f.claim_id: f for f in record.claims if f.kind == "fact"}
    if not set(test.supporting_fact_ids) <= facts.keys():
        raise ChallengeValidationError("challenge_fact_reference")
    allowed = {e for fid in test.supporting_fact_ids for e in facts[fid].evidence_ids}
    if not allowed <= baseline:
        raise ChallengeValidationError("challenge_fact_reference")
    try:
        for eid in allowed:
            if _qualified_source(record, eid).content is None:
                raise _Unavailable("content_unusable")
    except _Unavailable:
        raise ChallengeValidationError("challenge_fact_reference") from None
    check = test.check
    if check is not None:
        if check.kind == "financial":
            operands = [check.current, *([check.base] if check.base else [])]
            if any(o.evidence_id not in allowed for o in operands):
                raise ChallengeValidationError("challenge_check_scope")
            if check.base and check.base.evidence_id != check.current.evidence_id:
                raise ChallengeValidationError("challenge_check_scope")
        else:
            metric = next((m for m in record.metrics if m.metric_id == check.metric_id), None)
            if metric is None or not set(metric.input_evidence_ids) <= allowed:
                raise ChallengeValidationError("challenge_check_scope")


def input_availability(record, test):
    from tradingagents.research.verification_tools import (
        _financial_operand,
        _qualified_source,
        _Unavailable,
    )
    result = []
    for index, requirement in enumerate(test.required_inputs):
        status, reason, eids = "missing", "input_not_saved", []
        if requirement.kind == "source":
            status, reason = "availability_unknown", "model_proposed_requirement"
        elif requirement.kind == "metric":
            metric = next((m for m in record.metrics if m.metric_id == requirement.metric_id), None)
            if metric is not None:
                status, reason = "unqualified", "metric_unqualified"
                try:
                    if metric.availability == "available" and metric.sample_size and metric.window_end:
                        for eid in metric.input_evidence_ids:
                            _qualified_source(record, eid)
                        status, reason, eids = "available", "saved_metric", list(metric.input_evidence_ids)
                except _Unavailable:
                    pass
        elif requirement.field not in VERIFIABLE_FIELDS[requirement.table]:
            status, reason = "unqualified", "field_not_supported"
        else:
            for source in record.evidence:
                if source.evidence_id not in record.snapshots[0].evidence_ids:
                    continue
                operand = FinancialOperandV1(evidence_id=source.evidence_id, table=requirement.table,
                    field=requirement.field, report_period=requirement.report_period)
                try:
                    _financial_operand(record, operand)
                except _Unavailable as exc:
                    # Only candidate statement records contribute diagnostic reasons.
                    if source.source_name.endswith(("financial_statements", "financial_detail")):
                        status, reason = "unqualified", exc.reason
                else:
                    eids.append(source.evidence_id)
            if eids:
                status, reason = "available", "saved_financial_field"
        result.append(ChallengeInputAvailabilityV1(input_index=index, availability=status,
            reason=reason, evidence_ids=tuple(sorted(set(eids)))))
    # A comparison needs a single saved record covering both periods.
    if (test.required_operation in {"difference", "growth"} and len(result) == 2
            and all(r.kind == "financial" for r in test.required_inputs)
            and all(r.availability == "available" for r in result)
            and not set(result[0].evidence_ids).intersection(result[1].evidence_ids)):
        result = [r.model_copy(update={"availability": "unqualified",
                   "reason": "comparison_source_unavailable"}) for r in result]
    return tuple(result)


def validate_test(record, test):
    """Reject mechanically false classifications; prose entailment remains unchecked."""
    from tradingagents.research.verification_tools import (
        _financial_operand,
        _qualified_source,
        _Unavailable,
    )
    check_scope(record, test)
    category = test.verifiability
    if category == "future_observation" and test.observation_date <= record.analysis_date:
        raise ChallengeValidationError("challenge_future_date")
    if category == "needs_source" and any(r.kind == "financial" and r.report_period > record.analysis_date.isoformat()
                                        for r in test.required_inputs):
        raise ChallengeValidationError("challenge_future_date")
    if category == "computable_now":
        check = test.check
        try:
            if check.kind == "financial":
                _financial_operand(record, check.current)
                if check.base:
                    base, _ = _financial_operand(record, check.base)
                    if check.operation == "growth" and base <= 0:
                        raise _Unavailable("nonpositive_growth_base")
            else:
                metric = next(m for m in record.metrics if m.metric_id == check.metric_id)
                if (metric.availability != "available" or not metric.sample_size
                        or metric.window_end is None or metric.unit != check.predicate.unit):
                    raise _Unavailable("metric_unqualified")
                for eid in metric.input_evidence_ids:
                    _qualified_source(record, eid)
        except _Unavailable:
            raise ChallengeValidationError("challenge_check_unavailable") from None
    inputs = input_availability(record, test)
    saved_metrics = {m.metric_id for m in record.metrics}
    if category == "needs_source" and (test.required_operation not in SUPPORTED_OPERATIONS or any(
            r.kind == "financial" and r.field not in VERIFIABLE_FIELDS[r.table]
            or r.kind == "metric" and r.metric_id not in saved_metrics
            and r.metric_id.rsplit(".", 1)[-1] not in SAVED_METRIC_NAMES
            for r in test.required_inputs
        ) or not any(r.availability != "available" for r in inputs)):
        raise ChallengeValidationError("challenge_requirement_invalid")
    if category == "computable_unsupported":
        reason = test.reason_code
        unsupported = False
        if reason == "field_not_supported":
            unsupported = any(r.kind == "financial" and r.field not in VERIFIABLE_FIELDS[r.table]
                              for r in test.required_inputs)
        elif reason == "operation_not_supported":
            unsupported = test.required_operation not in SUPPORTED_OPERATIONS
        elif reason == "metric_not_supported":
            unsupported = any(r.kind == "metric" and r.metric_id not in saved_metrics
                and r.metric_id.rsplit(".", 1)[-1] not in SAVED_METRIC_NAMES for r in test.required_inputs)
        elif reason == "input_domain_unsupported":
            reqs = test.required_inputs
            if (test.required_operation == "growth" and len(reqs) == 2
                    and all(r.kind == "financial" for r in reqs)
                    and (reqs[0].table, reqs[0].field) == (reqs[1].table, reqs[1].field)
                    and reqs[1].report_period < reqs[0].report_period
                    and reqs[1].report_period[5:] == reqs[0].report_period[5:]
                    and all(r.availability == "available" for r in inputs)):
                for eid in set(inputs[0].evidence_ids).intersection(inputs[1].evidence_ids):
                    operand = FinancialOperandV1(evidence_id=eid, table=reqs[1].table,
                        field=reqs[1].field, report_period=reqs[1].report_period)
                    value, _ = _financial_operand(record, operand)
                    unsupported |= value <= Decimal(0)
        if not unsupported:
            raise ChallengeValidationError("challenge_requirement_invalid")
    return inputs


def condition_choices(conditions):
    """Stable per-hypothesis order survives JSON key sorting and checkpoint reload."""
    result = {}
    for cid in sorted(conditions):
        condition = conditions[cid]
        items = result.setdefault(condition["hypothesis_id"], [])
        items.append({"condition_index": len(items), "condition_id": cid, "text": condition["text"]})
    return result


def resolve_challenge_condition(proposal, conditions):
    """Resolve the local index, retaining strict consistency for legacy IDs."""
    cid = proposal.condition_id
    if proposal.condition_index is not None:
        choices = condition_choices(conditions).get(proposal.hypothesis_id, [])
        if proposal.condition_index >= len(choices):
            raise ChallengeValidationError("challenge_condition_reference")
        selected = choices[proposal.condition_index]["condition_id"]
        if cid is not None and cid != selected:
            raise ChallengeValidationError("challenge_condition_reference")
        cid = selected
    if cid and (cid not in conditions or conditions[cid]["hypothesis_id"] != proposal.hypothesis_id):
        raise ChallengeValidationError("challenge_condition_reference")
    return cid


def validate_challenge(record, proposal, conditions=None):
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    if proposal.hypothesis_id not in hypotheses:
        raise ChallengeValidationError("challenge_target_reference")
    if conditions is not None:
        resolve_challenge_condition(proposal, conditions)
    return validate_test(record, challenge_test(proposal))


def make_challenge_task(record, challenge):
    test = challenge.test
    if test is None or test.verifiability != "computable_now":
        return None
    validate_test(record, test)
    hypothesis = next(h for h in record.hypotheses if challenge.target_claim_ids == (h.claim_id,))
    return ChallengeVerificationTaskV1(task_id="t." + canonical_sha256({"challenge": challenge.challenge_id}),
        challenge_id=challenge.challenge_id, hypothesis_id=hypothesis.hypothesis_id,
        proposition=challenge.proposed_test, challenge_sha256=canonical_sha256(challenge), check=test.check)


def make_challenge_plan(record):
    return VerificationPlanV2(run_id=record.run_id, ticker=record.ticker, mode=record.mode,
        analysis_date=record.analysis_date.isoformat(), input_snapshot_id=record.snapshots[0].snapshot_id,
        tasks=tuple(task for c in record.challenges if (task := make_challenge_task(record, c)) is not None))


def validate_challenge_record(record):
    """Public replay gate; absence preserves legacy record bytes and behavior."""
    if record.challenge_check_policy is None:
        if record.challenge_outcomes is not None or any(c.test is not None for c in record.challenges):
            raise ValueError("challenge checks require a frozen policy")
        return
    if record.challenge_check_policy != CHALLENGE_CHECK_POLICY or record.construction != "native":
        raise ValueError("challenge check policy invalid")
    for challenge in record.challenges:
        if len(challenge.target_claim_ids) != 1 or not any(
            h.claim_id == challenge.target_claim_ids[0] and h.origin == "hypothesis_stage"
            for h in record.hypotheses
        ):
            raise ValueError("challenge check requires exactly one native hypothesis")
        if challenge.severity in {"material", "critical"} and (
                challenge.test is None or challenge.test.verifiability is None):
            raise ValueError("important challenge requires classification")
        if challenge.test is not None:
            validate_test(record, challenge.test)
    if record.challenge_outcomes is None:
        if record.assessment is not None or record.dialogue is not None or record.verifications:
            raise ValueError("challenge check outcomes missing")
        return
    by_id = {o.challenge_id: o for o in record.challenge_outcomes}
    if len(by_id) != len(record.challenge_outcomes) or by_id.keys() != {c.challenge_id for c in record.challenges}:
        raise ValueError("challenge outcome coverage invalid")
    plan_hash = canonical_sha256(make_challenge_plan(record))
    for challenge in record.challenges:
        outcome, task = by_id[challenge.challenge_id], make_challenge_task(record, challenge)
        verifications = [v for v in record.verifications if v.challenge_id == challenge.challenge_id]
        if task is None:
            category = challenge.test.verifiability if challenge.test else None
            if (outcome.state != "not_generated" or outcome.reason != (category or "minor_unclassified")
                    or outcome.inputs != (validate_test(record, challenge.test) if challenge.test else ())
                    or verifications):
                raise ValueError("ungenerated challenge outcome changed")
        elif (outcome.state == "not_generated" or outcome.task_id != task.task_id or outcome.plan_sha256 != plan_hash
                or len(verifications) != (1 if outcome.state == "completed" else 0)):
            raise ValueError("challenge task outcome changed")
        elif verifications:
            v = verifications[0]
            if (v.scope != "challenge_predicate_only" or v.hypothesis_id != task.hypothesis_id
                    or v.condition_text != task.proposition or v.plan_sha256 != outcome.plan_sha256
                    or v.check_sha256 != canonical_sha256(task.check)
                    or v.verification_id != "check." + canonical_sha256({"plan": plan_hash, "task": task.task_id})):
                raise ValueError("challenge verification binding changed")
            from tradingagents.research.verification_tools import inspect_predicate
            if v.result_reason == "tool_failed":
                if v.status != "unavailable" or v.value is not None or v.predicate_met is not None or v.evidence_ids:
                    raise ValueError("failed tool cannot claim a predicate result")
            else:
                result = inspect_predicate(record, task.check)
                if (v.status, v.result_reason, v.value, v.predicate_met) != (
                        result.status, result.reason, result.value, result.predicate_met):
                    raise ValueError("challenge predicate result changed")
                expected_evidence = (*result.evidence_ids, "verification." + canonical_sha256({
                    "plan": plan_hash, "task": task.task_id})) if result.calculation is not None else ()
                if v.evidence_ids != expected_evidence:
                    raise ValueError("challenge predicate evidence changed")
                if result.calculation is not None:
                    derived = next(e for e in record.evidence if e.evidence_id == expected_evidence[-1])
                    if (derived.source_name != "code.numeric_predicate.v1" or derived.content is None
                            or json.loads(derived.content.text) != result.calculation):
                        raise ValueError("challenge predicate lineage changed")
