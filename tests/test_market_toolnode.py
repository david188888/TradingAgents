"""The Market Analyst executor matches its raw-snapshot-only permission set."""
import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_market_toolnode_respects_wind_feature_flag():
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
