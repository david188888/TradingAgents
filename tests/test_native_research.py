"""Offline native C2 kernel: isolation, conditions, gates and durable replay."""

import copy
import threading
import time

import pytest

from tests.test_bounded_verification import inputs, journal_for
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.budget import BudgetBucket
from tradingagents.graph.native_research import load_native_seed, run_native_research
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict, CatalystJournal


def seed_for(journal, mode="company_research"):
    record, _ = inputs(run_id=journal.ledger.run_id, mode=mode)
    payload = record.model_dump(mode="json")
    payload.update(claims=[payload["claims"][0]], hypotheses=[], challenges=[])
    return ResearchRecordV1.model_validate(payload)


class Caller:
    def __init__(self, challenge=True, check=True):
        self.calls = []
        self.challenge = challenge
        self.check = check

    def __call__(self, stage, context):
        self.calls.append((stage, copy.deepcopy(context)))
        if stage in ("operating_quality", "market_context", "event_context"):
            fact = context["facts"][0]
            condition = {"condition_role": "invalidation", "text": "收入下降"}
            if self.check:
                condition["check"] = {"kind": "financial", "operation": "value", "current": {
                    "evidence_id": fact["evidence_ids"][0], "table": "income", "field": "revenue", "report_period": "2026-06-30"},
                    "predicate": {"operator": "lt", "threshold": "110", "unit": "CNY"}}
            return {"hypotheses": [{"statement": "经营改善可能延续", "supporting_fact_ids": [fact["claim_id"]],
                "conditions": [condition], "alternative_explanation": "一次性贡献也可能解释改善"}]}
        if stage == "challenge":
            if not self.challenge:
                return {"challenges": []}
            assert all(not any(role in h["hypothesis_id"] for role in ("operating", "event", "market"))
                       for h in context["record"]["hypotheses"])
            hypothesis = context["record"]["hypotheses"][0]
            return {"challenges": [{"hypothesis_id": hypothesis["hypothesis_id"], "condition_id": next(iter(context["conditions"])),
                "statement": "收入字段不足以证明持续性", "severity": "critical", "risk_type": "operations",
                "proposed_test": "核查收入门槛，同时等待更多经营证据"}]}
        record = context["record"]
        inference = next(c for c in record["claims"] if c["kind"] == "inference")
        return {"judgement": "经营改善仍有待核查", "next_check": "关注下一期经营兑现", "key_claim_ids": [inference["claim_id"]],
            "dimensions": [{"dimension": name, "status": "conditional" if name == "operating_quality" else "unresolved",
                "judgement": "受限的判断", "claim_ids": [inference["claim_id"]] if name == "operating_quality" else [],
                "limitations": [] if name == "operating_quality" else [reason]}
                for name, (_, reason) in context["dimension_policy"].items()],
            "challenge_assessments": [{"challenge_id": c["challenge_id"], "rationale": "条件核查不足以证明整个假设"} for c in record["challenges"]]}


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_three_modes_verify_before_synthesis_and_replay_without_calls(tmp_path, mode):
    journal = journal_for(tmp_path)
    seed = seed_for(journal, mode)
    caller = Caller()
    output = run_native_research(seed, caller=caller, ledger=journal.ledger)
    assert [s for s, _ in caller.calls] == ["operating_quality", "challenge", "synthesis"]
    assert len(output.snapshots) == 2
    assert output.verifications[0].scope == "predicate_only"
    assert caller.calls[-1][1]["record"]["verifications"]
    assert output.assessment.quality == "LOW_CONFIDENCE"
    assert output.assessment.completeness == "partial"
    assert output.assessment.dimensions[0 if mode != "holding_review" else 1].challenge_ids == (output.challenges[0].challenge_id,)
    assert all(c.outcome == "unresolved" for c in output.assessment.challenge_assessments)
    assert (output.assessment.forward_window_calendar_days == 84) == (mode == "catalyst_research")
    restored = CatalystJournal(journal.observer, {"test": "bounded-verification"}, require_existing=True)
    def forbidden(*args):
        pytest.fail("durable replay must not call models")
    assert run_native_research(seed, caller=forbidden, ledger=restored.ledger) == output
    assert restored.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 3


def test_no_forced_challenge_or_verification(tmp_path):
    journal = journal_for(tmp_path)
    output = run_native_research(seed_for(journal), caller=Caller(challenge=False), ledger=journal.ledger)
    assert not output.challenges and not output.verifications and len(output.snapshots) == 1
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_ROUNDS) == 0


def test_no_numeric_condition_no_fake_tool_execution(tmp_path):
    journal = journal_for(tmp_path)
    output = run_native_research(seed_for(journal), caller=Caller(check=False), ledger=journal.ledger)
    assert output.challenges and not output.verifications and len(output.snapshots) == 1


def test_empty_evidence_skips_every_model(tmp_path):
    journal = journal_for(tmp_path)
    payload = seed_for(journal).model_dump(mode="json")
    payload["claims"] = []
    output = run_native_research(ResearchRecordV1.model_validate(payload), caller=lambda *_: pytest.fail("no facts"), ledger=journal.ledger)
    assert output.assessment.quality == "LOW_CONFIDENCE"
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 0


def test_lost_dispatched_model_is_not_redispatched(tmp_path):
    journal = journal_for(tmp_path)
    token = journal.ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="native.operating_quality", logical_call_id="native.operating_quality")
    journal.ledger.mark_dispatched(token)
    restored = CatalystJournal(journal.observer, {"test": "bounded-verification"}, require_existing=True)
    caller = Caller()
    output = run_native_research(seed_for(restored), caller=caller, ledger=restored.ledger)
    assert not any(stage == "operating_quality" for stage, _ in caller.calls)
    assert output.assessment.quality == "LOW_CONFIDENCE"
    assert restored.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 2  # one unknown + one synthesis


def test_changed_question_conflicts(tmp_path):
    journal = journal_for(tmp_path)
    seed = seed_for(journal)
    run_native_research(seed, caller=Caller(), ledger=journal.ledger)
    with pytest.raises(CatalystCheckpointConflict):
        run_native_research(seed, caller=Caller(), ledger=journal.ledger, research_question="不同问题")


def test_wrong_specialist_fact_fails_before_publication(tmp_path):
    journal = journal_for(tmp_path)
    base = Caller()
    def bad(stage, context):
        value = base(stage, context)
        if stage == "operating_quality":
            value["hypotheses"][0]["supporting_fact_ids"] = ["fabricated"]
        return value
    with pytest.raises(ValueError, match="outside its view"):
        run_native_research(seed_for(journal), caller=bad, ledger=journal.ledger)
    assert journal.ledger.cached_result("native.output") is None


def test_cancelled_before_dispatch_consumes_no_models(tmp_path):
    journal = journal_for(tmp_path)
    output = run_native_research(seed_for(journal), caller=lambda *_: pytest.fail("cancelled"), ledger=journal.ledger, cancelled=lambda: True)
    assert output.assessment.quality == "LOW_CONFIDENCE"
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 0


def test_legacy_record_wire_hash_does_not_grow_null_assessment(tmp_path):
    seed = seed_for(journal_for(tmp_path))
    assert "assessment" not in seed.model_dump(mode="json")
    assert "assessment" not in seed.model_dump_json()


def test_missing_valuation_replaces_unsupported_value_narrative(tmp_path):
    journal = journal_for(tmp_path)
    caller = Caller(challenge=False)
    def unsupported(stage, context):
        value = caller(stage, context)
        if stage == "synthesis":
            value["dimensions"][1]["judgement"] = "合理价值20至30元"
        return value
    output = run_native_research(seed_for(journal), caller=unsupported, ledger=journal.ledger)
    assert "20至30" not in output.assessment.model_dump_json()
    assert output.assessment.dimensions[1].status == "unresolved"


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_serialized_policy_order_is_normalized_without_another_model_call(tmp_path, mode):
    from tradingagents.agents.schemas._research_assessment import DIMENSIONS_BY_MODE
    journal = journal_for(tmp_path)
    caller = Caller(challenge=False)

    def serialized(stage, context):
        value = caller(stage, context)
        if stage == "synthesis":
            value["dimensions"].sort(key=lambda item: item["dimension"])
        return value

    output = run_native_research(seed_for(journal, mode), caller=serialized, ledger=journal.ledger)
    assert tuple(item.dimension for item in output.assessment.dimensions) == DIMENSIONS_BY_MODE[mode]
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 3


@pytest.mark.parametrize("damage", ["missing", "duplicate", "unknown_ref"])
def test_dimension_normalization_retains_reference_and_membership_gates(tmp_path, damage):
    journal = journal_for(tmp_path)
    caller = Caller(challenge=False)

    def invalid(stage, context):
        value = caller(stage, context)
        if stage == "synthesis":
            if damage == "missing":
                value["dimensions"].pop()
            elif damage == "duplicate":
                value["dimensions"][-1] = value["dimensions"][0]
            else:
                value["dimensions"][1]["claim_ids"] = ["fabricated"]
        return value

    with pytest.raises(ValueError):
        run_native_research(seed_for(journal), caller=invalid, ledger=journal.ledger)


def test_qualified_dimension_still_rejects_unknown_support(tmp_path):
    from tradingagents.agents.schemas._native_stage import SynthesisProposalV1
    from tradingagents.research.native_policy import gate_dimensions
    journal = journal_for(tmp_path)
    captured = {}
    caller = Caller(challenge=False)

    def capture(stage, context):
        value = caller(stage, context)
        if stage == "synthesis":
            captured.update(record=ResearchRecordV1.model_validate(context["record"]), proposal=value)
        return value

    run_native_research(seed_for(journal), caller=capture, ledger=journal.ledger)
    record = captured["record"]
    record = record.model_copy(update={"claims": tuple(
        c.model_copy(update={"kind": "unknown"}) if c.kind == "inference" else c
        for c in record.claims)})
    with pytest.raises(ValueError, match="wrong dimension"):
        gate_dimensions(record, SynthesisProposalV1.model_validate(captured["proposal"]).dimensions)


def test_unavailable_dimension_discards_cross_role_support_and_value_narrative(tmp_path):
    journal = journal_for(tmp_path)
    caller = Caller(challenge=False)

    def unavailable(stage, context):
        value = caller(stage, context)
        if stage == "synthesis":
            value["dimensions"][1].update(status="supported", judgement="价值20元",
                claim_ids=value["dimensions"][0]["claim_ids"])
        return value

    output = run_native_research(seed_for(journal), caller=unavailable, ledger=journal.ledger)
    valuation = output.assessment.dimensions[1]
    assert valuation.status == "unresolved" and not valuation.claim_ids
    assert "20元" not in valuation.judgement
    assert "unqualified_dimension_claims_discarded" in valuation.limitations


def test_adapter_cached_response_survives_lost_kernel_cache(tmp_path):
    journal = journal_for(tmp_path)
    token = journal.ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="native.operating_quality", logical_call_id="native.operating_quality")
    journal.ledger.mark_dispatched(token)
    restored = CatalystJournal(journal.observer, {"test": "bounded-verification"}, require_existing=True)
    class RecoveryCaller(Caller):
        def recover_cached(self, stage, context):
            if stage == "operating_quality":
                return Caller.__call__(Caller(), stage, context)
            return None
    caller = RecoveryCaller(challenge=False)
    output = run_native_research(seed_for(restored), caller=caller, ledger=restored.ledger)
    assert output.hypotheses
    assert [stage for stage, _ in caller.calls] == ["challenge", "synthesis"]
    assert restored.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 3


def test_checkpoint_conflict_is_not_downgraded_to_unavailable(tmp_path):
    journal = journal_for(tmp_path)
    def conflicting(*args):
        raise CatalystCheckpointConflict("prompt changed")
    with pytest.raises(CatalystCheckpointConflict):
        run_native_research(seed_for(journal), caller=conflicting, ledger=journal.ledger)
    assert journal.ledger.cached_result("native.output") is None


def test_unavailable_fact_seed_rejected_before_any_model(tmp_path):
    from tests.test_bounded_verification import frozen
    journal = journal_for(tmp_path)
    payload = seed_for(journal).model_dump(mode="json")
    payload["evidence"][0]["availability"] = "unavailable"
    seed = frozen(payload)
    with pytest.raises(ValueError, match="qualified saved source"):
        run_native_research(seed, caller=lambda *_: pytest.fail("unqualified"), ledger=journal.ledger)
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 0


def test_minor_primary_cannot_hide_critical_challenge(tmp_path):
    journal = journal_for(tmp_path)
    caller = Caller(check=False)
    def competing(stage, context):
        value = caller(stage, context)
        if stage == "challenge":
            minor = {**value["challenges"][0], "statement": "较小疑点", "severity": "minor"}
            value["challenges"] = [minor, value["challenges"][0]]
        if stage == "synthesis":
            value["primary_challenge_id"] = context["record"]["challenges"][0]["challenge_id"]
        return value
    output = run_native_research(seed_for(journal), caller=competing, ledger=journal.ledger)
    primary = next(c for c in output.challenges if c.challenge_id == output.assessment.primary_challenge_id)
    assert primary.severity == "critical"


@pytest.mark.parametrize("concurrency", [1, 2])
def test_tight_budget_is_reserved_in_role_order(tmp_path, monkeypatch, concurrency):
    from tests.test_native_record import fixture
    from tradingagents.execution.budget import DEFAULT_LIMITS
    from tradingagents.research.native_record import build_native_record
    monkeypatch.setitem(DEFAULT_LIMITS, BudgetBucket.MAIN_ANALYSIS, 1)
    journal = journal_for(tmp_path)
    draft, context = fixture()
    draft = draft.model_copy(update={"run_id": journal.ledger.run_id, "evidence": tuple(
        {**source, "run_id": journal.ledger.run_id} for source in draft.evidence)})
    seed = build_native_record(draft, context, mode="company_research")
    caller = Caller(check=False)
    output = run_native_research(seed, caller=caller, ledger=journal.ledger, concurrency=concurrency)
    assert [stage for stage, _ in caller.calls] == ["operating_quality"]
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert output.assessment.quality == "LOW_CONFIDENCE"


def test_saved_seed_missing_tampered_or_different_run(tmp_path):
    journal = journal_for(tmp_path)
    assert load_native_seed(journal.ledger) is None
    seed = seed_for(journal)
    run_native_research(seed, caller=Caller(challenge=False), ledger=journal.ledger)
    assert load_native_seed(journal.ledger) == seed
    journal.state["native_seed"]["ticker"] = "000001"
    with pytest.raises(CatalystCheckpointConflict, match="identity mismatch"):
        load_native_seed(journal.ledger)


def test_fact_partition_isolation_and_two_worker_bound(tmp_path):
    journal = journal_for(tmp_path)
    seed = seed_for(journal)
    # Financial plus an announcement yields two independent specialist views.
    payload = seed.model_dump(mode="json")
    source = copy.deepcopy(payload["evidence"][0])
    source.update(evidence_id="e2", source_name="cninfo.announcements")
    payload["evidence"].append(source)
    payload["claims"].append({"claim_id": "f2", "kind": "fact", "statement": "披露公告标题", "evidence_ids": ["e2"]})
    from tradingagents.agents.schemas._research_record import (
        SourceEvidenceV1,
        make_evidence_snapshot,
    )
    payload["snapshots"] = [make_evidence_snapshot(tuple(SourceEvidenceV1.model_validate(s) for s in payload["evidence"])).model_dump(mode="json")]
    seed = ResearchRecordV1.model_validate(payload)
    lock, active, maximum = threading.Lock(), 0, 0
    base = Caller(challenge=False, check=False)
    def tracked(stage, context):
        nonlocal active, maximum
        if stage in ("operating_quality", "event_context"):
            assert len(context["facts"]) == 1
            assert context["facts"][0]["claim_id"] == ("f1" if stage == "operating_quality" else "f2")
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            result = base(stage, context)
            with lock:
                active -= 1
            return result
        return base(stage, context)
    run_native_research(seed, caller=tracked, ledger=journal.ledger)
    assert maximum == 2


def test_scoped_unknowns_cannot_be_confused_with_global_source_coverage(tmp_path):
    journal=journal_for(tmp_path)
    base=Caller(challenge=False,check=False)
    seen={}
    def caller(stage,context):
        seen[stage]=context
        proposal=base(stage,context)
        if stage == 'operating_quality':
            proposal['unknowns'] = ['尚未取得产品毛利细分']
        return proposal
    record=run_native_research(seed_for(journal),caller=caller,ledger=journal.ledger,scoped=True)
    assert seen['operating_quality']['view_scope']['role']=='operating_quality'
    assert 'global_coverage' in seen['synthesis']
    assert seen['synthesis']['dimension_policy']['operating_quality'][1]=='dimension_judgement_requires_further_validation'
    assert 'specialist_unknown:operating_quality:尚未取得产品毛利细分' in record.limitations
    from tradingagents.runtime.reports import build_markdown_from_native_record
    report=build_markdown_from_native_record(record)
    assert '经营专项待核查（仅代表该专项视图）' in report
    assert 'specialist\\_unknown' not in report
    assert run_native_research(seed_for(journal),caller=lambda *_:pytest.fail('cached replay dispatched'),ledger=journal.ledger,scoped=True)==record
