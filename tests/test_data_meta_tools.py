"""Regression coverage for analyst-facing allowlisted data meta tools."""

from __future__ import annotations

import json

import pytest

from tradingagents.agents.utils import data_meta_tools as meta
from tradingagents.dataflows.coverage import CoveredText, SourceCoverageV1
from tradingagents.dataflows.errors import VendorRateLimitError


@pytest.mark.unit
def test_market_bundle_prioritizes_explicit_a_share_capability_over_defaults():
    selected = meta.select_capabilities(
        "market", "600519", "请检查资金流和 RSI 是否支持当前趋势"
    )

    selected_ids = [capability.id for capability in selected]
    assert "capital_flow" in selected_ids
    assert "rsi" in selected_ids
    assert len(selected_ids) <= meta.MAX_CAPABILITIES_PER_BUNDLE


@pytest.mark.unit
def test_market_bundle_does_not_offer_a_share_only_sources_for_us_symbol():
    selected = meta.select_capabilities("market", "AAPL", "资金流、龙虎榜和趋势")

    assert not any(capability.a_share_only for capability in selected)


@pytest.mark.unit
def test_a_share_bundle_exposes_northbound_and_insider_only_when_requested():
    selected = meta.select_capabilities("market", "600519", "北向持仓和董监高增持是否支持？")

    selected_ids = [capability.id for capability in selected]
    assert "northbound_flow" in selected_ids
    assert "northbound_holdings" in selected_ids
    assert "insider_trades" in selected_ids

    news_selected = meta.select_capabilities("news", "600519", "中国宏观经济周期和景气如何？")
    assert "china_macro" in [capability.id for capability in news_selected]


@pytest.mark.unit
def test_bundle_returns_stable_capability_order_after_parallel_execution(monkeypatch):
    def fake_execute(capability, _symbol, _curr_date, _request):
        return {
            "capability": capability.id,
            "route_method": capability.route_method,
            "status": "ok",
            "data": capability.id,
            "truncated": "false",
        }

    monkeypatch.setattr(meta, "_execute", fake_execute)
    expected = [
        capability.id
        for capability in meta.select_capabilities("fundamentals", "600519", "营收、现金流和负债")
    ]

    payload = json.loads(
        meta.run_data_bundle("fundamentals", "600519", "2026-07-23", "营收、现金流和负债")
    )

    assert payload["status"] == "ok"
    assert [item["capability"] for item in payload["results"]] == expected
    assert payload["provenance"]["parallelism_limit"] == meta.MAX_PARALLEL_CAPABILITIES


@pytest.mark.unit
def test_bundle_redacts_provider_failure_details():
    capability = meta.Capability(
        "test_capability",
        "get_stock_data",
        "market",
        lambda *_args: (_ for _ in ()).throw(VendorRateLimitError("provider-secret")),
    )

    result = meta._execute(capability, "600519", "2026-07-23", "price")

    assert result["status"] == "error"
    assert result["error_type"] == "source_unavailable"
    assert "provider-secret" not in result["message"]


@pytest.mark.unit
def test_bundle_redacts_unavailable_sentinel_details():
    capability = meta.Capability(
        "test_capability",
        "get_stock_data",
        "market",
        lambda *_args: "NO_DATA_AVAILABLE: vendor-specific response that must not leak",
    )

    result = meta._execute(capability, "600519", "2026-07-23", "price")

    assert result["status"] == "unavailable"
    assert "data" not in result
    assert "vendor-specific" not in result["message"]


@pytest.mark.unit
def test_margin_financing_bundle_uses_explicit_requested_window(monkeypatch):
    captured = {}

    def fake_route(method, *args, **kwargs):
        captured.update({"method": method, "args": args, "kwargs": kwargs})
        return "margin data"

    monkeypatch.setattr(meta, "route_to_vendor", fake_route)

    result = meta._margin_financing("600519.SH", "2026-07-31", "融资余额趋势")

    assert result == "margin data"
    assert captured == {
        "method": "get_a_share_margin_financing",
        "args": ("600519.SH", "2026-07-01", "2026-07-31"),
        "kwargs": {},
    }


@pytest.mark.unit
def test_news_bundle_uses_run_horizon_for_company_and_official_windows(monkeypatch):
    calls: list[tuple[str, tuple, dict]] = []

    def fake_route(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return "ok"

    monkeypatch.setattr(meta, "route_to_vendor", fake_route)
    meta._company_news_for_horizon("000338.SZ", "2026-07-31", "long")
    meta._cninfo_announcements_for_horizon("000338.SZ", "2026-07-31", "long")
    meta._research_reports_for_horizon("000338.SZ", "2026-07-31", "long")

    assert calls == [
        ("get_news", ("000338.SZ", "2025-07-31", "2026-07-31"), {}),
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
def test_bundle_exposes_structured_coverage_without_parsing_report_text():
    coverage = SourceCoverageV1(
        capability="capital_flow",
        source_id="eastmoney",
        requested_start="2026-07-01",
        requested_end="2026-07-31",
        actual_start="2026-07-10",
        actual_end="2026-07-31",
        item_count=16,
        page_count=None,
        pagination_exhausted=None,
        completeness="partial",
        sources=["eastmoney"],
        degradations=["requested_start_not_observed"],
        as_of="2026-07-31",
    )
    capability = meta.Capability(
        "capital_flow",
        "get_a_share_capital_flow",
        "market",
        lambda *_args: CoveredText("opaque rendered report", coverage),
    )

    result = meta._execute(capability, "600519", "2026-07-31", "资金流")

    assert result["data"] == "opaque rendered report"
    assert result["coverage"]["actual_start"] == "2026-07-10"
    assert result["coverage"]["completeness"] == "partial"


@pytest.mark.unit
def test_langchain_meta_tool_is_invocable_without_dynamic_callable_resolution(monkeypatch):
    monkeypatch.setattr(
        meta,
        "run_data_bundle",
        lambda focus, symbol, curr_date, request: json.dumps(
            {"focus": focus, "symbol": symbol, "as_of": curr_date, "request": request}
        ),
    )

    payload = json.loads(
        meta.get_news_research_bundle.invoke(
            {"symbol": "600519", "curr_date": "2026-07-23", "request": "宏观和公司新闻"}
        )
    )

    assert payload["focus"] == "news"
    assert payload["symbol"] == "600519"
