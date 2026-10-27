"""Challenge prompt views preserve evidence, frozen history and request accounting."""

from copy import deepcopy

import pytest

from scripts.profile_native_inputs import prompt_parts
from tests import test_native_model as model_tests
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity, validate_native_resume
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

journal = model_tests.journal
POLICY = "search-trace-summary-v1"


def context():
    hit = {"provider": "tavily", "url": "https://example.com/article",
           "summary": "DISCOVERY_SUMMARY", "content": "DISCOVERY_BODY" * 100,
           "document": {"pages": [{"text": "DISCOVERY_PDF"}]}}
    return {"mode": "company_research", "question": "研究问题", "conditions": {},
        "record": {"schema_version": "research-record-v2",
            "claims": [{"claim_id": "f.saved", "statement": "KEPT_FACT"}],
            "evidence": [{"evidence_id": "e.saved", "source_name": "web.example.com",
                "published_at": "2026-10-26", "limitations": ["selected_excerpt"],
                "content": {"text": "KEPT_ADMITTED_BODY", "content_sha256": "a" * 64}}],
            "hypotheses": [{"hypothesis_id": "h.saved"}],
            "search_batches": [{"batch_id": "batch.saved", "input_snapshot_id": "s.saved",
                "requests": [{"task_id": "task.saved", "provider": "tavily", "query": "公司 行业"}],
                "hits": [hit], "stop_reasons": ["deadline"],
                "outcomes": [{"task_id": "task.saved", "provider": "tavily", "status": "ok",
                    "hits": [hit], "reason": None, "retryable": False, "usage": 1.0},
                    {"task_id": "task.other", "provider": "deepseek", "status": "failed",
                     "hits": [], "reason": "transport_timeout", "retryable": True, "usage": None}]}]},
        "numeric_catalog": {"anchors": [{"anchor_id": "n.saved", "value": "123.45"}]},
        "factual_observations": [{"observation_id": "o.saved", "text": "KEPT_OBSERVATION"}]}


def identity(journal, policy=POLICY):
    journal.put("identity", {"workflow_version": "evidence-production-v8",
                             **({"challenge_input_policy": policy} if policy is not None else {})})


def test_challenge_main_and_repair_omit_only_search_payloads(journal, monkeypatch):
    identity(journal)
    model_tests.main(journal, "challenge")
    stub, _ = model_tests.sdk(monkeypatch, ["invalid JSON", {"challenges": []}])
    value = context()
    before = deepcopy(value)
    model = model_tests.caller(journal)
    assert model("challenge", value) == {"challenges": []}
    for prompt in stub.prompts:
        _, _, view = prompt_parts(prompt)
        assert "DISCOVERY_" not in prompt
        batches = view["record"].pop("search_batches")
        expected = deepcopy(before)
        expected["record"].pop("search_batches")
        assert view == expected
        assert batches == [{"batch_id": "batch.saved", "input_snapshot_id": "s.saved",
            "requests": before["record"]["search_batches"][0]["requests"],
            "stop_reasons": ["deadline"], "merged_hit_count": 1,
            "outcomes": [{"task_id": "task.saved", "provider": "tavily", "status": "ok",
                "reason": None, "retryable": False, "usage": 1.0, "hit_count": 1},
                {"task_id": "task.other", "provider": "deepseek", "status": "failed",
                 "reason": "transport_timeout", "retryable": True, "usage": None, "hit_count": 0}]}]
    assert value == before
    assert len(stub.prompts) == 2
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0
    assert model.recover_cached("challenge", value) == {"challenges": []}
    assert len(stub.prompts) == 2


def test_unmarked_v8_prompt_keeps_full_search_trace(journal):
    identity(journal, None)
    value = context()
    model = model_tests.caller(journal)
    _, _, view = prompt_parts(model._prompt("challenge", value))
    assert view == value
    assert "challenge_input_policy" not in journal.state["identity"]


def test_challenge_policy_does_not_change_other_stage_views(journal):
    identity(journal)
    value = context()
    assert model_tests.caller(journal)._model_context("event_context", value) == value


@pytest.mark.parametrize("version,policy", [
    ("evidence-production-v8", "unknown"), ("evidence-production-v7", POLICY),
])
def test_invalid_challenge_view_policy_refuses_model_dispatch(journal, monkeypatch, version, policy):
    journal.put("identity", {"workflow_version": version, "challenge_input_policy": policy})
    stub, _ = model_tests.sdk(monkeypatch, [])
    with pytest.raises(CatalystCheckpointConflict, match="challenge input policy"):
        model_tests.caller(journal)
    assert not stub.factories


def test_new_identity_freezes_challenge_view_and_legacy_resume_stays_unchanged(journal):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
                              effective_config=model_tests.CONFIG)
    fresh = native_identity(request)
    assert fresh["challenge_input_policy"] == POLICY
    journal.put("identity", fresh)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    legacy = deepcopy(fresh)
    legacy.pop("challenge_input_policy")
    journal.put("identity", legacy)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert journal.state["identity"] == legacy
    assert "challenge_input_policy" not in native_identity(request, workflow_version="evidence-production-v7")
    journal.put("identity", {**fresh, "challenge_input_policy": "unknown"})
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
