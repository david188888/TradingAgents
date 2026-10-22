"""Structured comparison never masquerades as a complete reported cash bridge."""

import copy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.test_native_record import financials, fixture
from tradingagents.agents.schemas._evidence_checks import EvidenceChecksV1
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.research.minimum_evidence import compute_checks
from tradingagents.research.native_record import build_native_record
from tradingagents.research.numeric_catalog import build_numeric_catalog, validate_numeric_catalog


def payload():
    value = financials(8)
    for row in value["income"]:
        row["n_income_attr_p"] = "9"
        row["n_income"] = "10" if row["end_date"].startswith("2026") else "20"
    for row in value["cashflow"]:
        row["n_cashflow_act"] = "30" if row["end_date"].startswith("2026") else "60"
    return value


def record(value=None, *, extra=(), enabled=True):
    draft, context = fixture(financial_payload=value or payload(), extra=extra)
    return build_native_record(draft, context, mode="company_research", include_minimum=True,
                               include_structured_financial=enabled)


def check(result, key="cashflow_comparison"):
    return next(c for c in result.evidence_checks.checks if c.check_id == key)


def test_no_pdf_passes_only_structured_questions_with_replayable_accounting_anchors():
    result = record()
    assert result.evidence_checks.calculation_version == "minimum-evidence-v3"
    assert len(result.evidence_checks.checks) == 5
    assert check(result, "operating_disclosures").status == check(result, "cash_conversion").status == "unavailable"
    assert check(result, "financial_baseline").status == check(result).status == "passed"
    values = {o.key: Decimal(o.value) for o in check(result).observations}
    assert values["n_income_current"] == 10  # not parent income 9
    assert values["n_cashflow_act_yoy_percent"] == -50
    assert values["cfo_minus_net_income_current"] == 20
    assert "structured_without_official_table_crosscheck" in check(result).limitations
    assert compute_checks(result) == result.evidence_checks
    assert ResearchRecordV1.model_validate_json(result.model_dump_json()) == result
    catalog = build_numeric_catalog(result)
    anchors = [a for a in catalog["anchors"] if a["lineage"].get("source_selector", {}).get("check_id") == "cashflow_comparison"]
    assert anchors and all(a["basis"] == "accounting_check" for a in anchors)
    assert all(a["metadata"]["report_period"] == "2026-06-30" for a in anchors)
    gap = next(a for a in anchors if a["definition_key"] == "check.cashflow_comparison.cfo_minus_net_income_current")
    assert len(gap["required_fact_ids"]) == 2
    claims = {c.claim_id: c for c in result.claims}
    assert {lim for fid in gap["required_fact_ids"] for lim in claims[fid].limitations if lim.startswith("source_field:")} == {
        "source_field:income[end_date=2026-06-30].n_income", "source_field:cashflow[end_date=2026-06-30].n_cashflow_act"}
    validate_numeric_catalog(result, catalog)
    # A derived comparison must be usable with its two real operands, rather
    # than forcing a model to cite every period/field in the supplier payload.
    from tradingagents.agents.schemas._research_assessment import SynthesisDimensionV1
    from tradingagents.research.native_policy import dimension_claim_ids
    from tradingagents.research.numeric_narrative import (
        compile_numeric_stage,
        prepare_numeric_context,
    )
    context = prepare_numeric_context("synthesis", {"record": result.model_dump(mode="json"),
        "dimension_claim_ids": dimension_claim_ids(result)}, result)
    alias = next(key for key, aid in context["numeric_aliases"].items() if aid == gap["anchor_id"])
    value = {"proposal": {"dimensions": [{"dimension": "operating_quality", "status": "conditional",
        "judgement": "端点差额为{{num:" + alias + "}}；尚未形成完整调节桥。", "claim_ids": gap["required_fact_ids"]}]}}
    rendered, _ = compile_numeric_stage("synthesis", value, context, SynthesisDimensionV1)
    assert "20" in rendered["dimensions"][0]["judgement"]
    value["proposal"]["dimensions"][0]["claim_ids"] = gap["required_fact_ids"][:1]
    with pytest.raises(ValueError):
        compile_numeric_stage("synthesis", value, context, SynthesisDimensionV1)


@pytest.mark.parametrize("damage", ["missing_current", "duplicate", "missing_prior", "missing_table", "no_parent_income"])
def test_missing_latest_cells_do_not_fall_back_or_synthesize_a_pair(damage):
    value = payload()
    if damage == "missing_current":
        value["cashflow"][0].pop("n_cashflow_act")
    elif damage == "duplicate":
        value["cashflow"].append(copy.deepcopy(value["cashflow"][0]))
        value["cashflow"][1] = copy.deepcopy(value["cashflow"][0])
    elif damage == "missing_prior":
        value["cashflow"] = [r for r in value["cashflow"] if r["end_date"] != "20250630"]
    elif damage == "missing_table":
        value.pop("cashflow")
    else:
        value["income"][0].pop("n_income_attr_p")
    result = record(value)
    assert check(result, "financial_baseline").status == "unavailable"
    assert check(result).status == ("passed" if damage == "no_parent_income" else "unavailable")


@pytest.mark.parametrize("base", ["0", "-60"])
def test_nonpositive_base_keeps_amount_comparison_without_percentage(base):
    value = payload()
    next(r for r in value["cashflow"] if r["end_date"] == "20250630")["n_cashflow_act"] = base
    result = record(value)
    assert check(result).status == "passed"
    observations = {o.key: o for o in check(result).observations}
    assert "n_cashflow_act_yoy_percent" not in observations
    assert Decimal(observations["n_cashflow_act_change"].value) == 30 - Decimal(base)
    assert "structured_nonpositive_growth_base:n_cashflow_act" in check(result).limitations


def test_suppliers_cannot_donate_missing_cells_or_hide_conflicting_cells():
    first, second = payload(), payload()
    first["cashflow"][0].pop("n_cashflow_act")
    second["income"][0].pop("n_income")
    extra = (("financial_statements", "sina.financial_statements", second, None),)
    # Use the actual collector capability, not an unqualified extra source.
    from tradingagents.research.evidence_freeze import CAP_FUNDAMENTALS
    extra = ((CAP_FUNDAMENTALS, extra[0][1], second, None),)
    result = record(first, extra=extra)
    assert check(result).status == "unavailable"
    second = payload()
    second["cashflow"][0]["n_cashflow_act"] = "31"
    result = record(extra=((CAP_FUNDAMENTALS, "sina.financial_statements", second, None),))
    assert check(result).status == "conflict"
    assert "structured_supplier_discrepancy:n_cashflow_act:current" in check(result).missing


@pytest.mark.parametrize("mutation", ["value", "question", "scope", "version", "duplicate"])
def test_check_provenance_and_question_tampering_is_rejected(mutation):
    raw = record().model_dump(mode="json")
    saved = raw["evidence_checks"]["checks"][-1]
    if mutation == "value":
        saved["observations"][0]["value"] = "999"
    elif mutation == "question":
        saved["question"] = "完整现金流桥已核对"
    elif mutation == "scope":
        saved["question_scope"] = "cash_conversion.reported_bridge"
    elif mutation == "version":
        raw["evidence_checks"]["calculation_version"] = "minimum-evidence-v2"
    else:
        raw["evidence_checks"]["checks"][-1] = raw["evidence_checks"]["checks"][-2]
    with pytest.raises(ValueError):
        ResearchRecordV1.model_validate(raw)


def test_v2_replay_retains_exact_saved_three_checks_and_forbids_new_ids():
    old = record(enabled=False)
    before = old.model_dump_json()
    assert old.evidence_checks.calculation_version == "minimum-evidence-v2"
    assert len(compute_checks(old).checks) == 3
    assert old.model_dump_json() == before
    raw = old.evidence_checks.model_dump(mode="json")
    raw["checks"][0]["check_id"] = "financial_baseline"
    with pytest.raises(ValidationError):
        EvidenceChecksV1.model_validate(raw)


def test_legacy_prompt_schema_retains_the_three_original_check_choices():
    from tradingagents.agents.schemas._native_stage import ChallengesProposalV2
    from tradingagents.execution.native_prompt_context import legacy_check_schema
    schema = ChallengesProposalV2.model_json_schema()
    field = schema["$defs"]["ChallengeProposalV2"]["properties"]["check_id"]["anyOf"][0]
    assert field["enum"][-2:] == ["financial_baseline", "cashflow_comparison"]
    legacy_check_schema(schema)
    assert field["enum"] == ["operating_disclosures", "cash_conversion", "valuation_context"]


def test_repeating_growth_retains_full_host_precision_without_loosening_supplier_values():
    from tradingagents.research.numeric_catalog import render_numeric_anchor
    from tradingagents.research.verification_tools import _number, _Unavailable
    value = payload()
    value["cashflow"][0]["n_cashflow_act"] = "31"
    result = record(value)
    observed = next(o for o in check(result).observations if o.key == "n_cashflow_act_yoy_percent")
    assert len(observed.value) > 64
    with pytest.raises(_Unavailable):
        _number(observed.value)  # external source parsing is unchanged
    catalog = build_numeric_catalog(result)
    anchor = next(a for a in catalog["anchors"] if a["definition_key"] == "check.cashflow_comparison.n_cashflow_act_yoy_percent")
    assert anchor["value"] == observed.value
    assert "-48.33%" in render_numeric_anchor(anchor)
    validate_numeric_catalog(result, catalog)


@pytest.mark.parametrize("damage", ["future_disclosure", "single_quarter", "wrong_same_period"])
def test_future_single_quarter_or_nonmatching_period_cannot_fill_current_pair(damage):
    value = payload()
    if damage == "future_disclosure":
        value["cashflow"][0]["ann_date"] = "20271001"
    elif damage == "single_quarter":
        value["cashflow"][0]["report_type"] = "2"
    else:
        value["cashflow"][0]["end_date"] = "20260331"
    assert check(record(value)).status == "unavailable"


@pytest.mark.parametrize("conflict", [False, True])
def test_official_crosscheck_is_optional_and_uses_raw_cell_precision(conflict):
    from tests.test_minimum_evidence import documents, fixture as official_fixture
    from tests.test_native_record import source
    from tradingagents.research.evidence_freeze import (
        CAP_FUNDAMENTALS,
        CapabilityStatus,
        FrozenCapability,
    )
    draft, context = official_fixture(forecasts=False, peers=False, snapshot=False)
    fields = {row["field"]: row for row in documents()[0]["numeric_rows"] if row["kind"] == "financial"}
    mapping = {"income": {"revenue": "revenue", "n_income": "consolidated_net_income", "n_income_attr_p": "parent_net_income"},
               "cashflow": {"n_cashflow_act": "cfo"}}
    value = {table: [{"ts_code": "600803.SH", "report_type": "1", "end_date": period, "ann_date": ann,
                      **{key: fields[field][attr] for key, field in names.items()}}
                     for attr, period, ann in (("current", "20260630", "20260830"), ("previous", "20250630", "20250830"))]
             for table, names in mapping.items()}
    if conflict:
        value["cashflow"][0]["n_cashflow_act"] = str(Decimal(value["cashflow"][0]["n_cashflow_act"]) + 1000000)
    evidence = source(CAP_FUNDAMENTALS, "sina.financial_statements", value, run_id=draft.run_id, ticker=draft.ticker)
    context[evidence["evidence_id"]] = value
    draft = draft.model_copy(update={"evidence": (*draft.evidence, evidence), "capabilities": (*draft.capabilities,
        FrozenCapability(capability=CAP_FUNDAMENTALS, status=CapabilityStatus.QUALIFIED, reason="offline structured fields"))})
    result = build_native_record(draft, context, mode="company_research", include_minimum=True, include_structured_financial=True)
    assert check(result).status == ("conflict" if conflict else "passed")
    assert "available_official_cells_crosschecked" in check(result).satisfied
    assert "structured_without_official_table_crosscheck" not in check(result).limitations
