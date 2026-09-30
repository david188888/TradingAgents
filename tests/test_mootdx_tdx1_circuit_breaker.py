"""T-D1 regression guard: mootdx must not re-pay its dead-server sweep per request.

Live probe 2026-09-29 (capability-probe-2026-09-29.md §4) recorded 13/13 mootdx
quote failures where the TCP handshake and ``Quotes.factory()`` both succeed and
every data call then returns an empty columnless DataFrame.  The pre-fix code
probed all 8 servers (25-28s) on *every* A-share request.

Every test in this file fails without the T-D1 fix.
"""

from __future__ import annotations

import sys
import time
import types

import pandas as pd
import pytest

from tradingagents.dataflows import mootdx_provider
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.registry import VENDOR_METHODS
from tradingagents.dataflows.symbol_utils import NoMarketDataError


class _EmptyBarsClient:
    """A client shaped like the live failure: handshake OK, data always empty.

    Every ``bars()`` call sleeps ``per_call_seconds`` to stand in for the real
    ~3s server round trip, so a test can assert on wall-clock cost without a
    26-second suite.
    """

    def __init__(self, per_call_seconds: float = 0.05) -> None:
        self.per_call_seconds = per_call_seconds
        self.calls = 0

    def bars(self, symbol="000001", frequency=9, start=0, offset=800, **kwargs):
        self.calls += 1
        time.sleep(self.per_call_seconds)
        # The live failure returns a DataFrame with *no columns at all*.
        return pd.DataFrame()


def _install_always_empty_mootdx(monkeypatch, per_call_seconds: float = 0.05):
    """Install a mootdx whose every server handshakes and every fetch is empty."""
    created: list[_EmptyBarsClient] = []

    class _FakeQuotes:
        def factory(self, market="std", **kwargs):
            client = _EmptyBarsClient(per_call_seconds)
            created.append(client)
            return client

    fake_quotes = types.SimpleNamespace(Quotes=_FakeQuotes())
    monkeypatch.setitem(sys.modules, "mootdx", types.SimpleNamespace(quotes=fake_quotes))
    monkeypatch.setitem(sys.modules, "mootdx.quotes", fake_quotes)

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr(
        mootdx_provider.socket, "create_connection", lambda *a, **kw: _Ctx()
    )
    return created


@pytest.fixture(autouse=True)
def _reset_breaker():
    mootdx_provider._reset_tdx_client_cache()
    yield
    mootdx_provider._reset_tdx_client_cache()


def test_second_request_does_not_repay_the_dead_server_sweep(monkeypatch):
    """T-D1 core acceptance: two consecutive requests must not each pay the sweep.

    Before the fix each call re-probed all ``_TDX_SERVERS`` (8 handshakes + 8
    one-bar validation fetches).  Here the per-fetch cost is 50ms, so the
    pre-fix sweep is ~800ms; the breaker must make the second call effectively
    free.
    """
    per_call = 0.05
    server_count = len(mootdx_provider._TDX_SERVERS)
    created = _install_always_empty_mootdx(monkeypatch, per_call_seconds=per_call)

    first_start = time.monotonic()
    with pytest.raises(ChinaDataUnavailableError):
        mootdx_provider.get_stock_mootdx_df("000001", "2026-01-01", "2026-07-01")
    first_elapsed = time.monotonic() - first_start

    second_start = time.monotonic()
    with pytest.raises(ChinaDataUnavailableError, match="circuit breaker open"):
        mootdx_provider.get_stock_mootdx_df("000001", "2026-01-01", "2026-07-01")
    second_elapsed = time.monotonic() - second_start

    # The first call still pays the full sweep; the second pays nothing.
    assert first_elapsed >= per_call * server_count
    assert second_elapsed < per_call  # not merely "smaller", but no I/O at all

    # And the second call opened no TCP connection and built no client.
    assert len(created) == server_count


def test_breaker_does_not_swallow_a_recovered_server(monkeypatch):
    """A cooldown must not freeze the vendor out forever."""
    per_call = 0.01
    created = _install_always_empty_mootdx(monkeypatch, per_call_seconds=per_call)

    with pytest.raises(ChinaDataUnavailableError):
        mootdx_provider.tdx_client()
    assert mootdx_provider._tdx_breaker_open() is True

    # Simulate the cooldown elapsing; a now-working server must be usable again.
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        mootdx_provider.time, "monotonic", lambda: real_monotonic() + 10_000.0
    )
    assert mootdx_provider._tdx_breaker_open() is False

    bars = pd.DataFrame(
        {
            "open": [10.0],
            "close": [10.5],
            "high": [11.0],
            "low": [9.5],
            "vol": [1000.0],
            "datetime": ["2026-06-01 15:00"],
        }
    )

    class _GoodQuotes:
        def factory(self, market="std", **kwargs):
            return types.SimpleNamespace(
                bars=lambda **kw: bars,
            )

    fake_quotes = types.SimpleNamespace(Quotes=_GoodQuotes())
    monkeypatch.setitem(
        sys.modules, "mootdx", types.SimpleNamespace(quotes=fake_quotes)
    )
    monkeypatch.setitem(sys.modules, "mootdx.quotes", fake_quotes)

    client = mootdx_provider.tdx_client()

    assert client is not None
    assert mootdx_provider._tdx_breaker_open() is False
    assert mootdx_provider._tdx_probe_failure_count == 0
    assert created  # sanity: the empty clients really were built first


def test_a_working_server_never_opens_the_breaker(monkeypatch):
    """Regression guard in the other direction: success must not be poisoned."""
    bars = pd.DataFrame(
        {
            "open": [10.0],
            "close": [10.5],
            "high": [11.0],
            "low": [9.5],
            "vol": [1000.0],
            "datetime": ["2026-06-01 15:00"],
        }
    )

    class _GoodQuotes:
        def factory(self, market="std", **kwargs):
            return types.SimpleNamespace(bars=lambda **kw: bars)

    fake_quotes = types.SimpleNamespace(Quotes=_GoodQuotes())
    monkeypatch.setitem(
        sys.modules, "mootdx", types.SimpleNamespace(quotes=fake_quotes)
    )
    monkeypatch.setitem(sys.modules, "mootdx.quotes", fake_quotes)

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr(
        mootdx_provider.socket, "create_connection", lambda *a, **kw: _Ctx()
    )

    mootdx_provider.tdx_client()
    mootdx_provider.tdx_client()

    assert mootdx_provider._tdx_probe_failure_count == 0
    assert mootdx_provider._tdx_breaker_open() is False


def test_mootdx_is_not_the_first_daily_bar_vendor():
    """T-D1 registry demotion, with diff evidence in registry.py."""
    chain = tuple(VENDOR_METHODS["get_stock_data"])

    assert chain[0] == "tushare", chain
    assert "mootdx" in chain, "mootdx must stay registered as a fallback"
    assert chain.index("tushare") < chain.index("mootdx")


def test_mootdx_finance_and_f10_capabilities_are_preserved():
    """Design §8.2 forbids deleting mootdx's finance/F10 capabilities."""
    finance = VENDOR_METHODS["get_a_share_fundamentals_mootdx"]
    assert finance == {"mootdx": mootdx_provider.get_fundamentals_mootdx}

    f10 = VENDOR_METHODS["get_a_share_f10"]
    assert f10 == {"mootdx": mootdx_provider.get_a_share_f10}


def test_ohlcv_loader_try_order_matches_registry(monkeypatch, tmp_path):
    """The local OHLCV loader must not re-introduce mootdx-first on its own."""
    from tradingagents.dataflows import stockstats_utils as su

    monkeypatch.setattr(
        su, "get_config", lambda: {"data_cache_dir": str(tmp_path)}
    )

    tried: list[str] = []

    def _record(name):
        def fetch(symbol, start, end):
            tried.append(name)
            raise ChinaDataUnavailableError(f"{name} down")

        return fetch

    from tradingagents.dataflows import china_data, mootdx_provider as mp

    monkeypatch.setattr(china_data, "get_stock_tushare_df", _record("tushare"))
    monkeypatch.setattr(mp, "get_stock_mootdx_df", _record("mootdx"))
    monkeypatch.setattr(china_data, "get_stock_akshare_df", _record("akshare"))

    with pytest.raises(NoMarketDataError) as ctx:
        su._load_ohlcv_a_share("600519.SH", "2026-07-01")
    # The chain is exhausted, and the message names every vendor tried -- a
    # reader must not be able to mistake this for "the stock had no data".
    message = str(ctx.value)
    for vendor in ("tushare", "mootdx", "akshare"):
        assert vendor in message, message

    assert tried == ["tushare", "mootdx", "akshare"]
