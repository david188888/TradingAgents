"""Provider request formats and strict schemas, entirely offline."""

import json
import time
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from tests import (
    test_chatgpt_subscription as subscription_tests,
    test_native_model as model_tests,
    test_synthesis_sections as section_tests,
)
from tradingagents.agents.schemas._native_stage import (
    ChallengesProposalV3,
    SpecialistProposalV1,
    SynthesisProposalV3,
)
from tradingagents.agents.schemas._research_dialogue import ResponsesProposalV1
from tradingagents.agents.schemas._research_focus import FocusProposalV1
from tradingagents.agents.schemas._search import SearchReviewProposalV1
from tradingagents.llm_clients.chatgpt_client import ChatGPTClient
from tradingagents.llm_clients.openai_client import OpenAIClient

journal = model_tests.journal
oauth = subscription_tests.oauth
sample = section_tests.sample


def test_strict_adapter_preserves_nonnullable_arrays_and_nullable_scalars():
    from tradingagents.llm_clients.structured_output import strict_schema

    class Output(BaseModel):
        plans: tuple[str, ...] = ()
        reason: str | None = None

    source = Output.model_json_schema()
    before = deepcopy(source)
    result = strict_schema(source)
    assert source == before
    assert result["properties"]["plans"]["type"] == "array"
    assert "anyOf" not in result["properties"]["plans"]
    assert result["properties"]["reason"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert set(result["required"]) == {"plans", "reason"}
    Output.model_validate({"plans": [], "reason": None})


@pytest.mark.parametrize("model", [SpecialistProposalV1, ChallengesProposalV3, SynthesisProposalV3,
                                  ResponsesProposalV1, FocusProposalV1, SearchReviewProposalV1])
@pytest.mark.parametrize("wire", ["plain", "numeric", "inline"])
def test_every_stage_schema_has_closed_required_objects_and_supported_unions(model, wire):
    from tradingagents.llm_clients.structured_output import strict_schema
    from tradingagents.research.inline_bindings import inline_prompt_schema
    from tradingagents.research.numeric_narrative import numeric_prompt_schema
    schema = model.model_json_schema()
    if wire == "numeric":
        schema = numeric_prompt_schema(schema, premises=True)
    elif wire == "inline":
        schema = inline_prompt_schema(schema)
    result = strict_schema(schema)

    def check(node):
        if isinstance(node, dict):
            assert not {"default", "minLength", "maxLength", "oneOf", "discriminator"} & node.keys()
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(result)


def test_siwc_strict_format_reaches_actual_http_payload(oauth):
    auth, _, _, _, connect = oauth
    captured = []
    schema = {"type": "object", "properties": {"answer": {"type": "string"}},
              "required": ["answer"], "additionalProperties": False}
    fmt = {"type": "json_schema", "json_schema": {"name": "native_stage", "schema": schema, "strict": True}}

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, text="data: " + json.dumps(subscription_tests.completed()) + "\n\n")

    result = ChatGPTClient("gpt-6.1-terra", auth=auth, account_ref=connect(), response_format=fmt,
                           stream_transport=httpx.MockTransport(handler)).get_llm().invoke("Return JSON.")
    assert result.content == '{"answer": "ok"}'
    assert captured[0]["text"]["format"] == {"type": "json_schema", **fmt["json_schema"]}


@pytest.mark.parametrize("provider,model,expected", [
    ("openai", "gpt-5.5", "json_schema"), ("deepseek", "deepseek-flash", "json_object"),
])
def test_api_key_format_reaches_real_sdk_payload(provider, model, expected):
    fmt = {"type": expected}
    if expected == "json_schema":
        fmt["json_schema"] = {"name": "native_stage", "strict": True,
            "schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
    llm = OpenAIClient(model, provider=provider, api_key="test", response_format=fmt).get_llm()
    payload = llm._get_request_payload([HumanMessage(content="Return JSON.")])
    if provider == "openai":
        assert payload["text"]["format"]["type"] == expected
        assert payload["text"]["format"]["strict"] is True
    else:
        assert payload["response_format"] == fmt


def test_native_dispatch_uses_schema_for_new_identity_only(journal, monkeypatch):
    from tradingagents.execution.native_model import NativeModelCaller
    journal.put("identity", {"workflow_version": "evidence-production-v8",
                            "structured_output_policy": "provider-schema-or-json-v1"})
    model_tests.main(journal)
    stub, _ = model_tests.sdk(monkeypatch, [{"hypotheses": [], "unknowns": [], "gaps": []}])
    model = NativeModelCaller(effective_config={**model_tests.CONFIG, "llm_provider": "openai",
        "quick_think_llm": "gpt-6.1-terra"}, run_id=journal.ledger.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)
    assert model("operating_quality", {"facts": []}) == {"hypotheses": [], "unknowns": []}
    fmt = stub.factories[0]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert journal.state["native.structured_output.operating_quality.main"]["method"] == "json_schema"


def test_deepseek_custom_model_uses_route_json_mode_instead_of_default_schema(journal, monkeypatch):
    journal.put("identity", {"workflow_version": "evidence-production-v8",
                            "structured_output_policy": "provider-schema-or-json-v1"})
    model_tests.main(journal)
    stub, _ = model_tests.sdk(monkeypatch, [{"hypotheses": [], "unknowns": [], "gaps": []}])
    model_tests.caller(journal)("operating_quality", {"facts": []})
    assert stub.factories[0]["response_format"] == {"type": "json_object"}


def test_repeated_large_citation_choices_fit_provider_enum_limit():
    from tests.test_inline_bindings import context
    from tradingagents.llm_clients.structured_output import strict_schema
    from tradingagents.research.evidence_packets import packet_schema
    from tradingagents.research.inline_bindings import inline_prompt_schema
    ctx = context.__wrapped__()
    observation = ctx["factual_observations"][0]
    ctx["factual_observations"] = [{**observation, "observation_id": f"observation.synthetic.{i}"}
                                   for i in range(277)]
    result = strict_schema(packet_schema(inline_prompt_schema(SynthesisProposalV3.model_json_schema()), ctx))
    choices = []

    def collect(node):
        if isinstance(node, dict):
            if len(node.get("enum", [])) == 277:
                choices.append(node["enum"])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
    collect(result)
    assert len(choices) == 1
    assert choices[0][0] == "E001" and choices[0][-1] == "E277"


def test_unmarked_identity_keeps_old_request_and_prompt_format(journal, monkeypatch):
    journal.put("identity", {"workflow_version": "evidence-production-v8"})
    model_tests.main(journal)
    stub, _ = model_tests.sdk(monkeypatch, [{"hypotheses": [], "unknowns": [], "gaps": []}])
    model_tests.caller(journal)("operating_quality", {"facts": []})
    assert "response_format" not in stub.factories[0]
    assert not any(key.startswith("native.structured_output.") for key in journal.state)


def test_structured_policy_is_frozen_and_unknown_versions_rejected(journal):
    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.execution.native_runner import native_identity, validate_native_resume
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
                              effective_config=model_tests.CONFIG)
    fresh = native_identity(request, workflow_version="evidence-production-v8")
    assert fresh["structured_output_policy"] == "provider-schema-or-json-v1"
    journal.put("identity", fresh)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    old = {key: value for key, value in fresh.items() if key != "structured_output_policy"}
    journal.put("identity", old)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert journal.state["identity"] == old
    journal.put("identity", {**fresh, "structured_output_policy": "unknown"})
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    with pytest.raises(CatalystCheckpointConflict):
        model_tests.caller(journal)


@pytest.mark.parametrize("targets", [None, ["dimension:valuation"]])
def test_actual_synthesis_request_schema_supports_disjoint_dimension_branches(sample, targets):
    from tradingagents.execution.native_prompt_context import reference_schema
    from tradingagents.llm_clients.structured_output import strict_schema
    from tradingagents.research.evidence_packets import packet_schema
    from tradingagents.research.inline_bindings import inline_prompt_schema
    from tradingagents.research.synthesis_sections import request_schema
    context, _ = sample
    schema = reference_schema(SynthesisProposalV3.model_json_schema(), "synthesis", context,
                              delivery=True, complete_sections=True)
    schema = request_schema(schema, context, targets)
    schema = packet_schema(inline_prompt_schema(schema), context)
    result = strict_schema(schema)
    branches = result["properties"]["proposal"]["properties"]["dimensions"]["items"]["anyOf"]
    assert len(branches) == (4 if targets is None else 1)
    assert {b["properties"]["dimension"]["enum"][0] for b in branches} == (
        {"operating_quality", "valuation", "catalyst_delivery", "market_context"} if targets is None else {"valuation"})


def test_ambiguous_one_of_is_not_silently_broadened():
    from tradingagents.llm_clients.structured_output import strict_schema
    branch = {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}
    with pytest.raises(ValueError, match="unsupported_structured_schema_union"):
        strict_schema({"type": "object", "properties": {"choice": {"oneOf": [branch, branch]}}})
