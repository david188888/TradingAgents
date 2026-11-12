from __future__ import annotations

import pytest

from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol


@pytest.mark.parametrize("ticker", ("600519.SZ", "SZ600519", "688981.SZ"))
def test_normalization_rejects_explicit_market_conflicts(ticker: str) -> None:
    with pytest.raises(ValueError, match="市场标识与号段矛盾"):
        normalize_ticker_symbol(ticker)
