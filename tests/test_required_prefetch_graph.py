from __future__ import annotations

from types import SimpleNamespace

from langgraph.prebuilt import ToolNode

from tradingagents.graph.setup import GraphSetup


def _logic():
    logic = SimpleNamespace()
    for key in ("market", "social", "news", "fundamentals"):
        setattr(logic, f"should_continue_{key}", lambda _state: "")
    logic.should_continue_debate = lambda _state: ""
    logic.should_continue_risk_analysis = lambda _state: ""
    return logic


def test_required_prefetch_chain_is_independent_of_selected_analyst():
    setup = GraphSetup(
        object(),
        object(),
        {
            key: ToolNode([])
            for key in ("market", "social", "news", "fundamentals")
        },
        _logic(),
    )

    graph = setup.setup_graph(["news"])

    assert {
        "Adjusted Price Prefetch",
        "News Window Prefetch",
        "Fundamentals Prefetch",
    } <= set(graph.nodes)
    assert (
        "Adjusted Price Prefetch",
        "News Window Prefetch",
    ) in graph.edges
    assert (
        "News Window Prefetch",
        "Fundamentals Prefetch",
    ) in graph.edges
    assert ("Fundamentals Prefetch", "News Analyst") in graph.edges
