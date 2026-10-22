"""F03 classification, independent propositions and durable offline execution."""

import copy
import json
from pathlib import Path

import pytest

from tests.test_bounded_verification import (
    fields_changed,
    frozen,
    inputs as legacy_inputs,
)
from tradingagents.agents.schemas._challenge_verification import (
    CHALLENGE_CHECK_POLICY,
    ChallengeTestV1,
)
from tradingagents.agents.schemas._native_stage import ChallengeProposalV3
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution import verification_executor as executor
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.challenge_checks import (
    ChallengeValidationError,
    make_challenge_plan,
    validate_test,
)
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

RUN_ID = "run_20261021T000000000000Z_01234567"


def inputs(**kwargs):
    return legacy_inputs(run_id=RUN_ID, **kwargs)


def journal_for(tmp_path):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(run_id=RUN_ID, ticker="600519", analysis_date="2026-09-30",
        llm_provider="openai", quick_think_llm="offline", deep_think_llm="offline",
        runtime_semantics_hash="a" * 64)
    store.create_run(snapshot)
    return store, CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False),
        {"test": "challenge-checks"})


def requirement(**updates):
    return {"kind": "financial", "table": "income", "field": "revenue",
            "report_period": "2026-06-30", **updates}


def now_test(check=None):
    if check is None:
        _, plan = inputs()
        check = plan.tasks[0].check.model_dump(mode="json")
    return ChallengeTestV1.model_validate_json(json.dumps({
        "verifiability": "computable_now", "supporting_fact_ids": ["f1"], "check": check}))


def directed_record(test=None, record=None):
    record = record or inputs()[0]
    payload = record.model_dump(mode="json")
    payload["challenge_check_policy"] = CHALLENGE_CHECK_POLICY
    payload["challenges"][0]["test"] = (test or now_test()).model_dump(mode="json")
    # This text does not occur in the original assumptions/falsifiers.
    payload["challenges"][0]["proposed_test"] = "同期收入是否达到所提议的增幅"
    return ResearchRecordV1.model_validate(payload)


@pytest.mark.parametrize("category,extra", [
    ("computable_unsupported", {"required_inputs": [requirement(field="unsupported_field")], "reason_code": "field_not_supported"}),
    ("needs_source", {"required_inputs": [requirement(report_period="2024-06-30")]}),
    ("future_observation", {"observation_date": "2026-12-31"}),
    ("not_testable", {"reason_code": "no_observable_counterevidence"}),
])
def test_all_noncomputable_categories_record_honest_no_task(tmp_path, category, extra):
    test = ChallengeTestV1.model_validate_json(json.dumps({"verifiability": category, **extra}))
    record = directed_record(test)
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    assert not result.outcomes and not result.record.verifications
    assert result.record.challenge_outcomes[0].reason == category
    assert result.record.challenge_outcomes[0].state == "not_generated"
    assert result.record.snapshots == record.snapshots


def test_independent_proposition_executes_and_replays_without_rewriting_hypothesis(tmp_path, monkeypatch):
    record = directed_record()
    plan = make_challenge_plan(record)
    assert plan.schema_version == "verification-plan-v2"
    assert plan.tasks[0].proposition not in record.hypotheses[0].assumptions
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, plan, ledger=journal.ledger)
    v = result.record.verifications[0]
    assert v.scope == "challenge_predicate_only" and v.condition_role is None
    assert v.predicate_met is True and v.result_reason == "predicate_evaluated"
    assert v.check_sha256 == canonical_sha256(plan.tasks[0].check)
    assert result.record.hypotheses == record.hypotheses
    assert result.record.claims == record.claims
    assert result.record.challenge_outcomes[0].state == "completed"
    # Replay must not dispatch the executor, even after cancellation.
    monkeypatch.setattr(executor, "evaluate_condition", lambda *args: pytest.fail("re-executed"))
    replayed = executor.execute_verification(record, plan, ledger=journal.ledger, cancelled=lambda: True)
    assert replayed == result


@pytest.mark.parametrize("defect", ["scope", "base_scope", "period", "future", "unit"])
def test_now_rejects_unavailable_or_unbound_checks(defect):
    record, plan = inputs()
    check = plan.tasks[0].check.model_dump(mode="json")
    if defect == "scope":
        check["current"]["evidence_id"] = "outside"
    elif defect == "base_scope":
        check["base"]["evidence_id"] = "another_same_family_source"
    elif defect == "period":
        check["current"]["report_period"] = "2027-06-30"
    elif defect == "future":
        check["current"]["report_period"] = "2026-12-31"
        check["base"]["report_period"] = "2025-12-31"
    else:
        check["predicate"]["unit"] = "wrong_unit"
    with pytest.raises(ValueError):
        validate_test(record, now_test(check))


def test_known_saved_field_cannot_be_claimed_missing_or_unsupported():
    record = inputs()[0]
    for category, reason in [("needs_source", None), ("computable_unsupported", "field_not_supported")]:
        test = ChallengeTestV1(verifiability=category, required_inputs=(requirement(),), reason_code=reason)
        with pytest.raises(ChallengeValidationError, match="challenge_requirement_invalid"):
            validate_test(record, test)


def test_raw_fields_do_not_imply_an_unimplemented_ratio_formula():
    record = inputs()[0]
    test = ChallengeTestV1(verifiability="computable_unsupported", required_inputs=(requirement(),),
        required_operation="cross_field_ratio", reason_code="operation_not_supported")
    assert validate_test(record, test)[0].availability == "available"


@pytest.mark.parametrize("base", [0, -100])
def test_growth_domain_gap_is_not_missing_source_or_an_executable_check(base):
    record, plan = inputs()
    record, _ = fields_changed(record, plan, lambda p: p["income"][1].update(revenue=base))
    with pytest.raises(ChallengeValidationError, match="challenge_check_unavailable"):
        validate_test(record, now_test())
    test = ChallengeTestV1(verifiability="computable_unsupported", required_operation="growth",
        required_inputs=(requirement(), requirement(report_period="2025-06-30")),
        reason_code="input_domain_unsupported")
    assert all(i.availability == "available" for i in validate_test(record, test))


def test_prose_requirement_is_model_proposed_and_availability_unknown():
    test = ChallengeTestV1(verifiability="needs_source", required_inputs=(
        {"kind": "source", "description": "费用变动原因的管理层说明"},))
    availability = validate_test(inputs()[0], test)[0]
    assert availability.availability == "availability_unknown"
    assert availability.reason == "model_proposed_requirement"


def test_missing_source_cannot_hide_a_future_financial_period():
    test = ChallengeTestV1(verifiability="needs_source", required_inputs=(requirement(report_period="2027-06-30"),))
    with pytest.raises(ChallengeValidationError, match="challenge_future_date"):
        validate_test(inputs()[0], test)


@pytest.mark.parametrize("date", ["2026-09-30", "2026-09-29"])
def test_observation_date_must_be_strictly_after_cutoff(date):
    test = ChallengeTestV1.model_validate_json(json.dumps({
        "verifiability": "future_observation", "observation_date": date}))
    with pytest.raises(ChallengeValidationError, match="challenge_future_date"):
        validate_test(inputs()[0], test)


def test_important_proposal_cannot_omit_classification():
    proposal = {"hypothesis_id": "h1", "statement": "具体疑点", "proposed_test": "具体核查命题",
        "severity": "material", "risk_type": "operations"}
    with pytest.raises(ValueError):
        ChallengeProposalV3(**proposal)
    assert ChallengeProposalV3(**{**proposal, "severity": "minor"}).verifiability is None


def test_cancelled_tasks_have_no_execution_or_predicate(tmp_path):
    record = directed_record()
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger,
        cancelled=lambda: True)
    assert result.record.challenge_outcomes[0].state == "cancelled"
    assert not result.record.verifications and result.record.snapshots == record.snapshots


def test_tool_failure_remains_executed_unavailable(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("private exception must not escape")
    monkeypatch.setattr(executor, "evaluate_condition", fail)
    record = directed_record()
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    v = result.record.verifications[0]
    assert v.status == "unavailable" and v.result_reason == "tool_failed"
    assert result.record.challenge_outcomes[0].state == "completed"
    assert v.predicate_met is None and v.value is None


@pytest.mark.parametrize("field,value", [("predicate_met", False), ("value", "99"),
    ("condition_text", "changed proposition"), ("check_sha256", "f" * 64)])
def test_public_record_rejects_changed_result_bindings(tmp_path, field, value):
    record = directed_record()
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    payload = result.record.model_dump(mode="json")
    payload["verifications"][0][field] = value
    with pytest.raises(ValueError):
        ResearchRecordV1.model_validate(payload)


def test_comparison_needs_same_evidence_not_just_same_family():
    record, plan = inputs()
    payload = record.model_dump(mode="json")
    second = copy.deepcopy(payload["evidence"][0])
    second["evidence_id"] = "e2"
    payload["evidence"].append(second)
    payload["claims"].append({"claim_id": "f2", "kind": "fact", "statement": "另一份保存输入", "evidence_ids": ["e2"]})
    record = frozen(payload)
    check = plan.tasks[0].check.model_dump(mode="json")
    check["base"]["evidence_id"] = "e2"
    test = now_test(check).model_copy(update={"supporting_fact_ids": ("f1", "f2")})
    with pytest.raises(ChallengeValidationError, match="challenge_check_scope"):
        validate_test(record, test)


def test_legacy_serialization_has_no_new_keys_and_v1_plan_still_executes(tmp_path):
    record, plan = inputs()
    raw = record.model_dump(mode="json")
    assert "challenge_check_policy" not in raw and "challenge_outcomes" not in raw
    assert "test" not in raw["challenges"][0]
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, plan, ledger=journal.ledger)
    assert result.record.verifications[0].scope == "predicate_only"
    assert "check_sha256" not in result.record.model_dump(mode="json")["verifications"][0]


def test_plan_cannot_omit_or_change_a_computable_challenge(tmp_path):
    record = directed_record()
    _, journal = journal_for(tmp_path)
    plan = make_challenge_plan(record)
    with pytest.raises(ValueError, match="cover every"):
        executor.execute_verification(record, plan.model_copy(update={"tasks": ()}), ledger=journal.ledger)
    with pytest.raises(ValueError, match="cover every"):
        executor.execute_verification(record, plan.model_copy(update={"tasks": (
            plan.tasks[0].model_copy(update={"proposition": "invented"}),)}), ledger=journal.ledger)
    assert not journal.ledger.records()


def test_frozen_denominators_retain_omissions_and_do_not_count_wrong_tasks(tmp_path):
    from tradingagents.research.challenge_metrics import FrozenChallengeCaseV1, challenge_metrics
    frozen_cases = json.loads((Path(__file__).parent / "fixtures/f03-important-challenges-v1.json").read_text())["cases"]
    case, missing = [FrozenChallengeCaseV1.model_validate(c) for c in frozen_cases]
    record = directed_record()
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    measured = challenge_metrics(result.record, cases=[case, missing])
    assert measured["classification_coverage"]["ratio"] == 0.5
    assert measured["accepted_classification_completeness"]["ratio"] == 1
    assert measured["task_generation_rate"]["ratio"] == 1
    assert measured["actual_execution_rate"]["ratio"] == measured["successful_result_rate"]["ratio"] == 1
    wrong = case.model_copy(update={"check": case.check.model_copy(update={
        "predicate": case.check.predicate.model_copy(update={"threshold": "0.9"})})})
    assert challenge_metrics(result.record, cases=[wrong])["task_generation_rate"]["numerator"] == 0
    assert challenge_metrics(result.record)["task_generation_rate"] is None
    with pytest.raises(ValueError, match="duplicate"):
        challenge_metrics(result.record, cases=[case, case])
    assert challenge_metrics(inputs()[0])["classification_coverage"] is None


def test_tool_failure_counts_execution_but_not_success(tmp_path, monkeypatch):
    from tradingagents.research.challenge_metrics import challenge_metrics
    monkeypatch.setattr(executor, "evaluate_condition", lambda *args: (_ for _ in ()).throw(RuntimeError()))
    record = directed_record()
    _, journal = journal_for(tmp_path)
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    measured = challenge_metrics(result.record)
    assert measured["actual_execution_rate"]["ratio"] == 1
    assert measured["successful_result_rate"]["ratio"] == 0
    assert measured["execution_reasons"] == {"tool_failed": 1}


@pytest.mark.parametrize("after_cache", [False, True])
def test_v2_interruption_preserves_result_or_unknown_without_redispatch(tmp_path, monkeypatch, after_cache):
    from tests.test_bounded_verification import Crash
    from tradingagents.execution.budget import BudgetBucket
    record = directed_record()
    plan = make_challenge_plan(record)
    _, journal = journal_for(tmp_path)
    with monkeypatch.context() as patch:
        if after_cache:
            original = journal.ledger.settle
            def interrupt(grant, **kwargs):
                if grant.bucket is BudgetBucket.SUPPLEMENT_CAPABILITIES:
                    raise Crash()
                return original(grant, **kwargs)
            patch.setattr(journal.ledger, "settle", interrupt)
        else:
            patch.setattr(executor, "evaluate_condition", lambda *args: (_ for _ in ()).throw(Crash()))
        with pytest.raises(Crash):
            executor.execute_verification(record, plan, ledger=journal.ledger)
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    monkeypatch.setattr(executor, "evaluate_condition", lambda *args: pytest.fail("unknown dispatch repeated"))
    result = executor.execute_verification(record, plan, ledger=restored.ledger, cancelled=lambda: True)
    assert result.record.challenge_outcomes[0].state == ("completed" if after_cache else "unknown")
    assert bool(result.record.verifications) is after_cache


def test_v2_budget_refusal_has_no_execution_and_does_not_hide_the_task(tmp_path, monkeypatch):
    from tradingagents.execution.budget import BudgetBucket
    from tradingagents.research.challenge_metrics import challenge_metrics
    record = directed_record()
    _, journal = journal_for(tmp_path)
    for index in range(journal.ledger.limit(BudgetBucket.DATA_CAPABILITY_CALLS)):
        grant = journal.ledger.reserve_or_raise(BudgetBucket.DATA_CAPABILITY_CALLS, stage="existing", logical_call_id=f"existing.{index}")
        journal.ledger.mark_dispatched(grant)
        journal.ledger.settle(grant, ok=True)
    monkeypatch.setattr(executor, "evaluate_condition", lambda *args: pytest.fail("budget refused"))
    result = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    assert result.record.challenge_outcomes[0].state == "budget_refused"
    assert not result.record.verifications
    assert challenge_metrics(result.record)["actual_execution_rate"] == {
        "numerator": 0, "denominator": 1, "ratio": 0, "basis": "counted"}


def test_duplicate_generated_challenges_cannot_inflate_frozen_case_coverage(tmp_path):
    from tradingagents.research.challenge_metrics import FrozenChallengeCaseV1, challenge_metrics
    record = directed_record()
    raw = record.model_dump(mode="json")
    raw["challenges"].append({**copy.deepcopy(raw["challenges"][0]), "challenge_id": "c2"})
    record = ResearchRecordV1.model_validate(raw)
    _, journal = journal_for(tmp_path)
    output = executor.execute_verification(record, make_challenge_plan(record), ledger=journal.ledger)
    case = FrozenChallengeCaseV1(case_id="one", target_claim_id="i1", proposition=record.challenges[0].proposed_test,
        severity="critical", verifiability="computable_now", check=record.challenges[0].test.check)
    metrics = challenge_metrics(output.record, cases=[case])
    assert metrics["important_challenges"] == 2
    assert metrics["classification_coverage"]["numerator"] == metrics["task_generation_rate"]["numerator"] == 1
