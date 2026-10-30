"""Distinct structural failures and sanitized locations, without provider calls."""

import json

import pytest

from tests import test_native_model as model_tests, test_synthesis_sections as section_tests
from tests.test_native_model import caller
from tests.test_numeric_narrative import envelope, numeric_context
from tradingagents.agents.schemas._native_stage import SpecialistProposalV1, SynthesisReferenceError
from tradingagents.agents.schemas._numeric_stage import NumericStageEnvelopeV1
from tradingagents.execution.native_model_diagnostics import safe_model_diagnostic
from tradingagents.research import numeric_narrative as numeric

journal = model_tests.journal
sample = section_tests.sample


@pytest.mark.parametrize("kind,code,path", [
    ("proposal", "numeric_proposal_schema", ["hypotheses", 0, "statement"]),
    ("envelope", "numeric_envelope_schema", ["plans"]),
    ("catalog", "numeric_catalog_invalid", ["numeric_catalog"]),
    ("cutoff", "numeric_cutoff_invalid", ["numeric_analysis_date"]),
    ("condition", "numeric_condition_reference", ["change_conditions", 0, "text"]),
    ("receipt", "numeric_receipt_invalid", ["path"]),
])
def test_distinct_numeric_failures_preserve_structural_location(kind, code, path):
    context, anchor, _ = numeric_context()
    value = envelope("待核查", anchor["required_fact_ids"])
    with pytest.raises(numeric.NumericNarrativeError) as caught:
        if kind == "proposal":
            value["proposal"]["hypotheses"][0].pop("statement")
            numeric._schema_validate(SpecialistProposalV1, value["proposal"])
        elif kind == "envelope":
            numeric._canonical_envelope({"proposal": {}, "plans": None}, SpecialistProposalV1)
        elif kind == "catalog":
            context.pop("numeric_catalog")
            numeric.compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
        elif kind == "cutoff":
            numeric._cutoff({"numeric_analysis_date": "invalid"})
        elif kind == "condition":
            numeric._compile_field("synthesis", "change_conditions.0.text", "待核查",
                {"change_conditions": [{"hypothesis_id": "missing", "invalidation_index": 0}]},
                {"record": {"hypotheses": []}}, {}, [0])
        else:
            numeric.validate_numeric_field({}, context["numeric_catalog"])
    diagnostic = safe_model_diagnostic("operating_quality", "main", "response_invalid", caught.value,
        schema=SpecialistProposalV1, envelope_schema=NumericStageEnvelopeV1)
    assert diagnostic["detail_code"] == code
    assert path in [issue["path"] for issue in diagnostic["issues"]]


def test_wrapped_schema_failure_never_leaks_unknown_keys_or_model_text():
    secret = "PRIVATE-MODEL-TEXT"
    with pytest.raises(numeric.NumericNarrativeError) as caught:
        numeric._schema_validate(SpecialistProposalV1, {secret: secret})
    result = safe_model_diagnostic("operating_quality", "main", "response_invalid", caught.value,
        schema=SpecialistProposalV1)
    assert result["issues"] == [{"path": ["<undeclared>"]}]
    assert secret not in json.dumps(result)


def test_segmented_diagnostic_exposes_all_codes_instead_of_first_failure():
    error = SynthesisReferenceError([
        ("numeric_proposal_schema", ("dimensions", 1)),
        ("premise_observation_scope", ("overall",)),
    ])
    result = safe_model_diagnostic("synthesis", "main", "response_invalid", error)
    assert result["detail_code"] == "section_validation"
    assert result["detail_codes"] == ["numeric_proposal_schema", "premise_observation_scope"]
    assert result["synthesis_reference_issues"] == [
        {"code": "numeric_proposal_schema", "path": ["dimensions", 1]},
        {"code": "premise_observation_scope", "path": ["overall"]},
    ]


def test_numeric_repair_names_exact_field_and_available_values(journal):
    journal.put("identity", {"workflow_version": "evidence-production-v8"})
    journal.put("native.model_diagnostics", {"operating_quality.main": {
        "detail_code": "numeric_proposal_schema",
        "issues": [{"path": ["hypotheses", 1, "conditions", 0, "text"]}],
    }})
    prompt = caller(journal)._repair_prompt("operating_quality", "original", {
        "numeric_aliases": {"n_0000": "anchor.saved"}, "numeric_meta": {},
    })
    assert "hypotheses[1].conditions[0].text" in prompt
    assert "n_0000" in prompt


def test_challenge_repair_groups_conditions_by_owning_hypothesis(journal):
    journal.put("identity", {"workflow_version": "evidence-production-v8"})
    journal.put("native.model_diagnostics", {"challenge.main": {"detail_code": "challenge_condition_reference"}})
    prompt = caller(journal)._repair_prompt("challenge", "original", {"conditions": {
        "condition.one": {"hypothesis_id": "h.one", "text": "条件甲"},
        "condition.two": {"hypothesis_id": "h.two", "text": "条件乙"},
    }})
    assert '"h.one"' in prompt and '"condition.one"' in prompt
    assert '"h.two"' in prompt and '"condition.two"' in prompt
    assert "same hypothesis" in prompt


def test_dispatched_repair_preserves_legacy_hash(journal):
    import hashlib

    from tradingagents.execution.native_model import _REPAIR_INSTRUCTION
    journal.put("identity", {"workflow_version": "evidence-production-v8"})
    journal.put("native.model_diagnostics", {"challenge.main": {"detail_code": "challenge_condition_reference"}})
    original = "original\n" + _REPAIR_INSTRUCTION
    journal.put("native.prompt.challenge.repair", hashlib.sha256(original.encode()).hexdigest())
    assert caller(journal)._repair_prompt("challenge", "original", {}) == original


@pytest.mark.parametrize("prefix", [[], ["PRIVATE-MALFORMED-SECTION"]])
def test_section_schema_failure_keeps_nested_location(sample, prefix):
    from tradingagents.research.synthesis_sections import parse_sections
    context, value = sample
    value["proposal"]["dimensions"][1].pop("judgement")
    value["proposal"]["dimensions"] = prefix + value["proposal"]["dimensions"]
    diagnostics = []
    candidate = parse_sections(value, context, phase="main", diagnostics=diagnostics)
    assert candidate["failures"]["dimension:valuation"] == "numeric_proposal_schema"
    assert ["dimensions", 1 + len(prefix), "judgement"] in [list(p) for p in diagnostics]
