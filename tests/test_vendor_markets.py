"""Tests for the vendor market capability matrix and routing skip logic."""

import pytest

from tradingagents.dataflows.interface import (
    VENDOR_LIST,
    VENDOR_MARKETS,
    _should_skip_vendor_for_symbol,
)


@pytest.mark.unit
class TestVendorMarketsMatrix:
    def test_every_vendor_has_a_market_entry(self):
        """Adding a vendor to VENDOR_LIST without a VENDOR_MARKETS entry is a
        silent routing bug (the fallback allows both markets). Enforce coverage."""
        missing = [v for v in VENDOR_LIST if v not in VENDOR_MARKETS]
        assert not missing, f"vendors without a VENDOR_MARKETS entry: {missing}"

    def test_a_share_only_vendors(self):
        for vendor in ("tushare", "akshare", "eastmoney", "china_exchange", "iwencai", "cls"):
            assert VENDOR_MARKETS[vendor] == frozenset({"a_share"}), vendor

    def test_global_only_vendors(self):
        for vendor in ("yfinance", "fred", "alpha_vantage"):
            assert VENDOR_MARKETS[vendor] == frozenset({"global"}), vendor

    def test_both_markets_vendors(self):
        # alpha_vantage has no A-share coverage and is deliberately global-only
        # so A-share chains never attempt a doomed call; tavily serves both.
        for vendor in ("tavily",):
            assert VENDOR_MARKETS[vendor] == frozenset({"a_share", "global"}), vendor


@pytest.mark.unit
class TestShouldSkipVendorForSymbol:
    def test_a_share_ticker_keeps_china_vendors(self):
        for vendor in ("tushare", "akshare", "eastmoney", "china_exchange"):
            assert _should_skip_vendor_for_symbol("get_stock_data", vendor, ("600519.SH",)) is False

    def test_a_share_ticker_skips_yfinance(self):
        assert _should_skip_vendor_for_symbol("get_stock_data", "yfinance", ("600519.SH",)) is True

    def test_global_ticker_skips_china_vendors(self):
        for vendor in ("tushare", "akshare", "eastmoney", "china_exchange", "iwencai", "cls"):
            assert _should_skip_vendor_for_symbol("get_stock_data", vendor, ("AAPL",)) is True, vendor

    def test_global_ticker_keeps_yfinance(self):
        assert _should_skip_vendor_for_symbol("get_stock_data", "yfinance", ("AAPL",)) is False

    def test_a_share_ticker_skips_alpha_vantage(self):
        assert _should_skip_vendor_for_symbol("get_stock_data", "alpha_vantage", ("600519.SH",)) is True

    def test_global_ticker_keeps_alpha_vantage(self):
        assert _should_skip_vendor_for_symbol("get_stock_data", "alpha_vantage", ("AAPL",)) is False

    def test_indicators_follow_the_market_matrix(self):
        # get_indicators must be market-filtered like the other core methods:
        # an unfiltered chain sent A-share indicator calls to yfinance /
        # alpha_vantage, burning doomed requests into rate-limit cooldowns
        # while the local (mootdx -> tushare) chain was the intended source.
        assert _should_skip_vendor_for_symbol("get_indicators", "yfinance", ("600519.SH",)) is True
        assert _should_skip_vendor_for_symbol("get_indicators", "alpha_vantage", ("600519.SH",)) is True
        assert _should_skip_vendor_for_symbol("get_indicators", "local", ("600519.SH",)) is False
        assert _should_skip_vendor_for_symbol("get_indicators", "yfinance", ("AAPL",)) is False

    def test_non_ticker_capability_never_skipped(self):
        # get_global_news is not in _A_SHARE_TICKER_CAPABILITIES -> no market filter
        assert _should_skip_vendor_for_symbol("get_global_news", "tavily", ("2026-07-23",)) is False
        assert _should_skip_vendor_for_symbol("get_global_news", "tushare", ("2026-07-23",)) is False

    def test_no_args_not_skipped(self):
        assert _should_skip_vendor_for_symbol("get_stock_data", "yfinance", ()) is False
