"""Frozen packet dispatch and budgets, alongside unchanged old inline calls."""
import json
from copy import deepcopy

from tests import test_inline_bindings as fixtures, test_native_model as model_tests
from tests.test_evidence_packets import packetize
from tests.test_inline_model_caller import enable

journal = model_tests.journal
context = fixtures.context


def test_sdk_packet_citations_save_canonical_proof_and_recover(journal, context, monkeypatch):
    from tradingagents.research.native_versions import RESEARCH_DELIVERY_POLICY
    enable(journal)
    journal.put("identity", {**journal.state["identity"], "research_delivery_policy": deepcopy(RESEARCH_DELIVERY_POLICY)})
    model_tests.main(journal)
    payload = packetize(fixtures.proposal(context), context)
    payload["gaps"] = []
    stub, _ = model_tests.sdk(monkeypatch, [payload])
    caller = model_tests.caller(journal)
    result = caller("operating_quality", context)
    saved = journal.ledger.cached_result("native.numeric.accepted.operating_quality")
    assert saved["proof"]["envelope"]["premises"][0]["observation_ids"]
    assert "evidence_packet_markdown" in stub.prompts[0]
    assert '"citations"' in stub.prompts[0]
    assert caller.recover_cached("operating_quality", context) == result
    assert len(stub.prompts) == 1
    assert '"field_path"' not in json.dumps(payload)


def test_fresh_repairs_do_not_let_early_stages_consume_the_synthesis_slot():
    from scripts.replay_synthesis_input import _MemoryJournal
    from tradingagents.execution.budget import BudgetBucket, BudgetLimitHit
    from tradingagents.execution.search_budget import SEARCH_BUDGET_POLICY
    from tradingagents.research.native_versions import RESEARCH_DELIVERY_POLICY
    base = {"run_id": "repair-budget", "results": {}, "records": [], "identity": {
        "workflow_version": "evidence-production-v8", "search_budget_policy": deepcopy(SEARCH_BUDGET_POLICY)}}
    for fresh in [False, True]:
        state = deepcopy(base)
        if fresh:
            state["identity"]["research_delivery_policy"] = deepcopy(RESEARCH_DELIVERY_POLICY)
        ledger = _MemoryJournal(state).ledger
        for stage in ["operating_quality", "challenge"]:
            token = ledger.reserve(BudgetBucket.STRUCTURED_REPAIR, stage="native." + stage, logical_call_id=stage)
            ledger.mark_dispatched(token)
            ledger.settle(token, ok=True, usage_available=False)
        synthesis = ledger.reserve(BudgetBucket.STRUCTURED_REPAIR, stage="native.synthesis", logical_call_id="synthesis")
        assert isinstance(synthesis, BudgetLimitHit) is not fresh


def test_empty_challenge_repair_must_still_supply_per_hypothesis_reviews(journal, monkeypatch):
    from tests.test_challenge_checks import inputs
    from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
    from tradingagents.research.native_versions import RESEARCH_DELIVERY_POLICY
    from tradingagents.research.numeric_narrative import prepare_numeric_context
    record = inputs()[0]
    ctx = prepare_numeric_context("challenge", {"record": record.model_dump(mode="json"), "conditions": {}},
                                  record, identity=fixtures.IDENTITY)
    enable(journal)
    journal.put("identity", {**journal.state["identity"], "research_delivery_policy": deepcopy(RESEARCH_DELIVERY_POLICY),
                            "challenge_check_policy": CHALLENGE_CHECK_POLICY})
    model_tests.main(journal, stage="challenge")
    bad = {"proposal": {"challenges": []}, "gaps": []}
    good = deepcopy(bad)
    good["proposal"]["reviews"] = [{"hypothesis_id": h.hypothesis_id,
        "disposition": "no_additional_counterevidence",
        "rationale": {"text": "暂未发现额外反证，后续仍需验证解释", "citations": ["E001"], "pending_questions": []}}
        for h in record.hypotheses]
    stub, _ = model_tests.sdk(monkeypatch, [bad, good])
    result = model_tests.caller(journal)("challenge", ctx)
    assert result == {"challenges": []}
    receipt = journal.ledger.cached_result("native.challenge_reviews")
    assert receipt is not None
    assert len(receipt["proposal"]["reviews"]) == len(record.hypotheses)
    assert len(stub.prompts) == 2
    assert "challenge_review_coverage" in stub.prompts[1]


def test_packet_protocol_publication_review_reader_and_resume(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from tests.test_dual_search_pipeline import Caller, setup
    from tradingagents.execution import native_model as adapter
    from tradingagents.execution.native_runner import NativeResumeGuard
    from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
    from tradingagents.web.reader_process_projection import project_reader_agent
    from tradingagents.web.research_record_projection import project_research_record

    runner, request, store, run_id, _, _ = setup(tmp_path, monkeypatch, enabled=False)
    active = threading.local()
    prompts = []

    class PacketCaller(adapter.NativeModelCaller):
        def __call__(self, stage, context):
            active.stage, active.context = stage, context
            return super().__call__(stage, context)

    class SDK:
        def invoke(self, prompt):
            prompts.append(prompt)
            stage, ctx = active.stage, active.context
            canonical = Caller()(stage, ctx)
            if stage == "challenge":
                canonical["proposal"]["reviews"] = []
                for index, h in enumerate(ctx["record"]["hypotheses"]):
                    canonical["proposal"]["reviews"].append({"hypothesis_id": h["hypothesis_id"],
                        "disposition": "no_additional_counterevidence", "rationale": "尚未发现额外反证，后续仍待验证"})
                    canonical["premises"].append({"field_path": f"reviews.{index}.rationale",
                        "observation_ids": [ctx["factual_observations"][0]["observation_id"]], "pending_questions": []})
            wire = packetize(canonical, ctx)
            if stage != "synthesis":
                wire["gaps"] = []
            return SimpleNamespace(content=json.dumps(wire), usage_metadata={"input_tokens": 1, "output_tokens": 1})

    monkeypatch.setattr(adapter, "create_llm_client", lambda **kwargs: SimpleNamespace(get_llm=lambda: SDK()))
    runner.caller_factory = PacketCaller
    runner.run(request, publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    result = project_research_record(store, run_id)
    checkpoint = load_checkpoint(store, run_id)
    assert checkpoint["native_stages"]["challenge"] == "completed"
    assert result["state"] == "ready"
    output = project_reader_agent(store, run_id, "challenge")
    assert len(output["challenge_reviews"]) == 1
    assert output["challenge_reviews"][0]["disposition"] == "no_additional_counterevidence"
    calls = len(prompts)
    runner.run(request, checkpoint_guard=NativeResumeGuard(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    assert len(prompts) == calls
    assert project_research_record(store, run_id) == result
