"""Inline metadata becomes canonical paths without changing evidence gates."""
import json
from copy import deepcopy

import pytest

from tests.factual_premise_fixtures import bind
from tests.test_factual_premises import IDENTITY, proposal
from tests.test_numeric_catalog import growth_record
from tests.test_numeric_narrative import financial_envelope, numeric_context
from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV3,
    SpecialistProposalV1,
    SynthesisProposalV3,
)
from tradingagents.agents.schemas._research_dialogue import ResponsesProposalV1
from tradingagents.agents.schemas._research_focus import ResearchFocusResponseV1
from tradingagents.agents.schemas._search import SearchReviewProposalV1
from tradingagents.research.inline_bindings import (
    InlineBindingError,
    decode_inline_envelope,
    inline_prompt_schema,
)
from tradingagents.research.numeric_narrative import (
    NumericNarrativeError,
    compile_numeric_stage,
    prepare_numeric_context,
    validate_numeric_stage,
)


def localize(envelope):
    """Test input builder; paths come only from trusted legacy fixtures."""
    value = {"proposal": deepcopy(envelope["proposal"])}
    def target(path):
        parts = path.split(".")
        parent = value["proposal"]
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        return parent, int(parts[-1]) if isinstance(parent, list) else parts[-1]
    def wrapper(path, key):
        parent, field = target(path)
        if not isinstance(parent[field], dict) or key not in parent[field]:
            parent[field] = {key: parent[field]}
        return parent[field]
    for entry in envelope.get("premises", []):
        wrapper(entry["field_path"], "text")["premise"] = {
            k: deepcopy(v) for k, v in entry.items() if k != "field_path"}
    for entry in envelope.get("plans", []):
        path = entry["field_path"]
        field = wrapper(path, "value" if path.endswith(".observation_date") else "text")
        field.setdefault("plans", []).append({k: deepcopy(v) for k, v in entry.items() if k != "field_path"})
    for entry in envelope.get("structured_bindings", []):
        wrapper(entry["field_path"], "value")["binding"] = {
            k: deepcopy(v) for k, v in entry.items() if k != "field_path"}
    return value


@pytest.fixture
def context():
    record = growth_record()
    return prepare_numeric_context("operating_quality", {
        "facts": [c.model_dump(mode="json") for c in record.claims if c.kind == "fact"], "metrics": []},
        record, identity=IDENTITY)


def test_inline_premises_compile_to_the_same_text_and_replay(context):
    old = proposal(context)
    value = localize(old)
    before = deepcopy(value)
    canonical = decode_inline_envelope(value)
    compiled, proof = compile_numeric_stage("operating_quality", canonical, context, SpecialistProposalV1)
    assert compiled == compile_numeric_stage("operating_quality", old, context, SpecialistProposalV1)[0]
    assert {p["field_path"] for p in proof["envelope"]["premises"]} == {
        "hypotheses.0.statement", "hypotheses.0.alternative_explanation"}
    assert value == before
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)


def test_numeric_only_inline_guidance_does_not_request_premise_metadata():
    from tradingagents.research.inline_bindings import inline_binding_instructions
    text = inline_binding_instructions(premises=False)
    assert "{text, premise}" not in text
    assert "observation_ids" not in text


def test_local_plan_and_structured_operands_keep_exact_predicate_binding():
    ctx, old = financial_envelope()
    canonical = decode_inline_envelope(localize(old), premises=False)
    compiled, proof = compile_numeric_stage("operating_quality", canonical, ctx, SpecialistProposalV1)
    assert compiled == compile_numeric_stage("operating_quality", old, ctx, SpecialistProposalV1)[0]
    assert {b["field_path"] for b in canonical["structured_bindings"]} == {
        "hypotheses.0.conditions.0.check.current", "hypotheses.0.conditions.0.check.predicate"}
    assert canonical["plans"][0]["field_path"] == "hypotheses.0.conditions.0.text"
    validate_numeric_stage("operating_quality", compiled, proof, ctx, SpecialistProposalV1)
    canonical["plans"][0]["threshold"] = "111"
    with pytest.raises(NumericNarrativeError, match="numeric_plan_mismatch"):
        compile_numeric_stage("operating_quality", canonical, ctx, SpecialistProposalV1)


def test_future_date_binding_is_generated_from_its_own_slot():
    ctx, _, _ = numeric_context()
    value = {"proposal": {"challenges": [{"hypothesis_id": "h.saved", "statement": "观察窗口仍需核查",
        "severity": "minor", "risk_type": "operations", "proposed_test": "等待后续披露",
        "verifiability": "future_observation", "observation_date": {
            "value": "2027-01-01", "binding": {"kind": "plan", "alias": "p_date"},
            "plans": [{"alias": "p_date", "kind": "date", "date": "2027-01-01"}]}}]}}
    canonical = decode_inline_envelope(value, premises=False)
    assert canonical["plans"][0]["field_path"] == "challenges.0.observation_date"
    compiled, proof = compile_numeric_stage("challenge", canonical, ctx, ChallengesProposalV3)
    validate_numeric_stage("challenge", compiled, proof, ctx, ChallengesProposalV3)


def test_extra_unknowns_annotation_is_ignored_but_the_text_is_checked(context):
    value = localize(proposal(context))
    value["proposal"]["unknowns"] = [{"text": "客户结构仍待核查", "premise": "unused malformed content"}]
    canonical = decode_inline_envelope(value)
    assert canonical["proposal"]["unknowns"] == ["客户结构仍待核查"]
    assert all(not p["field_path"].startswith("unknowns") for p in canonical["premises"])
    compile_numeric_stage("operating_quality", canonical, context, SpecialistProposalV1)
    value["proposal"]["unknowns"][0]["text"] = "营收增长25%仍待查"
    with pytest.raises(NumericNarrativeError, match="numeric_literal_unbound"):
        compile_numeric_stage("operating_quality", decode_inline_envelope(value), context, SpecialistProposalV1)


@pytest.mark.parametrize("damage", ["observation", "number", "missing"])
def test_bad_item_keeps_its_own_index_and_valid_sibling(context, damage):
    old = proposal(context)
    old["proposal"]["hypotheses"].append(deepcopy(old["proposal"]["hypotheses"][0]))
    old = bind("operating_quality", old, context)
    value = localize(old)
    field = value["proposal"]["hypotheses"][0]["statement"]
    if damage == "observation":
        field["premise"]["observation_ids"] = ["o.unknown"]
    elif damage == "number":
        field["text"] = "营收增长25%"
    else:
        field.pop("premise")
    canonical = decode_inline_envelope(value)
    compiled, proof = compile_numeric_stage("operating_quality", canonical, context, SpecialistProposalV1, isolate=True)
    assert proof["indices"] == [1]
    assert proof["rejections"][0]["index"] == 0
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)


@pytest.mark.parametrize("damage", ["top_legacy", "path", "premise_path", "unknown_metadata"])
def test_inline_input_never_accepts_or_guesses_model_paths(context, damage):
    value = localize(proposal(context))
    field = value["proposal"]["hypotheses"][0]["statement"]
    if damage == "top_legacy":
        value["premises"] = []
    elif damage == "path":
        field["field_path"] = "proposal.hypotheses.0.statement"
    elif damage == "premise_path":
        field["premise"]["field_path"] = "hypotheses.99.statement"
    else:
        field["extra"] = "unowned metadata"
    with pytest.raises(InlineBindingError):
        decode_inline_envelope(value)


@pytest.mark.parametrize("model", [SpecialistProposalV1, ChallengesProposalV3, SynthesisProposalV3,
                                 ResponsesProposalV1, ResearchFocusResponseV1, SearchReviewProposalV1])
def test_prompt_schema_has_no_model_paths_and_all_references_resolve(model):
    schema = inline_prompt_schema(model.model_json_schema())
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"proposal"}
    def check(node):
        if isinstance(node, dict):
            assert "field_path" not in node.get("properties", {})
            if "$ref" in node:
                assert node["$ref"].removeprefix("#/$defs/") in schema["$defs"]
            for ref in node.get("discriminator", {}).get("mapping", {}).values():
                assert ref.removeprefix("#/$defs/") in schema["$defs"]
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(schema)
    assert "observation_ids" in json.dumps(schema)
