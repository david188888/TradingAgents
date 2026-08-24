"""Offline tests for strict ticker parsing and ETF/index routing.

Mirrors a-stock-data v3.6.0 ``norm_ticker()`` / ``get_prefix()`` semantics:
malformed or contradictory input must raise instead of silently picking the
wrong instrument, and exchange inference must cover Shanghai/Shenzhen ETFs.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows.ticker_utils import (
    infer_a_share_exchange,
    normalize_ticker_symbol,
    strict_ticker_code,
)


@pytest.mark.unit
class TestStrictTickerCode:
    def test_accepts_bare_and_prefixed_forms(self):
        assert strict_ticker_code("600519") == "600519"
        assert strict_ticker_code("SH600519") == "600519"
        assert strict_ticker_code("sh600519") == "600519"
        assert strict_ticker_code("600519.SH") == "600519"
        assert strict_ticker_code("BJ920982") == "920982"
        assert strict_ticker_code("SZ000001") == "000001"

    def test_rejects_malformed_input_instead_of_truncating(self):
        with pytest.raises(ValueError):
            strict_ticker_code("6005190")  # 7 digits must not be truncated
        with pytest.raises(ValueError):
            strict_ticker_code("foo600519bar")
        with pytest.raises(ValueError):
            strict_ticker_code("茅台")
        with pytest.raises(ValueError):
            strict_ticker_code("")

    def test_rejects_contradictory_market_identifiers(self):
        with pytest.raises(ValueError):
            strict_ticker_code("SH000001.SZ")  # prefix and suffix together
        with pytest.raises(ValueError):
            strict_ticker_code("SZ600519")  # 600519 is Shanghai

    def test_stock_only_rejects_shanghai_index_codes(self):
        with pytest.raises(ValueError):
            strict_ticker_code("SH000001", stock_only=True)
        with pytest.raises(ValueError):
            strict_ticker_code("000001.SH", stock_only=True)
        # The same code without an explicit Shanghai identifier stays valid.
        assert strict_ticker_code("000001") == "000001"
        # Explicit Shenzhen disambiguation for the 000xxx segment is legal.
        assert strict_ticker_code("sz000016") == "000016"


@pytest.mark.unit
class TestExchangeInference:
    def test_etf_codes_route_to_their_exchange(self):
        assert infer_a_share_exchange("510300") == "SH"
        assert infer_a_share_exchange("510050") == "SH"
        assert infer_a_share_exchange("588000") == "SH"
        assert infer_a_share_exchange("159915") == "SZ"

    def test_etf_codes_normalize_with_suffix(self):
        assert normalize_ticker_symbol("510300") == "510300.SS"
        assert normalize_ticker_symbol("159915") == "159915.SZ"

    def test_stock_codes_unchanged(self):
        assert infer_a_share_exchange("600519") == "SH"
        assert infer_a_share_exchange("000001") == "SZ"
        assert infer_a_share_exchange("920982") == "BJ"
        assert infer_a_share_exchange("000300") == "SH"  # index whitelist
