"""Compatibility contracts that a future shared AnalysisRunner must preserve."""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.runner import AnalysisRunner
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph

pytestmark = pytest.mark.unit


def test_initial_state_preserves_legacy_fourth_positional_past_context():
    state = Propagator().create_initial_state(
        "AAPL",
        "2026-07-17",
        "stock",
        "legacy past context",
    )

    assert state["past_context"] == "legacy past context"
    assert state["horizon"] == "medium"


def _bare_graph(*, checkpoint_enabled: bool = False) -> TradingAgentsGraph:
    """Build a graph shell without constructing providers or the real workflow."""
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "checkpoint_enabled": checkpoint_enabled,
        "data_cache_dir": "/tmp/tradingagents-test-cache",
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    }
    graph.selected_analysts = ("market",)
    graph.debug = False
    graph.curr_state = None
    graph.ticker = None
    graph._checkpointer_ctx = None
    graph.memory_log = MagicMock()
    graph.propagator = MagicMock()
    graph.graph = MagicMock()
    graph.workflow = MagicMock()
    graph._log_state = MagicMock()
    graph.resolve_instrument_context = MagicMock(return_value={"symbol": "AAPL"})
    return graph


def _request() -> AnalysisRequest:
    return AnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-17",
        asset_type="stock",
        selected_analysts=("market",),
        max_debate_rounds=1,
        max_risk_discuss_rounds=1,
    )


def test_success_clears_checkpoint_after_state_is_persisted():
    graph = _bare_graph(checkpoint_enabled=True)
    graph.memory_log.get_past_context.return_value = ""
    graph.propagator.create_initial_state.return_value = {"input": True}
    graph.propagator.get_graph_args.return_value = {}
    compiled = MagicMock()
    restored = MagicMock()
    graph.workflow.compile.side_effect = [compiled, restored]
    compiled.invoke.return_value = {"final_trade_decision": "Rating: Hold"}
    context = MagicMock()
    context.__enter__.return_value = object()

    with (
        patch("tradingagents.execution.runner.get_checkpointer", return_value=context),
        patch("tradingagents.execution.runner.checkpoint_step", return_value=None),
        patch("tradingagents.execution.runner.clear_checkpoint") as clear,
    ):
        AnalysisRunner(graph).run(_request())

    graph._log_state.assert_called_once()
    clear.assert_called_once_with(
        "/tmp/tradingagents-test-cache",
        "AAPL",
        "2026-07-17",
        "analysts=market|debate=1|risk=1|asset=stock|horizon=medium",
    )
