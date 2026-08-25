"""H1 - Localhost server for Playwright e2e with a deterministic fake runner.

Started by ``frontend/playwright.config.ts`` webServer. Composes the real
FastAPI app + SingleRunManager + RunStore with a fake runner that emits a
deterministic 13-role event sequence, so the browser exercises the real
SPA + SSE + artifact pipeline without a live LLM or data vendor.

The fake runner also writes the typed public outputs (research / trader /
risk / portfolio) the reader-first DecisionBrief consumes, and the debate
summary LLM is replaced with a deterministic stub so L2 round cards and L3
full-text lanes are exercised against fixed fixtures.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from tradingagents.execution.models import (
    AnalysisCancelled,
    AnalysisRequest,
    AnalysisResult,
    CancellationToken,
)
from tradingagents.observability.events import RunEventDraft
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.broker import EventBroker
from tradingagents.web.manager import SingleRunManager

# Deterministic 13-role script: (actor_id, response_text, business_delta).
_SCRIPT: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("analyst.market", "市场行情偏强，成交量放大", {"market_report": "市场行情偏强，成交量放大"}),
    ("analyst.sentiment", "社区情绪中性偏多", {"sentiment_report": "社区情绪中性偏多"}),
    ("analyst.news", "公司新闻覆盖充分", {"news_report": "公司新闻覆盖充分"}),
    ("analyst.fundamentals", "基本面稳健，现金流充足", {"fundamentals_report": "基本面稳健，现金流充足"}),
    ("evidence.steward", "证据门已通过", {"evidence_status": "sufficient", "evidence_report": "证据门已通过"}),
    ("researcher.bull", "多方：品牌护城河支撑估值", {"investment_debate_state": {"current_response": "多方：品牌护城河支撑估值", "count": 1}}),
    ("researcher.bear", "空方：估值安全边际不足", {"investment_debate_state": {"current_response": "空方：估值安全边际不足", "count": 1}}),
    ("manager.research", "研究经理裁决：多方占优", {"investment_debate_state": {"judge_decision": "研究经理裁决：多方占优"}}),
    ("trader", "交易员计划：分批建仓", {"trader_investment_plan": "交易员计划：分批建仓"}),
    ("risk.aggressive", "激进观点：可加仓", {"risk_debate_state": {"current_aggressive_response": "激进观点：可加仓"}}),
    ("risk.neutral", "中性观点：维持仓位", {"risk_debate_state": {"current_neutral_response": "中性观点：维持仓位"}}),
    ("risk.conservative", "保守观点：减仓对冲", {"risk_debate_state": {"current_conservative_response": "保守观点：减仓对冲"}}),
    ("manager.portfolio", "组合经理最终决策：HOLD", {"final_trade_decision": "HOLD", "risk_debate_state": {"judge_decision": "组合经理最终决策：HOLD"}}),
)

# Typed public outputs for the five typed-role turns. Evidence refs use the
# placeholder below and are substituted with the real evidence artifact ref id
# at run time (the digest is content-derived and cannot be known in advance).
_EVIDENCE_REF_PLACEHOLDER = "evidence:e2e-claim"

_PUBLIC_OUTPUT_TEMPLATES: dict[str, dict[str, Any]] = {
    "manager.research": {
        "kind": "research",
        "value": {
            "recommendation": "Buy",
            "rationale": "多方关于服务收入的论证更充分，AI 需求上行支撑估值。",
            "strategic_actions": "分批建仓",
            "strategy_signals": [
                {
                    "strategy_id": "fundamentals",
                    "conviction": 0.7,
                    "confidence": 0.9,
                    "abstain": False,
                    "key_findings": [
                        {"text": "服务收入同比增 15%", "evidence_ref_ids": [_EVIDENCE_REF_PLACEHOLDER]},
                    ],
                }
            ],
            "public_digest": {
                "agreed_facts": [{"text": "两家一致认可现金流稳健", "evidence_ref_ids": [_EVIDENCE_REF_PLACEHOLDER]}],
                "key_disagreements": [{"text": "增速假设存在分歧", "evidence_ref_ids": [_EVIDENCE_REF_PLACEHOLDER]}],
                "changed_views": [],
                "remaining_uncertainties": [],
            },
        },
    },
    "trader": {
        "kind": "trader",
        "value": {
            "action": "Buy",
            "reasoning": "分批建仓控制风险",
            "entry_price": 180.0,
            "stop_loss": 165.0,
            "position_sizing": "30%",
        },
    },
    "risk.aggressive": {
        "kind": "risk",
        "value": {
            "role": "aggressive",
            "conviction": 0.6,
            "confidence": 0.8,
            "abstain": False,
            "evidence_summary": "监管风险可控",
            "evidence_summary_ref": None,
        },
    },
    "risk.neutral": {
        "kind": "risk",
        "value": {
            "role": "neutral",
            "conviction": 0.0,
            "confidence": 0.8,
            "abstain": False,
            "evidence_summary": "维持现有仓位",
            "evidence_summary_ref": None,
        },
    },
    "risk.conservative": {
        "kind": "risk",
        "value": {
            "role": "conservative",
            "conviction": -0.6,
            "confidence": 0.8,
            "abstain": False,
            "evidence_summary": "集中度风险偏高",
            "evidence_summary_ref": None,
        },
    },
    "manager.portfolio": {
        "kind": "portfolio",
        "value": {
            "rating": "Hold",
            "execution_action": "Hold",
            "requested_quantity": 0,
            "price_target": None,
            "time_horizon": None,
            "top_drivers": [
                {"label": "服务收入增长", "evidence_ref_ids": [_EVIDENCE_REF_PLACEHOLDER], "direction": "positive", "importance": 0.8},
                {"label": "估值集中度风险", "evidence_ref_ids": [_EVIDENCE_REF_PLACEHOLDER], "direction": "risk", "importance": 0.6},
            ],
            "reader_fields": {
                "executive_summary": {"text": "组合经理维持中性评级，等待更多确认", "evidence_ref_ids": [_EVIDENCE_REF_PLACEHOLDER]},
                "catalysts": [],
                "invalidation_conditions": [],
            },
        },
    },
}


def _substitute_ref(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {key: _substitute_ref(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_ref(item, old, new) for item in value]
    return new if value == old else value


def _evidence_ref_id(artifact_id: str) -> str:
    """Mirror projections._evidence_ref_index's deterministic ref id."""
    return hashlib.sha256(
        json.dumps(
            {"kind": "artifact", "artifact_id": artifact_id},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


class _FakeRunner:
    """Deterministic ManagedRunner that emits the 13-role script via observer."""

    def __init__(self, request: AnalysisRequest, observer: DurableRunObserver) -> None:
        self._request = request
        self._observer = observer

    def run(
        self,
        request: AnalysisRequest,
        *,
        cancellation_token: CancellationToken,
        observation_context: Any,
        callbacks: list[Any],
        checkpoint_run_id: str,
        checkpoint_guard: Any,
    ) -> AnalysisResult:
        import time

        observer = self._observer
        graph_step = 1
        final_state: dict[str, Any] = {}
        evidence_ref_id: str | None = None
        for index, (actor_id, _text, business_delta) in enumerate(_SCRIPT):
            if cancellation_token.is_cancelled:
                raise AnalysisCancelled(partial_state={})
            ref = observer.start_turn(
                actor_id=actor_id,
                graph_task_id=f"gt-{actor_id}-{index}",
                graph_step=graph_step,
                turn_index=1,
            )
            graph_step += 1
            artifact = observer.store_artifact("data", business_delta)
            observer.mark_turn_output_ready(ref.turn_id, artifact=artifact)
            observer.complete_turn(ref.turn_id, duration_ms=10, reason="fake_complete")

            if actor_id == "evidence.steward":
                evidence_ref_id = _evidence_ref_id(artifact.artifact_id)

            template = _PUBLIC_OUTPUT_TEMPLATES.get(actor_id)
            if template is not None:
                value = template["value"]
                if evidence_ref_id is not None:
                    value = _substitute_ref(value, _EVIDENCE_REF_PLACEHOLDER, evidence_ref_id)
                _promote_public_output(
                    observer,
                    actor_id=actor_id,
                    turn_id=ref.turn_id,
                    committed_sequence=index + 1,
                    kind=template["kind"],
                    value=value,
                )

            final_state.update(business_delta)
            # Pace the event stream so live SSE delivery is observable and
            # cancellation tests have a window to click cancel mid-run.
            time.sleep(_PACE_SECONDS)
        return AnalysisResult(
            final_state=final_state,
            final_signal="HOLD",
        )


def _promote_public_output(
    observer: DurableRunObserver,
    *,
    actor_id: str,
    turn_id: str,
    committed_sequence: int,
    kind: str,
    value: dict[str, Any],
) -> str:
    """Write a typed public output artifact + artifact.written event, mirroring
    runner._promote_public_output for the deterministic e2e script."""
    public_value = {
        "schema_version": 1,
        "run_id": observer.run_id,
        "turn_id": turn_id,
        "committed_sequence": committed_sequence,
        **dict(value),
    }
    artifact = observer.store.store_artifact(
        observer.run_id,
        kind=f"public-{kind}",
        value=public_value,
    )
    observer.emit(
        RunEventDraft(
            observer.run_id,
            "artifact.written",
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "content_sha256": artifact.content_sha256,
                "byte_size": artifact.byte_size,
                "locator": artifact.locator,
                "turn_id": turn_id,
                "public_output_kind": kind,
                "committed_sequence": committed_sequence,
            },
            actor_id=actor_id,
            status="committed",
        )
    )
    return artifact.artifact_id


def _fake_runner_factory(request: AnalysisRequest, observer: DurableRunObserver) -> _FakeRunner:
    return _FakeRunner(request, observer)


def _stub_summary_llm() -> None:
    """Replace tradingagents.llm_clients.create_llm_client with a deterministic
    stub returning a fixed DebateSummaryArtifact (sources are merged in by
    ensure_debate_summary after the call, mirroring production)."""
    import tradingagents.llm_clients as llm_clients
    from tradingagents.web.debate_summary import (
        DebateSummaryArtifact,
        ResearchRoundSummary,
        RiskRoundSummary,
    )

    def make_artifact() -> DebateSummaryArtifact:
        return DebateSummaryArtifact(
            run_id="",
            generated_at="",
            model="stub",
            global_summary="经过 1 轮辩论，多方在品牌护城河论证上占优，组合经理最终维持中性评级。",
            research_debate=[
                ResearchRoundSummary(
                    round_index=1,
                    topic="估值与护城河",
                    summary="多方强调品牌护城河支撑估值，空方担忧安全边际不足。",
                    keywords=["护城河", "估值", "安全边际"],
                    bull_summary="多方：品牌护城河支撑估值",
                    bear_summary="空方：估值安全边际不足",
                    bull_estimated_conviction=0.8,
                    bear_estimated_conviction=0.6,
                )
            ],
            risk_debate=[
                RiskRoundSummary(
                    round_index=1,
                    topic="风险偏好",
                    summary="激进方认为可加仓，保守方强调集中度风险。",
                    keywords=["加仓", "集中度"],
                    aggressive_summary="激进观点：可加仓",
                    neutral_summary="中性观点：维持仓位",
                    conservative_summary="保守观点：减仓对冲",
                )
            ],
        )

    class _StubStructured:
        def __init__(self, schema) -> None:
            self._schema = schema

        def invoke(self, _prompt: str) -> DebateSummaryArtifact:
            return make_artifact()

    class _StubLLM:
        def with_structured_output(self, schema) -> _StubStructured:
            return _StubStructured(schema)

    class _StubClient:
        def get_llm(self) -> _StubLLM:
            return _StubLLM()

    llm_clients.create_llm_client = lambda **kwargs: _StubClient()  # noqa: ARG005


# Per-turn pause (seconds). Default 50ms keeps the suite fast; raise via
# E2E_TURN_PACE_MS so cancellation tests have a window to click cancel mid-run.
_PACE_SECONDS = float(os.environ.get("E2E_TURN_PACE_MS", "50")) / 1000.0


def build_app() -> Any:
    root = os.environ.get("TRADINGAGENTS_E2E_RUN_ROOT", "/tmp/tradingagents-e2e-runs")
    store = RunStore(root=root)
    broker = EventBroker(store)
    manager = SingleRunManager(store, broker=broker, runner_factory=_fake_runner_factory)
    environment = {"DEEPSEEK_API_KEY": "fake-deepseek-e2e-key"}
    _stub_summary_llm()
    app = create_app(
        store=store,
        broker=broker,
        manager=manager,
        checkpoint_available=False,
        environment=environment,
    )
    return app


if __name__ == "__main__":
    import uvicorn

    # Default matches frontend/playwright.config.ts baseURL (and the
    # reader-harness route mocks pinned to the same origin).
    port = int(os.environ.get("TRADINGAGENTS_E2E_PORT", "4173"))
    uvicorn.run(build_app(), host="127.0.0.1", port=port)
