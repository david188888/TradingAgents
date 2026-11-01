"""Offline adjustment, cutoff and source-admission counterexamples."""

from datetime import datetime, timezone

import pytest

from tradingagents.dataflows.tushare_price_history import (
    PriceHistoryQualificationError,
    prepare_tushare_price_history,
    settled_sessions,
)

NOW = datetime(2026, 9, 30, 9, tzinfo=timezone.utc)


def inputs():
    calendar = [{"cal_date": f"202609{day}", "is_open": 1} for day in (28, 29, 30)]
    daily = [{"ts_code": "600519.SH", "trade_date": f"202609{day}",
        "open": close, "high": close + 1, "low": close - 1, "close": close}
        for day, close in ((28, 100), (29, 102), (30, 51))]
    factors = [{"ts_code": "600519.SH", "trade_date": f"202609{day}", "adj_factor": factor}
        for day, factor in ((28, 2), (29, 2), (30, 4))]
    return daily, factors, calendar


def prepare(daily, factors, calendar, **kwargs):
    return prepare_tushare_price_history(daily, factors, calendar,
        ts_code="600519.SH", start="2026-09-28", cutoff="2026-09-30", captured_at=NOW, **kwargs)


def test_dated_factor_join_removes_split_without_future_anchor():
    daily, factors, calendar = inputs()
    result = prepare(daily[::-1], factors, calendar)
    assert [row["Close"] for row in result["bars"]] == [50, 51, 51]
    assert result["bars"][0]["High"] == 50.5
    assert result["provenance"]["adjustment_anchor"] == "2026-09-30"
    assert result["provenance"]["pit_status"] == "verified"
    assert result["provenance"]["window_covered"] is True
    assert result["provenance"]["input_sha256"] == prepare(daily, factors[::-1], calendar[::-1])["provenance"]["input_sha256"]


def test_retrospective_capture_does_not_prove_historical_vintage():
    daily, factors, calendar = inputs()
    result = prepare_tushare_price_history(daily[:2], factors[:2], calendar[:2],
        ts_code="600519.SH", start="2026-09-28", cutoff="2026-09-29", captured_at=NOW)
    assert result["provenance"]["window_covered"] is True
    assert result["provenance"]["pit_status"] == "unverified"
    assert result["provenance"]["degradations"] == ["historical_factor_vintage_unverified"]


def test_calendar_gap_is_retained_without_filled_price():
    daily, factors, calendar = inputs()
    result = prepare([daily[0], daily[2]], factors, calendar)
    assert len(result["bars"]) == 2
    assert result["provenance"]["missing_sessions"] == ["2026-09-29"]
    assert result["provenance"]["window_covered"] is False


@pytest.mark.parametrize("pollution", ["wrong_security", "future_factor", "duplicate_price", "missing_factor", "nan_close", "bad_ohlc", "truncated_calendar"])
def test_polluted_responses_fail_closed(pollution):
    daily, factors, calendar = inputs()
    if pollution == "wrong_security":
        daily[0]["ts_code"] = "000001.SZ"
    elif pollution == "future_factor":
        factors.append({"ts_code": "600519.SH", "trade_date": "20261001", "adj_factor": 99})
    elif pollution == "duplicate_price":
        daily.append(daily[0])
    elif pollution == "missing_factor":
        factors.pop(1)
    elif pollution == "nan_close":
        daily[0]["close"] = float("nan")
    elif pollution == "bad_ohlc":
        daily[0]["high"] = 80
    else:
        calendar.pop(1)
    with pytest.raises(PriceHistoryQualificationError):
        prepare(daily, factors, calendar)


def test_current_unsettled_session_excluded_before_request():
    _, _, calendar = inputs()
    before_close = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)
    assert settled_sessions(calendar, start="2026-09-28", cutoff="2026-09-30", captured_at=before_close) == ("2026-09-28", "2026-09-29")


@pytest.mark.parametrize("cutoff, capture", [("2026-10-01", NOW), ("2026-09-30", NOW.replace(tzinfo=None))])
def test_future_cutoff_or_timezone_ambiguity_rejected(cutoff, capture):
    _, _, calendar = inputs()
    with pytest.raises(PriceHistoryQualificationError):
        settled_sessions(calendar, start="2026-09-28", cutoff=cutoff, captured_at=capture)
