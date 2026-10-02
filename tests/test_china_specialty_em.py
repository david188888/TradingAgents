"""Unit tests for the EastMoney direct-HTTP A-share specialty adapters."""

from __future__ import annotations

import pytest

from tradingagents.dataflows import china_specialty_em, eastmoney
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.coverage import CoveredText
from tradingagents.dataflows.errors import VendorHTTPError


def _envelope(data, *, pages=1, count=None, code=0, message=""):
    """The real EastMoney datacenter envelope, which the strict pager requires.

    A bare ``{"result": {"data": [...]}}`` is exactly the loose shape the old
    helper accepted; it cannot prove pagination or distinguish a throttle from
    "no records", so the fakes must carry ``code``/``pages``/``count`` too.
    """
    return {
        "code": code,
        "message": message,
        "result": {
            "pages": pages,
            "count": len(data) if count is None else count,
            "data": data,
        },
    }


def _install_em_get(monkeypatch, handler):
    """Patch the transport the strict pager actually resolves.

    ``em_datacenter_strict`` lives in ``eastmoney`` and looks up ``em_get`` in
    that module's globals, so patching ``china_specialty_em.em_get`` would not
    intercept a datacenter request.
    """
    monkeypatch.setattr(eastmoney, "em_get", handler)


def test_dragon_tiger_em_parses_records_and_seats(monkeypatch):
    records = [
        {"TRADE_DATE": "2026-07-20", "SECURITY_CODE": "000001", "EXPLANATION": "日涨幅偏离值达7%", "BILLBOARD_NET_AMT": 50000000, "TURNOVERRATE": "3.2"},
    ]
    buy_seats = [{"TRADE_DATE": "2026-07-20", "SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "机构专用", "BUY": 30000000, "SELL": 0, "NET": 30000000}]
    sell_seats = [{"TRADE_DATE": "2026-07-20", "SECURITY_CODE": "000001", "OPERATEDEPT_NAME": "营业部A", "BUY": 0, "SELL": 20000000, "NET": -20000000}]

    def handler(_url, *, params, **_kwargs):
        report_name = params["reportName"]
        if report_name == "RPT_DAILYBILLBOARD_DETAILSNEW":
            return _envelope(records)
        if report_name == "RPT_BILLBOARD_DAILYDETAILSBUY":
            return _envelope(buy_seats)
        if report_name == "RPT_BILLBOARD_DAILYDETAILSSELL":
            return _envelope(sell_seats)
        raise AssertionError(report_name)

    _install_em_get(monkeypatch, handler)

    report = china_specialty_em.get_a_share_dragon_tiger_em("000001", "2026-07-20")

    assert isinstance(report, str)
    assert isinstance(report, CoveredText)
    assert "Source: eastmoney" in report
    assert "2026-07-20" in report
    assert "机构专用" in report
    assert "TOP5 buy/sell seats" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 1
    assert report.coverage.requested_scope.startswith("ticker=000001.SZ window=")


def test_dragon_tiger_em_completed_query_with_zero_rows_does_not_raise(monkeypatch):
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope([], count=0))

    report = china_specialty_em.get_a_share_dragon_tiger_em("000001", "2026-07-20")

    assert isinstance(report, str)
    assert "# Coverage: complete (0 matching records)" in report
    assert "# Note:" in report
    assert "not a fetch failure" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 0
    # No appearance means no latest date, so no seat section to anchor.
    assert "TOP5" not in report


def test_dragon_tiger_em_page_one_9201_is_a_legitimate_empty_result(monkeypatch):
    _install_em_get(
        monkeypatch,
        lambda *_args, **_kwargs: {"code": 9201, "message": "数据为空"},
    )

    report = china_specialty_em.get_a_share_dragon_tiger_em("000001", "2026-07-20")

    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 0


def test_dragon_tiger_em_nonzero_provider_code_raises(monkeypatch):
    _install_em_get(
        monkeypatch,
        lambda *_args, **_kwargs: _envelope([], code=9501, message="sortTypes 个数不一致"),
    )

    with pytest.raises(ChinaDataUnavailableError, match="9501"):
        china_specialty_em.get_a_share_dragon_tiger_em("000001", "2026-07-20")


def test_dragon_tiger_em_transport_error_stays_typed(monkeypatch):
    def handler(*_args, **_kwargs):
        raise VendorHTTPError("eastmoney", 503)

    _install_em_get(monkeypatch, handler)

    with pytest.raises(ChinaDataUnavailableError, match="请求失败"):
        china_specialty_em.get_a_share_dragon_tiger_em("000001", "2026-07-20")


def test_dragon_tiger_em_rejects_rows_for_another_instrument(monkeypatch):
    # A filter the interface ignored must raise, never render another
    # instrument's board appearances as this ticker's.
    _install_em_get(
        monkeypatch,
        lambda *_args, **_kwargs: _envelope(
            [{"TRADE_DATE": "2026-07-20", "SECURITY_CODE": "600519", "BILLBOARD_NET_AMT": 1}]
        ),
    )

    with pytest.raises(ChinaDataUnavailableError, match="结果不可信"):
        china_specialty_em.get_a_share_dragon_tiger_em("000001", "2026-07-20")


def test_lockup_releases_em_parses_history_and_upcoming(monkeypatch):
    history = [{"FREE_DATE": "2026-01-15", "SECURITY_CODE": "000001", "FREE_SHARES_TYPE": "定向增发", "FREE_SHARES": 1000, "ABLE_FREE_SHARES": 800, "FREE_RATIO": 0.1}]
    upcoming = [{"FREE_DATE": "2026-08-01", "SECURITY_CODE": "000001", "FREE_SHARES_TYPE": "股权激励", "FREE_SHARES": 500, "ABLE_FREE_SHARES": 500, "FREE_RATIO": 0.05}]

    def handler(_url, *, params, **_kwargs):
        assert params["reportName"] == "RPT_LIFT_STAGE"
        return _envelope(upcoming if "FREE_DATE>=" in params["filter"] else history)

    _install_em_get(monkeypatch, handler)

    report = china_specialty_em.get_a_share_lockup_releases_em("000001", "2026-07-01", "2026-12-31")

    assert isinstance(report, str)
    assert "history" in report
    assert "upcoming" in report
    assert "定向增发" in report
    assert "股权激励" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 2
    assert report.coverage.requested_scope == (
        "ticker=000001.SZ history=all upcoming=2026-07-01..2026-12-31"
    )


def test_bulk_trades_em_parses_premium(monkeypatch):
    data = [
        {
            "SECURITY_CODE": "000001",
            "TRADE_DATE": "2026-07-20",
            "DEAL_PRICE": 10.5,
            "CLOSE_PRICE": 10.0,
            "DEAL_VOLUME": 100,
            "DEAL_AMT": 1050,
            "BUYER_NAME": "买方",
            "SELLER_NAME": "卖方",
        }
    ]
    captured: dict = {}

    def handler(_url, *, params, **_kwargs):
        captured["params"] = params
        return _envelope(data)

    _install_em_get(monkeypatch, handler)

    report = china_specialty_em.get_a_share_bulk_trades_em("000001", "2026-07-01", "2026-07-31")

    assert isinstance(report, str)
    assert "Premium %" in report
    assert "买方" in report
    assert 'SECURITY_CODE="000001"' in captured["params"]["filter"]
    assert "TRADE_DATE>='2026-07-01'" in captured["params"]["filter"]
    assert "TRADE_DATE<='2026-07-31'" in captured["params"]["filter"]
    assert captured["params"]["sortColumns"] == "TRADE_DATE"
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 1
    assert report.coverage.requested_scope == "ticker=000001.SZ window=2026-07-01..2026-07-31"


def test_bulk_trades_em_completed_empty_result_is_complete(monkeypatch):
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope([], count=0))

    report = china_specialty_em.get_a_share_bulk_trades_em("000001", "2026-07-01", "2026-07-31")

    assert isinstance(report, CoveredText)
    assert "# Coverage: complete (0 matching records)" in report
    assert "# Note:" in report
    assert "not a fetch failure" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 0


def test_shareholder_counts_em_parses(monkeypatch):
    data = [{"END_DATE": "2026-06-30", "SECURITY_CODE": "000001", "HOLDER_NUM": 10000, "HOLDER_NUM_CHANGE": -500, "HOLDER_NUM_RATIO": -4.76, "AVG_HOLD_NUM": 1000}]
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope(data))

    report = china_specialty_em.get_a_share_shareholder_counts_em("000001")

    assert isinstance(report, str)
    assert "Holder Num" in report
    assert "10000" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.requested_scope == "ticker=000001.SZ series=quarterly"


def test_shareholder_counts_em_row_cap_truncation_is_partial(monkeypatch):
    rows = [
        {"END_DATE": "2026-06-30", "SECURITY_CODE": "000001", "HOLDER_NUM": index + 1}
        for index in range(200)
    ]
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope(rows, pages=2, count=250))

    report = china_specialty_em.get_a_share_shareholder_counts_em("000001")

    assert "# Coverage: partial (200 matching records)" in report
    assert report.coverage.completeness == "partial"
    assert report.coverage.pagination_exhausted is False
    assert report.coverage.item_count == 200
    assert "row_cap_truncated" in report.coverage.degradations


def test_shareholder_counts_em_partial_pagination_raises(monkeypatch):
    rows = [
        {"END_DATE": "2026-06-30", "SECURITY_CODE": "000001", "HOLDER_NUM": index + 1}
        for index in range(100)
    ]
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope(rows, pages=2, count=250))

    with pytest.raises(ChinaDataUnavailableError, match="结果不完整"):
        china_specialty_em.get_a_share_shareholder_counts_em("000001")


def test_shareholder_counts_em_changed_schema_raises(monkeypatch):
    # SECURITY_CODE disappearing is a schema change, not an answer.
    _install_em_get(
        monkeypatch,
        lambda *_args, **_kwargs: _envelope([{"END_DATE": "2026-06-30", "HOLDER_NUM": 1}]),
    )

    with pytest.raises(ChinaDataUnavailableError, match="无法确认筛选条件"):
        china_specialty_em.get_a_share_shareholder_counts_em("000001")


def test_limit_up_ladder_em_parses_pool(monkeypatch):
    pool = [
        {
            "c": "000001",
            "n": "平安银行",
            "p": 15000,
            "zdp": 10.0,
            "lbc": 2,
            "fund": 500000000,
            "zbc": 0,
            "hybk": "银行",
            "zttj": {"days": 2, "ct": 2},
        }
    ]
    monkeypatch.setattr(china_specialty_em, "_em_zt_pool", lambda date: pool)

    report = china_specialty_em.get_a_share_limit_up_ladder_em("2026-07-20")

    assert "平安银行" in report
    assert "Source: eastmoney" in report


def test_limit_up_ladder_em_raises_on_empty(monkeypatch):
    monkeypatch.setattr(china_specialty_em, "_em_zt_pool", lambda date: [])
    with pytest.raises(ChinaDataUnavailableError, match="no limit-up pool"):
        china_specialty_em.get_a_share_limit_up_ladder_em("2026-07-20")


def test_daily_dragon_tiger_em_parses(monkeypatch):
    data = [
        {
            "SECURITY_CODE": "000001",
            "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2026-07-20",
            "EXPLANATION": "日涨幅偏离值",
            "CLOSE_PRICE": 15.0,
            "CHANGE_RATE": 10.0,
            "BILLBOARD_NET_AMT": 50000000,
            "BILLBOARD_BUY_AMT": 80000000,
            "BILLBOARD_SELL_AMT": 30000000,
        }
    ]
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope(data))

    report = china_specialty_em.get_a_share_daily_dragon_tiger("2026-07-20")

    assert isinstance(report, str)
    assert "平安银行" in report
    assert "Net Buy (wan)" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 1
    assert report.coverage.requested_scope == "market=all window=2026-07-20"


def test_daily_dragon_tiger_em_rejects_out_of_window_rows(monkeypatch):
    # The trade-date filter is only a request: a page for another day must raise
    # instead of being rendered as this date's board.
    data = [
        {
            "SECURITY_CODE": "000001",
            "SECURITY_NAME_ABBR": "平安银行",
            "TRADE_DATE": "2026-07-21",
            "BILLBOARD_NET_AMT": 50000000,
        }
    ]
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope(data))

    with pytest.raises(ChinaDataUnavailableError, match="结果不可信"):
        china_specialty_em.get_a_share_daily_dragon_tiger("2026-07-20")


def test_daily_dragon_tiger_em_completed_empty_result_is_complete(monkeypatch):
    _install_em_get(monkeypatch, lambda *_args, **_kwargs: _envelope([], count=0))

    report = china_specialty_em.get_a_share_daily_dragon_tiger("2026-07-20")

    assert isinstance(report, CoveredText)
    assert "# Coverage: complete (0 matching records)" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 0


def test_daily_dragon_tiger_em_nonzero_provider_code_raises(monkeypatch):
    _install_em_get(
        monkeypatch,
        lambda *_args, **_kwargs: _envelope([], code=114514, message="拒绝访问"),
    )

    with pytest.raises(ChinaDataUnavailableError, match="114514"):
        china_specialty_em.get_a_share_daily_dragon_tiger("2026-07-20")


def test_specialty_em_rejects_non_a_share():
    with pytest.raises(ChinaDataUnavailableError, match="not recognized as an A-share"):
        china_specialty_em.get_a_share_dragon_tiger_em("AAPL", "2026-07-20")


def test_dragon_tiger_official_parses_szse(monkeypatch):
    class _FakeResp:
        text = ""

        def json(self):
            return [{"data": [{"zqdm": "000001", "zqjc": "平安银行", "cjje": "100000000", "plyy": "日涨幅偏离值"}]}]

    monkeypatch.setattr(china_specialty_em.requests, "get", lambda *a, **kw: _FakeResp())

    report = china_specialty_em.get_a_share_dragon_tiger_official("2026-07-20")

    assert "SZSE" in report
    assert "平安银行" in report


def test_dragon_tiger_official_raises_when_all_empty(monkeypatch):
    class _FakeResp:
        text = ""

        def json(self):
            return []

    monkeypatch.setattr(china_specialty_em.requests, "get", lambda *a, **kw: _FakeResp())

    with pytest.raises(ChinaDataUnavailableError, match="no data"):
        china_specialty_em.get_a_share_dragon_tiger_official("2026-07-20")


def test_break_board_pool_parses(monkeypatch):
    pool = [{"c": "000001", "n": "平安银行", "p": 15000, "ztp": 16500, "zdp": -5.0, "hs": 3.2, "zbc": 2, "zf": 8.5, "zs": -2.1, "hybk": "银行"}]
    monkeypatch.setattr(china_specialty_em, "_em_zt_api", lambda endpoint, sort, date: pool)

    report = china_specialty_em.get_a_share_break_board_pool("2026-07-22")

    assert "平安银行" in report
    assert "break-board" in report


def test_limit_down_pool_parses(monkeypatch):
    pool = [{"c": "000002", "n": "万科A", "p": 9000, "zdp": -10.0, "hs": 2.1, "fund": 100000000, "days": 1, "oc": 0, "hybk": "地产"}]
    monkeypatch.setattr(china_specialty_em, "_em_zt_api", lambda endpoint, sort, date: pool)

    report = china_specialty_em.get_a_share_limit_down_pool("2026-07-22")

    assert "万科A" in report
    assert "limit-down" in report


def test_prev_limit_up_pool_parses(monkeypatch):
    pool = [{"c": "000003", "n": "示例股", "p": 10000, "zdp": 5.0, "hs": 4.0, "zf": 6.0, "zs": 1.5, "ylbc": 2, "hybk": "科技"}]
    monkeypatch.setattr(china_specialty_em, "_em_zt_api", lambda endpoint, sort, date: pool)

    report = china_specialty_em.get_a_share_prev_limit_up_pool("2026-07-22")

    assert "示例股" in report
    assert "previous-day limit-up" in report


def test_break_board_pool_raises_on_empty(monkeypatch):
    monkeypatch.setattr(china_specialty_em, "_em_zt_api", lambda endpoint, sort, date: [])
    with pytest.raises(ChinaDataUnavailableError, match="no break-board pool"):
        china_specialty_em.get_a_share_break_board_pool("2026-07-22")


def test_research_reports_parses(monkeypatch):
    payload = {
        "data": [
            {
                "publishDate": "2026-07-20",
                "orgSName": "中信",
                "title": "买入评级",
                "emRatingName": "买入",
                "predictThisYearEps": 2.5,
                "predictNextYearEps": 3.0,
                "indvInduName": "银行",
            }
        ],
        "TotalPage": 1,
    }
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *a, **kw: payload)

    report = china_specialty_em.get_a_share_research_reports("000001")

    assert "中信" in report
    assert "买入" in report
    assert "Source: eastmoney" in report
    assert report.coverage.page_count == 1
    assert report.coverage.pagination_exhausted is True
    assert report.coverage.completeness == "unknown"


def test_research_reports_raises_on_empty(monkeypatch):
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *a, **kw: {"data": [], "TotalPage": 1})
    with pytest.raises(ChinaDataUnavailableError, match="no research reports"):
        china_specialty_em.get_a_share_research_reports("000001")


def test_research_reports_filters_window_and_proves_complete_pagination(monkeypatch):
    payloads = [
        {
            "data": [
                {"publishDate": "2026-08-04", "title": "end", "orgSName": "A"},
                {"publishDate": "2026-08-05", "title": "future", "orgSName": "A"},
            ],
            "TotalPage": 2,
        },
        {
            "data": [
                {"publishDate": "2026-08-01", "title": "start", "orgSName": "B"},
                {"publishDate": "2026-07-31", "title": "old", "orgSName": "B"},
            ],
            "TotalPage": 2,
        },
    ]
    pages = []

    def em_get(*_args, **kwargs):
        pages.append(kwargs["params"]["pageNo"])
        return payloads.pop(0)

    monkeypatch.setattr(china_specialty_em, "em_get", em_get)

    report = china_specialty_em.get_a_share_research_reports(
        "000001",
        max_pages=3,
        as_of="2026-08-04",
        start_date="2026-08-01",
    )

    assert pages == ["1", "2"]
    assert "future" not in report
    assert "old" not in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.actual_start == "2026-08-01"
    assert report.coverage.actual_end == "2026-08-04"


def test_research_reports_completed_mid_window_query_is_complete(monkeypatch):
    # The list was read to the end, so the query covered the requested interval
    # even though no report exists on either boundary date: a sparse event
    # series must not be reported as a partial fetch.
    payload = {
        "data": [{"publishDate": "2026-08-03", "title": "mid", "orgSName": "A"}],
        "TotalPage": 1,
    }
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *_a, **_k: payload)

    report = china_specialty_em.get_a_share_research_reports(
        "000001", as_of="2026-08-04", start_date="2026-08-01"
    )

    assert report.coverage.completeness == "complete"
    assert report.coverage.degradations == ()
    assert report.coverage.pagination_exhausted is True
    assert report.coverage.actual_start == "2026-08-01"
    assert report.coverage.actual_end == "2026-08-04"


def test_research_reports_marks_page_budget_truncation(monkeypatch):
    calls = 0

    def em_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "data": [
                {
                    "publishDate": f"2026-08-0{5 - calls}",
                    "title": f"page {calls}",
                    "orgSName": "A",
                }
            ],
            "TotalPage": 5,
        }

    monkeypatch.setattr(china_specialty_em, "em_get", em_get)

    report = china_specialty_em.get_a_share_research_reports(
        "000001", max_pages=2, as_of="2026-08-04", start_date="2026-08-01"
    )

    assert calls == 2
    assert report.coverage.completeness == "partial"
    assert report.coverage.pagination_exhausted is False
    assert report.coverage.degradations == ("pagination_budget_exhausted",)


def test_research_reports_invalid_date_prevents_false_complete(monkeypatch):
    payload = {
        "data": [
            {"publishDate": "2026-08-04", "title": "end", "orgSName": "A"},
            {"publishDate": "2026-08-01", "title": "start", "orgSName": "B"},
            {"publishDate": "", "title": "unknown date", "orgSName": "C"},
        ],
        "TotalPage": 1,
    }
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *_a, **_k: payload)

    report = china_specialty_em.get_a_share_research_reports(
        "000001", as_of="2026-08-04", start_date="2026-08-01"
    )

    assert "unknown date" not in report
    assert report.coverage.completeness == "partial"
    assert report.coverage.degradations == ("invalid_or_missing_published_at",)


def test_eps_forecast_parses(monkeypatch):
    html = '<html><body><table><tr><th>年度</th><th>每股收益均值</th></tr><tr><td>2026</td><td>2.5</td></tr></table></body></html>'

    class _FakeResp:
        text = html
        encoding = "gbk"

    monkeypatch.setattr(china_specialty_em.requests, "get", lambda *a, **kw: _FakeResp())

    report = china_specialty_em.get_a_share_eps_forecast("000001")

    assert "2026" in report
    assert "Source: ths" in report


def test_eps_forecast_rejects_non_a_share():
    with pytest.raises(ChinaDataUnavailableError, match="无法把 'AAPL' 解析"):
        china_specialty_em.get_a_share_eps_forecast("AAPL")


def test_industry_ranking_parses(monkeypatch):
    payload = {
        "data": {
            "diff": [
                {"f14": "银行", "f3": 2.5, "f12": "BK0448", "f104": 30, "f105": 10, "f140": "平安银行", "f136": 5.0},
                {"f14": "地产", "f3": -1.0, "f12": "BK0451", "f104": 5, "f105": 50, "f140": "万科A", "f136": -2.0},
            ]
        }
    }
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *a, **kw: payload)

    report = china_specialty_em.get_a_share_industry_ranking()

    assert "银行" in report
    assert "Source: eastmoney" in report


def test_industry_ranking_raises_on_empty(monkeypatch):
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *a, **kw: {"data": {"diff": []}})
    with pytest.raises(ChinaDataUnavailableError, match="no industry-board"):
        china_specialty_em.get_a_share_industry_ranking()


def test_concept_blocks_parses(monkeypatch):
    payload = {
        "data": {
            "diff": {
                "1": {"f14": "白酒", "f12": "BK0477", "f3": 3.0, "f128": "贵州茅台"},
                "2": {"f14": "食品饮料", "f12": "BK0438", "f3": 2.0, "f128": "五粮液"},
            }
        }
    }
    monkeypatch.setattr(china_specialty_em, "em_get", lambda *a, **kw: payload)

    report = china_specialty_em.get_a_share_concept_blocks("600519")

    assert "白酒" in report
    assert "贵州茅台" in report


def test_concept_blocks_rejects_non_a_share():
    with pytest.raises(ChinaDataUnavailableError, match="not recognized as an A-share"):
        china_specialty_em.get_a_share_concept_blocks("AAPL")
