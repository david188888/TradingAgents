"""Offline programmatic C2 spine; this does not exercise public RunManager wiring."""

import copy
import threading

import pytest

from tests.test_native_record import fixture
from tests.test_price_statistics_context import context as price_context
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.graph.native_research import load_native_seed, run_native_research
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.evidence_freeze import CAP_PRICE
from tradingagents.research.native_record import build_native_record
from tradingagents.research.price_statistics import build_price_statistics
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal, load_checkpoint
from tradingagents.runtime.reports import build_markdown_from_native_record
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.research_record_projection import project_research_record


class PipelineCaller:
    """Deterministic proposals over the actual frozen fact partitions."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, stage, context):
        with self.lock:
            self.calls.append((stage, copy.deepcopy(context)))
        if stage in {"operating_quality", "event_context", "market_context"}:
            sources = {item["evidence_id"]: item["source_name"] for item in context["sources"]}
            names = set(sources.values())
            if stage == "operating_quality":
                assert names <= {"tushare.financial_statements", "user.original_thesis"}
                financial = next(fact for fact in context["facts"] if "income.revenue" in fact["statement"])
                support = [financial["claim_id"]]
                support.extend(fact["claim_id"] for fact in context["facts"]
                    if any(sources[key] == "user.original_thesis" for key in fact["evidence_ids"]))
                condition = {"condition_role": "invalidation", "text": "本期披露收入低于110 CNY",
                    "check": {"kind": "financial", "operation": "value", "current": {
                        "evidence_id": financial["evidence_ids"][0], "table": "income",
                        "field": "revenue", "report_period": "2026-06-30"},
                        "predicate": {"operator": "lt", "threshold": "110", "unit": "CNY"}}}
                statement = "收入兑现可能支撑经营改善，持续性仍待核查。"
            else:
                assert names == ({"cninfo.announcements"} if stage == "event_context" else {"tushare.adjusted_daily"})
                support = [context["facts"][0]["claim_id"]]
                condition = {"condition_role": "invalidation", "text": "后续合格证据与目前解释相矛盾"}
                statement = "公告的经济影响尚待正文核对。" if stage == "event_context" else "历史市场表现可能反映关注变化，不能据此估值。"
            return {"hypotheses": [{"statement": statement, "supporting_fact_ids": support,
                "conditions": [condition], "alternative_explanation": "一次性因素或统计窗口也可能解释当前观察。"}]}
        if stage == "challenge":
            condition_id, condition = next((key, value) for key, value in context["conditions"].items()
                if value["check"] is not None and value["check"]["kind"] == "financial")
            assert not any(role in condition["hypothesis_id"] for role in ("operating", "event", "market"))
            return {"challenges": [{"hypothesis_id": condition["hypothesis_id"], "condition_id": condition_id,
                "statement": "收入门槛不能证明经营改善可持续。", "severity": "critical",
                "risk_type": "operations", "proposed_test": "核对收入门槛，并补充后续经营兑现证据。"}]}
        assert stage == "synthesis"
        record = context["record"]
        assert record["verifications"] and record["verifications"][0]["scope"] == "predicate_only"
        sources = {item["evidence_id"]: item["source_name"] for item in record["evidence"]}
        inferences = [item for item in record["claims"] if item["kind"] == "inference"]
        financial = next(item for item in inferences if "tushare.financial_statements" in {sources[key] for key in item["evidence_ids"]})
        event = next(item for item in inferences if "cninfo.announcements" in {sources[key] for key in item["evidence_ids"]})
        market = next(item for item in inferences if "tushare.adjusted_daily" in {sources[key] for key in item["evidence_ids"]})
        dimension_claims = {"operating_quality": financial, "holding_thesis": financial,
            "catalyst_delivery": event, "market_context": market}
        dimensions = []
        for name, (ceiling, reason) in context["dimension_policy"].items():
            dimensions.append({"dimension": name, "status": ceiling, "judgement": "证据支持条件性研究，仍需补齐核查。",
                "claim_ids": [dimension_claims[name]["claim_id"]] if ceiling != "unresolved" else [],
                "limitations": [reason] if ceiling == "unresolved" else []})
        return {"judgement": "值得继续核查经营兑现；收入条件核查仍不足以证明持续性。",
            "dimensions": dimensions, "key_claim_ids": [financial["claim_id"], event["claim_id"], market["claim_id"]],
            "primary_challenge_id": record["challenges"][0]["challenge_id"], "next_check": "补充公告正文与下一期经营兑现。",
            "challenge_assessments": [{"challenge_id": item["challenge_id"],
                "rationale": "局部条件核查没有解决整体经济假设。"} for item in record["challenges"]]}


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_programmatic_three_mode_spine_publishes_projects_reports_and_replays_without_calls(tmp_path, monkeypatch, mode):
    """Actual stores/adapters; mock proposals; no route/default migration claim."""
    def forbidden(*args, **kwargs):
        pytest.fail("programmatic acceptance must not call a real provider or model")

    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    monkeypatch.setattr("tradingagents.execution.native_model.create_llm_client", forbidden)
    store = RunStore(tmp_path)
    thesis = "经营现金流改善可能延续。" if mode == "holding_review" else None
    thesis_date = "2026-09-01" if thesis else None
    snapshot = RunSnapshot.create(ticker="600519", analysis_date="2026-09-30",
        mode="holding_review" if thesis else "company_research",
        holding_context={"original_thesis": thesis, "facts_as_of": thesis_date} if thesis else None,
        # Existing projection maps catalyst through this metadata. This fixture
        # does not create a catalyst request or alter the public profile route.
        metadata={"research_profile": "catalyst_v1"} if mode == "catalyst_research" else {})
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    identity = {"test": "native-programmatic-pipeline", "mode": mode}
    journal = CatalystJournal(observer, identity)
    bars, provenance = price_context(30)
    provenance["input_sha256"] = "a" * 64
    prices = {"bars": bars, "provenance": provenance, "computed_statistics": build_price_statistics(bars, provenance)}
    draft, context = fixture(extra=((CAP_PRICE, "tushare.adjusted_daily", prices, None),))
    draft = draft.model_copy(update={"run_id": snapshot.run_id,
        "evidence": tuple({**item, "run_id": snapshot.run_id} for item in draft.evidence)})
    journal.put("draft", draft.model_dump(mode="json"))
    journal.put("evidence_context", context)
    seed = build_native_record(draft, context, mode=mode, original_thesis=thesis, holding_facts_as_of=thesis_date)
    caller = PipelineCaller()
    record = run_native_research(seed, caller=caller, ledger=journal.ledger)
    stages = [stage for stage, _ in caller.calls]
    assert set(stages[:3]) == {"operating_quality", "event_context", "market_context"}
    assert stages[3:] == ["challenge", "synthesis"]
    assert len(record.snapshots) == 2 and len(record.verifications) == 1
    assert record.verifications[0].status == "inconclusive"
    assert record.assessment.quality == "LOW_CONFIDENCE"
    assert record.assessment.primary_challenge_id == record.challenges[0].challenge_id
    assert all(item.outcome == "unresolved" for item in record.assessment.challenge_assessments)
    assert (record.assessment.forward_window_calendar_days == 84) == (mode == "catalyst_research")
    dimensions = {item.dimension: item for item in record.assessment.dimensions}
    assert dimensions["operating_quality"].status == dimensions["market_context"].status == "conditional"
    if mode == "holding_review":
        assert dimensions["holding_thesis"].status == "conditional"
        assert dimensions["holding_thesis"].challenge_ids == (record.challenges[0].challenge_id,)
    if mode != "catalyst_research":
        assert dimensions["valuation"].status == "unresolved"

    def authorize(value):
        saved = load_checkpoint(store, snapshot.run_id)
        assert saved["native_publication_candidate"] == record.model_dump(mode="json")
        value.put("publication_authorized", True)

    artifact = publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=authorize)
    events = store.read_events(snapshot.run_id)
    assert ResearchRecordV1.model_validate_json(store.read_artifact(snapshot.run_id, artifact)) == record
    projection = project_research_record(store, snapshot.run_id)
    assert projection["state"] == "ready"
    projected = ResearchRecordV1.model_validate(projection["record"])
    assert projected == record
    markdown = build_markdown_from_native_record(projected)
    assert record.assessment.judgement in markdown
    assert record.challenges[0].statement in markdown
    assert "仅检验条件" in markdown and "不自动关闭挑战" in markdown
    assert "签订重大合同的公告" in markdown
    assert "原文与来源回溯" in markdown and "120.125" in markdown
    assert len(record.metrics) == 6
    for bucket, count in ((BudgetBucket.MAIN_ANALYSIS, 5), (BudgetBucket.SUPPLEMENT_ROUNDS, 1),
        (BudgetBucket.SUPPLEMENT_CAPABILITIES, 1), (BudgetBucket.DATA_CAPABILITY_CALLS, 1),
        (BudgetBucket.DATA_HTTP_ATTEMPTS, 0)):
        assert journal.ledger.consumed(bucket) == count

    # Reopen the actual store and recover the exact public V0. Raw context
    # JSON undergoes RFC8785 normalization (e.g. 2.0 -> 2); it must not be used
    # to reconstruct the provider-representation source-family hash on replay.
    recovered_store = RunStore(tmp_path)
    recovered_observer = DurableRunObserver(recovered_store, snapshot.run_id, development_assertions=False)
    recovered = CatalystJournal(recovered_observer, identity, require_existing=True)
    restored_events = recovered_store.read_events(snapshot.run_id)
    assert all(event.type == "artifact.written" and event.payload.get("kind") == "catalyst-checkpoint"
               for event in restored_events[len(events):])
    restored_seed = load_native_seed(recovered.ledger)
    assert restored_seed == seed
    resumed = run_native_research(restored_seed, caller=forbidden, ledger=recovered.ledger)
    assert resumed == record
    assert publish_native_record(recovered_observer, record=resumed, ledger=recovered.ledger,
        publication_authorizer=forbidden) == artifact
    assert project_research_record(recovered_store, snapshot.run_id) == projection
    assert build_markdown_from_native_record(resumed) == markdown
    assert recovered_store.read_events(snapshot.run_id) == restored_events
    assert recovered.ledger.records() == journal.ledger.records()
    assert len(caller.calls) == 5
    assert not any(event.type == "run.completed" for event in events)
