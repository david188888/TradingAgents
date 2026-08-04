"""Unit tests for the per-run yfinance reachability preflight."""

from __future__ import annotations

import pytest

from tradingagents.web.connectivity import (
    YahooUnavailableError,
    check_yfinance_reachable,
    requires_yfinance,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


class _FakeSession:
    def __init__(self, *, status_code: int = 200, raises: Exception | None = None):
        self._status = status_code
        self._raises = raises
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self._raises is not None:
            raise self._raises
        return _FakeResponse(self._status)


def test_a_share_ticker_does_not_require_yfinance():
    assert requires_yfinance("688825") is False
    assert requires_yfinance("600519") is False
    assert requires_yfinance("000001.SZ") is False


def test_global_tickers_require_yfinance():
    assert requires_yfinance("AAPL") is True
    assert requires_yfinance("0700.HK") is True
    assert requires_yfinance("GC=F") is True


def test_a_share_preflight_is_noop_without_network():
    session = _FakeSession(raises=AssertionError("must not be called"))
    # Must not raise and must not touch the session for an A-share ticker.
    check_yfinance_reachable("688825", session=session)
    assert session.calls == []


def test_global_preflight_accepts_successful_probe():
    session = _FakeSession(status_code=200)
    check_yfinance_reachable("AAPL", session=session)
    assert session.calls
    assert "query2.finance.yahoo.com" in session.calls[0]["url"]


def test_global_preflight_uses_normalized_symbol():
    # Broker aliases (XAUUSD) must be normalized to Yahoo's GC=F before probing.
    session = _FakeSession(status_code=200)
    check_yfinance_reachable("XAUUSD", session=session)
    assert "GC=F" in session.calls[0]["url"]


def test_global_preflight_raises_on_connection_error():
    import requests

    session = _FakeSession(raises=requests.ConnectionError("blocked"))
    with pytest.raises(YahooUnavailableError):
        check_yfinance_reachable("AAPL", session=session)


def test_global_preflight_raises_on_server_error():
    session = _FakeSession(status_code=503)
    with pytest.raises(YahooUnavailableError):
        check_yfinance_reachable("AAPL", session=session)


def test_global_preflight_treats_429_as_reachable():
    # A 429 still proves the host is reachable; do not block the run.
    session = _FakeSession(status_code=429)
    check_yfinance_reachable("AAPL", session=session)
