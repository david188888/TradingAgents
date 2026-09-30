"""Offline contract tests for the EastMoney event-driven A-share adapters.

Every test monkeypatches the throttled ``em_get`` gateway, so no network call is
made.  The focus is the part that is easy to get wrong: the pagination
strictness (partial page sets must raise), the request contract (report name,
filter columns, sort columns/types), the output field mapping, and the
"genuinely empty" vs "interface broke" split.
"""

from __future__ import annotations

import io
import sys
import types
from typing import Any

import pandas as pd
import pytest

from tradingagents.dataflows import a_share_events
from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.errors import VendorHTTPError

# ---------------------------------------------------------------------------
# Offline gateway + report parsing helpers
# ---------------------------------------------------------------------------


def _payload(
    data: list[dict[str, Any]],
    *,
    pages: int = 1,
    count: int | None = None,
    code: int = 0,
    message: str = "ok",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "result": {"pages": pages, "count": len(data) if count is None else count, "data": data},
    }


def _install(monkeypatch, responder):
    """Replace the EastMoney gateway with an offline responder; return the call log."""
    calls: list[dict[str, Any]] = []

    def fake_em_get(url, **kwargs):
        call = {"url": url, "params": dict(kwargs.get("params") or {})}
        calls.append(call)
        return responder(call)

    monkeypatch.setattr(a_share_events, "em_get", fake_em_get)
    monkeypatch.setattr(a_share_events, "_capture_vendor_raw", lambda *args, **kwargs: None)
    return calls


def _parse_report(text: str) -> pd.DataFrame:
    _, _, body = text.partition("\n\n")
    return pd.read_csv(io.StringIO(body), dtype=str).fillna("")


# ---------------------------------------------------------------------------
# Realistic EastMoney rows (exact upstream field names)
# ---------------------------------------------------------------------------

_FORECAST_ROW = {
    "SECURITY_CODE": "600519",
    "SECURITY_NAME_ABBR": "贵州茅台",
    "NOTICE_DATE": "2026-09-28 00:00:00",
    "REPORT_DATE": "2026-09-30 00:00:00",
    "PREDICT_FINANCE": "归母净利润",
    "PREDICT_FINANCE_CODE": "004",
    "PREDICT_TYPE": "预增",
    "PREDICT_AMT_LOWER": "1,000,000",
    "PREDICT_AMT_UPPER": 2000000,
    "ADD_AMP_LOWER": "10.5",
    "ADD_AMP_UPPER": "20.5",
    "PREYEAR_SAME_PERIOD": "900000",
    "PREDICT_CONTENT": "预计同比增长",
    "CHANGE_REASON_EXPLAIN": "主营业务增长",
}

_SURVEY_ROW = {
    "SECURITY_CODE": "688062",
    "SECURITY_NAME_ABBR": "迈威生物",
    "NOTICE_DATE": "2026-09-20 00:00:00",
    "RECEIVE_START_DATE": "2026-09-16 00:00:00",
    "RECEIVE_END_DATE": "2026-09-17 00:00:00",
    "SUM": "12",
    "RECEIVE_WAY_EXPLAIN": "电话会议",
    "RECEIVE_PLACE": "公司会议室",
    "RECEPTIONIST": "董秘",
    "IS_SOURCE": "1",
    "NUMBERNEW": "1",
    "RECEIVE_OBJECT": "某某基金",
    "ORG_TYPE": "基金公司",
    "INVESTIGATORS": "张三",
}

_BUYBACK_ROW = {
    "DIM_SCODE": "600519",
    "SECURITYSHORTNAME": "贵州茅台",
    "REPURPROGRESS": "004",
    "REPURSTARTDATE": "2026-01-05 00:00:00",
    "REPURENDDATE": "2026-12-31 00:00:00",
    "REPURPRICECAP": "1800.00",
    "REPURNUMLOWER": 100000,
    "REPURNUMCAP": "200000",
    "REPURAMOUNTLOWER": 100000000.0,
    "REPURAMOUNTLIMIT": "200000000",
    "ZSZXX": "0.05",
    "ZSZSX": "0.10",
    "REPURNUM": 50000,
    "REPURAMOUNT": 90000000.0,
    "REPURPRICELOWER1": "1750.00",
    "REPURPRICECAP1": "1799.00",
    "UPDATEDATE": "2026-09-18 00:00:00",
    "REPURCODE": "R1",
    "REPUROBJECTIVE": "员工持股计划",
}

_PLEDGE_ROW = {
    "TRADE_DATE": "2026-09-18 00:00:00",
    "SECURITY_CODE": "600519",
    "SECURITY_NAME_ABBR": "贵州茅台",
    "INDUSTRY": "白酒",
    "PLEDGE_RATIO": "0.35",
    "REPURCHASE_BALANCE": 1000.0,
    "PLEDGE_MARKET_CAP": "250000",
    "PLEDGE_DEAL_NUM": "3",
    "REPURCHASE_UNLIMITED_BALANCE": 600.0,
    "REPURCHASE_LIMITED_BALANCE": 400.0,
}

_IPO_ROW = {
    "SECURITY_CODE": "301234",
    "SECURITY_NAME": "某某科技",
    "APPLY_CODE": "301234",
    "TRADE_MARKET": "深交所",
    "MARKET": "深交所创业板",
    "MARKET_TYPE_NEW": "深交所其他",
    "APPLY_DATE": "2026-09-25 00:00:00",
    "BALLOT_NUM_DATE": "2026-09-29 00:00:00",
    "BALLOT_PAY_DATE": "2026-09-30 00:00:00",
    "LISTING_DATE": None,
    "ISSUE_PRICE": 0,
    "AFTER_ISSUE_PE": 22.5,
    "INDUSTRY_PE": "30.1",
    "ISSUE_NUM": 4000.0,
    "ONLINE_ISSUE_NUM": 1600.0,
    "ONLINE_APPLY_UPPER": 16000.0,
    "TOP_APPLY_MARKETCAP": 160000.0,
    "ONLINE_ISSUE_LWR": "0.0312",
    "CLOSE_PRICE": None,
    "LD_CLOSE_CHANGE": None,
}


# ---------------------------------------------------------------------------
# §14.1 earnings forecast
# ---------------------------------------------------------------------------


def test_earnings_forecast_maps_fields_and_request(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_FORECAST_ROW)]))
    report = a_share_events.get_a_share_earnings_forecast(
        ticker="600519", report_date="20260930", limit=10
    )
    params = calls[0]["params"]
    assert params["reportName"] == "RPT_PUBLIC_OP_NEWPREDICT"
    assert params["columns"] == "ALL"
    assert params["sortColumns"] == "NOTICE_DATE,SECURITY_CODE,REPORT_DATE,PREDICT_FINANCE_CODE"
    assert params["sortTypes"] == "-1,1,-1,1"
    assert params["filter"] == '(REPORT_DATE=\'2026-09-30\')(SECURITY_CODE="600519")'
    assert params["pageSize"] == "10"
    assert params["pageNumber"] == "1"

    row = _parse_report(report).iloc[0]
    assert row["code"] == "600519"
    assert row["name"] == "贵州茅台"
    assert row["notice_date"] == "2026-09-28"
    assert row["report_date"] == "2026-09-30"
    assert row["indicator"] == "归母净利润"
    assert row["forecast_type"] == "预增"
    assert float(row["amount_lower"]) == 1000000.0
    assert float(row["amount_upper"]) == 2000000.0
    assert float(row["change_pct_lower"]) == 10.5
    assert float(row["change_pct_upper"]) == 20.5
    assert float(row["prior_year_amount"]) == 900000.0
    assert row["content"] == "预计同比增长"
    assert row["reason"] == "主营业务增长"
    assert "Source: eastmoney" in report
    assert "Total records: 1" in report


def test_earnings_forecast_period_only_is_market_wide_and_narrowed(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_FORECAST_ROW)]))
    a_share_events.get_a_share_earnings_forecast(report_date="2026-09-30")
    assert calls[0]["params"]["filter"] == "(REPORT_DATE='2026-09-30')"


def test_earnings_forecast_rejects_shanghai_index(monkeypatch):
    def boom(call):  # pragma: no cover - must never be reached
        raise AssertionError("no request should be issued for an index form")

    _install(monkeypatch, boom)
    with pytest.raises(ChinaDataUnavailableError, match="沪市指数"):
        a_share_events.get_a_share_earnings_forecast(ticker="SH000001")


def test_earnings_forecast_narrowed_empty_degrades_instead_of_empty_table(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 9201, "message": "返回数据为空"})
    with pytest.raises(ChinaDataUnavailableError, match="returned no rows"):
        a_share_events.get_a_share_earnings_forecast(ticker="600519")


# ---------------------------------------------------------------------------
# §14.2 institution survey
# ---------------------------------------------------------------------------


def test_institution_survey_detail_maps_org_rows(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_SURVEY_ROW)]))
    report = a_share_events.get_a_share_institution_survey(
        ticker="688062", start="2026-09-01", end="2026-09-30", detail=True
    )
    params = calls[0]["params"]
    assert params["reportName"] == "RPT_ORG_SURVEYNEW"
    assert params["sortColumns"] == "NOTICE_DATE,SECURITY_CODE,RECEIVE_START_DATE,NUMBERNEW"
    assert params["sortTypes"] == "-1,1,-1,1"
    assert params["filter"] == (
        '(IS_SOURCE="1")(SECURITY_CODE="688062")'
        "(NOTICE_DATE>='2026-09-01')(NOTICE_DATE<='2026-09-30')"
    )
    row = _parse_report(report).iloc[0]
    assert row["code"] == "688062"
    assert row["notice_date"] == "2026-09-20"
    assert row["survey_date"] == "2026-09-16"
    assert row["survey_end"] == "2026-09-17"
    assert float(row["org_count"]) == 12.0
    assert row["survey_way"] == "电话会议"
    assert row["place"] == "公司会议室"
    assert row["receptionist"] == "董秘"
    assert row["org_name"] == "某某基金"
    assert row["org_type"] == "基金公司"
    assert row["investigators"] == "张三"


def test_institution_survey_summary_uses_numbernew_filter(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_SURVEY_ROW)]))
    report = a_share_events.get_a_share_institution_survey(limit=20)
    params = calls[0]["params"]
    assert params["filter"] == '(IS_SOURCE="1")(NUMBERNEW="1")'
    assert params["sortColumns"] == "NOTICE_DATE,SECURITY_CODE,RECEIVE_START_DATE"
    assert params["sortTypes"] == "-1,1,-1"
    row = _parse_report(report).iloc[0]
    assert "org_name" not in row.index
    assert float(row["org_count"]) == 12.0


def test_institution_survey_rejects_inverted_window():
    with pytest.raises(ValueError, match="start 不能晚于 end"):
        a_share_events.get_a_share_institution_survey(start="2026-09-30", end="2026-09-01")


# ---------------------------------------------------------------------------
# §14.3 share buyback
# ---------------------------------------------------------------------------


def test_share_buyback_uses_dim_scode_and_progress_code(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_BUYBACK_ROW)]))
    report = a_share_events.get_a_share_share_buyback(ticker="600519", progress="实施中")
    params = calls[0]["params"]
    assert params["reportName"] == "RPTA_WEB_GETHGLIST_NEW"
    assert params["filter"] == '(DIM_SCODE="600519")(REPURPROGRESS="004")'
    assert params["sortColumns"] == "UPD,DIM_SCODE,REPURCODE"
    assert params["sortTypes"] == "-1,1,1"
    row = _parse_report(report).iloc[0]
    assert row["code"] == "600519"
    assert row["name"] == "贵州茅台"
    assert row["progress"] == "实施中"
    assert row["progress_code"] == "004"
    assert row["plan_start"] == "2026-01-05"
    assert row["plan_end"] == "2026-12-31"
    assert float(row["price_cap"]) == 1800.0
    assert float(row["shares_lower"]) == 100000.0
    assert float(row["shares_upper"]) == 200000.0
    assert float(row["amount_lower"]) == 100000000.0
    assert float(row["pct_total_upper"]) == 0.10
    assert float(row["done_shares"]) == 50000.0
    assert row["latest_notice"] == "2026-09-18"
    assert row["objective"] == "员工持股计划"


def test_share_buyback_unknown_progress_code_maps_to_none(monkeypatch):
    row = {**_BUYBACK_ROW, "REPURPROGRESS": "007"}
    calls = _install(monkeypatch, lambda call: _payload([row, {**row, "REPURCODE": "R2"}]))
    report = a_share_events.get_a_share_share_buyback(limit=5)
    assert calls[0]["params"]["filter"] == ""
    out = _parse_report(report)
    assert set(out["progress_code"]) == {"007"}
    assert set(out["progress"]) == {""}


def test_share_buyback_rejects_unknown_progress_label():
    with pytest.raises(ValueError, match="progress 只能是"):
        a_share_events.get_a_share_share_buyback(progress="瞎写")


# ---------------------------------------------------------------------------
# §14.4 equity pledge
# ---------------------------------------------------------------------------


def test_equity_pledge_uses_latest_statistical_date(monkeypatch):
    def responder(call):
        if call["params"]["filter"] == "":
            return _payload([{"TRADE_DATE": "2026-09-18 00:00:00"}], count=2212)
        return _payload([dict(_PLEDGE_ROW)])

    calls = _install(monkeypatch, responder)
    report = a_share_events.get_a_share_equity_pledge()
    assert calls[0]["params"]["sortColumns"] == "TRADE_DATE"
    assert calls[0]["params"]["filter"] == ""
    assert calls[0]["params"]["pageSize"] == "1"
    assert calls[1]["params"]["filter"] == "(TRADE_DATE='2026-09-18')"
    assert calls[1]["params"]["sortColumns"] == "PLEDGE_RATIO,SECURITY_CODE"
    assert calls[1]["params"]["sortTypes"] == "-1,1"
    row = _parse_report(report).iloc[0]
    assert row["date"] == "2026-09-18"
    assert row["code"] == "600519"
    assert row["industry"] == "白酒"
    assert float(row["pledge_ratio_pct"]) == 0.35
    assert float(row["pledged_shares_10k"]) == 1000.0
    assert float(row["pledged_mktcap_10k"]) == 250000.0
    assert float(row["pledge_count"]) == 3.0
    assert float(row["unrestricted_pledged_10k"]) == 600.0
    assert float(row["restricted_pledged_10k"]) == 400.0


def test_equity_pledge_by_ticker_uses_trade_date_sort(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_PLEDGE_ROW)]))
    a_share_events.get_a_share_equity_pledge(ticker="600519", limit=20)
    params = calls[0]["params"]
    assert params["filter"] == '(SECURITY_CODE="600519")'
    assert params["sortColumns"] == "TRADE_DATE"
    assert params["sortTypes"] == "-1"
    assert params["pageSize"] == "20"


def test_equity_pledge_rejects_bse_ticker():
    with pytest.raises(ValueError, match="北交所"):
        a_share_events.get_a_share_equity_pledge(ticker="920982")


def test_equity_pledge_rejects_ticker_and_date_together():
    with pytest.raises(ValueError, match="只能给一个"):
        a_share_events.get_a_share_equity_pledge(ticker="600519", date="2026-09-18")


def test_equity_pledge_non_statistical_date_raises_value_error(monkeypatch):
    _install(monkeypatch, lambda call: _payload([], count=0))
    with pytest.raises(ValueError, match="不是中国结算质押统计日"):
        a_share_events.get_a_share_equity_pledge(date="2026-09-17")


def test_equity_pledge_rejects_balance_mismatch(monkeypatch):
    row = {**_PLEDGE_ROW, "REPURCHASE_BALANCE": 1000.0,
           "REPURCHASE_UNLIMITED_BALANCE": 10.0, "REPURCHASE_LIMITED_BALANCE": 20.0}
    _install(monkeypatch, lambda call: _payload([row]))
    with pytest.raises(ChinaDataUnavailableError, match="无限售"):
        a_share_events.get_a_share_equity_pledge(date="2026-09-18")


# ---------------------------------------------------------------------------
# §14.5 IPO calendar
# ---------------------------------------------------------------------------


def test_ipo_calendar_maps_fields_and_board_fallback(monkeypatch):
    bse_row = {**_IPO_ROW, "SECURITY_CODE": "920575", "SECURITY_NAME": "*ST康乐",
               "MARKET": None, "MARKET_TYPE_NEW": "北交所", "ISSUE_PRICE": 12.5}
    calls = _install(monkeypatch, lambda call: _payload([dict(_IPO_ROW), bse_row]))
    report = a_share_events.get_a_share_ipo_calendar(limit=30)
    params = calls[0]["params"]
    assert params["reportName"] == "RPTA_APP_IPOAPPLY"
    assert params["filter"] == ""
    assert params["sortColumns"] == "APPLY_DATE,SECURITY_CODE"
    assert params["sortTypes"] == "-1,-1"
    out = _parse_report(report)
    assert list(out["code"]) == ["301234", "920575"]
    first = out.iloc[0]
    assert first["apply_code"] == "301234"
    assert first["exchange"] == "深交所"
    assert first["board"] == "深交所创业板"
    assert first["apply_date"] == "2026-09-25"
    assert first["ballot_date"] == "2026-09-29"
    assert first["pay_date"] == "2026-09-30"
    assert first["listing_date"] == ""
    assert first["issue_price"] == ""  # 0 before pricing -> None
    assert float(first["issue_pe"]) == 22.5
    assert float(first["industry_pe"]) == 30.1
    assert float(first["issue_shares_10k"]) == 4000.0
    assert float(first["win_rate_pct"]) == 0.0312
    assert first["first_close"] == ""
    assert out.iloc[1]["board"] == "北交所"
    assert float(out.iloc[1]["issue_price"]) == 12.5


def test_ipo_calendar_rejects_duplicate_codes(monkeypatch):
    duplicate = {**_IPO_ROW, "SECURITY_NAME": "重复"}
    _install(monkeypatch, lambda call: _payload([dict(_IPO_ROW), duplicate]))
    with pytest.raises(ChinaDataUnavailableError, match="代码重复"):
        a_share_events.get_a_share_ipo_calendar()


# ---------------------------------------------------------------------------
# §6.8 ST / *ST list
# ---------------------------------------------------------------------------

_SHSZ = "m:0+f:4,m:1+f:4"
_BSE = "m:0+t:81+s:2048"


def _clist_responder(mapping):
    def responder(call):
        entry = mapping[call["params"]["fs"]]
        return {"rc": 0, "data": {"total": entry["total"], "diff": entry["diff"]}}

    return responder


def _clist_row(code: str, market_id: int, name: str, price=1.0, pct=0.0):
    return {"f12": code, "f13": market_id, "f14": name, "f2": price, "f3": pct}


def test_st_stock_list_combines_shsz_board_with_bse_name_filter(monkeypatch):
    _install(
        monkeypatch,
        _clist_responder(
            {
                _SHSZ: {
                    "total": 2,
                    "diff": [
                        _clist_row("600519", 1, "*ST茅台", price=1500.5, pct=4.8),
                        _clist_row("000001", 0, "ST平安", price=11.2, pct=-1.5),
                    ],
                },
                _BSE: {
                    "total": 2,
                    "diff": [
                        _clist_row("920575", 0, "*ST康乐", price=3.3, pct=5.0),
                        _clist_row("920982", 0, "贝特瑞", price=20.1, pct=1.0),
                    ],
                },
            }
        ),
    )
    report = a_share_events.get_a_share_st_stock_list()
    out = _parse_report(report)
    assert list(out["code"]) == ["600519", "000001", "920575"]
    assert list(out["market"]) == ["sh", "sz", "bj"]
    assert list(out["st_type"]) == ["*ST", "ST", "*ST"]
    assert float(out.iloc[0]["price"]) == 1500.5
    assert float(out.iloc[1]["pct_change"]) == -1.5
    assert "Coverage: 沪深京" in report
    assert "push2.eastmoney.com" in report


def test_st_stock_list_requires_non_empty_bse_half(monkeypatch):
    _install(
        monkeypatch,
        _clist_responder(
            {
                _SHSZ: {"total": 1, "diff": [_clist_row("600519", 1, "*ST茅台")]},
                _BSE: {"total": 0, "diff": []},
            }
        ),
    )
    with pytest.raises(ChinaDataUnavailableError, match="有一边为空"):
        a_share_events.get_a_share_st_stock_list()


def test_st_stock_list_requires_non_empty_shsz_half(monkeypatch):
    _install(
        monkeypatch,
        _clist_responder(
            {
                _SHSZ: {"total": 0, "diff": []},
                _BSE: {"total": 1, "diff": [_clist_row("920575", 0, "*ST康乐")]},
            }
        ),
    )
    with pytest.raises(ChinaDataUnavailableError, match="有一边为空"):
        a_share_events.get_a_share_st_stock_list()


def test_st_stock_list_rejects_unrecognized_code_or_market(monkeypatch):
    _install(
        monkeypatch,
        _clist_responder(
            {
                _SHSZ: {"total": 1, "diff": [_clist_row("60051", 1, "*ST茅台")]},
                _BSE: {"total": 1, "diff": [_clist_row("920575", 0, "*ST康乐")]},
            }
        ),
    )
    with pytest.raises(ChinaDataUnavailableError, match="认不出的代码 / 市场号"):
        a_share_events.get_a_share_st_stock_list()


def test_st_stock_list_rejects_boolean_market_id(monkeypatch):
    _install(
        monkeypatch,
        _clist_responder(
            {
                _SHSZ: {"total": 1, "diff": [_clist_row("600519", True, "*ST茅台")]},
                _BSE: {"total": 1, "diff": [_clist_row("920575", 0, "*ST康乐")]},
            }
        ),
    )
    with pytest.raises(ChinaDataUnavailableError, match="认不出的代码 / 市场号"):
        a_share_events.get_a_share_st_stock_list()


def test_st_stock_list_rejects_blank_name(monkeypatch):
    _install(
        monkeypatch,
        _clist_responder(
            {
                _SHSZ: {"total": 1, "diff": [_clist_row("600519", 1, "   ")]},
                _BSE: {"total": 1, "diff": [_clist_row("920575", 0, "*ST康乐")]},
            }
        ),
    )
    with pytest.raises(ChinaDataUnavailableError, match="没有名称"):
        a_share_events.get_a_share_st_stock_list()


class _BSResult:
    error_code = "0"

    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.fields = fields
        self._rows = rows
        self._i = 0

    def next(self) -> bool:
        if self._i < len(self._rows):
            self._i += 1
            return True
        return False

    def get_row_data(self) -> list[str]:
        return self._rows[self._i - 1]


def _install_baostock(monkeypatch, rows: list[list[str]]) -> None:
    module = types.ModuleType("baostock")
    module.login = lambda: types.SimpleNamespace(error_code="0")
    module.logout = lambda: None
    module.query_stock_basic = lambda *args, **kwargs: _BSResult(
        ["code", "code_name", "ipoDate", "outDate", "type", "status"], rows
    )
    monkeypatch.setitem(sys.modules, "baostock", module)


def _unreachable(call):  # pragma: no cover - raised, not returned
    raise VendorHTTPError("eastmoney", 0, "network request failed")


def test_st_stock_list_falls_back_to_baostock_when_both_hosts_down(monkeypatch):
    _install(monkeypatch, _unreachable)
    _install_baostock(
        monkeypatch,
        [
            ["sh.600519", "*ST茅台", "2001-08-27", "", "1", "1"],
            ["sz.300001", "特锐德", "2009-10-30", "", "1", "1"],
        ],
    )
    report = a_share_events.get_a_share_st_stock_list()
    out = _parse_report(report)
    assert list(out["code"]) == ["600519"]
    assert list(out["market"]) == ["sh"]
    assert list(out["name"]) == ["*ST茅台"]
    assert out.iloc[0]["price"] == ""
    assert "Source: baostock" in report
    assert "Coverage: 沪深" in report
    assert "Fallback reason" in report


def test_st_stock_list_without_baostock_degrades_typed(monkeypatch):
    _install(monkeypatch, _unreachable)
    monkeypatch.setitem(sys.modules, "baostock", None)
    with pytest.raises(AshareCapabilityUnavailableError, match="st_stock_list"):
        a_share_events.get_a_share_st_stock_list()


def test_clist_falls_back_to_delayed_host_on_transport_failure(monkeypatch):
    attempted: list[str] = []

    def fake_em_get(url, **kwargs):
        attempted.append(url)
        if "push2delay" not in url:
            raise VendorHTTPError("eastmoney", 0, "network request failed")
        return {"rc": 0, "data": {"total": 1, "diff": [_clist_row("920575", 0, "*ST康乐")]}}

    monkeypatch.setattr(a_share_events, "em_get", fake_em_get)
    rows, url = a_share_events._em_clist_all(_BSE, "f12,f13,f14,f2,f3")
    assert url.startswith("https://push2delay.eastmoney.com")
    assert rows[0]["f12"] == "920575"
    assert attempted == [
        "https://push2.eastmoney.com/api/qt/clist/get",
        "https://push2delay.eastmoney.com/api/qt/clist/get",
    ]


@pytest.mark.parametrize("detail", ["invalid JSON response", "JSON root is not an object"])
def test_clist_content_failure_does_not_switch_host(monkeypatch, detail):
    attempted: list[str] = []

    def fake_em_get(url, **kwargs):
        attempted.append(url)
        raise VendorHTTPError("eastmoney", 200, detail)

    monkeypatch.setattr(a_share_events, "em_get", fake_em_get)
    with pytest.raises(ChinaDataUnavailableError, match="请求失败"):
        a_share_events._em_clist_all(_SHSZ, "f12")
    assert attempted == ["https://push2.eastmoney.com/api/qt/clist/get"]


def test_clist_server_error_payload_does_not_switch_host(monkeypatch):
    attempted: list[str] = []

    def fake_em_get(url, **kwargs):
        attempted.append(url)
        return {"rc": -1, "data": None}

    monkeypatch.setattr(a_share_events, "em_get", fake_em_get)
    with pytest.raises(ChinaDataUnavailableError, match="返回异常或无数据"):
        a_share_events._em_clist_all(_SHSZ, "f12")
    assert attempted == ["https://push2.eastmoney.com/api/qt/clist/get"]


def test_clist_row_count_must_match_self_reported_total(monkeypatch):
    def fake_em_get(url, **kwargs):
        page = kwargs["params"]["pn"]
        diff = [_clist_row("600519", 1, "*ST茅台")] if page == 1 else []
        return {"rc": 0, "data": {"total": 5, "diff": diff}}

    monkeypatch.setattr(a_share_events, "em_get", fake_em_get)
    with pytest.raises(ChinaDataUnavailableError, match=r"与 total=5 不符"):
        a_share_events._em_clist_all(_SHSZ, "f12,f13,f14,f2,f3")


# ---------------------------------------------------------------------------
# Strict pagination contract (_em_datacenter_strict)
# ---------------------------------------------------------------------------


def test_datacenter_9201_on_first_page_returns_empty(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 9201, "message": "返回数据为空"})
    assert a_share_events._em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1") == []


def test_datacenter_9201_after_first_page_raises(monkeypatch):
    def responder(call):
        if call["params"]["pageNumber"] == "1":
            return _payload([dict(_FORECAST_ROW), {**_FORECAST_ROW, "SECURITY_CODE": "000001"}],
                            pages=2, count=4)
        return {"code": 9201, "message": "返回数据为空"}

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="数据为空"):
        a_share_events._em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=2, max_rows=4
        )


def test_datacenter_non_zero_error_code_raises_with_code_and_message(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 9501, "message": "排序字段和顺序数量不一致",
                                        "result": None})
    with pytest.raises(ChinaDataUnavailableError, match=r"9501 排序字段和顺序数量不一致"):
        a_share_events._em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_short_non_final_page_raises(monkeypatch):
    def responder(call):
        return _payload([dict(_FORECAST_ROW), {**_FORECAST_ROW, "SECURITY_CODE": "000001"}],
                        pages=2, count=6)

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="非末页应为 3 条"):
        a_share_events._em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=3, max_rows=6
        )


def test_datacenter_empty_non_final_page_raises(monkeypatch):
    def responder(call):
        if call["params"]["pageNumber"] == "1":
            return _payload([dict(_FORECAST_ROW)], pages=2, count=2)
        return _payload([], pages=2, count=2)

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="页是空的"):
        a_share_events._em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=1, max_rows=2
        )


def test_datacenter_page_or_count_change_across_pages_raises(monkeypatch):
    def responder(call):
        if call["params"]["pageNumber"] == "1":
            return _payload([dict(_FORECAST_ROW), {**_FORECAST_ROW, "SECURITY_CODE": "000001"}],
                            pages=2, count=4)
        return _payload([dict(_FORECAST_ROW), {**_FORECAST_ROW, "SECURITY_CODE": "000002"}],
                        pages=3, count=6)

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="翻页时总页数"):
        a_share_events._em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=2, max_rows=6
        )


def test_datacenter_final_total_mismatch_raises(monkeypatch):
    _install(monkeypatch, lambda call: _payload([dict(_FORECAST_ROW)], pages=1, count=3))
    with pytest.raises(ChinaDataUnavailableError, match="与总数 3 不符"):
        a_share_events._em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_never_truncates_when_count_is_within_cap(monkeypatch):
    rows = [dict(_FORECAST_ROW), {**_FORECAST_ROW, "SECURITY_CODE": "000001"}]
    _install(monkeypatch, lambda call: _payload(rows, pages=1, count=1))
    with pytest.raises(ChinaDataUnavailableError, match="与总数 1 不符"):
        a_share_events._em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=10, max_rows=10
        )


def test_datacenter_truncates_only_when_count_exceeds_cap(monkeypatch):
    rows = [dict(_FORECAST_ROW), {**_FORECAST_ROW, "SECURITY_CODE": "000001"}]
    _install(monkeypatch, lambda call: _payload(rows, pages=2, count=2212))
    out = a_share_events._em_datacenter_strict(
        "RPT_X", sort_columns="A", sort_types="-1", page_size=2, max_rows=2
    )
    assert len(out) == 2


def test_datacenter_validates_sort_columns_and_types_before_request(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_FORECAST_ROW)]))
    with pytest.raises(ValueError, match="个数不一致"):
        a_share_events._em_datacenter_strict("RPT_X", sort_columns="A,B", sort_types="-1")
    assert calls == []


def test_datacenter_rejects_non_object_data(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 0, "result": {"pages": 1, "count": 1,
                                                             "data": ["not-a-dict"]}})
    with pytest.raises(ChinaDataUnavailableError, match="不是由对象组成的列表"):
        a_share_events._em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_missing_pagination_info_raises(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 0, "result": {"data": [dict(_FORECAST_ROW)]}})
    with pytest.raises(ChinaDataUnavailableError, match="缺少分页信息"):
        a_share_events._em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_provider_error_is_typed(monkeypatch):
    def fake_em_get(url, **kwargs):
        raise VendorHTTPError("eastmoney", 503)

    monkeypatch.setattr(a_share_events, "em_get", fake_em_get)
    with pytest.raises(ChinaDataUnavailableError, match="请求失败"):
        a_share_events._em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


# ---------------------------------------------------------------------------
# Filter verification and duplicate detection (_em_event_rows)
# ---------------------------------------------------------------------------


def test_event_rows_full_market_zero_rows_raises_but_narrowed_is_empty(monkeypatch):
    _install(monkeypatch, lambda call: _payload([], count=0))
    with pytest.raises(ChinaDataUnavailableError, match="全市场返回 0 行"):
        a_share_events._em_event_rows("RPT_X", "", "A", "-1", 10, narrowed=False)
    assert a_share_events._em_event_rows("RPT_X", "", "A", "-1", 10, narrowed=True) == []


def test_event_rows_rejects_another_instrument(monkeypatch):
    _install(monkeypatch, lambda call: _payload([{**_FORECAST_ROW, "SECURITY_CODE": "000001"}]))
    with pytest.raises(ChinaDataUnavailableError, match="结果不可信"):
        a_share_events._em_event_rows(
            "RPT_X", '(SECURITY_CODE="600519")', "A", "-1", 10, narrowed=True,
            equal={"SECURITY_CODE": "600519"},
        )


def test_event_rows_rejects_another_period(monkeypatch):
    _install(monkeypatch, lambda call: _payload([{**_FORECAST_ROW, "REPORT_DATE": "2026-06-30"}]))
    with pytest.raises(ChinaDataUnavailableError, match="结果不可信"):
        a_share_events._em_event_rows(
            "RPT_X", "(REPORT_DATE='2026-09-30')", "A", "-1", 10, narrowed=True,
            dates={"REPORT_DATE": ("2026-09-30", "2026-09-30")},
        )


def test_event_rows_rejects_duplicate_rows(monkeypatch):
    _install(monkeypatch, lambda call: _payload([dict(_FORECAST_ROW), dict(_FORECAST_ROW)],
                                                pages=1, count=2))
    with pytest.raises(ChinaDataUnavailableError, match="重复行"):
        a_share_events._em_event_rows("RPT_X", "", "A", "-1", 10, narrowed=True)


def test_event_rows_rejects_unrecognized_source_date(monkeypatch):
    _install(monkeypatch, lambda call: _payload([{**_FORECAST_ROW, "REPORT_DATE": "2026/09/30"}]))
    with pytest.raises(ChinaDataUnavailableError, match="无法识别的日期"):
        a_share_events._em_event_rows(
            "RPT_X", "", "A", "-1", 10, narrowed=True,
            dates={"REPORT_DATE": ("2026-09-30", "2026-09-30")},
        )


def test_source_contract_wraps_missing_field(monkeypatch):
    row = {k: v for k, v in _FORECAST_ROW.items() if k != "SECURITY_CODE"}
    _install(monkeypatch, lambda call: _payload([row]))
    with pytest.raises(ChinaDataUnavailableError, match="缺少字段"):
        a_share_events.get_a_share_earnings_forecast()


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def test_v39_num_normalizes_and_rejects_bad_values():
    assert a_share_events._v39_num(None) is None
    assert a_share_events._v39_num("") is None
    assert a_share_events._v39_num("-") is None
    assert a_share_events._v39_num("--") is None
    assert a_share_events._v39_num("None") is None
    assert a_share_events._v39_num("1,234.50") == 1234.5
    assert a_share_events._v39_num(7) == 7.0
    assert a_share_events._v39_num(float("nan")) is None
    assert a_share_events._v39_num(float("inf")) is None
    with pytest.raises(ChinaDataUnavailableError, match="布尔值"):
        a_share_events._v39_num(True)
    with pytest.raises(ChinaDataUnavailableError, match="无法识别的数值"):
        a_share_events._v39_num("garbage")


def test_v39_date_accepts_supported_forms_and_rejects_others():
    assert a_share_events._v39_date("20260918") == "2026-09-18"
    assert a_share_events._v39_date("2026-09-18") == "2026-09-18"
    with pytest.raises(ValueError):
        a_share_events._v39_date("2026/09/18")
    with pytest.raises(ValueError):
        a_share_events._v39_date("2026-13-40")


def test_em_day_rejects_non_iso_spelling():
    assert a_share_events._em_day(None) is None
    assert a_share_events._em_day("2026-09-18 00:00:00") == "2026-09-18"
    with pytest.raises(ChinaDataUnavailableError, match="无法识别的日期"):
        a_share_events._em_day("18/09/2026")


def test_v39_limit_validates_range():
    assert a_share_events._v39_limit(1) == 1
    assert a_share_events._v39_limit("5000") == 5000
    for bad in (0, 5001, -1):
        with pytest.raises(ValueError, match="limit 范围"):
            a_share_events._v39_limit(bad)
    with pytest.raises(ValueError):
        a_share_events._v39_limit("abc")


def test_public_limit_validation_raises_value_error():
    with pytest.raises(ValueError, match="limit 范围"):
        a_share_events.get_a_share_ipo_calendar(limit=0)
    with pytest.raises(ValueError, match="limit 范围"):
        a_share_events.get_a_share_earnings_forecast(limit=5001)
