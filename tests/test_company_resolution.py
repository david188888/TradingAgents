"""Unit tests for user-input resolution (company names + multi-format codes).

The network lookups are monkeypatched so the suite stays offline and fast.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows import company_resolution
from tradingagents.dataflows.company_resolution import resolve_input_to_ticker


@pytest.fixture(autouse=True)
def _clear_resolution_caches():
    """Sina/Yahoo suggest results are lru_cached; clear between tests.

    Uses getattr so teardown also works when a test monkeypatched the function
    with a plain lambda (no cache_clear).
    """
    for func in (company_resolution._sina_suggest, company_resolution._yahoo_search):
        clear = getattr(func, "cache_clear", None)
        if clear:
            clear()
    yield
    for func in (company_resolution._sina_suggest, company_resolution._yahoo_search):
        clear = getattr(func, "cache_clear", None)
        if clear:
            clear()


# --- local code forms (zero network) ---
@pytest.mark.parametrize("raw,expected", [
    ("688825", "688825.SS"),
    ("SH688825", "688825.SS"),
    ("688825.SH", "688825.SS"),
    ("sh688825", "688825.SS"),
    ("688825.SS", "688825.SS"),
    ("600519", "600519.SS"),
    ("002636", "002636.SZ"),
    ("430047", "430047.BJ"),
    # Shanghai index whitelist: 000300 -> SH, not SZ.
    ("000300", "000300.SS"),
    ("000016", "000016.SS"),
    # BSE new segment: 920xxx -> BJ.
    ("920982", "920982.BJ"),
    # 000001 stays SZ (Ping An Bank) unless explicitly prefixed.
    ("000001", "000001.SZ"),
    ("SH000001", "000001.SS"),
    # commodity / forex / crypto aliases.
    ("XAUUSD", "GC=F"),
    ("BTCUSD", "BTC-USD"),
    ("EURUSD", "EURUSD=X"),
    # plain US ticker stays as-is without a network call.
    ("AAPL", "AAPL"),
    ("TSLA", "TSLA"),
])
def test_local_code_forms(raw, expected):
    assert resolve_input_to_ticker(raw) == expected


# --- company names via Sina suggest (CJK) ---
def test_chinese_company_name_via_sina(monkeypatch):
    monkeypatch.setattr(
        company_resolution,
        "_sina_suggest",
        lambda query: (("贵州茅台", "600519"),),
    )
    assert resolve_input_to_ticker("茅台") == "600519.SS"
    assert resolve_input_to_ticker("贵州茅台") == "600519.SS"


def test_chinese_name_no_sina_result_falls_back(monkeypatch):
    monkeypatch.setattr(company_resolution, "_sina_suggest", lambda query: ())
    # CJK with no hit -> cannot resolve to anything.
    assert resolve_input_to_ticker("不存在的公司名") == ""


# --- English company names via Yahoo search ---
def test_english_company_name_via_yahoo(monkeypatch):
    monkeypatch.setattr(
        company_resolution,
        "_yahoo_search",
        lambda query: ("AAPL",),
    )
    assert resolve_input_to_ticker("Apple") == "AAPL"


def test_english_name_yahoo_returns_us_first(monkeypatch):
    # A non-US equity must not shadow the US listing when Yahoo returns both.
    monkeypatch.setattr(
        company_resolution,
        "_yahoo_search",
        lambda query: ("APC.DE",),
    )
    assert resolve_input_to_ticker("Apple") == "APC.DE"


def test_mixed_case_ascii_company_name_triggers_search(monkeypatch):
    called = []
    monkeypatch.setattr(
        company_resolution, "_yahoo_search", lambda query: called.append(query) or ("MSFT",)
    )
    assert resolve_input_to_ticker("Microsoft") == "MSFT"
    assert called == ["Microsoft"]


def test_all_upper_ascii_does_not_trigger_search(monkeypatch):
    called = []
    monkeypatch.setattr(
        company_resolution, "_yahoo_search", lambda query: called.append(query) or ("AAPL",)
    )
    # AAPL is a code; no network search should be attempted.
    assert resolve_input_to_ticker("AAPL") == "AAPL"
    assert called == []


def test_empty_and_garbage_inputs():
    assert resolve_input_to_ticker("") == ""
    assert resolve_input_to_ticker("   ") == ""
    assert resolve_input_to_ticker(None) == ""


# --- suggest / search parsers (synthetic responses) ---
def test_sina_suggest_parses_gbk_response(monkeypatch):
    class _FakeResp:
        content = (
            'var suggestvalue="贵州茅台,11,600519,sh600519,贵州茅台,,贵州茅台,99,1,ESG,,;'
            '平安银行,11,000001,sz000001,平安银行,,平安银行,99,1,ESG,,";'
        ).encode("gbk")

    monkeypatch.setattr(company_resolution.requests, "get", lambda *a, **kw: _FakeResp())
    rows = company_resolution._sina_suggest("茅台")
    assert rows == (("贵州茅台", "600519"), ("平安银行", "000001"))


def test_sina_suggest_skips_non_a_share_rows(monkeypatch):
    class _FakeResp:
        content = (
            'var suggestvalue="贵州茅台,11,600519,sh600519,贵州茅台,,贵州茅台,99,1,ESG,,;'
            '腾讯控股,13,00700,hk00700,腾讯控股,,腾讯控股,99,1,,,";'
        ).encode("gbk")

    monkeypatch.setattr(company_resolution.requests, "get", lambda *a, **kw: _FakeResp())
    rows = company_resolution._sina_suggest("茅台")
    # HK row (market type 13) is skipped by this endpoint.
    assert rows == (("贵州茅台", "600519"),)


def test_yahoo_search_filters_to_equities(monkeypatch):
    class _FakeResp:
        def json(self):
            return {
                "quotes": [
                    {"symbol": "AAPL", "quoteType": "EQUITY", "exchange": "NMS"},
                    {"symbol": "BTC-USD", "quoteType": "CRYPTOCURRENCY", "exchange": "CCC"},
                ]
            }

    monkeypatch.setattr(company_resolution.requests, "get", lambda *a, **kw: _FakeResp())
    assert company_resolution._yahoo_search("Apple") == ("AAPL",)
