"""Horizon-owned A-share supplement bundle and graph routing contracts."""

from __future__ import annotations

import json

from tradingagents.agents.utils import a_share_supplement_tools as tools
from tradingagents.graph.setup import GraphSetup
from tradingagents.research.a_share_supplement import build_a_share_supplement_plan


def test_policy_uses_horizon_windows_and_independent_capability_budgets():
    short = build_a_share_supplement_plan("short", "2026-07-31")
    medium = build_a_share_supplement_plan("medium", "2026-07-31")
    long = build_a_share_supplement_plan("long", "2026-07-31")

    assert max(item["value"] for item in short.requested_flow_windows) == 20
    assert max(item["value"] for item in medium.requested_flow_windows) == 120
    assert max(item["value"] for item in long.requested_flow_windows) == 120
    assert short.board_period == "5d"
    assert medium.board_period == long.board_period == "10d"
    assert all(capability.max_chars > 0 for capability in medium.capabilities)
    assert "interactive_questions" not in {
        capability.capability_id for capability in short.capabilities
    }
    assert "interactive_questions" in {
        capability.capability_id for capability in medium.capabilities
    }


def test_prefetch_is_stable_and_one_failure_only_degrades_that_capability(monkeypatch):
    calls: list[tuple[str, tuple, dict]] = []

    def route(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        if method == "get_a_share_hot_list":
            raise RuntimeError("provider detail must not leak")
        return f"{method} data"

    monkeypatch.setattr(tools, "route_to_vendor", route)
    monkeypatch.setattr(tools, "_current_shanghai_date", lambda: "2026-07-31")

    payload = json.loads(
        tools.run_a_share_supplement_prefetch(
            "000338.SZ",
            "2026-07-31",
            horizon="medium",
        )
    )

    expected_order = [
        capability.capability_id
        for capability in build_a_share_supplement_plan(
            "medium", "2026-07-31"
        ).capabilities
    ]
    assert [item["capability"] for item in payload["results"]] == expected_order
    assert payload["status"] == "partial"
    hot_list = next(item for item in payload["results"] if item["capability"] == "hot_list")
    assert hot_list == {
        "capability": "hot_list",
        "route_method": "get_a_share_hot_list",
        "status": "unavailable",
        "degradations": ["capability_unavailable"],
        "error_type": "source_failed",
    }
    assert "provider detail" not in json.dumps(payload)
    ordinary = next(
        item for item in payload["results"] if item["capability"] == "capital_flow"
    )
    assert ordinary["coverage"]["completeness"] == "unknown"
    assert payload["parallelism_limit"] == tools.MAX_PARALLEL_SUPPLEMENTS
    assert calls


def test_historical_run_never_fetches_current_only_sources(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        tools,
        "route_to_vendor",
        lambda method, *_args, **_kwargs: calls.append(method) or "ok",
    )
    monkeypatch.setattr(tools, "_current_shanghai_date", lambda: "2026-08-09")

    payload = json.loads(
        tools.run_a_share_supplement_prefetch(
            "000338.SZ",
            "2026-07-31",
            horizon="medium",
        )
    )

    current_only = {
        "get_a_share_board_fund_flow",
        "get_a_share_hot_list",
        "get_a_share_hot_concept",
        "get_a_share_concept_blocks",
        "get_a_share_interactive_questions",
        "get_cls_telegraph",
        "get_a_share_northbound_holdings",
    }
    assert not current_only.intersection(calls)
    for item in payload["results"]:
        if item["route_method"] in current_only:
            assert item["degradations"] == ["point_in_time_source_not_replayable"]


def test_industry_report_is_explicitly_unavailable_without_company_substitution(
    monkeypatch,
):
    calls: list[str] = []
    monkeypatch.setattr(
        tools,
        "route_to_vendor",
        lambda method, *_args, **_kwargs: calls.append(method) or "ok",
    )
    monkeypatch.setattr(tools, "_current_shanghai_date", lambda: "2026-07-31")

    payload = json.loads(
        tools.run_a_share_supplement_prefetch(
            "000338.SZ",
            "2026-07-31",
            horizon="long",
        )
    )
    industry = next(
        item
        for item in payload["results"]
        if item["capability"] == "industry_research_reports"
    )

    assert industry["status"] == "unavailable"
    assert industry["degradations"] == ["industry_report_qtype1_not_verified"]
    assert industry["substitution_allowed"] is False
    assert "get_a_share_research_reports" not in calls


def test_global_ticker_is_not_applicable_and_calls_no_a_share_provider(monkeypatch):
    monkeypatch.setattr(
        tools,
        "route_to_vendor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not call")),
    )

    payload = json.loads(
        tools.run_a_share_supplement_prefetch(
            "AAPL",
            "2026-07-31",
            horizon="medium",
        )
    )

    assert payload["status"] == "not_applicable"
    assert payload["results"] == []


def test_graph_runs_supplement_prefetch_once_before_first_analyst():
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

    assert ("__start__", "A-share Supplement Prefetch") in edges
    assert ("A-share Supplement Prefetch", "Adjusted Price Prefetch") in edges
    # The prefetch chain runs to completion before the first analyst node.
    assert ("Adjusted Price Prefetch", "News Window Prefetch") in edges
    assert ("Fundamentals Prefetch", "Market Analyst") in edges
