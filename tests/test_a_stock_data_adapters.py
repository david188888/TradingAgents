"""Offline contracts for the a-stock-data-derived A-share adapters."""

from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.agents.utils import data_meta_tools
from tradingagents.agents.utils.data_meta_tools import select_capabilities
from tradingagents.dataflows import china_specialty, china_specialty_em, mootdx_provider


def test_news_bundle_prioritizes_official_and_theme_capabilities_for_a_share():
    selected = select_capabilities("news", "000338.SZ", "巨潮公告全文和行业资金")
    ids = [capability.id for capability in selected]
    assert "cninfo_announcements" in ids
    assert "board_fund_flow" in ids


def test_cninfo_announcement_adapter_filters_by_analysis_cutoff(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {
                "stockList": [{"code": "000338", "orgId": "gssz0000338"}],
                "announcements": [
                    {"announcementTime": 1785801600000, "announcementTypeName": "定期报告", "announcementTitle": "before", "announcementId": "a1", "adjunctUrl": "/a1.pdf"},
                    {"announcementTime": 1785974400000, "announcementTypeName": "公告", "announcementTitle": "after", "announcementId": "a2"},
                ],
            }

    monkeypatch.setattr(china_specialty.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(china_specialty.requests, "post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(china_specialty, "_CNINFO_ORGID_MAP", {})
    monkeypatch.setattr(china_specialty, "_capture_cninfo_raw", lambda *args, **kwargs: None)

    report = china_specialty.get_a_share_cninfo_announcements(
        "000338.SZ", start_date="2026-08-01", end_date="2026-08-05"
    )
    assert "before" in report
    assert "after" not in report
    assert "a1.pdf" in report


def test_cninfo_announcement_adapter_paginates_and_exposes_complete_coverage(
    monkeypatch,
):
    pages = [
        {
            "totalpages": 2,
            "announcements": [
                {
                    "announcementTime": 1785772800000,
                    "announcementTitle": "window end",
                    "announcementId": "end",
                }
            ],
        },
        {
            "totalpages": 2,
            "announcements": [
                {
                    "announcementTime": 1785513600000,
                    "announcementTitle": "window start",
                    "announcementId": "start",
                }
            ],
        },
    ]
    requested_pages: list[str] = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def post(*_args, **kwargs):
        requested_pages.append(kwargs["data"]["pageNum"])
        return Response(pages.pop(0))

    monkeypatch.setattr(china_specialty.requests, "post", post)
    monkeypatch.setattr(
        china_specialty, "_CNINFO_ORGID_MAP", {"000338": "gssz0000338"}
    )
    monkeypatch.setattr(
        china_specialty, "_capture_cninfo_raw", lambda *args, **kwargs: None
    )

    report = china_specialty.get_a_share_cninfo_announcements(
        "000338.SZ",
        start_date="2026-08-01",
        end_date="2026-08-04",
        max_pages=3,
    )

    assert requested_pages == ["1", "2"]
    assert "window start" in report
    assert "window end" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.page_count == 2
    assert report.coverage.pagination_exhausted is True


def test_cninfo_announcement_adapter_marks_page_budget_truncation(monkeypatch):
    class Response:
        status_code = 200

        def __init__(self, page):
            self._page = page

        def json(self):
            return {
                "totalpages": 5,
                "announcements": [
                    {
                        "announcementTime": 1785772800000,
                        "announcementTitle": f"page {self._page}",
                        "announcementId": str(self._page),
                    }
                ],
            }

    calls = 0

    def post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response(calls)

    monkeypatch.setattr(china_specialty.requests, "post", post)
    monkeypatch.setattr(
        china_specialty, "_CNINFO_ORGID_MAP", {"000338": "gssz0000338"}
    )
    monkeypatch.setattr(
        china_specialty, "_capture_cninfo_raw", lambda *args, **kwargs: None
    )

    report = china_specialty.get_a_share_cninfo_announcements(
        "000338.SZ",
        start_date="2026-08-01",
        end_date="2026-08-04",
        max_pages=2,
    )

    assert calls == 2
    assert report.coverage.completeness == "partial"
    assert report.coverage.pagination_exhausted is False
    assert report.coverage.degradations == ("pagination_budget_exhausted",)


def test_cninfo_invalid_date_is_excluded_and_prevents_false_complete(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {
                "totalpages": 1,
                "announcements": [
                    {
                        "announcementTime": 1785772800000,
                        "announcementTitle": "end",
                        "announcementId": "end",
                    },
                    {
                        "announcementTime": 1785513600000,
                        "announcementTitle": "start",
                        "announcementId": "start",
                    },
                    {
                        "announcementTime": None,
                        "announcementTitle": "unknown date",
                        "announcementId": "unknown",
                    },
                ],
            }

    monkeypatch.setattr(china_specialty.requests, "post", lambda *_a, **_k: Response())
    monkeypatch.setattr(
        china_specialty, "_CNINFO_ORGID_MAP", {"000338": "gssz0000338"}
    )
    monkeypatch.setattr(
        china_specialty, "_capture_cninfo_raw", lambda *args, **kwargs: None
    )

    report = china_specialty.get_a_share_cninfo_announcements(
        "000338.SZ", start_date="2026-08-01", end_date="2026-08-04"
    )

    assert "unknown date" not in report
    assert report.coverage.completeness == "partial"
    assert report.coverage.degradations == ("invalid_or_missing_published_at",)


def test_board_fund_flow_preserves_period_specific_units(monkeypatch):
    monkeypatch.setattr(
        china_specialty_em,
        "em_get",
        lambda *args, **kwargs: {
            "data": {
                "total": 1,
                "diff": [{"f12": "BK0001", "f14": "电力设备", "f3": 2.5, "f62": 100000000, "f184": 1.2, "f204": "龙头", "f66": 60000000, "f72": 40000000, "f78": -1000000, "f84": -2000000}],
            }
        },
    )
    monkeypatch.setattr(china_specialty_em, "_capture_vendor_raw", lambda *args, **kwargs: None)

    report = china_specialty_em.get_a_share_board_fund_flow("industry", "today", 1)
    assert "Main Net Inflow (CNY)" in report
    assert "100000000" in report
    assert "电力设备" in report


def test_mootdx_finance_snapshot_keeps_source_type_and_cutoff(monkeypatch):
    class Client:
        def finance(self, symbol):
            return pd.DataFrame([{"symbol": symbol, "eps": 1.2, "profit": 100000000}])

    monkeypatch.setattr(mootdx_provider, "tdx_client", lambda: Client())
    monkeypatch.setattr(mootdx_provider, "_capture_vendor_raw", lambda *args, **kwargs: None)
    report = mootdx_provider.get_fundamentals_mootdx("000338.SZ", "2026-08-05")
    assert "quarterly snapshot" in report
    assert "2026-08-05" in report
    assert "profit" in report




def test_dragon_tiger_capability_passes_analysis_date(monkeypatch):
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        data_meta_tools,
        "route_to_vendor",
        lambda *args, **_kwargs: calls.append(args) or "ok",
    )

    assert data_meta_tools._dragon_tiger("000338.SZ", "2026-08-07", "龙虎榜") == "ok"
    assert calls == [("get_a_share_dragon_tiger", "000338.SZ", "2026-08-07")]


def test_stock_monitor_preserves_bse_market_and_active_window(monkeypatch):
    from datetime import date, timedelta

    # Active window is anchored to "now" so this test does not expire.
    active_start = (date.today() - timedelta(days=1)).isoformat()
    active_end = (date.today() + timedelta(days=7)).isoformat()
    rows = [
        {
            "STKCODE": "920575", "STKNAME": "*ST康乐", "MARKET": "B",
            "VALIDATESTARTDATE": active_start, "VALIDATEENDDATE": active_end,
            "LINK_URL": "https://example.com/detail",
        },
        {
            "STKCODE": "600519", "STKNAME": "贵州茅台", "MARKET": "1",
            "VALIDATESTARTDATE": "2020-01-01", "VALIDATEENDDATE": "2020-01-14",
        },
    ]
    monkeypatch.setattr(china_specialty_em, "em_get_json", lambda *args, **kwargs: rows)
    monkeypatch.setattr(china_specialty_em, "_capture_vendor_raw", lambda *args, **kwargs: None)

    report = china_specialty_em.get_a_share_stock_monitor_em(only_active=True)
    # The expired 2020 row is filtered out; the BSE row keeps its real market.
    assert "920575" in report
    assert "BJ" in report
    assert "600519" not in report


def test_price_anomaly_maps_star_tier_rule_and_keeps_market(monkeypatch):
    payload = {
        "result": 0,
        "date": "20260807",
        "pages": 1,
        "data": [
            {"c": "688001", "n": "华兴源创", "m": 1, "s": 6, "e": 4,
             "a": 12.3, "x": 105.0, "d": 10, "o": 1},
            {"c": "920575", "n": "*ST康乐", "m": 0, "s": 8, "e": 8,
             "a": 5.0, "x": 20.0, "d": 10, "o": 2},
        ],
    }
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *args, **kwargs: payload)
    monkeypatch.setattr(china_specialty_em, "_capture_vendor_raw", lambda *args, **kwargs: None)

    report = china_specialty_em.get_a_share_price_anomaly_em(page_size=200, page_no=1)
    # s==6 (STAR) + e==4 maps to the stricter +150% tier (rule code 40).
    assert "+150%" in report
    assert "688001" in report
    # BSE rule code 8 keeps market BJ even though m==0.
    assert "920575" in report
    assert "BJ" in report


def test_price_anomaly_fails_fast_on_api_rejection(monkeypatch):
    from tradingagents.dataflows.china_data import ChinaDataUnavailableError

    monkeypatch.setattr(
        china_specialty_em,
        "em_get",
        lambda *args, **kwargs: {"result": 1001, "msg": "unknow team"},
    )
    monkeypatch.setattr(china_specialty_em, "_capture_vendor_raw", lambda *args, **kwargs: None)

    with pytest.raises(ChinaDataUnavailableError):
        china_specialty_em.get_a_share_price_anomaly_em()


def test_anomaly_market_uses_wide_bse_segment_rule():
    """a-stock-data #51: anomaly records must use the same wide BSE segment
    rule (4/8/92) as exchange inference, not only the legacy 43/83/87/920
    enumeration."""
    assert china_specialty_em._anomaly_market("920575", 0) == "BJ"
    assert china_specialty_em._anomaly_market("832982", 0) == "BJ"
    assert china_specialty_em._anomaly_market("430047", 0) == "BJ"
    # Reserved-but-unlisted BSE segments also route to BJ.
    assert china_specialty_em._anomaly_market("400001", 0) == "BJ"
    assert china_specialty_em._anomaly_market("810001", 0) == "BJ"
    # Rule code 8 stays a BSE tie-breaker regardless of the code.
    assert china_specialty_em._anomaly_market("920575", 0, board=8) == "BJ"
    # Non-BSE codes keep the m-based routing.
    assert china_specialty_em._anomaly_market("600519", 1) == "SH"
    assert china_specialty_em._anomaly_market("000001", 0) == "SZ"
