"""Valuation-history rows: baostock parsing and Tushare fallback."""

from datetime import date

import pytest

from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
from tradingagents.dataflows.valuation_history import get_a_share_valuation_history_rows


def test_baostock_rows_are_parsed_and_sorted_newest_first(monkeypatch):
    text = "\n".join([
        "# China A-share valuation history for 002130.SZ", "# Source: baostock", "",
        "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM,turn,tradestatus,isST",
        "2026-11-03,002130.SZ,16.0,17.0,2.1,14.0,1.3,2.2,1,0",
        "2026-11-05,002130.SZ,14.5,15.0,1.9,12.0,1.1,2.5,1,0",
    ])
    monkeypatch.setattr("tradingagents.dataflows.a_stock_v37.get_a_share_valuation_history",
                        lambda ticker, start, end: text)
    rows = get_a_share_valuation_history_rows("002130.SZ", "2026-11-01", "2026-11-05")
    assert [row["published"] for row in rows] == ["2026-11-05", "2026-11-03"]
    assert rows[0]["pe_ttm"] == 15.0 and rows[0]["source_name"] == "baostock.valuation_history"


def test_baostock_failure_falls_back_to_tushare(monkeypatch):
    def unavailable(ticker, start, end):
        raise AshareCapabilityUnavailableError("valuation_history", "baostock", "login failed")

    monkeypatch.setattr("tradingagents.dataflows.valuation_history._baostock_rows", unavailable)
    monkeypatch.setattr("tradingagents.dataflows.valuation_history._tushare_rows",
                        lambda ticker, start, end, *, session: (
                            {"published": "2026-11-04", "close": 16.0, "pe_ttm": 17.1, "pb_mrq": 2.1,
                             "ps_ttm": None, "pcf": None, "turnover": None, "is_st": "",
                             "source_name": "tushare.valuation_history"},))
    rows = get_a_share_valuation_history_rows("002130.SZ", "2026-11-01", "2026-11-05")
    assert rows[0]["source_name"] == "tushare.valuation_history"


def test_window_and_ticker_are_validated():
    with pytest.raises(ValueError):
        get_a_share_valuation_history_rows("002130.SZ", "2026-11-05", "2026-11-01")
    with pytest.raises(AshareCapabilityUnavailableError):
        get_a_share_valuation_history_rows("AAPL", "2026-11-01", "2026-11-05")


def test_rows_never_go_past_the_requested_window(monkeypatch):
    import tradingagents.dataflows.valuation_history as module

    monkeypatch.setattr(module, "_baostock_rows", lambda ticker, start, end: (
        {"published": "2026-11-05", "close": 14.0, "pe_ttm": 15.0, "pb_mrq": 1.9,
         "ps_ttm": None, "pcf": None, "turnover": None, "is_st": "", "source_name": "baostock.valuation_history"},))
    rows = module.get_a_share_valuation_history_rows("002130.SZ", "2026-11-01", "2026-11-05")
    assert rows[0]["published"] == "2026-11-05"
    assert date.fromisoformat(rows[0]["published"]) <= date(2026, 11, 5)
