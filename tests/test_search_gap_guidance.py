"""Fresh-run gap instructions match the strict saved-target contract."""
import json
from copy import deepcopy

import pytest

from scripts.profile_native_inputs import prompt_parts
from tests import test_native_model as model_tests
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity, validate_native_resume
from tradingagents.execution.search_reviews import extract_stage_gaps
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

journal = model_tests.journal
POLICY = "supplied-gap-targets-v1"


def scope_prompt(journal, stage, context):
    journal.put("identity", {"workflow_version": "evidence-production-v8", "search_gap_guidance_policy": POLICY})
    journal.put("native.reference_aliases." + stage, 1)
    return model_tests.caller(journal)._prompt(stage, context)


def constraints(prompt):
    return json.JSONDecoder().raw_decode(prompt.split("Search gap constraints:\n", 1)[1])[0]


def test_initial_specialist_gap_targets_are_explicitly_empty(journal):
    ctx = {"facts": [{"claim_id": "f.saved"}], "numeric_analysis_date": "2026-10-26"}
    before = deepcopy(ctx)
    prompt = scope_prompt(journal, "operating_quality", ctx)
    assert constraints(prompt) == {"required_role": "operating_quality", "cutoff": "2026-10-26",
                                    "allowed_target_ids": []}
    assert "target_ids must be []" in prompt
    assert "newly proposed" in prompt
    _, schema, _ = prompt_parts(prompt)
    fields = schema["$defs"]["EvidenceGapV1"]["properties"]
    assert fields["role"]["const"] == "operating_quality"
    assert fields["cutoff"]["const"] == "2026-10-26"
    assert fields["target_ids"]["maxItems"] == 0
    assert ctx == before


def test_reply_gap_targets_use_the_same_aliases_as_the_model_context(journal):
    ctx = {"numeric_analysis_date": "2026-10-26", "hypotheses": [{"hypothesis_id": "h.saved"}],
           "challenges": [{"challenge_id": "c.saved"}], "facts": [{"claim_id": "f.saved"}],
           "record": {"hypotheses": [{"hypothesis_id": "h.saved"}],
                      "challenges": [{"challenge_id": "c.saved"}]}}
    prompt = scope_prompt(journal, "response_event_context", ctx)
    assert constraints(prompt) == {"required_role": "event_context", "cutoff": "2026-10-26",
                                    "allowed_target_ids": ["challenge_001", "hypothesis_001"]}
    _, schema, _ = prompt_parts(prompt)
    assert schema["$defs"]["EvidenceGapV1"]["properties"]["target_ids"]["items"]["enum"] == [
        "challenge_001", "hypothesis_001"]
    gap = {"gap_id": "gap", "question": "需核对正式披露", "capability": "news", "role": "event_context",
           "priority": "material", "cutoff": "2026-10-26", "evidence_needed": "原始披露",
           "rationale": "当前资料不足", "target_ids": ["h.saved", "c.saved"]}
    extract_stage_gaps({"gaps": [gap]}, stage="response_event_context", context=ctx,
                       ledger=journal.ledger, persist=False)
    gap["target_ids"] = ["f.saved"]
    with pytest.raises(ValueError, match="gap target outside supplied scope"):
        extract_stage_gaps({"gaps": [gap]}, stage="response_event_context", context=ctx,
                           ledger=journal.ledger, persist=False)
    gap.update(target_ids=[], role="market_context")
    with pytest.raises(ValueError, match="gap role changed"):
        extract_stage_gaps({"gaps": [gap]}, stage="response_event_context", context=ctx,
                           ledger=journal.ledger, persist=False)


def test_challenge_may_direct_a_gap_to_any_specialist_role(journal):
    ctx = {"numeric_analysis_date": "2026-10-26", "record": {
        "hypotheses": [{"hypothesis_id": "h.saved"}]}}
    prompt = scope_prompt(journal, "challenge", ctx)
    assert constraints(prompt)["required_role"] is None
    _, schema, _ = prompt_parts(prompt)
    assert "const" not in schema["$defs"]["EvidenceGapV1"]["properties"]["role"]


def test_fresh_gap_guidance_identity_preserves_legacy_resume(journal):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
                              effective_config=model_tests.CONFIG)
    fresh = native_identity(request, workflow_version="evidence-production-v8")
    assert fresh["search_gap_guidance_policy"] == POLICY
    journal.put("identity", fresh)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    legacy = {k: v for k, v in fresh.items() if k != "search_gap_guidance_policy"}
    journal.put("identity", legacy)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert journal.state["identity"] == legacy
    assert "search_gap_guidance_policy" not in native_identity(request, workflow_version="evidence-production-v7")
    journal.put("identity", {**fresh, "search_gap_guidance_policy": "unknown"})
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id, request)


@pytest.mark.parametrize("version,policy", [("evidence-production-v8", "unknown"),
                                         ("evidence-production-v7", POLICY)])
def test_invalid_gap_guidance_never_dispatches(journal, monkeypatch, version, policy):
    journal.put("identity", {"workflow_version": version, "search_gap_guidance_policy": policy})
    stub, _ = model_tests.sdk(monkeypatch, [])
    with pytest.raises(CatalystCheckpointConflict, match="search gap guidance policy"):
        model_tests.caller(journal)
    assert not stub.factories


def test_unmarked_prompt_keeps_legacy_shape(journal):
    journal.put("identity", {"workflow_version": "evidence-production-v8"})
    prompt = model_tests.caller(journal)._prompt("event_context", {"facts": []})
    assert "Search gap constraints:" not in prompt


def test_gap_target_repair_gets_specific_feedback_without_echo_or_new_budget(journal, monkeypatch):
    secret = "private-model-invented-target"
    stage = "event_context"
    ctx = {"facts": [], "numeric_analysis_date": "2026-10-26"}
    scope_prompt(journal, stage, ctx)
    model_tests.main(journal, stage)
    bad = {**model_tests.valid(stage), "gaps": [{"gap_id": "gap", "question": "需补充披露",
        "capability": "news", "role": stage, "priority": "material", "cutoff": "2026-10-26",
        "evidence_needed": "原始披露", "rationale": "当前资料不足", "target_ids": [secret]}]}
    good = {**model_tests.valid(stage), "gaps": []}
    stub, _ = model_tests.sdk(monkeypatch, [bad, good])
    model = model_tests.caller(journal)
    assert model(stage, ctx) == model_tests.valid(stage)
    assert len(stub.prompts) == 2
    assert "Validation failure: gap_target_scope" in stub.prompts[1]
    assert secret not in stub.prompts[1] + json.dumps(journal.state)
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert model.recover_cached(stage, ctx) == model_tests.valid(stage)
    assert len(stub.prompts) == 2


@pytest.mark.parametrize("message,code", [("gap cutoff changed", "gap_cutoff_changed"),
    ("gap role changed", "gap_role_changed"), ("gap target outside supplied scope", "gap_target_scope")])
def test_gap_failures_have_closed_diagnostics(message, code):
    from tradingagents.execution.native_model_diagnostics import safe_model_diagnostic
    value = safe_model_diagnostic("event_context", "main", "response_invalid", ValueError(message))
    assert (value["category"], value.get("detail_code")) == ("reference_validation", code)
    assert message not in json.dumps(value)
