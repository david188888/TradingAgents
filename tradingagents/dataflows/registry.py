"""Static vendor / tool / market registry for the dataflow layer.

Single source of truth for:
- tool categories (``TOOLS_CATEGORIES``)
- known vendor names (``VENDOR_LIST``)
- vendor market capability matrix (``VENDOR_MARKETS``)
- method -> vendor implementations (``VENDOR_METHODS``)
- category/method vendor resolution (``get_category_for_method`` / ``get_vendor``)

New vendors or tools are registered here, not by editing routing branches.
``interface.py`` re-exports these symbols so existing callers and tests keep
working while new code imports directly from this module.
"""

import logging

from .a_stock_v37 import (
    get_a_share_adjust_factors,
    get_a_share_chip_distribution,
    get_a_share_listing_history,
    get_a_share_valuation_history,
    get_china_pmi,
    get_china_social_financing,
    get_sw_industry_history,
)
from .alpha_vantage import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_global_news as get_alpha_vantage_global_news,
    get_income_statement as get_alpha_vantage_income_statement,
    get_indicator as get_alpha_vantage_indicator,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_stock as get_alpha_vantage_stock,
)
from .alpha_vantage_stock import get_adjusted_stock as get_alpha_vantage_adjusted_stock
from .bocha_news import (
    get_global_news_bocha,
    get_news_bocha,
)
from .china_capabilities import (
    get_a_share_interactive_answers,
    get_a_share_interactive_questions,
    get_cls_telegraph,
    search_a_share_iwencai,
)
from .china_capital_flow import (
    get_a_share_insider_trades,
    get_a_share_northbound_flow,
    get_a_share_northbound_holdings,
)
from .china_data import (
    get_balance_sheet_sina,
    get_balance_sheet_tushare,
    get_cashflow_sina,
    get_cashflow_tushare,
    get_fundamentals_akshare,
    get_fundamentals_tushare,
    get_income_statement_sina,
    get_income_statement_tushare,
    get_stock_akshare_qfq,
    get_stock_tushare,
    get_stock_tushare_qfq,
)
from .china_macro import get_china_macro_indicators
from .china_specialty import (
    get_a_share_cninfo_announcements,
    get_a_share_exchange_announcements,
    get_a_share_official_news,
)
from .china_specialty_em import (
    get_a_share_board_fund_flow,
    get_a_share_break_board_pool,
    get_a_share_bulk_trades_em,
    get_a_share_concept_blocks,
    get_a_share_daily_dragon_tiger,
    get_a_share_dragon_tiger_em,
    get_a_share_dragon_tiger_official,
    get_a_share_eps_forecast,
    get_a_share_industry_ranking,
    get_a_share_limit_down_pool,
    get_a_share_limit_up_ladder_em,
    get_a_share_lockup_releases_em,
    get_a_share_prev_limit_up_pool,
    get_a_share_price_anomaly_count_em,
    get_a_share_price_anomaly_em,
    get_a_share_research_reports,
    get_a_share_shareholder_counts_em,
    get_a_share_stock_monitor_em,
)
from .config import get_config
from .doubao_news import (
    get_global_news_doubao,
    get_news_doubao,
)
from .eastmoney import (
    get_a_share_capital_flow,
    get_a_share_capital_flow_sina,
    get_a_share_margin_financing,
)
from .eastmoney_news import get_news_eastmoney
from .fred import get_macro_data as get_fred_macro_data
from .index_provider import (
    get_index_history_eastmoney,
    get_index_snapshot_eastmoney,
)
from .mootdx_provider import get_a_share_f10, get_fundamentals_mootdx, get_stock_mootdx
from .option_provider import get_a_share_option_greeks, get_a_share_option_tquote
from .sentiment_provider import get_a_share_hot_concept, get_a_share_hot_list
from .tavily_news import (
    get_global_news_tavily,
    get_news_tavily,
)
from .tencent_provider import get_a_share_valuation
from .wind_provider import (
    get_equity_risk_metrics as get_wind_equity_risk_metrics,
    get_index_fundamentals as get_wind_index_fundamentals,
    get_index_history as get_wind_index_history,
    get_index_profile as get_wind_index_profile,
    get_index_snapshot as get_wind_index_snapshot,
    get_macro_series as get_wind_macro_series,
    get_stock_adjusted_price_history as get_wind_stock_adjusted_price_history,
    search_macro_series as search_wind_macro_series,
)

# Import from vendor-specific modules
from .y_finance import (
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_fundamentals as get_yfinance_fundamentals,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
    get_stock_stats_indicators_local,
    get_stock_stats_indicators_window,
    get_YFin_adjusted_data_online,
    get_YFin_data_online,
)
from .yfinance_news import get_global_news_yfinance, get_news_yfinance

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": ["get_stock_data", "get_adjusted_price_history"],
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": ["get_indicators"],
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"],
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ],
    },
    "macro_data": {
        "description": "Macroeconomic indicators (rates, inflation, labor, growth)",
        "tools": [
            "get_macro_indicators",
        ],
    },
    "a_share_market_data": {
        "description": "A-share supplemental capital-flow, northbound, insider, margin-financing, and announcements",
        "tools": [
            "get_a_share_capital_flow",
            "get_a_share_northbound_flow",
            "get_a_share_northbound_holdings",
            "get_a_share_insider_trades",
            "get_a_share_margin_financing",
            "get_a_share_exchange_announcements",
            "get_a_share_board_fund_flow",
        ],
    },
    "a_share_official_data": {
        "description": "A-share primary official disclosures via CNINFO and exchange fallback",
        "tools": ["get_a_share_cninfo_announcements"],
    },
    "a_share_company_data": {
        "description": "A-share mootdx quarterly finance snapshot and bounded F10 company sections",
        "tools": ["get_a_share_fundamentals_mootdx", "get_a_share_f10"],
    },
    "a_share_valuation": {
        "description": "A-share realtime valuation (PE/PB/market-cap/turnover/price-limits) via Tencent",
        "tools": ["get_a_share_valuation"],
    },
    "a_share_research": {
        "description": "A-share research reports and consensus EPS forecast",
        "tools": ["get_a_share_research_reports", "get_a_share_eps_forecast"],
    },
    "a_share_options": {
        "description": "A-share ETF option T-quotes and Greeks/IV",
        "tools": ["get_a_share_option_tquote", "get_a_share_option_greeks"],
    },
    "a_share_sentiment": {
        "description": "A-share market hot list and hot-concept hits",
        "tools": ["get_a_share_hot_list", "get_a_share_hot_concept"],
    },
    "china_macro_data": {
        "description": "Optional China macro and economic-cycle source series",
        "tools": ["get_china_macro_indicators"],
    },
    "wind_index_data": {
        "description": "Wind A-share index snapshot, history, profile, and fundamentals (PE/PB/yield)",
        "tools": [
            "get_index_snapshot",
            "get_index_history",
            "get_index_profile",
            "get_index_fundamentals",
        ],
    },
    "wind_macro_data": {
        "description": "Wind EDB macro/industry indicator search and time-series fetch",
        "tools": ["search_macro_series", "get_macro_series"],
    },
    "wind_risk_data": {
        "description": "Wind A-share equity risk metrics (Beta, volatility, drawdown, Sharpe)",
        "tools": ["get_equity_risk_metrics"],
    },
    "a_share_specialty_data": {
        "description": "A-share public specialty datasets (bulk trades, holders, lockups, dragon-tiger, limit-up, and Interactive Q&A)",
        "tools": [
            "get_a_share_bulk_trades",
            "get_a_share_shareholder_counts",
            "get_a_share_lockup_releases",
            "get_a_share_dragon_tiger",
            "get_a_share_limit_up_ladder",
            "get_a_share_daily_dragon_tiger",
            "get_a_share_industry_ranking",
            "get_a_share_board_fund_flow",
            "get_a_share_concept_blocks",
            "get_a_share_break_board_pool",
            "get_a_share_limit_down_pool",
            "get_a_share_prev_limit_up_pool",
            "get_a_share_interactive_questions",
            "get_a_share_interactive_answers",
            "get_a_share_stock_monitor",
            "get_a_share_price_anomaly",
            "get_a_share_price_anomaly_count",
        ],
    },
    "a_share_query_data": {
        "description": "Optional iWenCai natural-language query capability",
        "tools": ["search_a_share_iwencai"],
    },
    "a_share_v37_supplement": {
        "description": "a-stock-data v3.7.0 supplement endpoints: adjust factors, valuation history, listing dates, chip distribution, SW industry history, China macro (PBC/NBS)",
        "tools": [
            "get_a_share_adjust_factors",
            "get_a_share_valuation_history",
            "get_a_share_listing_history",
            "get_a_share_chip_distribution",
            "get_sw_industry_history",
            "get_china_social_financing",
            "get_china_pmi",
        ],
    },
    "a_share_telegraph": {
        "description": "CLS telegraph capability; unavailable unless a reviewed signer is configured",
        "tools": ["get_cls_telegraph"],
    },
}

VENDOR_LIST = [
    "mootdx",
    "tencent",
    "ths",
    "tushare",
    "akshare",
    "sina",
    "local",
    "tavily",
    "doubao",
    "bocha",
    "yfinance",
    "fred",
    "alpha_vantage",
    "eastmoney",
    "china_exchange",
    "cninfo",
    "iwencai",
    "cls",
    "wind",
    "baostock",
    "swsresearch",
    "pbc",
    "nbs",
]

# Vendor market capability matrix.
# Each vendor lists the markets it can serve. A-share-only vendors are skipped
# for non-A-share tickers; global-only vendors are skipped for A-share tickers.
# Vendors serving both markets are never skipped by the market filter. Adding a
# vendor only needs an entry here, not a new branch in _should_skip_vendor_for_symbol.
VENDOR_MARKETS: dict[str, frozenset[str]] = {
    "mootdx": frozenset({"a_share"}),
    "tencent": frozenset({"a_share"}),
    "ths": frozenset({"a_share"}),
    "tushare": frozenset({"a_share"}),
    "akshare": frozenset({"a_share"}),
    "eastmoney": frozenset({"a_share"}),
    "china_exchange": frozenset({"a_share"}),
    "cninfo": frozenset({"a_share"}),
    "iwencai": frozenset({"a_share"}),
    "cls": frozenset({"a_share"}),
    "wind": frozenset({"a_share"}),
    "sina": frozenset({"a_share"}),
    "local": frozenset({"a_share"}),
    "yfinance": frozenset({"global"}),
    "fred": frozenset({"global"}),
    # alpha_vantage has no A-share coverage (OHLCV/fundamentals/indicators all
    # return empty for Chinese tickers), so it is excluded from every A-share
    # chain. Keeping it global-only avoids one doomed HTTP call per A-share
    # request while preserving its non-A-share fallback role.
    "alpha_vantage": frozenset({"global"}),
    "tavily": frozenset({"a_share", "global"}),
    "doubao": frozenset({"a_share", "global"}),
    "bocha": frozenset({"a_share", "global"}),
    # a-stock-data v3.7.0 supplement sources are A-share only (baostock does
    # not serve BSE segments; the adapters degrade per-method for those).
    "baostock": frozenset({"a_share"}),
    "swsresearch": frozenset({"a_share"}),
    "pbc": frozenset({"a_share"}),
    "nbs": frozenset({"a_share"}),
}

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "mootdx": get_stock_mootdx,
        "tushare": get_stock_tushare,
        # akshare removed from the A-share OHLCV chain: mootdx (TCP 7709, no IP
        # ban) is the primary source and tushare is the stable fallback; akshare
        # only added import/install overhead on this path.
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    "get_adjusted_price_history": {
        # Wind explicitly requests daily forward-adjusted (qfq) bars. Raw
        # providers are intentionally excluded from this capability.
        "wind": get_wind_stock_adjusted_price_history,
        "tushare": get_stock_tushare_qfq,
        "akshare": get_stock_akshare_qfq,
        "yfinance": get_YFin_adjusted_data_online,
        "alpha_vantage": get_alpha_vantage_adjusted_stock,
    },
    # technical_indicators
    # ``local`` computes indicators locally from the A-share OHLCV chain
    # (mootdx -> tushare) via stockstats, giving A-shares a working indicator
    # source instead of the NO_DATA_AVAILABLE sentinel from alpha_vantage.
    "get_indicators": {
        "local": get_stock_stats_indicators_local,
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "tushare": get_fundamentals_tushare,
        "akshare": get_fundamentals_akshare,
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "tushare": get_balance_sheet_tushare,
        # Sina direct (quotes.sina.cn, zero key) replaces the akshare wrapper of
        # the same underlying source; see china_data._get_sina_statement_direct.
        "sina": get_balance_sheet_sina,
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "tushare": get_cashflow_tushare,
        "sina": get_cashflow_sina,
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "tushare": get_income_statement_tushare,
        "sina": get_income_statement_sina,
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "tavily": get_news_tavily,
        # Doubao Global search - ByteDance/Volcengine web search with strong
        # Chinese and English coverage.  Supports both A-share and global
        # tickers; no server-side date filter (client-side filtering applied).
        "doubao": get_news_doubao,
        # Bocha web search - domestic Chinese Bing-compatible search API.
        # Supports both A-share and global tickers with optional server-side
        # date filtering (freshness; defaults to noLimit per vendor guidance).
        "bocha": get_news_bocha,
        # Keyless domestic A-share company-news fallback (search-api-web).
        # yfinance/alpha_vantage are global-only and skipped for A-share tickers,
        # so this is the natural second source before exchange announcements.
        "eastmoney": get_news_eastmoney,
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        # A fallback-only adapter for public exchange announcements.  It is
        # appended only after ordinary news sources cannot return usable A
        # share news; see ``_news_official_fallback_vendors``.
        "china_exchange": get_a_share_official_news,
    },
    "get_global_news": {
        "tavily": get_global_news_tavily,
        "doubao": get_global_news_doubao,
        "bocha": get_global_news_bocha,
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # macro_data
    "get_macro_indicators": {
        "fred": get_fred_macro_data,
    },
    "get_china_macro_indicators": {
        "akshare": get_china_macro_indicators,
    },
    # a-stock-data v3.7.0 supplement endpoints (zero-key direct sources)
    "get_a_share_adjust_factors": {"sina": get_a_share_adjust_factors},
    "get_a_share_valuation_history": {"baostock": get_a_share_valuation_history},
    "get_a_share_listing_history": {"baostock": get_a_share_listing_history},
    "get_a_share_chip_distribution": {"baostock": get_a_share_chip_distribution},
    "get_sw_industry_history": {"swsresearch": get_sw_industry_history},
    "get_china_social_financing": {"pbc": get_china_social_financing},
    "get_china_pmi": {"nbs": get_china_pmi},
    # Optional, zero-key supplemental A-share capabilities.  They are kept
    # separate from OHLCV so a changed public endpoint cannot poison core
    # price/fundamental routing.
    "get_a_share_capital_flow": {
        "eastmoney": get_a_share_capital_flow,
        "sina": get_a_share_capital_flow_sina,
    },
    "get_a_share_northbound_flow": {"ths": get_a_share_northbound_flow},
    "get_a_share_northbound_holdings": {"eastmoney": get_a_share_northbound_holdings},
    "get_a_share_insider_trades": {"eastmoney": get_a_share_insider_trades},
    "get_a_share_margin_financing": {
        "eastmoney": get_a_share_margin_financing,
    },
    "get_a_share_exchange_announcements": {
        # This adapter itself uses the relevant official exchange first and
        # explicitly-labelled keyless public fallback second.
        "china_exchange": get_a_share_exchange_announcements,
    },
    "get_a_share_cninfo_announcements": {
        "cninfo": get_a_share_cninfo_announcements,
        "china_exchange": get_a_share_exchange_announcements,
    },
    # Public specialty datasets delivered by AKShare.  These are deliberately
    # separate from core market data because they are optional supplements.
    "get_a_share_bulk_trades": {"eastmoney": get_a_share_bulk_trades_em},
    "get_a_share_shareholder_counts": {"eastmoney": get_a_share_shareholder_counts_em},
    "get_a_share_lockup_releases": {"eastmoney": get_a_share_lockup_releases_em},
    "get_a_share_dragon_tiger": {"eastmoney": get_a_share_dragon_tiger_em},
    "get_a_share_limit_up_ladder": {"eastmoney": get_a_share_limit_up_ladder_em},
    "get_a_share_daily_dragon_tiger": {
        "eastmoney": get_a_share_daily_dragon_tiger,
        "china_exchange": get_a_share_dragon_tiger_official,
    },
    "get_a_share_break_board_pool": {"eastmoney": get_a_share_break_board_pool},
    "get_a_share_valuation": {"tencent": get_a_share_valuation},
    "get_a_share_fundamentals_mootdx": {"mootdx": get_fundamentals_mootdx},
    "get_a_share_f10": {"mootdx": get_a_share_f10},
    "get_a_share_research_reports": {"eastmoney": get_a_share_research_reports},
    "get_a_share_eps_forecast": {"ths": get_a_share_eps_forecast},
    "get_a_share_industry_ranking": {"eastmoney": get_a_share_industry_ranking},
    "get_a_share_board_fund_flow": {"eastmoney": get_a_share_board_fund_flow},
    "get_a_share_concept_blocks": {"eastmoney": get_a_share_concept_blocks},
    "get_a_share_option_tquote": {"sina": get_a_share_option_tquote},
    "get_a_share_option_greeks": {"sina": get_a_share_option_greeks},
    "get_a_share_hot_list": {"ths": get_a_share_hot_list},
    "get_a_share_hot_concept": {"eastmoney": get_a_share_hot_concept},
    "get_a_share_limit_down_pool": {"eastmoney": get_a_share_limit_down_pool},
    "get_a_share_prev_limit_up_pool": {"eastmoney": get_a_share_prev_limit_up_pool},
    "get_a_share_interactive_questions": {"akshare": get_a_share_interactive_questions},
    "get_a_share_interactive_answers": {"akshare": get_a_share_interactive_answers},
    "get_a_share_stock_monitor": {"eastmoney": get_a_share_stock_monitor_em},
    "get_a_share_price_anomaly": {"eastmoney": get_a_share_price_anomaly_em},
    "get_a_share_price_anomaly_count": {"eastmoney": get_a_share_price_anomaly_count_em},
    "search_a_share_iwencai": {"iwencai": search_a_share_iwencai},
    "get_cls_telegraph": {"cls": get_cls_telegraph},
    "get_index_snapshot": {
        "wind": get_wind_index_snapshot,
        "eastmoney": get_index_snapshot_eastmoney,
    },
    "get_index_history": {
        "wind": get_wind_index_history,
        "eastmoney": get_index_history_eastmoney,
    },
    "get_index_profile": {"wind": get_wind_index_profile},
    "get_index_fundamentals": {"wind": get_wind_index_fundamentals},
    "search_macro_series": {"wind": search_wind_macro_series},
    "get_macro_series": {"wind": get_wind_macro_series},
    "get_equity_risk_metrics": {"wind": get_wind_equity_risk_metrics},
}




logger = logging.getLogger("tradingagents.dataflows.registry")


def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")


def registry_consistency_problems() -> list[str]:
    """Return structural inconsistencies in the static registry.

    An empty list means the registry is internally consistent. New vendors or
    tools must keep the registry green so category lookup and fallback routing
    cannot silently break.
    """
    problems: list[str] = []
    known_vendors = set(VENDOR_LIST)
    for method, vendors in VENDOR_METHODS.items():
        category = None
        for info in TOOLS_CATEGORIES.values():
            if method in info["tools"]:
                category = True
                break
        if category is None:
            problems.append(f"method {method!r} is not listed in any TOOLS_CATEGORIES")
        for vendor in vendors:
            if vendor not in known_vendors:
                problems.append(f"method {method!r} references unknown vendor {vendor!r}")
    for category, info in TOOLS_CATEGORIES.items():
        for method in info["tools"]:
            if method not in VENDOR_METHODS:
                problems.append(
                    f"category {category!r} lists method {method!r} with no VENDOR_METHODS entry"
                )
    return problems


def validate_data_vendors(config: dict) -> list[str]:
    """Return vendor-config problems; [] means the vendor config is usable.

    Checks that every ``data_vendors`` / ``tool_vendors`` value names only
    known vendors and that every tool-level override targets a known method.
    """
    problems: list[str] = []
    known = set(VENDOR_LIST)
    for category, value in (config.get("data_vendors") or {}).items():
        if not isinstance(value, str):
            problems.append(f"data_vendors.{category} must be a comma-separated string")
            continue
        for vendor in (v.strip() for v in value.split(",") if v.strip()):
            if vendor not in known:
                problems.append(f"data_vendors.{category} references unknown vendor {vendor!r}")
    for method, value in (config.get("tool_vendors") or {}).items():
        if method not in VENDOR_METHODS:
            problems.append(f"tool_vendors references unknown method {method!r}")
        if not isinstance(value, str):
            problems.append(f"tool_vendors.{method} must be a comma-separated string")
            continue
        for vendor in (v.strip() for v in value.split(",") if v.strip()):
            if vendor not in known:
                problems.append(f"tool_vendors.{method} references unknown vendor {vendor!r}")
    return problems
