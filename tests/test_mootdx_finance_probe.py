"""a-stock-data #52: finance/F10 must be valued independently of dead quotes.

The 2026-09 TDX change killed the quote commands (``bars`` / ``quotes`` /
``transaction``) while ``finance`` and the F10 「最新提示」 category kept
answering.  Validating every caller with a one-bar fetch therefore reports
"every TDX server is dead" for capabilities that are in fact healthy, and a
single shared breaker then suppresses finance/F10 for the whole cooldown.

These tests pin the fix: a per-class probe (``check='bars'`` vs
``check='finance'``), a per-class client cache, and a per-class breaker.
"""

from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from tradingagents.dataflows import mootdx_provider
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _SplitClient:
    """A client shaped like the live 2026-09 state: quotes dead, finance alive."""

    def __init__(self, *, bars_empty: bool = True, finance_ok: bool = True) -> None:
        self.bars_empty = bars_empty
        self.finance_ok = finance_ok
        self.calls: list[str] = []

    def bars(self, symbol="000001", frequency=9, start=0, offset=800, **kwargs):
        self.calls.append("bars")
        if self.bars_empty:
            return pd.DataFrame()
        return pd.DataFrame([{"symbol": symbol, "close": 10.0, "datetime": "2026-09-30 15:00"}])

    def F10C(self, symbol="000001"):
        self.calls.append("F10C")
        return [{"name": "最新提示"}, {"name": "公司概况"}]

    def F10(self, symbol="000001", name="最新提示"):
        self.calls.append("F10")
        return "最新提示正文" if name == "最新提示" else ""

    def finance(self, symbol="000001"):
        self.calls.append("finance")
        if not self.finance_ok:
            return pd.DataFrame()
        return pd.DataFrame([{"symbol": symbol, "eps": 1.2}])


def _install(monkeypatch, client: _SplitClient) -> list[_SplitClient]:
    created: list[_SplitClient] = []

    class _FakeQuotes:
        def factory(self, market="std", **kwargs):
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

    monkeypatch.setattr(mootdx_provider.socket, "create_connection", lambda *a, **kw: _Ctx())
    return created


@pytest.fixture(autouse=True)
def _reset():
    mootdx_provider._reset_tdx_client_cache()
    yield
    mootdx_provider._reset_tdx_client_cache()


def test_finance_probe_succeeds_while_the_quote_probe_fails(monkeypatch):
    """The whole point of #52: dead bars must not condemn finance/F10."""
    client = _SplitClient(bars_empty=True, finance_ok=True)
    _install(monkeypatch, client)

    with pytest.raises(ChinaDataUnavailableError, match="No mootdx/TDX server"):
        mootdx_provider.tdx_client(check="bars")

    finance_client = mootdx_provider.tdx_client(check="finance")
    assert finance_client is client


def test_breakers_are_scoped_to_the_validation_class(monkeypatch):
    """A dead-quote sweep must not freeze finance out for the cooldown."""
    client = _SplitClient(bars_empty=True, finance_ok=True)
    _install(monkeypatch, client)

    with pytest.raises(ChinaDataUnavailableError):
        mootdx_provider.tdx_client(check="bars")

    assert mootdx_provider._tdx_breaker_open("bars") is True
    assert mootdx_provider._tdx_breaker_open("finance") is False

    # And the finance class still probes and succeeds rather than being
    # short-circuited by the bars breaker.
    assert mootdx_provider.tdx_client(check="finance") is client


def test_client_cache_is_keyed_by_validation_class(monkeypatch):
    """A bar-validated client must never be handed to a finance caller."""
    bars_client = _SplitClient(bars_empty=False, finance_ok=False)
    _install(monkeypatch, bars_client)

    bars_cached = mootdx_provider.tdx_client(check="bars")
    assert bars_cached is bars_client

    finance_client = _SplitClient(bars_empty=True, finance_ok=True)
    _install(monkeypatch, finance_client)
    assert mootdx_provider.tdx_client(check="finance") is finance_client

    # Re-asking for bars returns the bar-validated client, not the finance one.
    assert mootdx_provider.tdx_client(check="bars") is bars_client


def test_finance_probe_requires_category_text_and_frame(monkeypatch):
    """Any one of the three checks failing rejects the server."""

    class _NoCategoryClient(_SplitClient):
        def F10C(self, symbol="000001"):
            self.calls.append("F10C")
            return [{"name": "公司概况"}]

    class _EmptyTextClient(_SplitClient):
        def F10(self, symbol="000001", name="最新提示"):
            self.calls.append("F10")
            return "   "

    for client in (_NoCategoryClient(), _EmptyTextClient(), _SplitClient(finance_ok=False)):
        mootdx_provider._reset_tdx_client_cache()
        _install(monkeypatch, client)
        with pytest.raises(ChinaDataUnavailableError, match="No mootdx/TDX server"):
            mootdx_provider.tdx_client(check="finance")


def test_unknown_check_is_a_caller_error(monkeypatch):
    _install(monkeypatch, _SplitClient())
    with pytest.raises(ValueError, match="check must be one of"):
        mootdx_provider.tdx_client(check="quotes")


def test_non_std_market_skips_validation(monkeypatch):
    """The probe sample is an A-share code; it cannot judge another market."""
    client = _SplitClient(bars_empty=True, finance_ok=True)
    _install(monkeypatch, client)

    # 'ext' (extended quotes) would reject a healthy server if the A-share
    # sample were used, so validation is skipped for every non-std market.
    assert mootdx_provider.tdx_client(market="ext", check="bars") is client
    assert "bars" not in client.calls


def test_finance_and_f10_adapters_request_the_finance_class(monkeypatch):
    """The two finance-class vendors must ask for the finance probe."""
    seen: list[str] = []

    def _fake_tdx_client(*, check=mootdx_provider._TDX_CHECK_BARS, market="std"):
        seen.append(check)
        return _SplitClient()

    monkeypatch.setattr(mootdx_provider, "tdx_client", _fake_tdx_client)
    monkeypatch.setattr(mootdx_provider, "_capture_vendor_raw", lambda *a, **kw: None)

    mootdx_provider.get_fundamentals_mootdx("600519.SH", "2026-09-30")
    mootdx_provider.get_a_share_f10("600519.SH")

    assert seen == ["finance", "finance"]
