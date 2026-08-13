from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import pytest

from tradingagents import default_config
from tradingagents.dataflows import interface, stockstats_utils
from tradingagents.dataflows.health import VendorHealthRegistry
from tradingagents.dataflows.symbol_utils import NoMarketDataError


def test_default_statement_routes_include_global_providers() -> None:
    vendors = default_config.DEFAULT_CONFIG["tool_vendors"]

    for method in ("get_balance_sheet", "get_cashflow", "get_income_statement"):
        assert vendors[method].split(",") == [
            "tushare",
            "sina",
            "yfinance",
            "alpha_vantage",
        ]


@pytest.mark.parametrize(
    "method", ("get_balance_sheet", "get_cashflow", "get_income_statement")
)
def test_default_global_statement_route_reaches_global_provider(
    monkeypatch, method: str
) -> None:
    calls: list[str] = []

    def a_share_only(*args, **kwargs):
        raise AssertionError("global symbol must skip A-share-only provider")

    def global_result(*args, **kwargs):
        calls.append("yfinance")
        return "global statement"

    configured = default_config.DEFAULT_CONFIG["tool_vendors"][method]
    monkeypatch.setattr(interface, "get_vendor", lambda category, name=None: configured)
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        method,
        {
            "tushare": a_share_only,
            "sina": a_share_only,
            "yfinance": global_result,
            "alpha_vantage": global_result,
        },
    )

    result = interface.route_to_vendor(method, "AAPL", "2026-08-13")

    assert result == "global statement"
    assert calls == ["yfinance"]


def test_ohlcv_cleaning_never_backfills_from_future_rows() -> None:
    raw = pd.DataFrame(
        {
            "Date": ["2026-08-11", "2026-08-12", "2026-08-13"],
            "Open": [None, 10.0, 11.0],
            "High": [None, 11.0, 12.0],
            "Low": [None, 9.0, 10.0],
            "Close": [None, 10.5, 11.5],
            "Volume": [None, None, 100.0],
        }
    )

    cleaned = stockstats_utils._clean_dataframe(raw)

    assert list(cleaned["Date"].dt.strftime("%Y-%m-%d")) == [
        "2026-08-12",
        "2026-08-13",
    ]
    assert pd.isna(cleaned.iloc[0]["Volume"])


def test_a_share_current_day_cache_obeys_ttl(monkeypatch, tmp_path) -> None:
    today = pd.Timestamp.today().normalize()
    curr_date = today.strftime("%Y-%m-%d")
    start_str = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end_str = (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cache = tmp_path / f"600519.SH-Tushare-data-{start_str}-{end_str}.csv"
    pd.DataFrame(
        {
            "Date": [curr_date],
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Volume": [1.0],
        }
    ).to_csv(cache, index=False)
    stale_mtime = datetime.now().timestamp() - (
        stockstats_utils.OHLCV_CACHE_TTL_SECONDS + 10
    )
    os.utime(cache, (stale_mtime, stale_mtime))

    fresh = pd.DataFrame(
        {
            "Date": [curr_date],
            "Open": [2.0],
            "High": [2.0],
            "Low": [2.0],
            "Close": [2.0],
            "Volume": [2.0],
        }
    )
    calls: list[str] = []

    def fetch(*args, **kwargs):
        calls.append("mootdx")
        return fresh

    monkeypatch.setattr(
        stockstats_utils, "get_config", lambda: {"data_cache_dir": str(tmp_path)}
    )
    from tradingagents.dataflows import mootdx_provider

    monkeypatch.setattr(mootdx_provider, "get_stock_mootdx_df", fetch)

    result = stockstats_utils._load_ohlcv_a_share("600519.SH", curr_date)

    assert calls == ["mootdx"]
    assert result.iloc[-1]["Close"] == 2.0


def test_cooldown_plus_no_data_is_provider_unavailable(monkeypatch) -> None:
    registry = VendorHealthRegistry(clock=lambda: 100.0)
    registry.record_failure(
        vendor="yfinance",
        market="global",
        capability="get_stock_data",
        cooldown_seconds=60,
        reason="rate_limit",
    )

    def must_not_call(*args, **kwargs):
        raise AssertionError("cooldown vendor must not be called")

    def no_data(symbol, *args, **kwargs):
        raise NoMarketDataError(symbol, symbol, "no rows")

    monkeypatch.setattr(interface, "_vendor_health", registry)
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "yfinance")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"yfinance": must_not_call, "alpha_vantage": no_data},
    )

    with pytest.raises(interface.DataUnavailableError):
        interface.route_to_vendor(
            "get_stock_data", "AAPL", "2026-08-01", "2026-08-13"
        )
