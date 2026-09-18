"""Insider data must not leak transactions after a historical run date."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from tradingagents.dataflows import alpha_vantage_news, y_finance


@pytest.mark.unit
def test_alpha_vantage_insiders_are_trimmed_to_curr_date(monkeypatch):
    monkeypatch.setattr(
        alpha_vantage_news,
        "_make_api_request",
        lambda *_args: json.dumps(
            {
                "data": [
                    {"transaction_date": "2026-08-13", "name": "Before"},
                    {"transaction_date": "2026-08-15", "name": "After"},
                ]
            }
        ),
    )

    result = json.loads(
        alpha_vantage_news.get_insider_transactions("AAPL", curr_date="2026-08-14")
    )

    assert result["data"] == [{"transaction_date": "2026-08-13", "name": "Before"}]


@pytest.mark.unit
def test_alpha_vantage_malformed_dated_insiders_fail_closed(monkeypatch):
    monkeypatch.setattr(
        alpha_vantage_news,
        "_make_api_request",
        lambda *_args: '{"data": [{"transaction_date": "not-a-date"}]}',
    )

    with pytest.raises(ValueError, match="transaction_date"):
        alpha_vantage_news.get_insider_transactions("AAPL", curr_date="2026-08-14")


@pytest.mark.unit
def test_yahoo_insiders_are_trimmed_to_curr_date(monkeypatch):
    data = pd.DataFrame(
        {"Shares": [10, 20]},
        index=pd.Index(["before", "after"]),
    )
    data["Start Date"] = pd.to_datetime(["2026-08-13", "2026-08-15"])

    monkeypatch.setattr(y_finance.yf, "Ticker", lambda _symbol: object())
    monkeypatch.setattr(y_finance, "yf_retry", lambda callback: data)

    result = y_finance.get_insider_transactions("AAPL", curr_date="2026-08-14")

    assert "before" in result
    assert "after" not in result


@pytest.mark.unit
def test_yahoo_insiders_disclose_retention_gap_not_no_transactions(monkeypatch):
    data = pd.DataFrame({"Shares": [10]})
    data["Start Date"] = pd.to_datetime(["2026-08-13"])

    monkeypatch.setattr(y_finance.yf, "Ticker", lambda _symbol: object())
    monkeypatch.setattr(y_finance, "yf_retry", lambda callback: data)

    result = y_finance.get_insider_transactions("AAPL", curr_date="2026-08-01")

    assert "unavailable" in result
    assert "coverage starts 2026-08-13" in result
    assert "No insider transactions" not in result
