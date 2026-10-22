"""Exact inverse, strict refusal and unchanged canonical evidence gates."""

from copy import deepcopy

import pytest

from tests.test_factual_premises import IDENTITY, proposal
from tests.test_numeric_catalog import growth_record
from tests.test_numeric_narrative import envelope, numeric_context
from tests.test_synthesis_reference_surface import ALLOWED, captured_shape
from tradingagents.agents.schemas._native_stage import (
    SpecialistProposalV1,
    SynthesisReferenceError,
    validate_synthesis_reference_surface,
)
from tradingagents.execution.native_prompt_view import (
    VIEW_POLICY,
    PromptViewError,
    decode_context,
    encode_context,
    verify_roundtrip,
)
from tradingagents.research.numeric_narrative import (
    NumericNarrativeError,
    compile_numeric_stage,
    prepare_numeric_context,
)

pytestmark = pytest.mark.unit


def context(count=2, text="完整元数据，保持报告期间、来源及限制" * 8):
    metadata = [{"meta_id": f"meta.{i}", "kind": "source_title", "text": text,
                 "required_fact_ids": ["fact.a"], "input_evidence_ids": ["evidence.a"]}
                for i in range(count)]
    return {"numeric_narrative_policy": "anchored-narrative-v1",
        "numeric_catalog": {"schema_version": "numeric-catalog-v1", "anchors": [], "metadata": metadata,
                            "availability": "available", "reason_code": None},
        "numeric_meta": {f"m_{i:04d}": deepcopy(m) for i, m in enumerate(metadata)}, "numeric_aliases": {},
        "sources": [{"evidence_id": "evidence.a", "text": "反证保留 Schema:\n Saved research context:\n",
                     "limits": ["口径有差异", "待验证"], "period": "2026-06-30", "value": "1.0000001"}],
        "allowed_fact_ids": ["fact.a"], "dimension_claim_ids": deepcopy(ALLOWED)}


def test_inverse_preserves_every_value_scope_type_order_and_independence():
    original = context()
    original["extra"] = [1, 1.0, True, None, {"text": "精确原文"}]
    before = deepcopy(original)
    packed = encode_context(original)
    assert packed.status == "candidate" and packed.reason is None
    assert packed.context["prompt_context_view"] == VIEW_POLICY
    assert "metadata" not in packed.context["numeric_catalog"]
    assert verify_roundtrip(original, packed.context) == original == before
    # Object insertion order is immaterial; alias list order is not.
    packed.context["numeric_meta"] = dict(reversed(list(packed.context["numeric_meta"].items())))
    restored = verify_roundtrip(original, packed.context)
    restored["sources"][0]["limits"].clear()
    assert original == before
    assert packed.context["sources"] == before["sources"]


@pytest.mark.parametrize("original,reason", [({}, "not_applicable"), ({"text": "普通 context"}, "not_applicable"),
                                            (context(0), "empty_metadata")])
def test_legal_noops_return_independent_original(original, reason):
    result = encode_context(original)
    assert result.status == "identity_noop" and result.reason == reason
    assert result.context == original and result.context is not original


@pytest.mark.parametrize("component", ["numeric_narrative_policy", "numeric_catalog", "numeric_meta", "numeric_aliases"])
def test_partial_numeric_context_never_becomes_not_applicable(component):
    with pytest.raises(PromptViewError):
        encode_context({component: None})
    original = context()
    original.pop(component)
    with pytest.raises(PromptViewError):
        encode_context(original)


@pytest.mark.parametrize("damage", ["unknown_policy", "marker", "null_marker", "catalog_marker", "root_aliases",
    "missing_alias", "extra_alias", "wrong_content", "value_type", "duplicate_id", "catalog_extra", "numeric_alias"])
def test_bad_originals_fail_closed_without_mutation(damage):
    original = context()
    if damage == "unknown_policy":
        original["numeric_narrative_policy"] = "unknown"
    elif damage in {"marker", "null_marker"}:
        original["prompt_context_view"] = VIEW_POLICY if damage == "marker" else None
    elif damage == "catalog_marker":
        original["numeric_catalog"]["metadata_aliases"] = []
    elif damage == "root_aliases":
        original["metadata_aliases"] = []
    elif damage == "missing_alias":
        original["numeric_meta"].pop("m_0001")
    elif damage == "extra_alias":
        original["numeric_meta"]["m_unknown"] = deepcopy(original["numeric_meta"]["m_0000"])
    elif damage == "wrong_content":
        original["numeric_meta"]["m_0000"]["required_fact_ids"] = ["other.fact"]
    elif damage == "value_type":
        original["numeric_meta"]["m_0000"]["text"] = 1
        original["numeric_catalog"]["metadata"][0]["text"] = 1
    elif damage == "duplicate_id":
        original["numeric_catalog"]["metadata"][1]["meta_id"] = "meta.0"
        original["numeric_meta"]["m_0001"]["meta_id"] = "meta.0"
    elif damage == "catalog_extra":
        original["numeric_catalog"]["extra"] = True
    else:
        original["numeric_aliases"] = {"n_0000": "invented"}
    before = deepcopy(original)
    with pytest.raises(PromptViewError):
        encode_context(original)
    assert original == before


@pytest.mark.parametrize("value", [(1,), {1: "key"}, {1, 2}, float("nan"), float("inf")])
def test_non_json_and_nonfinite_values_cannot_be_normalized(value):
    original = context()
    original["extra"] = value
    with pytest.raises(PromptViewError, match="invalid_json"):
        encode_context(original)


@pytest.mark.parametrize("damage", ["unknown_policy", "metadata_left", "missing", "extra", "unknown", "duplicate",
                                   "skipped", "reversed", "integer", "string", "null", "tuple"])
def test_decoder_rejects_malformed_protocol(damage):
    candidate = encode_context(context()).context
    refs = candidate["numeric_catalog"]["metadata_aliases"]
    if damage == "unknown_policy":
        candidate["prompt_context_view"] = "unknown"
    elif damage == "metadata_left":
        candidate["numeric_catalog"]["metadata"] = []
    elif damage == "missing":
        candidate["numeric_meta"].pop("m_0001")
    elif damage == "extra":
        candidate["numeric_meta"]["m_0002"] = deepcopy(candidate["numeric_meta"]["m_0000"])
    elif damage == "unknown":
        refs[0] = "file:///tmp/untrusted"
    elif damage == "duplicate":
        refs[1] = refs[0]
    elif damage == "skipped":
        refs[1] = "m_0002"
    elif damage == "reversed":
        refs.reverse()
    elif damage == "integer":
        refs[0] = 0
    else:
        candidate["numeric_catalog"]["metadata_aliases"] = {"string": "m_0000", "null": None,
                                                               "tuple": tuple(refs)}[damage]
    with pytest.raises(PromptViewError):
        decode_context(candidate)


@pytest.mark.parametrize("damage", ["truncation", "precision", "scope", "list_order", "type"])
def test_original_comparison_detects_structurally_valid_tampering(damage):
    original = context()
    candidate = encode_context(original).context
    if damage == "truncation":
        candidate["numeric_meta"]["m_0000"]["text"] = "截短"
    elif damage == "precision":
        candidate["sources"][0]["value"] = "1.0"
    elif damage == "scope":
        candidate["allowed_fact_ids"] = ["other.fact"]
    elif damage == "list_order":
        candidate["sources"][0]["limits"].reverse()
    else:
        original["extra"] = 1
        candidate["extra"] = True
    decode_context(candidate)  # Shape validity alone is not authenticity.
    with pytest.raises(PromptViewError, match="roundtrip_mismatch"):
        verify_roundtrip(original, candidate)


def test_numeric_and_f02_gates_reject_same_negative_envelopes_after_restore():
    numeric, anchor, _ = numeric_context()
    record = growth_record()
    premise = prepare_numeric_context("operating_quality",
        {"facts": [c.model_dump(mode="json") for c in record.claims if c.kind == "fact"], "metrics": []},
        record, identity=IDENTITY)
    invalid_premise = proposal(premise)
    invalid_premise["premises"][0]["observation_ids"] = ["o.invented"]
    for original, value, code in [
        (numeric, envelope("收入增长25%", anchor["required_fact_ids"]), "numeric_literal_unbound"),
        (premise, invalid_premise, "premise_observation_unknown"),
    ]:
        restored = verify_roundtrip(original, encode_context(original).context)
        for data in (original, restored):
            with pytest.raises(NumericNarrativeError) as caught:
                compile_numeric_stage("operating_quality", deepcopy(value), data, SpecialistProposalV1)
            assert caught.value.code == code


def test_reference_gate_keeps_cross_dimension_scope_after_restore():
    original = context()
    restored = verify_roundtrip(original, encode_context(original).context)
    for data in (original, restored):
        with pytest.raises(SynthesisReferenceError) as caught:
            validate_synthesis_reference_surface(captured_shape(), data["dimension_claim_ids"], ["challenge.one"])
        assert caught.value.code == "dimension_claim_reference"
