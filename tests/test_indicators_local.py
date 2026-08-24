"""Unit tests for the A-share local indicator vendor.

``get_stock_stats_indicators_local`` must compute indicators from the vendor
OHLCV chain (mootdx -> tushare) instead of yfinance, while producing the same
``date: value`` report contract as the global window function.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import y_finance


def _ohlcv_frame() -> pd.DataFrame:
    """250 trading days of synthetic OHLCV ending 2026-08-05."""
    dates = pd.bdate_range("2025-07-01", "2026-08-05")
    n = len(dates)
    base = pd.Series(range(10, 10 + n), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": base - 0.2,
            "High": base + 0.5,
            "Low": base - 0.5,
            "Close": base,
            "Volume": [1_000_000] * n,
        }
    )


def test_local_indicators_use_vendor_ohlcv_and_match_contract(monkeypatch):
    captured = {}

    def fake_load_ohlcv(symbol, curr_date, via_vendor=False):
        captured["via_vendor"] = via_vendor
        return _ohlcv_frame()

    monkeypatch.setattr(y_finance, "load_ohlcv", fake_load_ohlcv)

    report = y_finance.get_stock_stats_indicators_local(
        "600519.SS", "close_10_ema", "2026-08-05", look_back_days=10
    )

    # A-share local path must request the vendor chain.
    assert captured["via_vendor"] is True
    # Output contract: header + date: value lines + description.
    assert "close_10_ema values from" in report
    assert "2026-08-05:" in report
    assert "10 EMA" in report


def test_local_indicators_reject_unknown_indicator(monkeypatch):
    monkeypatch.setattr(
        y_finance,
        "load_ohlcv",
        lambda symbol, curr_date, via_vendor=False: _ohlcv_frame(),
    )
    with pytest.raises(ValueError, match="is not supported"):
        y_finance.get_stock_stats_indicators_local(
            "600519.SS", "not_an_indicator", "2026-08-05", look_back_days=10
        )


def test_global_window_stays_on_yfinance_path(monkeypatch):
    captured = {}

    def fake_load_ohlcv(symbol, curr_date, via_vendor=False):
        captured["via_vendor"] = via_vendor
        return _ohlcv_frame()

    monkeypatch.setattr(y_finance, "load_ohlcv", fake_load_ohlcv)

    y_finance.get_stock_stats_indicators_window(
        "AAPL", "rsi", "2026-08-05", look_back_days=5
    )
    # The global entry point must NOT switch to the vendor chain.
    assert captured["via_vendor"] is False


def test_bulk_calculates_macd_values(monkeypatch):
    monkeypatch.setattr(
        y_finance,
        "load_ohlcv",
        lambda symbol, curr_date, via_vendor=False: _ohlcv_frame(),
    )
    values = y_finance._get_stock_stats_bulk(
        "600519.SS", "macd", "2026-08-05", via_vendor=True
    )
    assert "2026-08-05" in values
    assert values["2026-08-05"] not in ("", "N/A")
