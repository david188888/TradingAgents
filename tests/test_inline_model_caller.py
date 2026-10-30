"""Fresh inline wire format, immutable canonical caches and legacy identity."""
import json
from copy import deepcopy

import pytest

from scripts.profile_native_inputs import prompt_parts
from tests import test_inline_bindings as fixtures, test_native_model as model_tests
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity, validate_native_resume
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

journal = model_tests.journal
context = fixtures.context
POLICY = "inline-bindings-v1"


def enable(journal):
    journal.put("identity", {**fixtures.IDENTITY, "workflow_version": "evidence-production-v8",
        "specialist_reference_policy": "bounded-repair-then-isolate-v1", "model_binding_policy": POLICY})


def test_sdk_inline_output_saves_only_canonical_proof_and_recovers(journal, context, monkeypatch):
    enable(journal)
    model_tests.main(journal)
    payload = fixtures.localize(fixtures.proposal(context))
    payload["gaps"] = []
    stub, _ = model_tests.sdk(monkeypatch, [payload])
    model = model_tests.caller(journal)
    result = model("operating_quality", context)
    assert result["hypotheses"][0]["statement"].startswith("解释假设：")
    _, schema, _ = prompt_parts(stub.prompts[0])
    assert set(schema["properties"]) == {"proposal", "gaps"}
    assert '"field_path"' not in json.dumps(schema)
    assert "declare its field_path" not in stub.prompts[0]
    assert "The envelope MUST also contain premises" not in stub.prompts[0]
    saved = journal.ledger.cached_result("native.numeric.accepted.operating_quality")
    assert isinstance(saved["proof"]["envelope"]["proposal"]["hypotheses"][0]["statement"], str)
    assert saved["proof"]["envelope"]["premises"][0]["field_path"].startswith("hypotheses.0.")
    assert len(stub.prompts) == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0
    before = deepcopy(journal.state)
    assert model.recover_cached("operating_quality", context) == result
    assert before == journal.state
    assert len(stub.prompts) == 1


def test_pathful_payload_repair_is_specific_and_never_echoes_response(journal, context, monkeypatch):
    enable(journal)
    model_tests.main(journal)
    old = fixtures.proposal(context)
    old["premises"][0]["field_path"] = "private-invalid-model-path"
    good = fixtures.localize(fixtures.proposal(context))
    good["gaps"] = []
    stub, _ = model_tests.sdk(monkeypatch, [old, good])
    assert model_tests.caller(journal)("operating_quality", context)["hypotheses"]
    assert len(stub.prompts) == 2
    assert "inline_binding_shape" in stub.prompts[1]
    assert "private-invalid-model-path" not in stub.prompts[1] + json.dumps(journal.state)
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1


def test_new_identity_marks_inline_protocol_and_resumes_unmarked_history(journal):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
                              effective_config=model_tests.CONFIG)
    fresh = native_identity(request, workflow_version="evidence-production-v8")
    assert fresh["model_binding_policy"] == POLICY
    journal.put("identity", fresh)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    legacy = {k: v for k, v in fresh.items() if k not in {"model_binding_policy", "research_delivery_policy"}}
    journal.put("identity", legacy)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert journal.state["identity"] == legacy
    assert "model_binding_policy" not in native_identity(request, workflow_version="evidence-production-v7")
    assert "model_binding_policy" not in native_identity(request, numeric_narrative_policy=False, workflow_version="evidence-production-v8")
    journal.put("identity", {**fresh, "model_binding_policy": "unknown"})
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id, request)


@pytest.mark.parametrize("version,numeric,policy", [
    ("evidence-production-v8", "anchored-narrative-v1", "unknown"),
    ("evidence-production-v7", "anchored-narrative-v1", POLICY),
    ("evidence-production-v8", None, POLICY),
])
def test_invalid_inline_policy_refuses_dispatch(journal, monkeypatch, version, numeric, policy):
    journal.put("identity", {"workflow_version": version, "model_binding_policy": policy,
                            **({"numeric_narrative_policy": numeric} if numeric else {})})
    stub, _ = model_tests.sdk(monkeypatch, [])
    with pytest.raises(CatalystCheckpointConflict, match="model binding policy"):
        model_tests.caller(journal)
    assert not stub.factories


def test_unmarked_numeric_prompt_retains_legacy_schema(journal, context):
    journal.put("identity", {**fixtures.IDENTITY, "workflow_version": "evidence-production-v8"})
    prompt = model_tests.caller(journal)._prompt("operating_quality", context)
    _, schema, _ = prompt_parts(prompt)
    assert {"proposal", "plans", "premises", "structured_bindings"} <= schema["properties"].keys()
    assert "declare its field_path" in prompt


def test_legacy_inline_protocol_full_v8_publication_reader_and_resume(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tests.test_dual_search_pipeline import Caller, setup
    from tradingagents.execution import native_model as adapter, native_runner as runner_module
    from tradingagents.execution.native_runner import NativeResumeGuard
    from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
    from tradingagents.web.research_record_projection import project_research_record

    original_identity = runner_module.native_identity
    monkeypatch.setattr(runner_module, "native_identity", lambda *args, **kwargs:
        original_identity(*args, **{**kwargs, "research_delivery_policy": False}))
    runner, request, store, run_id, _, _ = setup(tmp_path, monkeypatch, enabled=False)
    prompts = []

    class SDK:
        def invoke(self, prompt):
            prompts.append(prompt)
            _, schema, ctx = prompt_parts(prompt)
            properties = schema["properties"]["proposal"]["properties"]
            if "hypotheses" in properties:
                constraints = json.JSONDecoder().raw_decode(prompt.split("Search gap constraints:\n", 1)[1])[0]
                stage = constraints["required_role"]
            elif "challenges" in properties:
                stage = "challenge"
            else:
                assert "judgement" in properties
                stage = "synthesis"
            canonical = Caller()(stage, ctx)
            if stage in {"operating_quality", "event_context", "market_context"}:
                label = {"operating_quality": "经营研究", "event_context": "事件研究", "market_context": "市场研究"}[stage]
                canonical["proposal"]["hypotheses"][0]["statement"] = label + "：" + canonical["proposal"]["hypotheses"][0]["statement"]
            canonical["proposal"] = {key: value for key, value in canonical["proposal"].items() if key in properties}
            for key, field in properties.items():
                if "default" in field:
                    canonical["proposal"].setdefault(key, deepcopy(field["default"]))
            wire = fixtures.localize(canonical)
            if "gaps" in schema["properties"]:
                wire["gaps"] = []
            return SimpleNamespace(content=json.dumps(wire), usage_metadata={"input_tokens": 1, "output_tokens": 1})

    monkeypatch.setattr(adapter, "create_llm_client", lambda **kwargs: SimpleNamespace(get_llm=lambda: SDK()))
    runner.caller_factory = adapter.NativeModelCaller
    runner.run(request, publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    result = project_research_record(store, run_id)
    checkpoint = load_checkpoint(store, run_id)
    assert all(checkpoint["native_stages"].get(stage) == "completed" for stage in (
        "operating_quality", "challenge", "synthesis"))
    # This fixture supplies financials only; empty event/market views still skip.
    assert checkpoint["native_stages"]["event_context"] == "skipped"
    assert checkpoint["native_stages"]["market_context"] == "skipped"
    assert result["state"] == "ready"
    assessment = result["record"]["assessment"]
    assert assessment["report_status"] == "analysis_unrated"
    assert all(section["status"] == "accepted" for section in assessment["synthesis_sections"]["sections"])
    assert len(result["record"]["hypotheses"]) == 1
    assert len(prompts) == 3
    calls = len(prompts)
    runner.run(request, checkpoint_guard=NativeResumeGuard(),
               publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    assert len(prompts) == calls
    assert project_research_record(store, run_id) == result
