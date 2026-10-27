"""Packet citations mechanically recover canonical fact and premise bindings."""
from copy import deepcopy

import pytest

from tests import test_inline_bindings as fixtures
from tradingagents.agents.schemas._native_stage import SpecialistProposalV1
from tradingagents.research.inline_bindings import decode_inline_envelope, inline_prompt_schema
from tradingagents.research.numeric_narrative import compile_numeric_stage

context = fixtures.context


def packetize(envelope, context):
    value = fixtures.localize(envelope)
    aliases = {o["observation_id"]: f"E{i:03d}" for i, o in enumerate(context["factual_observations"], 1)}
    def visit(node):
        if isinstance(node, dict):
            for field in ("supporting_fact_ids", "claim_ids", "key_claim_ids", "evidence_ids"):
                node.pop(field, None)
            if "premise" in node:
                binding = node.pop("premise")
                node["citations"] = [aliases[x] for x in binding["observation_ids"]]
                node["pending_questions"] = binding["pending_questions"]
            for x in node.values():
                visit(x)
        elif isinstance(node, list):
            for x in node:
                visit(x)
    visit(value)
    return value


def test_citations_generate_both_support_and_premise_lists(context):
    from tradingagents.research.evidence_packets import decode_packet_envelope
    old = fixtures.proposal(context)
    wire = packetize(old, context)
    decoded = decode_inline_envelope(decode_packet_envelope(wire, context))
    actual, proof = compile_numeric_stage("operating_quality", decoded, context, SpecialistProposalV1)
    expected, _ = compile_numeric_stage("operating_quality", old, context, SpecialistProposalV1)
    assert actual == expected
    assert proof["envelope"]["premises"]
    assert "supporting_fact_ids" not in wire["proposal"]["hypotheses"][0]


@pytest.mark.parametrize("citations", [["E999999"], [123], "E001", {"bad": "E001"}])
def test_unknown_citation_rejects_only_its_hypothesis(context, citations):
    from tradingagents.research.evidence_packets import decode_packet_envelope
    wire = packetize(fixtures.proposal(context), context)
    wire["proposal"]["hypotheses"].append(deepcopy(wire["proposal"]["hypotheses"][0]))
    wire["proposal"]["hypotheses"][0]["statement"]["citations"] = citations
    canonical = decode_inline_envelope(decode_packet_envelope(wire, context))
    _, proof = compile_numeric_stage("operating_quality", canonical, context, SpecialistProposalV1, isolate=True)
    assert proof["indices"] == [1]
    assert proof["rejections"][0]["code"] == "premise_observation_unknown"


def test_schema_limits_citations_and_does_not_request_parallel_fact_lists(context):
    from tradingagents.research.evidence_packets import packet_schema
    schema = packet_schema(inline_prompt_schema(SpecialistProposalV1.model_json_schema()), context)
    import json
    text = json.dumps(schema)
    assert '"citations"' in text
    assert '"supporting_fact_ids"' not in text
    assert '"observation_ids"' not in text
    assert '"E001"' in text


def test_packet_keeps_all_observations_and_source_retrieval_is_scoped():
    from tradingagents.research.evidence_packets import packet_context, retrieve_evidence
    ctx = {"facts": [{"claim_id": "f.a", "evidence_ids": ["e.a"]}],
        "sources": [{"evidence_id": "e.a", "source_name": "report", "content": {"text": "收入增加。现金流减少。", "locator_label": "第十二页"}},
                    {"evidence_id": "e.foreign", "content": {"text": "现金流很好"}}],
        "factual_observations": [{"observation_id": "o.a", "text": "收入增加", "kind": "source", "fact_ids": ["f.a"], "evidence_ids": ["e.a"], "limitations": ["原因待查"]}],
        "numeric_catalog": {"anchors": [], "metadata": []}, "numeric_aliases": {}, "numeric_meta": {}}
    found = retrieve_evidence(ctx, "现金流", limit=2)
    assert found and {x["evidence_id"] for x in found} == {"e.a"}
    assert "现金流减少" in found[0]["text"]
    view = packet_context("operating_quality", ctx)
    assert "E001" in view["evidence_packet_markdown"]
    assert "收入增加" in view["evidence_packet_markdown"]
    assert "原因待查" in view["evidence_packet_markdown"]
    assert "第十二页" in view["evidence_packet_markdown"]
    assert "factual_observations" not in view
    assert "F001" in view["evidence_packet_markdown"]


def test_packet_instructions_preserve_numeric_rules_and_safe_missing_checks():
    from tradingagents.research.evidence_packets import PACKET_INSTRUCTIONS

    assert "Every narrative quantity, date and numbered identity" in PACKET_INSTRUCTIONS
    assert "never type observed values" in PACKET_INSTRUCTIONS
    assert "check:null" in PACKET_INSTRUCTIONS
    assert "union" in PACKET_INSTRUCTIONS
    assert "pending_questions" in PACKET_INSTRUCTIONS
    assert "{text,premise:" not in PACKET_INSTRUCTIONS


def test_retrieval_uses_saved_hypothesis_claim_text():
    from tradingagents.research.evidence_packets import packet_context

    ctx = {"question": "投资吸引力", "record": {
        "hypotheses": [{"hypothesis_id": "h.saved", "claim_id": "i.saved"}],
        "claims": [{"claim_id": "i.saved", "kind": "inference", "statement": "应收款回收可能承压"},
                   {"claim_id": "f.saved", "kind": "fact", "evidence_ids": ["e.saved"]}],
        "evidence": [{"evidence_id": "e.saved", "content": {"text": "应收款回收情况尚待核实"}}]}}
    view = packet_context("challenge", ctx)
    assert view["retrieved_source_passages"][0]["evidence_id"] == "e.saved"


def test_model_cannot_supply_a_parallel_fact_list(context):
    from tradingagents.research.evidence_packets import decode_packet_envelope
    from tradingagents.research.inline_bindings import InlineBindingError
    wire = packetize(fixtures.proposal(context), context)
    wire["proposal"]["hypotheses"][0]["supporting_fact_ids"] = ["invented"]
    with pytest.raises(InlineBindingError):
        decode_packet_envelope(wire, context)


def test_unused_unknowns_citations_are_discarded_before_metadata_validation(context):
    from tradingagents.research.evidence_packets import decode_packet_envelope
    wire = packetize(fixtures.proposal(context), context)
    wire["proposal"]["unknowns"] = [{"text": "资料仍待补充", "citations": {"unused": True}}]
    canonical = decode_inline_envelope(decode_packet_envelope(wire, context))
    assert canonical["proposal"]["unknowns"] == ["资料仍待补充"]
    compile_numeric_stage("operating_quality", canonical, context, SpecialistProposalV1)
