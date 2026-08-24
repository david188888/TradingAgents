"""Deterministic adjusted-price prefetch and Market Analyst permissions."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable

import tradingagents.agents.analysts.market_analyst as market_analyst
from tradingagents.agents.utils import market_data_validation_tools as market_tools
from tradingagents.dataflows.coverage import CoveredText, PriceSeriesCoverageV1
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _adjusted_text() -> CoveredText:
    return CoveredText(
        "Date,Close\n2026-07-31,17.0",
        PriceSeriesCoverageV1(
            capability="adjusted_price_history",
            source_id="tushare.qfq_daily",
            requested_start="2025-07-31",
            requested_end="2026-07-31",
            actual_start="2025-07-31",
            actual_end="2026-07-31",
            item_count=250,
            completeness="complete",
            sources=("tushare.qfq_daily",),
            as_of="2026-07-31",
            price_basis="qfq",
            adjustment_source="tushare.pro_bar(adj=qfq)",
            adjustment_verified=True,
            granularity="daily",
        ),
    )


def test_price_prefetch_separates_adjusted_requirement_from_raw_audit(monkeypatch):
    calls: list[str] = []

    def route(method, *_args):
        calls.append(method)
        return _adjusted_text() if method == "get_adjusted_price_history" else "raw"

    monkeypatch.setattr(market_tools, "route_to_vendor", route)
    payload = json.loads(
        market_tools.run_adjusted_price_prefetch(
            "000338.SZ",
            "2026-07-31",
            horizon="short",
        )
    )

    assert calls == ["get_adjusted_price_history", "get_stock_data"]
    assert payload["adjusted"]["coverage"]["price_basis"] == "qfq"
    assert payload["raw_audit"]["status"] == "ok"


def test_adjusted_failure_is_not_replaced_by_raw_audit(monkeypatch):
    def route(method, *_args):
        if method == "get_adjusted_price_history":
            raise RuntimeError("adjusted unavailable")
        return "raw data"

    monkeypatch.setattr(market_tools, "route_to_vendor", route)
    payload = json.loads(
        market_tools.run_adjusted_price_prefetch(
            "000338.SZ",
            "2026-07-31",
            horizon="long",
        )
    )

    assert payload["adjusted"]["status"] == "unavailable"
    assert payload["adjusted"]["degradations"] == [
        "adjusted_price_source_unavailable"
    ]
    assert payload["raw_audit"]["status"] == "ok"


def test_market_graph_forces_price_prefetch_before_analyst():
    class DummyConditional:
        def should_continue_market(self, _state):
            return "Msg Clear Market"

        def should_continue_debate(self, _state):
            return "Research Manager"

        def should_continue_risk_analysis(self, _state):
            return "Portfolio Manager"

    graph = GraphSetup(
        None,
        None,
        {"market": lambda state: state},
        DummyConditional(),
    ).setup_graph(["market"]).compile()
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    assert ("A-share Supplement Prefetch", "Adjusted Price Prefetch") in edges
    assert ("Adjusted Price Prefetch", "News Window Prefetch") in edges
    assert ("Fundamentals Prefetch", "Market Analyst") in edges
    assert ("__start__", "Market Analyst") not in edges


def test_market_tool_executor_respects_wind_feature_flag():
    disabled = TradingAgentsGraph._create_tool_nodes(
        type("Config", (), {"config": {"wind_enabled": False}})()
    )["market"]
    enabled = TradingAgentsGraph._create_tool_nodes(
        type("Config", (), {"config": {"wind_enabled": True}})()
    )["market"]

    assert set(disabled.tools_by_name) == {"get_verified_current_market_snapshot"}
    assert set(enabled.tools_by_name) == {
        "get_verified_current_market_snapshot",
        "get_index_snapshot",
        "get_index_history",
        "get_index_fundamentals",
        "get_equity_risk_metrics",
    }


def test_market_bundle_is_lower_priority_and_raw_tools_are_not_bound(monkeypatch):
    class RecordingLLM(Runnable):
        bound_tools = ()
        prompt_messages = ()

        def bind_tools(self, tools):
            self.bound_tools = tuple(tool.name for tool in tools)
            return self

        def invoke(self, prompt, config=None, **kwargs):
            self.prompt_messages = tuple(prompt.messages)
            return AIMessage(content="draft", tool_calls=[])

    monkeypatch.setattr(
        market_analyst,
        "emit_methodology_artifact",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        market_analyst,
        "finalize_role_report",
        lambda *_a, **_k: ("draft", None),
    )
    llm = RecordingLLM()
    node = market_analyst.create_market_analyst(llm)

    node(
        {
            "trade_date": "2026-07-31",
            "company_of_interest": "000338.SZ",
            "messages": [HumanMessage(content="analyze")],
            "horizon": "long",
            "adjusted_price_bundle": '{"adjusted":{"status":"ok"}}',
            "a_share_supplement_bundle": '{"capital_flow":{"status":"ok"}}',
        }
    )

    assert llm.bound_tools == (
        "get_verified_current_market_snapshot",
        "get_index_snapshot",
        "get_index_history",
        "get_index_fundamentals",
        "get_equity_risk_metrics",
    )
    system = "\n".join(
        message.content for message in llm.prompt_messages if message.type == "system"
    )
    assistant = "\n".join(
        message.content for message in llm.prompt_messages if message.type == "ai"
    )
    assert '{"adjusted":' not in system
    assert '"status": "ok"' in assistant
    assert '{"capital_flow":' not in system
    assert '"capital_flow"' in assistant
    assert '"status": "ok"' in assistant
