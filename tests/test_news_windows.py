"""Deterministic horizon-aware news prefetch contracts."""

from __future__ import annotations

import json

import pytest

from tradingagents.agents.utils import news_data_tools
from tradingagents.dataflows.coverage import CoveredText, SourceCoverageV1
from tradingagents.dataflows.news_curator import _format_curated_news


@pytest.mark.unit
def test_long_horizon_news_windows_are_policy_owned(monkeypatch):
    calls: list[tuple[str, tuple, dict]] = []

    def route(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return f"{method} data"

    monkeypatch.setattr(news_data_tools, "route_to_vendor", route)
    payload = json.loads(
        news_data_tools.run_news_windows("000338.SZ", "2026-07-31", horizon="long")
    )

    assert payload["horizon"] == "long"
    assert payload["policy_version"] == "horizon-policy-v2"
    company = payload["windows"]["company_events"]
    assert list(company) == ["event_7d", "event_30d", "event_90d", "event_365d"]
    assert company["event_7d"]["start_date"] == "2026-07-24"
    assert company["event_365d"]["start_date"] == "2025-07-31"
    assert payload["windows"]["official"]["start_date"] == "2021-07-31"
    assert payload["windows"]["research_reports"]["start_date"] == "2021-07-31"
    assert calls == [
        (
            "get_news",
            ("000338.SZ", "2026-07-24", "2026-07-31"),
            {"max_pages": 2},
        ),
        (
            "get_news",
            ("000338.SZ", "2026-07-01", "2026-07-31"),
            {"max_pages": 2},
        ),
        (
            "get_news",
            ("000338.SZ", "2026-05-02", "2026-07-31"),
            {"max_pages": 2},
        ),
        (
            "get_news",
            ("000338.SZ", "2025-07-31", "2026-07-31"),
            {"max_pages": 2},
        ),
        (
            "get_a_share_cninfo_announcements",
            ("000338.SZ", "2021-07-31", "2026-07-31"),
            {"max_pages": 20},
        ),
        (
            "get_a_share_research_reports",
            ("000338.SZ",),
            {
                "as_of": "2026-07-31",
                "start_date": "2021-07-31",
                "max_pages": 20,
            },
        ),
    ]


@pytest.mark.unit
def test_bare_news_window_tool_defaults_to_medium_for_legacy_callers(monkeypatch):
    monkeypatch.setattr(news_data_tools, "route_to_vendor", lambda *_a, **_k: "ok")

    payload = json.loads(
        news_data_tools.get_news_windows.invoke({"ticker": "000338.SZ", "curr_date": "2026-07-31"})
    )

    assert payload["horizon"] == "medium"
    company = payload["windows"]["company_events"]
    assert company["new_events"]["lookback_days"] == 7
    assert company["active_themes"]["lookback_days"] == 30
    assert company["theme_evolution"]["lookback_days"] == 180
    assert payload["windows"]["official"]["lookback_years"] == 4


@pytest.mark.unit
def test_global_news_window_never_calls_a_share_disclosure_routes(monkeypatch):
    calls: list[str] = []

    def route(method, *_args, **_kwargs):
        calls.append(method)
        return "ok"

    monkeypatch.setattr(news_data_tools, "route_to_vendor", route)
    payload = json.loads(news_data_tools.run_news_windows("AAPL", "2026-07-31", horizon="short"))

    assert calls == ["get_news", "get_news", "get_news"]
    assert payload["windows"]["official"]["status"] == "unavailable"
    assert payload["windows"]["research_reports"]["status"] == "unavailable"


@pytest.mark.unit
def test_curator_preserves_provider_owned_pagination_coverage():
    coverage = SourceCoverageV1(
        capability="company_news",
        source_id="eastmoney.company_news",
        requested_start="2026-07-01",
        requested_end="2026-07-31",
        actual_start="2026-07-01",
        actual_end="2026-07-31",
        item_count=3,
        page_count=2,
        pagination_exhausted=True,
        completeness="complete",
        sources=("eastmoney.company_news",),
        as_of="2026-07-31",
    )
    raw = {
        "source": "eastmoney",
        "items": [
            {
                "title": "Company update",
                "published": "2026-07-31",
                "content": "Public company news.",
                "source": "eastmoney",
            }
        ],
        "coverage": coverage.model_dump(mode="json"),
    }

    curated = _format_curated_news(
        "get_news",
        [("eastmoney", raw)],
        [],
        "2026-07-01",
        "2026-07-31",
    )
    public = news_data_tools._public_window_result(curated)

    assert isinstance(curated, CoveredText)
    assert public["coverage"]["page_count"] == 2
    assert public["coverage"]["pagination_exhausted"] is True
    assert public["coverage"]["completeness"] == "complete"


@pytest.mark.unit
def test_success_without_provider_coverage_is_explicitly_unknown():
    public = news_data_tools._public_window_result("plain provider result")

    assert public["status"] == "ok"
    assert public["coverage"] == {
        "completeness": "unknown",
        "degradations": ["source_coverage_not_reported"],
    }
