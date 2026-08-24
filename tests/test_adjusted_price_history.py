"""Explicit adjusted-price provider contracts and raw-fallback exclusion."""

from __future__ import annotations

from io import StringIO

import pandas as pd

from tradingagents.dataflows import alpha_vantage_stock, china_data, y_finance
from tradingagents.dataflows.coverage import CoveredText
from tradingagents.dataflows.registry import VENDOR_METHODS
from tradingagents.research.price_prefetch import build_price_prefetch_plan


def test_tushare_adjusted_history_requests_qfq_and_exposes_typed_basis(monkeypatch):
    calls: list[dict] = []

    class FakeTushare:
        def pro_bar(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                {
                    "trade_date": ["20260611", "20260610"],
                    "open": [50.0, 50.0],
                    "high": [51.0, 51.0],
                    "low": [49.0, 49.0],
                    "close": [50.0, 50.0],
                    "vol": [1000, 900],
                }
            )

    monkeypatch.setattr(china_data, "_get_tushare_module", lambda: FakeTushare())
    monkeypatch.setattr(china_data, "_save_raw_data", lambda *_a, **_k: None)

    result = china_data.get_stock_tushare_qfq(
        "000338.SZ",
        "2026-06-10",
        "2026-06-11",
    )

    assert calls == [
        {
            "ts_code": "000338.SZ",
            "start_date": "20260610",
            "end_date": "20260611",
            "adj": "qfq",
            "freq": "D",
        }
    ]
    assert isinstance(result, CoveredText)
    assert result.coverage.price_basis == "qfq"
    assert result.coverage.adjustment_verified is True
    assert "# Price basis: qfq" in result


def test_akshare_adjusted_history_ignores_raw_default_and_forces_qfq(monkeypatch):
    calls: list[dict] = []

    class FakeAkshare:
        def stock_zh_a_hist(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                {
                    "日期": ["2026-06-10", "2026-06-11"],
                    "开盘": [50.0, 50.0],
                    "最高": [51.0, 51.0],
                    "最低": [49.0, 49.0],
                    "收盘": [50.0, 50.0],
                    "成交量": [900, 1000],
                }
            )

    monkeypatch.setattr(
        china_data,
        "_import_optional",
        lambda module, _hint: FakeAkshare() if module == "akshare" else None,
    )
    monkeypatch.setattr(china_data, "_save_raw_data", lambda *_a, **_k: None)

    result = china_data.get_stock_akshare_qfq(
        "000338.SZ",
        "2026-06-10",
        "2026-06-11",
    )

    assert calls[0]["adjust"] == "qfq"
    assert result.coverage.source_id == "akshare.qfq_daily"


def test_adjusted_route_has_no_raw_provider_fallback():
    assert tuple(VENDOR_METHODS["get_adjusted_price_history"]) == (
        "wind",
        "tushare",
        "akshare",
        "yfinance",
        "alpha_vantage",
    )
    assert "mootdx" not in VENDOR_METHODS["get_adjusted_price_history"]


def test_yfinance_adjusted_history_pins_auto_adjust_semantics(monkeypatch):
    calls: list[dict] = []
    frame = pd.DataFrame(
        {
            "Open": [50.0, 50.0],
            "High": [51.0, 51.0],
            "Low": [49.0, 49.0],
            "Close": [50.0, 50.0],
            "Volume": [900, 1000],
        },
        index=pd.DatetimeIndex(["2026-06-10", "2026-06-11"], name="Date"),
    )

    class FakeTicker:
        def history(self, **kwargs):
            calls.append(kwargs)
            return frame.copy()

    monkeypatch.setattr(y_finance.yf, "Ticker", lambda _symbol: FakeTicker())
    monkeypatch.setattr(y_finance, "yf_retry", lambda call: call())
    monkeypatch.setattr(y_finance, "_assert_ohlcv_not_stale", lambda *_a: None)
    monkeypatch.setattr(y_finance, "_capture_yfinance_frame", lambda *_a, **_k: None)

    result = y_finance.get_YFin_adjusted_data_online(
        "AAPL",
        "2026-06-10",
        "2026-06-11",
    )

    assert calls == [
        {
            "start": "2026-06-10",
            "end": "2026-06-12",
            "auto_adjust": True,
            "actions": False,
        }
    ]
    assert result.coverage.price_basis == "split_dividend_adjusted"
    assert result.coverage.adjustment_verified is True


def test_alpha_vantage_adjusts_all_ohlc_with_adjusted_close_ratio(monkeypatch):
    source = """timestamp,open,high,low,close,adjusted_close,volume
2026-06-10,100,102,98,100,50,900
2026-06-11,50,51,49,50,50,1000
"""
    monkeypatch.setattr(alpha_vantage_stock, "get_stock", lambda *_a: source)

    result = alpha_vantage_stock.get_adjusted_stock(
        "AAPL",
        "2026-06-10",
        "2026-06-11",
    )

    frame = pd.read_csv(StringIO(str(result).split("\n\n", 1)[1]))
    assert frame.loc[0, ["open", "high", "low", "close"]].tolist() == [
        50.0,
        51.0,
        49.0,
        50.0,
    ]
    assert result.coverage.price_basis == "split_dividend_adjusted"
    assert result.coverage.adjustment_verified is True


def test_corporate_action_fixture_distinguishes_raw_from_qfq_returns():
    raw = pd.Series([100.0, 50.0, 51.0])
    qfq = pd.Series([50.0, 50.0, 51.0])

    assert raw.pct_change().iloc[1] == -0.5
    assert qfq.pct_change().iloc[1] == 0.0


def test_price_prefetch_plan_is_horizon_owned():
    short = build_price_prefetch_plan("short", "2026-07-31", market="a_share")
    medium = build_price_prefetch_plan("medium", "2026-07-31", market="a_share")
    long = build_price_prefetch_plan("long", "2026-07-31", market="a_share")

    assert short.start_date == "2025-07-31"
    assert short.required_trading_days == 60
    assert medium.required_trading_days == 250
    assert medium.start_date == "2025-07-17"
    assert long.start_date == "2021-07-31"
    assert long.granularities == ("weekly", "monthly")
    assert all(plan.price_basis == "qfq" for plan in (short, medium, long))
    global_long = build_price_prefetch_plan("long", "2026-07-31", market="global")
    assert global_long.price_basis == "split_dividend_adjusted"
