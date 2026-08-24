"""Unit tests for the post-completion debate summary projection."""

from __future__ import annotations

import pytest

from tradingagents.observability.events import RunEventDraft
from tradingagents.web.debate_summary import (
    DEBATE_SUMMARY_LOCATOR,
    DebateSummaryArtifact,
    ResearchRoundSummary,
    RiskRoundSummary,
    ensure_debate_summary,
    reconstruct_debate,
)
from tradingagents.web.run_models import RunSnapshot
from tradingagents.web.store import RunStore

pytestmark = pytest.mark.unit


def _snapshot(*, run_id: str, status: str = "completed", provider: str = "deepseek") -> RunSnapshot:
    return RunSnapshot.create(
        run_id=run_id,
        ticker="600519.SS",
        analysis_date="2026-08-05",
        selected_analysts=("market",),
        llm_provider=provider,
        quick_think_llm="deepseek-v4-flash",
        deep_think_llm="deepseek-v4-pro",
    ).evolve(status=status)


def _output_event(
    run_id: str,
    actor_id: str,
    sequence: int,
    artifact_id: str,
) -> RunEventDraft:
    return RunEventDraft(
        run_id,
        "turn.output_ready",
        {
            "turn_id": f"{actor_id}-{sequence}",
            "turn_index": 1,
            "turn_status": "output_ready",
            "role_instance_id": actor_id,
            "graph_task_id": f"gt-{actor_id}-{sequence}",
            "graph_step": sequence,
            "artifact_id": artifact_id,
        },
        actor_id=actor_id,
    )


def _seed_run(store: RunStore, snapshot: RunSnapshot) -> list:
    run_id = snapshot.run_id
    store.create_run(snapshot)
    persisted = []
    seq = 1
    script = [
        ("researcher.bull", {"investment_debate_state": {"current_response": "多方第一轮：服务收入强劲"}}),
        ("researcher.bear", {"investment_debate_state": {"current_response": "空方第一轮：估值偏高"}}),
        ("researcher.bull", {"investment_debate_state": {"current_response": "多方第二轮：AI 需求上修"}}),
        ("researcher.bear", {"investment_debate_state": {"current_response": "空方第二轮：硬件周期下滑"}}),
        ("manager.research", {"investment_debate_state": {"judge_decision": "多方论证更充分，评级 Buy"}}),
        ("trader", {"trader_investment_plan": "分批建仓，止损 180"}),
        ("risk.aggressive", {"risk_debate_state": {"current_aggressive_response": "激进：监管风险可控"}}),
        ("risk.neutral", {"risk_debate_state": {"current_neutral_response": "中性：维持现有仓位"}}),
        ("risk.conservative", {"risk_debate_state": {"current_conservative_response": "保守：集中度风险高"}}),
        ("manager.portfolio", {"final_trade_decision": "HOLD"}),
    ]
    for actor_id, payload in script:
        ref = store.store_artifact(run_id, kind="data", value=payload)
        persisted.append(store.append_event(_output_event(run_id, actor_id, seq, ref.artifact_id)))
        seq += 1
    return persisted


def test_reconstruct_pairs_rounds_from_committed_artifacts(tmp_path):
    store = RunStore(tmp_path / "runs")
    snapshot = _snapshot(run_id="run_20260805T010101000000Z_aaaaaaaa")
    events = _seed_run(store, snapshot)

    research, risk, verdicts, research_sources, risk_sources = reconstruct_debate(
        store, snapshot.run_id, events
    )

    assert [item["round_index"] for item in research] == ["1", "2"]
    assert research[0]["bull"]["text"] == "多方第一轮：服务收入强劲"
    assert research[0]["bear"]["text"] == "空方第一轮：估值偏高"
    assert research[1]["bull"]["text"] == "多方第二轮：AI 需求上修"
    assert len(risk) == 1
    assert risk[0]["aggressive"]["text"].startswith("激进")
    assert verdicts["research_manager"] == "多方论证更充分，评级 Buy"
    assert verdicts["portfolio_manager"] == "HOLD"
    # L3 source maps carry the exact output artifact ids, keyed by lane.
    assert research_sources[0]["bull"].startswith("data:")
    assert research_sources[1]["bear"].startswith("data:")
    assert set(risk_sources[0].keys()) == {"round_index", "aggressive", "neutral", "conservative"}


def test_ensure_summary_returns_none_for_non_completed_run(tmp_path):
    store = RunStore(tmp_path / "runs")
    snapshot = _snapshot(run_id="run_20260805T020202000000Z_bbbbbbbb", status="running")
    store.create_run(snapshot)
    assert ensure_debate_summary(store, snapshot.run_id) is None


def test_ensure_summary_generates_and_caches_via_llm(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "runs")
    snapshot = _snapshot(run_id="run_20260805T030303000000Z_cccccccc")
    _seed_run(store, snapshot)

    expected = DebateSummaryArtifact(
        run_id=snapshot.run_id,
        generated_at="2026-08-05T00:00:00Z",
        model=snapshot.quick_think_llm,
        global_summary="5 轮辩论后多方占优",
        research_debate=[
            ResearchRoundSummary(
                round_index=1,
                topic="服务收入",
                summary="双方就增长前景分歧",
                keywords=["服务收入", "估值"],
                bull_summary="多方看好服务收入",
                bear_summary="空方担忧估值",
                bull_estimated_conviction=0.8,
                bear_estimated_conviction=0.6,
            )
        ],
        risk_debate=[
            RiskRoundSummary(
                round_index=1,
                topic="尾部风险",
                summary="保守方强调集中度风险",
                keywords=["监管", "集中度"],
            )
        ],
    )

    class _FakeStructured:
        def invoke(self, prompt):  # noqa: ANN001
            assert "研究辩论" in prompt
            return expected

    class _FakeLLM:
        def with_structured_output(self, schema):
            assert schema is DebateSummaryArtifact
            return _FakeStructured()

    class _FakeClient:
        def get_llm(self):
            return _FakeLLM()

    monkeypatch.setattr(
        "tradingagents.llm_clients.create_llm_client",
        lambda **kwargs: _FakeClient(),
    )

    first = ensure_debate_summary(store, snapshot.run_id)
    assert first is not None
    assert first["run_id"] == snapshot.run_id
    assert first["research_debate"][0]["bull_estimated_conviction"] == 0.8
    # Identity fields always come from the snapshot, not the LLM echo.
    assert first["model"] == snapshot.quick_think_llm

    # Second call reads from cache without invoking the LLM again.
    monkeypatch.setattr(
        "tradingagents.llm_clients.create_llm_client",
        lambda **kwargs: pytest.fail("LLM must not be called on cache hit"),
    )
    second = ensure_debate_summary(store, snapshot.run_id)
    assert second == first
    assert (tmp_path / "runs" / snapshot.run_id / DEBATE_SUMMARY_LOCATOR).is_file()


def test_ensure_summary_degrades_when_llm_raises(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "runs")
    snapshot = _snapshot(run_id="run_20260805T040404000000Z_dddddddd")
    _seed_run(store, snapshot)

    class _Boom:
        def get_llm(self):
            raise RuntimeError("upstream 500")

    monkeypatch.setattr(
        "tradingagents.llm_clients.create_llm_client",
        lambda **kwargs: _Boom(),
    )

    assert ensure_debate_summary(store, snapshot.run_id) is None
    # Run directory and snapshot untouched; no cache file written.
    assert store.read_snapshot(snapshot.run_id).status == "completed"
    assert not (tmp_path / "runs" / snapshot.run_id / DEBATE_SUMMARY_LOCATOR).exists()


def test_ensure_summary_returns_none_without_debate_turns(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "runs")
    snapshot = _snapshot(run_id="run_20260805T050505000000Z_eeeeeeee")
    store.create_run(snapshot)
    # No LLM should be constructed when there is nothing to summarize.
    monkeypatch.setattr(
        "tradingagents.llm_clients.create_llm_client",
        lambda **kwargs: pytest.fail("LLM must not be called without debates"),
    )
    assert ensure_debate_summary(store, snapshot.run_id) is None
