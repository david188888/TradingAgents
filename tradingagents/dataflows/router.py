"""Shared routing helpers for the dataflow layer.

``_should_skip_vendor_for_symbol`` / ``_market_for_request`` implement the
vendor market capability matrix and are shared by the general vendor
router and the news router.
"""

from __future__ import annotations

from typing import Any

from .registry import VENDOR_MARKETS
from .ticker_utils import is_a_share_ticker

_A_SHARE_TICKER_CAPABILITIES = {
    "get_stock_data",
    "get_adjusted_price_history",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_a_share_valuation",
    "get_a_share_research_reports",
    "get_a_share_eps_forecast",
    "get_a_share_concept_blocks",
    "get_a_share_hot_concept",
    "get_a_share_capital_flow",
    "get_a_share_margin_financing",
    "get_a_share_northbound_holdings",
    "get_a_share_insider_trades",
    "get_a_share_exchange_announcements",
    "get_a_share_bulk_trades",
    "get_a_share_shareholder_counts",
    "get_a_share_lockup_releases",
    "get_a_share_dragon_tiger",
    "get_a_share_interactive_questions",
    "get_news",
    "get_equity_risk_metrics",
}


_A_SHARE_NON_TICKER_CAPABILITIES = {
    "get_a_share_limit_up_ladder",
    "get_a_share_daily_dragon_tiger",
    "get_a_share_industry_ranking",
    "get_a_share_option_tquote",
    "get_a_share_option_greeks",
    "get_a_share_hot_list",
    "get_a_share_break_board_pool",
    "get_a_share_limit_down_pool",
    "get_a_share_prev_limit_up_pool",
    "get_a_share_northbound_flow",
    "get_a_share_stock_monitor",
    "get_a_share_price_anomaly",
    "get_a_share_price_anomaly_count",
    "get_china_macro_indicators",
    "get_a_share_interactive_answers",
    "search_a_share_iwencai",
    "get_cls_telegraph",
    # Wind index/macro capabilities: first arg is an index code/name or EDB
    # codes, not a stock ticker, so they bypass the ticker market filter but
    # are still bucketed as a_share for health/circuit-breaker isolation.
    "get_index_snapshot",
    "get_index_history",
    "get_index_profile",
    "get_index_fundamentals",
    "search_macro_series",
    "get_macro_series",
}


def _should_skip_vendor_for_symbol(method: str, vendor: str, args: tuple[Any, ...]) -> bool:
    """Route A-share tickers away from overseas vendors and vice versa.

    Uses the ``VENDOR_MARKETS`` capability matrix: a vendor is skipped when
    the request's market is not among the vendor's declared markets. China-only
    providers (tushare/akshare/eastmoney/china_exchange/iwencai/cls) are skipped
    for non-A-share tickers; yfinance is skipped for A-share tickers (requires
    VPN, poor coverage, wastes ~15s on rate-limit retries when tushare/akshare
    are the correct primary sources).

    Date-only and query-only A-share capabilities do not have a ticker in
    position zero, so they are recognised by method rather than being skipped
    by the generic ticker check.
    """
    if method not in _A_SHARE_TICKER_CAPABILITIES:
        return False
    if not args:
        return False
    is_a_share = is_a_share_ticker(str(args[0]))
    markets = VENDOR_MARKETS.get(vendor, frozenset({"a_share", "global"}))
    if is_a_share:
        return "a_share" not in markets
    return "global" not in markets


def _market_for_request(args: tuple[Any, ...], method: str | None = None) -> str:
    if method in _A_SHARE_NON_TICKER_CAPABILITIES:
        return "a_share"
    if args and is_a_share_ticker(str(args[0])):
        return "a_share"
    return "global"
