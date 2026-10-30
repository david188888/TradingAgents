"""Sanitized structural regressions from the authorized 2026-10-18 capture.

Keep the wrong operating scope and missing adjudications, replacing all
company prose, facts, identifiers and values with synthetic examples.
"""

import copy
import json
import time
from types import SimpleNamespace

import pytest

from tests.test_native_model import main
from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.agents.schemas._native_stage import (
    SynthesisProposalV3,
    SynthesisReferenceError,
    validate_synthesis_reference_surface,
)
from tradingagents.execution import native_model as adapter
from tradingagents.execution.native_model_diagnostics import safe_model_diagnostic
from tradingagents.execution.native_prompt_context import reference_schema
from tradingagents.research.numeric_narrative import NumericNarrativeError, _field_scope


def captured_shape():
    return {"dimensions": [
        {"dimension": "catalyst_delivery", "claim_ids": ["fact.event"], "judgement": "事件观察"},
        {"dimension": "market_context", "claim_ids": ["fact.market"], "judgement": "市场观察"},
        {"dimension": "operating_quality", "claim_ids": ["fact.operating", "fact.event"], "judgement": "经营观察"},
        {"dimension": "valuation", "claim_ids": ["fact.valuation"], "judgement": "估值观察"}],
        "challenge_assessments": [{"challenge_id": "challenge.one"}]}


ALLOWED = {"operating_quality": ["fact.operating"], "valuation": ["fact.valuation"],
           "catalyst_delivery": ["fact.event"], "market_context": ["fact.market"]}


def test_qualitative_reference_failure_is_not_a_numeric_error_and_reports_all_sections():
    proposal = captured_shape()
    # This is the old failure path: no numeral/token is needed to misclassify it.
    with pytest.raises(NumericNarrativeError, match="numeric_anchor_scope"):
        _field_scope("synthesis", "dimensions.2.judgement", proposal, {"dimension_claim_ids": ALLOWED})
    with pytest.raises(SynthesisReferenceError) as caught:
        validate_synthesis_reference_surface(proposal, ALLOWED, ["challenge.one"])
    diagnostic = safe_model_diagnostic("synthesis", "main", "response_invalid", caught.value)
    assert diagnostic["detail_code"] == "section_validation"
    assert diagnostic["detail_codes"] == ["adjudication_coverage", "dimension_claim_reference"]
    assert diagnostic["synthesis_reference_issues"] == [
        {"code": "dimension_claim_reference", "path": ["dimensions", 2, "claim_ids"]},
        {"code": "adjudication_coverage", "path": ["adjudications"]}]
    assert "经营观察" not in json.dumps(diagnostic, ensure_ascii=False)


@pytest.mark.parametrize("adjudications", [[], [{"challenge_id": "other"}],
    [{"challenge_id": "challenge.one"}, {"challenge_id": "challenge.one"}]])
def test_omitted_wrong_or_duplicate_adjudication_cannot_pass(adjudications):
    with pytest.raises(SynthesisReferenceError) as caught:
        validate_synthesis_reference_surface({"adjudications": adjudications,
            "challenge_assessments": [{"challenge_id": "challenge.one"}]}, ALLOWED, ["challenge.one"])
    assert caught.value.code == "adjudication_coverage"


def test_zero_challenges_requires_no_invented_adjudication():
    validate_synthesis_reference_surface({"adjudications": [], "challenge_assessments": []}, ALLOWED, [])


@pytest.fixture
def context(tmp_path):
    journal, seed = setup(tmp_path / "kernel", delivery=True)
    proposals = UnifiedCaller()
    run(journal, seed, proposals)
    return next(ctx for stage, ctx in proposals.calls if stage == "synthesis")


def test_new_schema_requires_both_challenge_sections_but_old_schema_is_unchanged(context):
    schema = SynthesisProposalV3.model_json_schema()
    old = reference_schema(schema, "synthesis", context, delivery=True)
    new = reference_schema(schema, "synthesis", context, delivery=True, complete_sections=True)
    assert "adjudications" not in old["required"]
    assert {"adjudications", "challenge_assessments"} <= set(new["required"])
    for name in ("adjudications", "challenge_assessments"):
        assert new["properties"][name]["minItems"] == len(context["record"]["challenges"])
        assert new["properties"][name]["maxItems"] == len(context["record"]["challenges"])
    assert "response_id" not in new["$defs"]["ChallengeAdjudicationV1"]["properties"]
    assert new["$defs"]["ChallengeAdjudicationV1"]["properties"]["challenge_id"]["enum"] == [
        item["challenge_id"] for item in context["record"]["challenges"]]
    assert "adjudications" not in schema["required"]


def test_one_bounded_repair_receives_every_surface_failure_and_retains_required_arrays(tmp_path, context, monkeypatch):
    journal, seed = setup(tmp_path / "adapter", delivery=True)
    main(journal, "synthesis")
    prompts = []
    proposer = UnifiedCaller()

    def invoke(prompt):
        prompts.append(prompt)
        encoded, _ = json.JSONDecoder().raw_decode(prompt.split("Saved research context:\n", 1)[1])
        value = proposer("synthesis", encoded)
        if len(prompts) == 1:
            value.pop("adjudications")
            value["dimensions"][1]["claim_ids"] = encoded["dimension_claim_ids"]["operating_quality"][:1]
        return SimpleNamespace(content=json.dumps(value))

    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: SimpleNamespace(
        get_llm=lambda: SimpleNamespace(invoke=invoke)))
    model = adapter.NativeModelCaller(effective_config={"llm_provider": "deepseek",
        "quick_think_llm": "quick", "deep_think_llm": "deep"}, run_id=seed.run_id,
        ledger=journal.ledger, cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)
    model("synthesis", context)
    assert len(prompts) == 2
    assert journal.state["native.reference_schema.synthesis"] == 2
    diagnostic = journal.state["native.model_diagnostics"]["synthesis.main"]
    assert {issue["code"] for issue in diagnostic["synthesis_reference_issues"]} == {
        "dimension_claim_reference", "adjudication_coverage"}
    assert "Correct ALL listed sections" in prompts[1]
    assert "does not replace adjudications" in prompts[1]
    assert "claim_" in prompts[1].split("Required challenge/reply bindings:")[0]


def test_missing_section_is_not_silently_created_by_preflight():
    proposal = {"challenge_assessments": [{"challenge_id": "challenge.one"}]}
    original = copy.deepcopy(proposal)
    with pytest.raises(SynthesisReferenceError):
        validate_synthesis_reference_surface(proposal, ALLOWED, ["challenge.one"])
    assert proposal == original
