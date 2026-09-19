"""Run-date enforcement at model-visible tool boundaries."""

from __future__ import annotations

from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tradingagents.agents.utils import (
    core_stock_tools,
    data_meta_tools,
    fundamental_data_tools,
    macro_data_tools,
    market_data_validation_tools,
    news_data_tools,
    technical_indicators_tools,
    wind_data_tools,
)
from tradingagents.dataflows.date_window import as_of, as_of_window, trade_date_from_state

TRADE_DATE = "2026-08-14"
_STATE = {"trade_date": TRADE_DATE}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("2026-09-14", TRADE_DATE),
        ("2026-08-01", "2026-08-01"),
        (None, TRADE_DATE),
        ("Sept 1", TRADE_DATE),
        ("", TRADE_DATE),
    ],
)
def test_as_of_takes_the_earlier_date(requested, expected):
    assert as_of(requested, TRADE_DATE) == expected


@pytest.mark.unit
def test_as_of_without_run_date_preserves_direct_call():
    assert as_of("2026-09-14", "") == "2026-09-14"
    assert as_of(None, "") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-08-01", "2026-09-14", ("2026-08-01", TRADE_DATE)),
        ("2026-08-01", "2026-08-10", ("2026-08-01", "2026-08-10")),
        ("2026-09-01", "2026-09-08", ("2026-08-07", TRADE_DATE)),
    ],
)
def test_as_of_window_clamps_without_reversing_window(start, end, expected):
    assert as_of_window(start, end, TRADE_DATE) == expected


@pytest.mark.unit
def test_invalid_nonempty_trade_date_fails_closed():
    with pytest.raises(ValueError, match="trade_date"):
        trade_date_from_state({"trade_date": "not-a-date"})


@pytest.mark.unit
def test_missing_state_preserves_legacy_direct_calls():
    assert trade_date_from_state(None) == ""
    assert as_of_window("2026-09-01", "2026-09-08", "") == (
        "2026-09-01",
        "2026-09-08",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool",
    [
        core_stock_tools.get_stock_data,
        fundamental_data_tools.get_fundamentals,
        fundamental_data_tools.get_balance_sheet,
        fundamental_data_tools.get_cashflow,
        fundamental_data_tools.get_income_statement,
        macro_data_tools.get_macro_indicators,
        market_data_validation_tools.get_verified_market_snapshot,
        market_data_validation_tools.get_verified_current_market_snapshot,
        news_data_tools.get_news,
        news_data_tools.get_global_news,
        news_data_tools.get_news_windows,
        technical_indicators_tools.get_indicators,
        wind_data_tools.get_index_snapshot,
        wind_data_tools.get_index_history,
        wind_data_tools.get_index_fundamentals,
        wind_data_tools.get_macro_series,
        wind_data_tools.get_equity_risk_metrics,
        data_meta_tools.get_market_research_bundle,
        data_meta_tools.get_fundamentals_research_bundle,
        data_meta_tools.get_news_research_bundle,
    ],
)
def test_injected_state_is_hidden_from_model_tool_schema(tool):
    assert "state" not in tool.tool_call_schema.model_json_schema()["properties"]


@pytest.mark.unit
class _ToolState(TypedDict):
    messages: Annotated[list, add_messages]
    trade_date: str


@pytest.mark.unit
def test_toolnode_injects_hidden_state_and_clamps_before_provider(monkeypatch):
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        core_stock_tools,
        "route_to_vendor",
        lambda _method, *args: calls.append(args) or "ok",
    )
    graph = StateGraph(_ToolState)
    graph.add_node("tools", ToolNode([core_stock_tools.get_stock_data]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)

    graph.compile().invoke(
        {
            "trade_date": TRADE_DATE,
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_stock_data",
                            "args": {
                                "symbol": "AAPL",
                                "start_date": "2026-09-01",
                                "end_date": "2026-09-08",
                            },
                            "id": "tool-call-1",
                        }
                    ],
                )
            ],
        }
    )

    assert calls == [("AAPL", "2026-08-07", TRADE_DATE)]


@pytest.mark.unit
def test_dated_tools_clamp_future_arguments_before_vendor_routing(monkeypatch):
    calls: list[tuple[str, tuple[object, ...]]] = []

    def record(method, *args, **_kwargs):
        calls.append((method, args))
        return "ok"

    for module in (
        core_stock_tools,
        fundamental_data_tools,
        macro_data_tools,
        news_data_tools,
        technical_indicators_tools,
        wind_data_tools,
    ):
        monkeypatch.setattr(module, "route_to_vendor", record)
    monkeypatch.setattr(
        market_data_validation_tools,
        "build_verified_market_snapshot",
        lambda *args: calls.append(("verified", args)) or "ok",
    )
    monkeypatch.setattr(
        market_data_validation_tools,
        "build_verified_current_market_snapshot",
        lambda *args: calls.append(("verified_current", args)) or "ok",
    )

    core_stock_tools.get_stock_data.func("AAPL", "2026-09-01", "2026-09-08", state=_STATE)
    fundamental_data_tools.get_fundamentals.func("AAPL", "2026-09-08", state=_STATE)
    fundamental_data_tools.get_balance_sheet.func("AAPL", curr_date=None, state=_STATE)
    macro_data_tools.get_macro_indicators.func("cpi", "2026-09-08", state=_STATE)
    market_data_validation_tools.get_verified_market_snapshot.func(
        "AAPL", "2026-09-08", state=_STATE
    )
    market_data_validation_tools.get_verified_current_market_snapshot.func(
        "AAPL", "2026-09-08", state=_STATE
    )
    news_data_tools.get_news.func("AAPL", "2026-09-01", "2026-09-08", state=_STATE)
    news_data_tools.get_global_news.func("2026-09-08", state=_STATE)
    technical_indicators_tools.get_indicators.func("AAPL", "rsi", "2026-09-08", state=_STATE)
    wind_data_tools.get_index_snapshot.func("000300.SH", "2026-09-08", state=_STATE)
    wind_data_tools.get_index_history.func(
        "000300.SH", "2026-09-01", "2026-09-08", state=_STATE
    )
    wind_data_tools.get_index_fundamentals.func("000300.SH", "2026-09-08", state=_STATE)
    wind_data_tools.get_macro_series.func(
        "M0001395", "2026-09-01", "2026-09-08", state=_STATE
    )

    assert calls == [
        ("get_stock_data", ("AAPL", "2026-08-07", TRADE_DATE)),
        ("get_fundamentals", ("AAPL", TRADE_DATE)),
        ("get_balance_sheet", ("AAPL", "quarterly", TRADE_DATE)),
        ("get_macro_indicators", ("cpi", TRADE_DATE, None)),
        ("verified", ("AAPL", TRADE_DATE, 30)),
        ("verified_current", ("AAPL", TRADE_DATE)),
        ("get_news", ("AAPL", "2026-08-07", TRADE_DATE)),
        ("get_global_news", (TRADE_DATE, None, None)),
        ("get_indicators", ("AAPL", "rsi", TRADE_DATE, 30)),
        ("get_index_snapshot", ("000300.SH", TRADE_DATE)),
        ("get_index_history", ("000300.SH", "2026-08-07", TRADE_DATE, "1d")),
        ("get_index_fundamentals", ("000300.SH", TRADE_DATE)),
        ("get_macro_series", ("M0001395", "2026-08-07", TRADE_DATE)),
    ]


@pytest.mark.unit
def test_news_windows_and_insider_transactions_inherit_the_run_date(monkeypatch):
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        news_data_tools,
        "run_news_windows",
        lambda *args, **kwargs: calls.append((args, kwargs)) or "ok",
    )
    monkeypatch.setattr(
        news_data_tools,
        "route_to_vendor",
        lambda _method, *args: calls.append((args, {})) or "ok",
    )

    news_data_tools.get_news_windows.func("AAPL", "2026-09-08", state=_STATE)
    news_data_tools.get_insider_transactions.func("AAPL", state=_STATE)

    assert calls[0][0] == ("AAPL", TRADE_DATE)
    assert calls[1] == (("AAPL", TRADE_DATE), {})


@pytest.mark.unit
def test_historical_wind_risk_metrics_are_withheld_without_vendor_call(monkeypatch):
    monkeypatch.setattr(wind_data_tools, "get_current_date", lambda: "2026-09-18")
    monkeypatch.setattr(
        wind_data_tools,
        "route_to_vendor",
        lambda *args: pytest.fail("live-only Wind metrics must not be fetched historically"),
    )

    result = wind_data_tools.get_equity_risk_metrics.func("600519.SS", state=_STATE)

    assert "DATA_UNAVAILABLE" in result
    assert TRADE_DATE in result


@pytest.mark.unit
def test_current_wind_risk_metrics_keep_vendor_route(monkeypatch):
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(wind_data_tools, "get_current_date", lambda: TRADE_DATE)
    monkeypatch.setattr(
        wind_data_tools,
        "route_to_vendor",
        lambda _method, *args: calls.append(args) or "ok",
    )

    assert wind_data_tools.get_equity_risk_metrics.func("600519.SS", state=_STATE) == "ok"
    assert calls == [("600519.SS", "1y", None, None)]


@pytest.mark.unit
def test_direct_calls_without_state_retain_their_legacy_dates(monkeypatch):
    captured: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        core_stock_tools,
        "route_to_vendor",
        lambda _method, *args: captured.append(args) or "ok",
    )

    core_stock_tools.get_stock_data.func("AAPL", "2026-09-01", "2026-09-08")

    assert captured == [("AAPL", "2026-09-01", "2026-09-08")]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool", "ask"),
    [
        (data_meta_tools.get_fundamentals_research_bundle, "balance sheet"),
        (data_meta_tools.get_market_research_bundle, "price history"),
    ],
)
def test_meta_bundle_tools_clamp_the_date_before_the_provider(monkeypatch, tool, ask):
    """The bundle wrappers are model-visible too, so they need the same bound.

    They take ``curr_date`` straight from the model and fan it out to every
    selected capability; without the clamp a historical run could ask for a
    future date and receive future prices, statements, or the live profile.
    """
    seen: list[tuple] = []
    monkeypatch.setattr(
        data_meta_tools,
        "route_to_vendor",
        lambda method, *args, **kwargs: seen.append((method, args, kwargs)) or "ok",
    )

    envelope = tool.func("AAPL", "2030-01-01", ask, state=_STATE)

    assert envelope  # a JSON envelope, degraded or not
    assert seen, "no capability reached the vendor"
    for item in seen:
        assert "2030-01-01" not in str(item)
    assert any(TRADE_DATE in str(item) for item in seen)
