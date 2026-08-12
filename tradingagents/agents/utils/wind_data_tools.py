"""Agent tools for Wind-backed index, macro EDB, and equity risk data.

These tools expose source-neutral capabilities backed by Wind AIFin Market.
Wind must be enabled via the ``wind_enabled`` config flag and WIND_API_KEY.
When disabled, the tools return an unavailable message through the standard
vendor-error path without affecting core A-share data.
"""

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_index_snapshot(
    index: Annotated[
        str,
        "Index code or name, e.g. '000300.SH' (CSI 300), '000001.SH' (SSE Composite), "
        "'399006.SZ' (ChiNext), or Chinese name like '沪深300'.",
    ],
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve the latest trading-day snapshot for a Chinese market index:
    latest level, open/high/low, previous close, and volume.

    Use this when the user asks about index levels, market-wide performance,
    or benchmark quotes (CSI 300, SSE Composite, CSI 500, etc.).

    Args:
        index (str): Index code (e.g. '000300.SH') or Chinese name (e.g. '沪深300')
        curr_date (str): Analysis date in yyyy-mm-dd format

    Returns:
        str: CSV-formatted index snapshot with source and coverage metadata
    """
    return route_to_vendor("get_index_snapshot", index, curr_date)


@tool
def get_index_history(
    index: Annotated[
        str,
        "Index code or name, e.g. '000300.SH', '沪深300'.",
    ],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    period: Annotated[
        str,
        "K-line period: '1d' (daily, default), '1w' (weekly), '1mo' (monthly), "
        "'1min'/'5min'/'15min'/'30min'/'60min' (intraday).",
    ] = "1d",
) -> str:
    """
    Retrieve historical OHLCV bars for a Chinese market index over a date range.

    Use this for index trend analysis, backtesting context, or regime assessment.
    Daily bars are the default; use intraday periods only when specifically needed.

    Args:
        index (str): Index code or name
        start_date (str): Start date yyyy-mm-dd
        end_date (str): End date yyyy-mm-dd
        period (str): Bar period (default '1d')

    Returns:
        str: CSV-formatted OHLCV bars with source and coverage metadata
    """
    return route_to_vendor("get_index_history", index, start_date, end_date, period)


@tool
def get_index_profile(
    index: Annotated[str, "Index code or name, e.g. '000300.SH', '沪深300'."],
) -> str:
    """
    Retrieve static profile information for a Chinese market index:
    full name, publisher, base date, and constituent count.

    Use this when the user asks about index composition, methodology, or basic facts.

    Args:
        index (str): Index code or name

    Returns:
        str: CSV-formatted index profile
    """
    return route_to_vendor("get_index_profile", index)


@tool
def get_index_fundamentals(
    index: Annotated[str, "Index code or name, e.g. '000300.SH', '沪深300'."],
    curr_date: Annotated[str, "Analysis date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve valuation fundamentals for a Chinese market index:
    weighted PE, PB, and dividend yield.

    Use this for market valuation assessment, historical percentile context,
    or comparing index valuations across benchmarks.

    Args:
        index (str): Index code or name
        curr_date (str): Analysis date in yyyy-mm-dd format

    Returns:
        str: CSV-formatted valuation metrics with source and coverage metadata
    """
    return route_to_vendor("get_index_fundamentals", index, curr_date)


@tool
def search_macro_series(
    query: Annotated[
        str,
        "Natural-language description of the macro/industry indicator, "
        "e.g. '中国GDP', '中国CPI', '社会融资规模', '新能源汽车销量'.",
    ],
) -> str:
    """
    Search Wind EDB (Economic Database) for macro or industry indicators
    matching a natural-language query. Returns candidate indicator codes,
    names, frequency, units, and source.

    Use this to discover the correct EDB indicator code before fetching
    time-series data with get_macro_series. Review returned codes before
    using them in production analysis.

    Args:
        query (str): Natural-language indicator description

    Returns:
        str: CSV of matching EDB indicators with codes and metadata
    """
    return route_to_vendor("search_macro_series", query)


@tool
def get_macro_series(
    series_ids: Annotated[
        str,
        "Comma-separated EDB indicator codes, e.g. 'M0001395' (China GDP annual). "
        "Use search_macro_series first to discover valid codes.",
    ],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Fetch time-series data for one or more Wind EDB macro/industry indicators.

    Use audited EDB codes (from search_macro_series or the built-in allowlist).
    Returns long-format CSV with code, name, date, value, unit, frequency, source.

    Args:
        series_ids (str): Comma-separated EDB codes
        start_date (str): Start date yyyy-mm-dd
        end_date (str): End date yyyy-mm-dd

    Returns:
        str: CSV of observations with source and coverage metadata
    """
    return route_to_vendor("get_macro_series", series_ids, start_date, end_date)


@tool
def get_equity_risk_metrics(
    symbol: Annotated[
        str,
        "A-share stock symbol, e.g. '600519.SS' (Kweichow Moutai), '300750.SZ' (CATL).",
    ],
    window: Annotated[
        str,
        "Lookback window in human-readable form: '1y' (1 year, default), "
        "'6m' (6 months), '3m', '3y', etc.",
    ] = "1y",
    fields: Annotated[
        str | None,
        "Comma-separated risk metrics to retrieve, e.g. 'Beta,年化波动率,最大回撤,夏普比率'. "
        "Defaults to Beta, annualised volatility, max drawdown, Sharpe ratio.",
    ] = None,
    benchmark: Annotated[
        str | None,
        "Benchmark index for Beta calculation, e.g. '000300.SH'. "
        "If omitted, Wind uses its default benchmark.",
    ] = None,
) -> str:
    """
    Retrieve quantitative risk metrics for an A-share stock: Beta, annualised
    volatility, maximum drawdown, Sharpe ratio, and related measures.

    Use this when the user asks about stock risk, volatility, Beta against
    a benchmark, drawdown, or risk-adjusted return metrics.

    Args:
        symbol (str): A-share stock symbol (e.g. '600519.SS')
        window (str): Lookback window (default '1y')
        fields (str): Comma-separated metric names; None for defaults
        benchmark (str): Benchmark index code for Beta; None for Wind default

    Returns:
        str: CSV-formatted risk metrics with source and coverage metadata
    """
    return route_to_vendor("get_equity_risk_metrics", symbol, window, fields, benchmark)
