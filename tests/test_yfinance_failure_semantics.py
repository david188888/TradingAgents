"""Provider failures are vendor failures, never report text or fake absence.

An ``"Error retrieving ..."`` string is counted by the router as a successful
answer: the fallback chain stops there and the error text reaches the analyst as
if it were data. An empty frame is ambiguous for the same reason -- yfinance
returns one both for an unknown symbol and for a request that never got an
answer. These tests pin the three-way distinction the fork requires:

* the vendor answered and had nothing -> ``NoMarketDataError``
* the vendor failed / was unreachable -> ``VendorRequestError``
* the vendor answered with data -> the report

Every reachability probe is mocked (``tests/conftest.py`` defaults it to "Yahoo
is answering"; the outage tests override it). No test here touches the network.
"""

from __future__ import annotations

import pandas as pd
import pytest
import requests

from tradingagents.dataflows import (
    interface,
    stockstats_utils,
    utils,
    y_finance,
    yfinance_news,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorError,
    VendorRequestError,
)

_PROVIDER_BLEW_UP = RuntimeError("yahoo transport blew up")


def _unreachable(monkeypatch) -> None:
    monkeypatch.setattr(stockstats_utils, "vendor_reachable", lambda *a, **k: False)


def _reachable(monkeypatch) -> None:
    monkeypatch.setattr(stockstats_utils, "vendor_reachable", lambda *a, **k: True)


def _ticker_whose_read_fails(monkeypatch) -> None:
    class FailingTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def __getattr__(self, name):
            raise _PROVIDER_BLEW_UP

    monkeypatch.setattr(y_finance.yf, "Ticker", FailingTicker)


# --------------------------------------------------------------------------- #
# A failing provider call is a typed error, not a report string.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: y_finance.get_fundamentals("AAPL"), id="fundamentals"),
        pytest.param(lambda: y_finance.get_balance_sheet("AAPL"), id="balance_sheet"),
        pytest.param(lambda: y_finance.get_cashflow("AAPL"), id="cashflow"),
        pytest.param(lambda: y_finance.get_income_statement("AAPL"), id="income_statement"),
        pytest.param(lambda: y_finance.get_insider_transactions("AAPL"), id="insider"),
    ],
)
def test_provider_failure_raises_instead_of_returning_error_text(monkeypatch, call):
    _ticker_whose_read_fails(monkeypatch)

    with pytest.raises(VendorRequestError) as excinfo:
        call()

    assert isinstance(excinfo.value, VendorError)
    assert "Error retrieving" not in str(excinfo.value)


@pytest.mark.unit
def test_company_news_failure_raises_instead_of_returning_error_text(monkeypatch):
    class FailingTicker:
        def __init__(self, symbol):
            pass

        def get_news(self, count):
            raise _PROVIDER_BLEW_UP

    monkeypatch.setattr(yfinance_news.yf, "Ticker", FailingTicker)

    with pytest.raises(VendorRequestError) as excinfo:
        yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-31")

    assert "Error fetching" not in str(excinfo.value)


@pytest.mark.unit
def test_global_news_failure_raises_instead_of_returning_error_text(monkeypatch):
    def failing_search(*args, **kwargs):
        raise _PROVIDER_BLEW_UP

    monkeypatch.setattr(yfinance_news.yf, "Search", failing_search)

    with pytest.raises(VendorRequestError) as excinfo:
        yfinance_news.get_global_news_yfinance("2026-01-31")

    assert "Error fetching" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# An empty result is only "no data" when the provider actually answered.
# --------------------------------------------------------------------------- #


class _EmptyStatementTicker:
    quarterly_balance_sheet = pd.DataFrame()
    balance_sheet = pd.DataFrame()
    quarterly_cashflow = pd.DataFrame()
    cashflow = pd.DataFrame()
    quarterly_income_stmt = pd.DataFrame()
    income_stmt = pd.DataFrame()

    def __init__(self, symbol):
        self.symbol = symbol


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    ["get_balance_sheet", "get_cashflow", "get_income_statement"],
)
def test_empty_statement_from_a_reachable_provider_is_no_data(monkeypatch, method):
    monkeypatch.setattr(y_finance.yf, "Ticker", _EmptyStatementTicker)
    _reachable(monkeypatch)

    with pytest.raises(NoMarketDataError):
        getattr(y_finance, method)("AAPL")


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    ["get_balance_sheet", "get_cashflow", "get_income_statement"],
)
def test_empty_statement_from_an_unreachable_provider_is_a_vendor_failure(monkeypatch, method):
    monkeypatch.setattr(y_finance.yf, "Ticker", _EmptyStatementTicker)
    _unreachable(monkeypatch)

    with pytest.raises(VendorRequestError) as excinfo:
        getattr(y_finance, method)("AAPL")

    message = str(excinfo.value)
    assert "not evidence about the symbol" in message
    assert "delisted" not in message


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reachable", "expected"),
    [(True, NoMarketDataError), (False, VendorRequestError)],
    ids=["provider-answered", "provider-unreachable"],
)
def test_empty_price_download_separates_outage_from_unknown_symbol(
    monkeypatch, tmp_path, reachable, expected
):
    set_config({"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(stockstats_utils.yf, "download", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(stockstats_utils, "vendor_reachable", lambda *a, **k: reachable)

    with pytest.raises(expected):
        stockstats_utils.load_ohlcv("NOSUCHSYMBOL", "2026-01-01")


@pytest.mark.unit
def test_empty_company_news_from_an_outage_is_not_reported_as_no_news(monkeypatch):
    class EmptyNewsTicker:
        def __init__(self, symbol):
            pass

        def get_news(self, count):
            return []

    monkeypatch.setattr(yfinance_news.yf, "Ticker", EmptyNewsTicker)

    _unreachable(monkeypatch)
    with pytest.raises(VendorRequestError):
        yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-31")

    _reachable(monkeypatch)
    assert (
        yfinance_news.get_news_yfinance("AAPL", "2026-01-01", "2026-01-31")
        == "No news found for AAPL"
    )


@pytest.mark.unit
def test_empty_insider_list_from_an_outage_is_not_reported_as_no_transactions(monkeypatch):
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: object())
    monkeypatch.setattr(y_finance, "yf_retry", lambda callback: pd.DataFrame())

    _unreachable(monkeypatch)
    with pytest.raises(VendorRequestError):
        y_finance.get_insider_transactions("AAPL")

    _reachable(monkeypatch)
    assert (
        "No insider transactions reported"
        in y_finance.get_insider_transactions("AAPL")
    )


# --------------------------------------------------------------------------- #
# The router reacts to the failure, and never claims authoritative no-data.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_router_falls_back_to_the_next_provider_after_a_vendor_failure(monkeypatch):
    calls: list[str] = []

    def provider_failure(*args, **kwargs):
        calls.append("yfinance")
        raise VendorRequestError("yfinance", "connection reset by peer")

    def serves_the_data(*args, **kwargs):
        calls.append("alpha_vantage")
        return "Date,Close\n2026-01-02,10.5\n"

    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "yfinance,alpha_vantage")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"yfinance": provider_failure, "alpha_vantage": serves_the_data},
    )

    result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")

    assert result == "Date,Close\n2026-01-02,10.5\n"
    assert calls == ["yfinance", "alpha_vantage"]


@pytest.mark.unit
def test_router_does_not_read_a_vendor_failure_as_authoritative_no_data(monkeypatch):
    def provider_failure(*args, **kwargs):
        raise VendorRequestError("yfinance", "connection reset by peer")

    def no_data(symbol, *args, **kwargs):
        raise NoMarketDataError(symbol, symbol, "no rows")

    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "yfinance,alpha_vantage")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_stock_data",
        {"yfinance": provider_failure, "alpha_vantage": no_data},
    )

    with pytest.raises(interface.DataUnavailableError) as excinfo:
        interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")

    # One vendor failed; the other merely had no rows. That mix cannot prove the
    # instrument is invalid, so the definitive no-data sentinel is wrong here.
    assert "NO_DATA_AVAILABLE" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# The reachability probe itself.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_reachability_probe_caches_its_verdict(monkeypatch):
    probes: list[str] = []

    def failing_head(url, timeout, allow_redirects):
        probes.append(url)
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(utils, "_REACHABILITY_CACHE", {})
    monkeypatch.setattr(utils.requests, "head", failing_head)

    assert utils.vendor_reachable("https://probe.invalid") is False
    assert utils.vendor_reachable("https://probe.invalid") is False
    assert probes == ["https://probe.invalid"]


@pytest.mark.unit
def test_reachability_probe_reports_success_and_can_bypass_the_cache(monkeypatch):
    probes: list[str] = []

    def head(url, timeout, allow_redirects):
        probes.append(url)

    monkeypatch.setattr(utils, "_REACHABILITY_CACHE", {})
    monkeypatch.setattr(utils.requests, "head", head)

    assert utils.vendor_reachable("https://probe.invalid", ttl_seconds=0) is True
    assert utils.vendor_reachable("https://probe.invalid", ttl_seconds=0) is True
    assert len(probes) == 2
