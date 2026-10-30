"""Actual SDK adapter isolation with durable checkpoints and no network."""

import json
import time
from copy import deepcopy

import pytest

from tests.test_native_model import CONFIG, caller, main, sdk
from tradingagents.agents.schemas._native_stage import SpecialistCandidateV1
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_model import NativeModelCancelled, NativeModelUnavailable
from tradingagents.execution.native_runner import native_identity, validate_native_resume
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.native_versions import SPECIALIST_REFERENCE_POLICY
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict, CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

ROLE = "operating_quality"
CONTEXT = {"facts": [{"claim_id": "f.allowed", "evidence_ids": ["e.allowed"]}], "metrics": []}


@pytest.fixture
def checkpoint(tmp_path):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1", effective_config=CONFIG)
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date,
        llm_provider="deepseek", quick_think_llm="quick", deep_think_llm="deep",
        runtime_semantics_hash="a" * 64, metadata={"effective_config_artifact_id": "data:" + "b" * 64})
    store.create_run(snapshot)
    # This suite freezes the pre-numeric V7 protocol. Fresh numeric identities
    # are exercised separately with their required envelope and catalog.
    return CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False), native_identity(request, numeric_narrative_policy=False, workflow_version="evidence-production-v8"))


def mixed(kind="fact"):
    good = {"statement": "合法经营假设", "supporting_fact_ids": ["f.allowed"],
        "conditions": [{"condition_role": "invalidation", "text": "后续披露不支持", "check": None}],
        "alternative_explanation": "一次性因素"}
    bad = deepcopy(good)
    if kind == "fact":
        bad["supporting_fact_ids"] = ["f.fabricated"]
    else:
        predicate = {"operator": "lt", "threshold": "0", "unit": "CNY"}
        check = {"kind": "metric", "metric_id": "m.fabricated", "predicate": predicate}
        if kind == "evidence":
            check = {"kind": "financial", "operation": "value", "current": {
                "evidence_id": "e.fabricated", "table": "cashflow", "field": "n_cashflow_act",
                "report_period": "2026-06-30"}, "predicate": predicate}
        bad["conditions"][0]["check"] = check
    return {"hypotheses": [bad, good], "unknowns": []}


@pytest.mark.parametrize("kind,code", [("fact", "specialist_fact_reference"),
    ("evidence", "condition_evidence_reference"), ("metric", "condition_metric_reference")])
def test_failed_repair_keeps_original_valid_hypothesis_and_index(checkpoint, monkeypatch, kind, code):
    main(checkpoint)
    original = mixed(kind)
    stub, _ = sdk(monkeypatch, [original, original])
    result = caller(checkpoint)(ROLE, CONTEXT)
    assert result["hypotheses"] == [original["hypotheses"][1]]
    accepted = SpecialistCandidateV1.model_validate(checkpoint.ledger.cached_result("native.specialist_accepted." + ROLE))
    assert accepted.indices == (1,)
    assert [(r.index, r.code) for r in accepted.rejections] == [(0, code)]
    assert checkpoint.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert len(stub.prompts) == 2
    assert "fabricated" not in json.dumps(checkpoint.state)
    assert caller(checkpoint)(ROLE, CONTEXT) == result
    assert len(stub.prompts) == 2


@pytest.mark.parametrize("repair", ["malformed", {"unapproved": True}, RuntimeError("private provider failure")])
def test_unusable_repair_salvages_only_schema_valid_main(checkpoint, monkeypatch, repair):
    main(checkpoint)
    stub, _ = sdk(monkeypatch, [mixed(), repair])
    result = caller(checkpoint)(ROLE, CONTEXT)
    assert len(result["hypotheses"]) == 1
    assert len(stub.prompts) == 2
    assert "private provider failure" not in json.dumps(checkpoint.state)


def test_successful_repair_replaces_main_without_merging_or_rejection(checkpoint, monkeypatch):
    main(checkpoint)
    repaired = {"hypotheses": [deepcopy(mixed()["hypotheses"][1])], "unknowns": []}
    repaired["hypotheses"][0]["statement"] = "修复后的完整提议"
    sdk(monkeypatch, [mixed(), repaired])
    assert caller(checkpoint)(ROLE, CONTEXT) == repaired
    accepted = checkpoint.ledger.cached_result("native.specialist_accepted." + ROLE)
    assert accepted["indices"] == [0] and accepted["rejections"] == []


def test_saved_valid_repair_precedes_main_candidate_after_cache_gap(checkpoint, monkeypatch):
    main(checkpoint)
    repaired = {"hypotheses": [mixed()["hypotheses"][1]], "unknowns": []}
    sdk(monkeypatch, [mixed(), repaired])
    caller(checkpoint)(ROLE, CONTEXT)
    checkpoint.state["results"].pop("native.adapter." + ROLE)
    checkpoint.state["results"].pop("native.specialist_accepted." + ROLE)
    checkpoint.persist()
    inactive = caller(checkpoint, cancelled=lambda: True, deadline=lambda: -1)
    before = json.dumps(checkpoint.state, sort_keys=True)
    assert inactive.recover_cached(ROLE, CONTEXT) == repaired
    assert json.dumps(checkpoint.state, sort_keys=True) == before


def test_refused_repair_preserves_candidate_without_extra_sdk_call(checkpoint, monkeypatch):
    main(checkpoint)
    checkpoint.ledger._limits[BudgetBucket.STRUCTURED_REPAIR] = 0
    stub, _ = sdk(monkeypatch, [mixed()])
    assert len(caller(checkpoint)(ROLE, CONTEXT)["hypotheses"]) == 1
    assert len(stub.prompts) == 1
    assert checkpoint.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0


def test_all_invalid_still_gets_one_repair_and_retains_no_hypotheses(checkpoint, monkeypatch):
    main(checkpoint)
    invalid = mixed()
    invalid["hypotheses"].pop()
    stub, _ = sdk(monkeypatch, [invalid, invalid])
    assert caller(checkpoint)(ROLE, CONTEXT)["hypotheses"] == []
    assert len(stub.prompts) == 2


def test_malformed_main_has_no_candidate_to_salvage(checkpoint, monkeypatch):
    main(checkpoint)
    sdk(monkeypatch, [{"hypotheses": mixed()["hypotheses"], "unapproved": True}, "invalid"])
    with pytest.raises(NativeModelUnavailable):
        caller(checkpoint)(ROLE, CONTEXT)
    assert checkpoint.ledger.cached_result("native.specialist_candidate." + ROLE) is None


@pytest.mark.parametrize("control", ["cancel", "deadline", "checkpoint"])
def test_repair_control_failures_do_not_accept_candidate(checkpoint, monkeypatch, control):
    main(checkpoint)
    active = {"cancel": False, "deadline": time.monotonic() + 30}
    def interrupt():
        if control == "checkpoint":
            raise CatalystCheckpointConflict("checkpoint persistence failed")
        active[control] = True if control == "cancel" else -1
        return mixed()
    sdk(monkeypatch, [mixed(), interrupt])
    model = caller(checkpoint, cancelled=lambda: active["cancel"], deadline=lambda: active["deadline"])
    error = {"cancel": NativeModelCancelled, "deadline": TimeoutError, "checkpoint": CatalystCheckpointConflict}[control]
    with pytest.raises(error):
        model(ROLE, CONTEXT)
    assert checkpoint.ledger.cached_result("native.specialist_accepted." + ROLE) is None


def test_candidate_recovery_is_readonly_under_unknown_repair_dispatch(checkpoint, monkeypatch):
    main(checkpoint)
    sdk(monkeypatch, [mixed(), mixed()])
    expected = caller(checkpoint)(ROLE, CONTEXT)
    checkpoint.state["results"].pop("native.adapter." + ROLE)
    checkpoint.state["results"].pop("native.specialist_accepted." + ROLE)
    repair = next(r for r in checkpoint.state["records"] if r["logical_call_id"] == "native." + ROLE + ".repair")
    repair.update(phase="dispatched", outcome=None, settled_at=None)
    checkpoint.persist()
    restored = CatalystJournal(checkpoint.observer, checkpoint.state["identity"], require_existing=True)
    inactive = caller(restored, cancelled=lambda: True, deadline=lambda: -1)
    before = json.dumps(restored.state, sort_keys=True)
    assert inactive.recover_cached(ROLE, CONTEXT) == expected
    assert json.dumps(restored.state, sort_keys=True) == before


def test_legacy_identity_retains_repair_failure_behavior(checkpoint, monkeypatch):
    identity = dict(checkpoint.state["identity"])
    identity.pop("specialist_reference_policy")
    checkpoint.put("identity", identity)
    main(checkpoint)
    sdk(monkeypatch, [mixed(), mixed()])
    with pytest.raises(NativeModelUnavailable):
        caller(checkpoint)(ROLE, CONTEXT)
    assert checkpoint.ledger.cached_result("native.specialist_candidate." + ROLE) is None


def test_resume_accepts_absent_policy_and_rejects_unknown_policy(checkpoint):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1", effective_config=CONFIG)
    assert checkpoint.state["identity"]["specialist_reference_policy"] == SPECIALIST_REFERENCE_POLICY
    validate_native_resume(checkpoint.observer.store, checkpoint.ledger.run_id, request)
    identity = native_identity(request, specialist_reference_policy=False, numeric_narrative_policy=False, workflow_version="evidence-production-v8")
    checkpoint.put("identity", identity)
    validate_native_resume(checkpoint.observer.store, checkpoint.ledger.run_id, request)
    identity["specialist_reference_policy"] = "unknown"
    checkpoint.put("identity", identity)
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(checkpoint.observer.store, checkpoint.ledger.run_id, request)
    with pytest.raises(CatalystCheckpointConflict):
        caller(checkpoint)


@pytest.mark.parametrize("corruption", ["indices", "proposal", "prompt", "dispatch"])
def test_corrupt_candidate_cannot_be_recovered(checkpoint, monkeypatch, corruption):
    main(checkpoint)
    sdk(monkeypatch, [mixed(), mixed()])
    caller(checkpoint)(ROLE, CONTEXT)
    checkpoint.state["results"].pop("native.adapter." + ROLE)
    checkpoint.state["results"].pop("native.specialist_accepted." + ROLE)
    candidate = checkpoint.state["results"]["native.specialist_candidate." + ROLE]
    if corruption == "indices":
        candidate["indices"] = [0]
    elif corruption == "proposal":
        candidate["proposal"]["hypotheses"][0]["supporting_fact_ids"] = ["f.fabricated"]
    elif corruption == "prompt":
        candidate["prompt_sha256"] = "a" * 64
    else:
        checkpoint.state.pop("native.model." + ROLE + ".dispatched")
    checkpoint.persist()
    with pytest.raises(CatalystCheckpointConflict):
        caller(checkpoint).recover_cached(ROLE, CONTEXT)
