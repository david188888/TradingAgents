"""Symbol normalization must apply on every yfinance path, not just price fetch.

Regression tests for #983 (instrument identity) and the news path: a broker
symbol like XAUUSD must resolve to the same Yahoo symbol (GC=F) that the price
path uses, so identity and news lookups hit the right instrument instead of
failing/mismatching.
"""
import tradingagents.agents.utils.agent_utils as au
import tradingagents.dataflows.yfinance_news as ynews


def test_identity_lookup_normalizes_symbol(monkeypatch):
    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            seen["symbol"] = symbol

        @property
        def info(self):
            return {"longName": "Gold Futures", "quoteType": "FUTURE"}

    monkeypatch.setattr(au.yf, "Ticker", FakeTicker)
    au.resolve_instrument_identity.cache_clear()

    identity = au.resolve_instrument_identity("XAUUSD")

    assert seen["symbol"] == "GC=F"  # normalized, not the raw broker symbol
    assert identity.get("company_name") == "Gold Futures"


def test_news_lookup_normalizes_symbol(monkeypatch):
    seen = {}

    class FakeTicker:
        def __init__(self, symbol):
            seen["symbol"] = symbol

        def get_news(self, count):
            return []

    monkeypatch.setattr(ynews.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(ynews, "yf_retry", lambda fn: fn())

    out = ynews.get_news_yfinance("XAUUSD", "2025-01-01", "2025-01-10")

    assert seen["symbol"] == "GC=F"   # news queried with the canonical symbol
    # An empty feed over a past window is a coverage gap, so the marker names
    # both the user's ticker and the resolved one. Assert that pair explicitly:
    # a bare substring check would also pass on an unrelated sentence.
    assert out.startswith("<Yahoo Finance news unavailable for 2025-01-01..2025-01-10")
    assert "news for XAUUSD (resolved to GC=F)" in out
