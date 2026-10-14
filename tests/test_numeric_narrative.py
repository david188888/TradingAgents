"""Adversarial quantity grammar, scope and replay over actual frozen fixtures."""

from copy import deepcopy

import pytest

from tests.test_numeric_catalog import growth_record
from tradingagents.agents.schemas._native_stage import SpecialistProposalV1
from tradingagents.research.numeric_narrative import (
    NumericNarrativeError,
    compile_numeric_stage,
    prepare_numeric_context,
    validate_numeric_stage,
)


def numeric_context():
    record = growth_record()
    context = prepare_numeric_context("operating_quality", {
        "facts": [c.model_dump(mode="json") for c in record.claims if c.kind == "fact"],
        "metrics": [],
    }, record)
    anchor = next(a for a in context["numeric_catalog"]["anchors"] if a["definition_key"] == "official.revenue.growth")
    alias = next(key for key, value in context["numeric_aliases"].items() if value == anchor["anchor_id"])
    return context, anchor, alias


def envelope(text, facts):
    return {"proposal": {"hypotheses": [{"statement": text, "supporting_fact_ids": facts,
        "conditions": [{"condition_role": "invalidation", "text": "下一期经营走弱", "check": None}],
        "alternative_explanation": "低基数可能影响持续性"}], "unknowns": []},
        "plans": [], "structured_bindings": []}


def test_anchor_compiles_then_replays_exactly():
    context, anchor, alias = numeric_context()
    proposal, proof = compile_numeric_stage("operating_quality", envelope("{{num:" + alias + "}}，持续性待核查", anchor["required_fact_ids"]), context, SpecialistProposalV1)
    assert "18.40%" in proposal["hypotheses"][0]["statement"]
    validate_numeric_stage("operating_quality", proposal, proof, context, SpecialistProposalV1)


@pytest.mark.parametrize("text", ["营收增长25%", "营收增长２５％", "增长2\u200b5%", "百分之二十五", "增长两成", "增长twenty-five percent", "增长2.5e1%", "增速一半", "1/4的收入", "截至2026年", "公司600803"])
def test_explicit_quantity_literals_cannot_hide_behind_valid_reference(text):
    context, anchor, _ = numeric_context()
    with pytest.raises(NumericNarrativeError):
        compile_numeric_stage("operating_quality", envelope(text, anchor["required_fact_ids"]), context, SpecialistProposalV1)


def test_scope_and_unknown_anchor_are_checked_per_hypothesis():
    context, _, alias = numeric_context()
    wrong_fact = context["facts"][-1]["claim_id"]
    for token in (alias, "n_unknown"):
        with pytest.raises(NumericNarrativeError):
            compile_numeric_stage("operating_quality", envelope("{{num:" + token + "}}", [wrong_fact]), context, SpecialistProposalV1)


def test_shared_unknowns_cannot_use_numbers_or_num_tokens():
    context, anchor, alias = numeric_context()
    for unknown in ("营收25%仍待查", "{{num:" + alias + "}}"):
        value = envelope("经营持续性待核查", anchor["required_fact_ids"])
        value["proposal"]["unknowns"] = [unknown]
        with pytest.raises(NumericNarrativeError):
            compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)


def test_isolated_original_index_and_receipt_do_not_retain_bad_prose():
    context, anchor, alias = numeric_context()
    value = envelope("营收增长25%", anchor["required_fact_ids"])
    good = deepcopy(value["proposal"]["hypotheses"][0])
    good["statement"] = "{{num:" + alias + "}}"
    value["proposal"]["hypotheses"].append(good)
    proposal, proof = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)
    assert proof["indices"] == [1]
    assert proof["rejections"] == [{"index": 0, "code": "numeric_literal_unbound"}]
    assert "25%" not in str(proof)
    validate_numeric_stage("operating_quality", proposal, proof, context, SpecialistProposalV1)


def test_mutated_compiled_text_or_receipt_is_not_replayed():
    context, anchor, alias = numeric_context()
    proposal, proof = compile_numeric_stage("operating_quality", envelope("{{num:" + alias + "}}", anchor["required_fact_ids"]), context, SpecialistProposalV1)
    modified = deepcopy(proposal)
    modified["hypotheses"][0]["statement"] = "营收增长25%"
    with pytest.raises(NumericNarrativeError):
        validate_numeric_stage("operating_quality", modified, proof, context, SpecialistProposalV1)
    modified_proof = deepcopy(proof)
    modified_proof["fields"] = []
    with pytest.raises(NumericNarrativeError):
        validate_numeric_stage("operating_quality", proposal, modified_proof, context, SpecialistProposalV1)


def financial_envelope():
    from tests.test_native_record import financials, fixture
    from tradingagents.research.native_record import build_native_record
    source = build_native_record(*fixture(financial_payload=financials(8)), mode="company_research")
    context = prepare_numeric_context("operating_quality", {
        "facts": [c.model_dump(mode="json") for c in source.claims if c.kind == "fact"], "metrics": []}, source)
    anchor = next(a for a in context["numeric_catalog"]["anchors"]
                  if a["definition_key"] == "financial.income.revenue"
                  and a["metadata"]["report_period"] == "2026-06-30")
    alias = next(key for key, value in context["numeric_aliases"].items() if value == anchor["anchor_id"])
    value = envelope("经营改善仍待核查", anchor["required_fact_ids"])
    condition = value["proposal"]["hypotheses"][0]["conditions"][0]
    condition["text"] = "收入失效条件：{{plan:p_threshold}}"
    operand = {k: anchor["lineage"]["source_selector"][k] for k in ("table", "field", "report_period")}
    operand["evidence_id"] = anchor["input_evidence_ids"][0]
    predicate = {"operator": "lt", "threshold": "110", "unit": "CNY"}
    condition["check"] = {"kind": "financial", "operation": "value", "current": operand, "predicate": predicate}
    root = "hypotheses.0.conditions.0"
    value["plans"] = [{"alias": "p_threshold", "field_path": root + ".text", "kind": "quantity", **predicate}]
    value["structured_bindings"] = [
        {"field_path": root + ".check.current", "kind": "num", "alias": alias},
        {"field_path": root + ".check.predicate", "kind": "plan", "alias": "p_threshold"},
    ]
    return context, value


def test_structural_predicate_is_exact_and_qualifies_model_plan():
    context, value = financial_envelope()
    proposal, proof = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
    assert "110.00元（非已披露事实）" in proposal["hypotheses"][0]["conditions"][0]["text"]
    validate_numeric_stage("operating_quality", proposal, proof, context, SpecialistProposalV1)
    for change in ("threshold", "operator"):
        altered = deepcopy(value)
        altered["plans"][0][change] = "111" if change == "threshold" else "gt"
        with pytest.raises(NumericNarrativeError):
            compile_numeric_stage("operating_quality", altered, context, SpecialistProposalV1)
    value["structured_bindings"] = []
    with pytest.raises(NumericNarrativeError):
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)


def test_unknown_financial_frequency_cannot_be_used_as_growth():
    context, value = financial_envelope()
    check = value["proposal"]["hypotheses"][0]["conditions"][0]["check"]
    current = check["current"]
    base = next(a for a in context["numeric_catalog"]["anchors"]
                if a["definition_key"] == "financial.income.revenue"
                and a["lineage"]["source_selector"]["report_period"] == "2025-06-30")
    check.update(operation="growth", base={**current, "report_period": base["lineage"]["source_selector"]["report_period"]})
    value["proposal"]["hypotheses"][0]["supporting_fact_ids"].extend(base["required_fact_ids"])
    check["predicate"]["unit"] = value["plans"][0]["unit"] = "ratio"
    alias = next(key for key, aid in context["numeric_aliases"].items() if aid == base["anchor_id"])
    value["structured_bindings"].append({"field_path": "hypotheses.0.conditions.0.check.base", "kind": "num", "alias": alias})
    with pytest.raises(NumericNarrativeError, match="numeric_basis_mismatch"):
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)


def test_future_plan_date_is_not_a_historical_observation():
    context, value = financial_envelope()
    value["proposal"]["hypotheses"][0]["conditions"][0] = {
        "condition_role": "invalidation", "text": "后续核查：{{plan:p_date}}", "check": None}
    value["structured_bindings"] = []
    value["plans"] = [{"alias": "p_date", "field_path": "hypotheses.0.conditions.0.text",
                       "kind": "date", "date": "2027-01-01"}]
    proposal, _ = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
    assert "模型提出的观察日期2027-01-01（非已披露事实）" in proposal["hypotheses"][0]["conditions"][0]["text"]
    value["plans"][0]["date"] = context["numeric_analysis_date"]
    with pytest.raises(NumericNarrativeError, match="numeric_plan_mismatch"):
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)


def test_forecast_fragment_is_labeled_but_surrounding_semantics_remain_unchecked():
    context, _, _ = numeric_context()
    forecast = next(a for a in context["numeric_catalog"]["anchors"] if a["basis"] == "institution_forecast")
    alias = next(k for k, aid in context["numeric_aliases"].items() if aid == forecast["anchor_id"])
    proposal, _ = compile_numeric_stage("operating_quality",
        envelope("已实现{{num:" + alias + "}}", forecast["required_fact_ids"]), context, SpecialistProposalV1)
    text = proposal["hypotheses"][0]["statement"]
    assert text.startswith("已实现") and "机构预测，非已实现" in text
