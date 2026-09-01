"""Latest-bar OHLCV guard (upstream #1201): the newest in-range bar with no
closing price is "not settled yet", not "does not exist".

Silently dropping it (the old ``_clean_dataframe`` dropna behavior) made the
previous trading day look like the latest. The guard raises NoMarketDataError so
the router surfaces the condition instead of fabricating a fallback. Dates are
parsed per element so mixed UTC offsets (cache CSVs spanning DST, non-US
positive-offset markets) keep each bar's local calendar day.
"""
from __future__ import annotations

import pandas as pd
import pytest

import tradingagents.dataflows.stockstats_utils as su
from tradingagents.dataflows.symbol_utils import NoMarketDataError

CURR = "2026-07-18"
TODAY = pd.Timestamp(CURR)  # pinned so the cache filename matches load_ohlcv's


def _seed_cache(tmp_path, filename: str, frame: pd.DataFrame) -> None:
    start = (TODAY - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = (TODAY + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    frame.to_csv(tmp_path / filename.format(start=start, end=end), index=False)


@pytest.mark.unit
def test_latest_bar_with_nan_close_is_rejected(tmp_path, monkeypatch):
    """A newest in-range bar without a close raises instead of being dropped."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})

    def _fake_download(*a, **k):
        return pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-07-16", "2026-07-17", "2026-07-18"]),
                "Open": [100.0, 101.0, 102.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.5, 101.5, float("nan")],
                "Volume": [1_000, 1_100, 1_200],
            }
        ).set_index("Date")

    monkeypatch.setattr(su.yf, "download", _fake_download)

    with pytest.raises(NoMarketDataError) as ctx:
        su.load_ohlcv("AAPL", CURR)
    assert "closing price" in str(ctx.value)


@pytest.mark.unit
def test_middle_incomplete_rows_are_dropped_not_filled(tmp_path, monkeypatch):
    """Local policy is preserved: interior rows missing OHLC are dropped, and
    nothing is forward- or backward-filled — only the *latest* bar is guarded."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})

    def _fake_download(*a, **k):
        return pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-07-15", "2026-07-16", "2026-07-17"]),
                "Open": [100.0, float("nan"), 102.0],
                "High": [101.0, float("nan"), 103.0],
                "Low": [99.0, float("nan"), 101.0],
                "Close": [100.5, float("nan"), 102.5],
                "Volume": [1_000, float("nan"), 1_200],
            }
        )

    monkeypatch.setattr(su.yf, "download", _fake_download)

    out = su.load_ohlcv("AAPL", CURR)
    assert list(out["Date"].dt.strftime("%Y-%m-%d")) == ["2026-07-15", "2026-07-17"]
    # No manufactured values: the NaN-close interior row must not reappear filled.
    assert out["Close"].notna().all()


@pytest.mark.unit
def test_cached_latest_bar_with_blank_close_is_rejected(tmp_path, monkeypatch):
    """A cache CSV round-trips a missing close as an empty string, which parses
    to NaN — the guard must fire on the cached path too."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    # Pin "today" so load_ohlcv computes the same cache filename we seeded
    # (otherwise the mismatch silently misses the cache and downloads live).
    monkeypatch.setattr(su.pd.Timestamp, "today", staticmethod(lambda: TODAY))
    frame = pd.DataFrame(
        {
            "Date": ["2026-07-15", "2026-07-16", "2026-07-17"],
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, ""],
            "Volume": [1_000, 1_100, 1_200],
        }
    )
    _seed_cache(tmp_path, "AAPL-YFin-data-{start}-{end}.csv", frame)

    # Historical request: the cache is always reused (never refetched).
    with pytest.raises(NoMarketDataError) as ctx:
        su.load_ohlcv("AAPL", CURR)
    assert "closing price" in str(ctx.value)


@pytest.mark.unit
def test_a_share_latest_bar_with_nan_close_is_rejected(tmp_path, monkeypatch):
    """The A-share (mootdx/tushare/akshare) path enforces the same guard."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})

    def fetch(symbol, start_str, end_str):
        return pd.DataFrame(
            {
                "Date": ["2026-07-16", "2026-07-17"],
                "Open": [10.0, 10.2],
                "High": [10.1, 10.3],
                "Low": [9.9, 10.1],
                "Close": [10.05, float("nan")],
                "Volume": [50_000, 51_000],
            }
        )

    from tradingagents.dataflows import mootdx_provider

    monkeypatch.setattr(mootdx_provider, "get_stock_mootdx_df", fetch)

    with pytest.raises(NoMarketDataError) as ctx:
        su._load_ohlcv_a_share("600519.SH", CURR)
    assert "closing price" in str(ctx.value)


@pytest.mark.unit
def test_normalize_dates_keep_local_calendar_day():
    """Positive-offset late-night bars must keep their local date: a utc-unify
    would shift them to the previous day and wrongly exclude them from an
    as-of filter. Mixed offsets (DST span) must parse without raising."""
    dates = su._normalize_dates(
        pd.Series(
            [
                "2026-07-18 01:00:00+09:00",   # UTC 2026-07-17 16:00 — local day is 07-18
                "2026-01-15 20:00:00-05:00",   # EST
                "2026-07-16 20:00:00-04:00",   # EDT — same wall clock, other offset
                "2026-07-17",
            ]
        )
    )
    assert dates.dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-18",
        "2026-01-15",
        "2026-07-16",
        "2026-07-17",
    ]
    assert pd.api.types.is_datetime64_any_dtype(dates)


@pytest.mark.unit
def test_source_id_attr_survives_filter_and_drop():
    """Provenance: ``source_id`` set by the loaders must survive the curr_date
    filter and ``_drop_incomplete_rows`` (pandas attrs are best-effort; this
    pins the behavior the evidence chain relies on)."""
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-07-15", "2026-07-16", "2026-07-17"]),
            "Open": [1.0, float("nan"), 3.0],
            "High": [1.0, float("nan"), 3.0],
            "Low": [1.0, float("nan"), 3.0],
            "Close": [1.0, float("nan"), 3.0],
            "Volume": [1.0, 2.0, 3.0],
        }
    )
    df = su._clean_dataframe(df)
    df.attrs["source_id"] = "mootdx.daily_bars"
    df = df[df["Date"] <= pd.Timestamp("2026-07-18")]
    df = su._drop_incomplete_rows(df)
    assert df.attrs.get("source_id") == "mootdx.daily_bars"


@pytest.mark.unit
def test_cached_csv_with_tz_offset_strings_parses(tmp_path, monkeypatch):
    """End-to-end: a cache CSV whose Date column carries UTC offsets (yfinance
    writes tz-aware stamps; the CSV round-trips them as strings) must parse per
    element instead of raising "Mixed timezones detected" and must compare
    against the naive curr_date cutoff without a TypeError."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(su.pd.Timestamp, "today", staticmethod(lambda: TODAY))
    frame = pd.DataFrame(
        {
            "Date": [
                "2026-01-15 00:00:00-05:00",  # EST bar
                "2026-07-16 00:00:00-04:00",  # EDT bar — mixed offsets in one cache
                "2026-07-17 00:00:00-04:00",
            ],
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1_000, 1_100, 1_200],
        }
    )
    _seed_cache(tmp_path, "AAPL-YFin-data-{start}-{end}.csv", frame)

    out = su.load_ohlcv("AAPL", CURR)  # historical request: cache is reused
    assert list(out["Date"].dt.strftime("%Y-%m-%d")) == [
        "2026-01-15",
        "2026-07-16",
        "2026-07-17",
    ]


@pytest.mark.unit
def test_local_midnight_variants():
    assert su._local_midnight(pd.NaT) is pd.NaT
    assert su._local_midnight(None) is pd.NaT
    assert su._local_midnight("not a date") is pd.NaT
    naive = su._local_midnight("2026-07-17 15:45:00")
    assert naive == pd.Timestamp("2026-07-17")
    assert naive.tzinfo is None
    aware = su._local_midnight(pd.Timestamp("2026-07-17 23:30:00+08:00"))
    assert aware == pd.Timestamp("2026-07-17")
    assert aware.tzinfo is None
