"""SDK stubs exercise one repair, isolation, numeric/F02 paths and replay."""

import copy
import json

import pytest

from tests.test_challenge_checks import journal_for
from tests.test_native_model import caller, main, sdk
from tests.test_native_record import financials, fixture
from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
from tradingagents.agents.schemas._native_stage import ChallengesProposalV3
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.budget import BudgetBucket
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_versions import UNIFIED_WORKFLOW_VERSION
from tradingagents.research.numeric_narrative import (
    compile_numeric_stage,
    prepare_numeric_context,
    validate_numeric_stage,
)


def context_and_value(*, numeric=False, premises=False):
    record = build_native_record(*fixture(financial_payload=financials(8)), mode="company_research")
    raw = record.model_dump(mode="json")
    fact = next(f for f in raw["claims"] if "income.revenue" in f["statement"])
    raw["claims"].append({"claim_id": "i1", "kind": "inference", "statement": "经营仍需观察",
        "evidence_ids": fact["evidence_ids"], "supporting_fact_ids": [fact["claim_id"]]})
    raw["hypotheses"] = [{"hypothesis_id": "h1", "claim_id": "i1", "origin": "hypothesis_stage",
        "input_snapshot_id": record.snapshots[0].snapshot_id, "invalidation_conditions": ["未来经营走弱"]}]
    record = ResearchRecordV1.model_validate(raw)
    context = {"record": record.model_dump(mode="json"), "conditions": {},
        "challenge_check_policy": CHALLENGE_CHECK_POLICY}
    value = {"challenges": [{"hypothesis_id": "h1", "statement": "盈利持续性仍待核查",
        "severity": "material", "risk_type": "operations", "proposed_test": "当前披露收入是否满足提议门槛",
        "verifiability": "computable_now", "supporting_fact_ids": [fact["claim_id"]],
        "check": {"kind": "financial", "operation": "value", "current": {
            "evidence_id": fact["evidence_ids"][0], "table": "income", "field": "revenue", "report_period": "2026-06-30"},
            "predicate": {"operator": "gt", "threshold": "0", "unit": "CNY"}}}]}
    if not numeric:
        return context, value
    identity = {"numeric_narrative_policy": "anchored-narrative-v1"}
    if premises:
        identity["factual_premise_policy"] = "factual-premises-v1"
    context = prepare_numeric_context("challenge", context, record, identity=identity)
    check = value["challenges"][0]["check"]
    anchors = {a["anchor_id"]: a for a in context["numeric_catalog"]["anchors"]}
    alias = next(alias for alias, aid in context["numeric_aliases"].items()
        if anchors[aid]["definition_key"] == "financial.income.revenue"
        and anchors[aid]["metadata"]["report_period"] == "2026-06-30")
    value["challenges"][0]["supporting_fact_ids"] = anchors[context["numeric_aliases"][alias]]["required_fact_ids"]
    value["challenges"][0]["proposed_test"] = "当前收入门槛：{{plan:p_threshold}}"
    value = {"proposal": value, "plans": [{"alias": "p_threshold", "kind": "quantity",
        "field_path": "challenges.0.proposed_test", **check["predicate"]}], "structured_bindings": [
            {"field_path": "challenges.0.check.current", "kind": "num", "alias": alias},
            {"field_path": "challenges.0.check.predicate", "kind": "plan", "alias": "p_threshold"}]}
    if premises:
        from tests.factual_premise_fixtures import bind
        value = bind("challenge", value, context)
    return context, value


def insert_bad(value, *, numeric):
    value = copy.deepcopy(value)
    proposal = value["proposal"] if numeric else value
    bad = {**proposal["challenges"][0], "verifiability": None, "statement": "rejected-private-text"}
    proposal["challenges"].insert(0, bad)
    if numeric:
        for key in ("plans", "structured_bindings", "premises"):
            for item in value.get(key, []):
                item["field_path"] = item["field_path"].replace("challenges.0.", "challenges.1.")
    return value


@pytest.mark.parametrize("numeric,premises", [(False, False), (True, False), (True, True)])
def test_bad_sibling_uses_one_repair_then_preserves_original_indices_and_receipts(tmp_path, monkeypatch, numeric, premises):
    _, journal = journal_for(tmp_path)
    identity = {"workflow_version": UNIFIED_WORKFLOW_VERSION, "challenge_check_policy": CHALLENGE_CHECK_POLICY}
    if numeric:
        identity["numeric_narrative_policy"] = "anchored-narrative-v1"
    if premises:
        identity["factual_premise_policy"] = "factual-premises-v1"
    journal.put("identity", identity)
    context, value = context_and_value(numeric=numeric, premises=premises)
    stub, _ = sdk(monkeypatch, [insert_bad(value, numeric=numeric), "invalid JSON"])
    main(journal, "challenge")
    model = caller(journal)
    accepted = model("challenge", context)
    assert len(accepted["challenges"]) == 1 and len(stub.prompts) == 2
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    candidate = journal.state["results"]["native.challenge_accepted"]
    assert candidate["indices"] == [1]
    assert candidate["rejections"] == [{"index": 0, "code": "challenge_schema_invalid"}]
    assert "rejected-private-text" not in json.dumps(candidate)
    if numeric:
        saved = journal.state["results"]["native.numeric.accepted.challenge"]
        assert saved["proof"]["indices"] == [1]
        assert all(f["path"].startswith("challenges.1.") for f in saved["proof"]["fields"])
        assert "rejected-private-text" not in json.dumps(saved)
        validate_numeric_stage("challenge", accepted, saved["proof"], context, ChallengesProposalV3)
    before = json.dumps(journal.state, sort_keys=True)
    inactive = caller(journal, cancelled=lambda: True, deadline=lambda: -1)
    assert inactive.recover_cached("challenge", context) == accepted
    assert json.dumps(journal.state, sort_keys=True) == before and len(stub.prompts) == 2


def test_successful_repair_revalidates_all_items_and_can_use_new_indices(tmp_path, monkeypatch):
    _, journal = journal_for(tmp_path)
    journal.put("identity", {"workflow_version": UNIFIED_WORKFLOW_VERSION, "challenge_check_policy": CHALLENGE_CHECK_POLICY})
    context, value = context_and_value()
    stub, _ = sdk(monkeypatch, [insert_bad(value, numeric=False), value])
    main(journal, "challenge")
    result = caller(journal)("challenge", context)
    assert len(result["challenges"]) == 1 and len(stub.prompts) == 2
    assert journal.state["results"]["native.challenge_accepted"]["indices"] == [0]
    assert not journal.state["results"]["native.challenge_accepted"]["rejections"]
    from tradingagents.research.challenge_metrics import challenge_admission_counts
    counts = challenge_admission_counts(journal.state)
    assert counts["first_proposal_slots"] == 2 and counts["initial_rejected_items"] == 1
    assert counts["final_rejected_items"] == 0 and counts["repair_removed_slots"] == 1


def test_new_numeric_check_requires_its_own_predicate_and_operand_receipts():
    context, value = context_and_value(numeric=True, premises=True)
    proposal, proof = compile_numeric_stage("challenge", value, context, ChallengesProposalV3)
    validate_numeric_stage("challenge", proposal, proof, context, ChallengesProposalV3)
    for defect in ("remove_binding", "wrong_plan_path", "wrong_threshold"):
        bad = copy.deepcopy(value)
        if defect == "remove_binding":
            bad["structured_bindings"].pop()
        elif defect == "wrong_plan_path":
            bad["plans"][0]["field_path"] = "challenges.0.statement"
        else:
            bad["proposal"]["challenges"][0]["check"]["predicate"]["threshold"] = "10"
        with pytest.raises(ValueError):
            compile_numeric_stage("challenge", bad, context, ChallengesProposalV3)
