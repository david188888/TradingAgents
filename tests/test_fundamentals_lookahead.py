"""Historical fundamentals must not leak a live company profile.

Vendor "company overview" endpoints (yfinance ``Ticker.info``, Alpha Vantage
``OVERVIEW``) serve only present-day values. Market cap, valuation multiples,
the 52-week range and TTM income move with today's quote, and even the name,
sector and industry shift when a company renames or is reclassified. None of it
carries a historical vintage, so serving it into a run dated in the past puts
post-decision information into the analyst's context.

Both vendors withhold on one shared rule (``date_window.withhold_live_profile``)
so switching ``data_vendors`` between them cannot reintroduce the leak. The
statement tools stay point-in-time by filtering on ``curr_date``, and a live run
is unchanged. All API access is mocked.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from tradingagents.dataflows import (
    alpha_vantage_fundamentals as av,
    date_window,
    y_finance,
)

_TODAY = "2026-09-19"
_PAST = "2024-05-10"

# A profile payload mixing stable-looking identity fields with market-dependent ones.
_INFO = {
    "longName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "marketCap": 3_500_000_000_000,
    "trailingPE": 34.2,
    "fiftyTwoWeekHigh": 260.1,
    "totalRevenue": 391_000_000_000,
}

# Values that must never reach a historical run.
_LEAKY = (
    "3500000000000",
    "34.2",
    "260.1",
    "391000000000",
    "Apple Inc.",
    "Technology",
    "Consumer Electronics",
)

_AV_OVERVIEW = json.dumps({"Symbol": "AAPL", "MarketCapitalization": "3500000000000"})


def _yf(curr_date, info=_INFO, today=_TODAY):
    with (
        mock.patch.object(date_window, "get_current_date", return_value=today),
        mock.patch.object(y_finance, "yf_retry", lambda fn: info),
        mock.patch.object(y_finance.yf, "Ticker"),
    ):
        return y_finance.get_fundamentals("AAPL", curr_date)


def _av(curr_date, today=_TODAY):
    """Alpha Vantage path; the API call is mocked so a leak would be visible."""
    with (
        mock.patch.object(date_window, "get_current_date", return_value=today),
        mock.patch.object(av, "_make_api_request", return_value=_AV_OVERVIEW) as request,
    ):
        return av.get_fundamentals("AAPL", curr_date), request


@pytest.mark.unit
def test_yfinance_withholds_the_profile_from_a_past_run():
    out = _yf(_PAST)

    for leaked in _LEAKY:
        assert leaked not in out
    assert "withheld" in out
    assert _PAST in out


@pytest.mark.unit
def test_alpha_vantage_withholds_the_profile_from_a_past_run_without_calling_the_api():
    out, request = _av(_PAST)

    for leaked in _LEAKY:
        assert leaked not in out
    assert "withheld" in out
    assert _PAST in out
    # The guard runs before the request, so a paid-for response is never fetched
    # just to be discarded.
    request.assert_not_called()


@pytest.mark.unit
def test_yfinance_still_serves_the_profile_on_the_analysis_date():
    out = _yf(_TODAY)

    assert "Apple Inc." in out
    assert "3500000000000" in out


@pytest.mark.unit
def test_alpha_vantage_still_serves_the_profile_on_the_analysis_date():
    out, request = _av(_TODAY)

    request.assert_called_once()
    assert "MarketCapitalization" in out


@pytest.mark.unit
def test_a_direct_call_without_a_date_keeps_its_legacy_behavior():
    assert "Apple Inc." in _yf(None)
    out, request = _av(None)
    request.assert_called_once()
    assert "MarketCapitalization" in out


@pytest.mark.unit
def test_both_vendors_withhold_on_the_same_rule():
    """One shared rule, so the vendor switch cannot reintroduce the leak."""
    withheld_text = date_window.withhold_live_profile(_PAST, "AAPL")

    assert withheld_text is not None
    assert withheld_text == _yf(_PAST, info={})
    assert withheld_text == _av(_PAST)[0]
    assert date_window.withhold_live_profile(_TODAY, "AAPL") is None
    assert date_window.withhold_live_profile(None, "AAPL") is None


@pytest.mark.unit
def test_statement_tools_stay_point_in_time(monkeypatch):
    """The withhold must not make the statements stop filtering by curr_date."""
    payload = json.dumps(
        {
            "annualReports": [
                {"fiscalDateEnding": "2023-09-30"},
                {"fiscalDateEnding": "2026-09-30"},
            ]
        }
    )
    monkeypatch.setattr(av, "_make_api_request", lambda *a, **k: payload)

    kept = json.loads(av.get_balance_sheet("AAPL", curr_date=_PAST))

    assert [r["fiscalDateEnding"] for r in kept["annualReports"]] == ["2023-09-30"]
