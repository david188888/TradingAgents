"""China A-share data providers backed by optional Tushare and AKShare SDKs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import requests

from tradingagents.dataflows.coverage import CoveredText, PriceSeriesCoverageV1

from .config import get_config
from .ticker_utils import (
    infer_a_share_exchange,
    is_a_share_ticker,
    to_akshare_prefixed_symbol,
    to_akshare_symbol,
    to_tushare_symbol,
)


class ChinaDataUnavailableError(Exception):
    """Raised when an optional China-market data source cannot provide data."""


def get_stock_tushare(symbol: str, start_date: str, end_date: str) -> str:
    """Retrieve A-share OHLCV data from Tushare daily quotes."""
    pro = _get_tushare_pro()
    ts_code = _require_a_share_tushare_symbol(symbol)
    try:
        df = pro.daily(
            ts_code=ts_code,
            start_date=_date_to_api(start_date),
            end_date=_date_to_api(end_date),
        )
    except Exception as exc:
        raise ChinaDataUnavailableError(f"Tushare daily request failed for {ts_code}: {exc}") from exc
    _save_raw_data(symbol, end_date, "tushare_get_stock", df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(f"Tushare returned no daily data for {ts_code}.")
    formatted = _format_tushare_daily(df)
    return _format_dataframe_report(
        formatted,
        title=f"China A-share stock data for {ts_code} from {start_date} to {end_date}",
        source="tushare",
    )


def get_stock_tushare_qfq_df(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Retrieve explicitly forward-adjusted A-share OHLCV from Tushare."""
    ts = _get_tushare_module()
    ts_code = _require_a_share_tushare_symbol(symbol)
    try:
        df = ts.pro_bar(
            ts_code=ts_code,
            start_date=_date_to_api(start_date),
            end_date=_date_to_api(end_date),
            adj="qfq",
            freq="D",
        )
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"Tushare qfq daily request failed for {ts_code}: {exc}"
        ) from exc
    _save_raw_data(symbol, end_date, "tushare_get_stock_qfq", df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(
            f"Tushare returned no qfq daily data for {ts_code}."
        )
    return _format_tushare_daily(df)


def get_stock_tushare_qfq(symbol: str, start_date: str, end_date: str) -> str:
    """Legacy-compatible text carrying typed qfq price coverage."""
    df = get_stock_tushare_qfq_df(symbol, start_date, end_date)
    return _render_adjusted_price_history(
        df,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        source="tushare",
        source_id="tushare.qfq_daily",
        price_basis="qfq",
        adjustment_source="tushare.pro_bar(adj=qfq)",
    )


def get_stock_akshare(symbol: str, start_date: str, end_date: str) -> str:
    """Retrieve A-share OHLCV data from AKShare historical quotes."""
    ak = _import_optional("akshare", "pip install akshare")
    ak_symbol = _require_a_share_akshare_symbol(symbol)
    try:
        df = ak.stock_zh_a_hist(
            symbol=ak_symbol,
            period="daily",
            start_date=_date_to_api(start_date),
            end_date=_date_to_api(end_date),
            adjust=get_config().get("akshare_adjust", ""),
        )
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"AKShare historical request failed for {ak_symbol}: {exc}"
        ) from exc
    _save_raw_data(symbol, end_date, "akshare_get_stock", df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(f"AKShare returned no historical data for {ak_symbol}.")
    formatted = _format_akshare_daily(df)
    return _format_dataframe_report(
        formatted,
        title=f"China A-share stock data for {ak_symbol} from {start_date} to {end_date}",
        source="akshare",
    )


def get_stock_akshare_qfq_df(
    symbol: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Retrieve A-share OHLCV with an explicit qfq request to AKShare."""
    ak = _import_optional("akshare", "pip install akshare")
    ak_symbol = _require_a_share_akshare_symbol(symbol)
    try:
        df = ak.stock_zh_a_hist(
            symbol=ak_symbol,
            period="daily",
            start_date=_date_to_api(start_date),
            end_date=_date_to_api(end_date),
            adjust="qfq",
        )
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"AKShare qfq historical request failed for {ak_symbol}: {exc}"
        ) from exc
    _save_raw_data(symbol, end_date, "akshare_get_stock_qfq", df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(
            f"AKShare returned no qfq historical data for {ak_symbol}."
        )
    return _format_akshare_daily(df)


def get_stock_akshare_qfq(symbol: str, start_date: str, end_date: str) -> str:
    """Legacy-compatible text carrying typed qfq price coverage."""
    df = get_stock_akshare_qfq_df(symbol, start_date, end_date)
    return _render_adjusted_price_history(
        df,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        source="akshare",
        source_id="akshare.qfq_daily",
        price_basis="qfq",
        adjustment_source="akshare.stock_zh_a_hist(adjust=qfq)",
    )


def get_stock_tushare_df(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """A-share OHLCV as a DataFrame (Date/Open/High/Low/Close/Volume/...).

    Same as ``get_stock_tushare`` but returns the formatted DataFrame instead
    of a markdown report, for callers (the ``load_ohlcv`` vendor path) that
    need raw rows rather than a rendered string.
    """
    pro = _get_tushare_pro()
    ts_code = _require_a_share_tushare_symbol(symbol)
    try:
        df = pro.daily(
            ts_code=ts_code,
            start_date=_date_to_api(start_date),
            end_date=_date_to_api(end_date),
        )
    except Exception as exc:
        raise ChinaDataUnavailableError(f"Tushare daily request failed for {ts_code}: {exc}") from exc
    _save_raw_data(symbol, end_date, "tushare_get_stock", df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(f"Tushare returned no daily data for {ts_code}.")
    return _format_tushare_daily(df)


def get_stock_akshare_df(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """A-share OHLCV as a DataFrame from AKShare (fallback for the vendor path)."""
    ak = _import_optional("akshare", "pip install akshare")
    ak_symbol = _require_a_share_akshare_symbol(symbol)
    try:
        df = ak.stock_zh_a_hist(
            symbol=ak_symbol,
            period="daily",
            start_date=_date_to_api(start_date),
            end_date=_date_to_api(end_date),
            adjust=get_config().get("akshare_adjust", ""),
        )
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"AKShare historical request failed for {ak_symbol}: {exc}"
        ) from exc
    _save_raw_data(symbol, end_date, "akshare_get_stock", df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(f"AKShare returned no historical data for {ak_symbol}.")
    return _format_akshare_daily(df)


def get_fundamentals_tushare(ticker: str, curr_date: str = None) -> str:
    """Retrieve a compact A-share fundamentals snapshot from Tushare."""
    pro = _get_tushare_pro()
    ts_code = _require_a_share_tushare_symbol(ticker)
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    end_date = _date_to_api(curr_date)
    start_date = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y%m%d")

    sections = []
    stock_basic = _safe_tushare_call(lambda: pro.stock_basic(ts_code=ts_code))
    daily_basic = _safe_tushare_call(
        lambda: pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
    )
    fina_indicator = _safe_tushare_call(
        lambda: pro.fina_indicator(ts_code=ts_code, start_date=start_date, end_date=end_date)
    )

    _save_raw_data(
        ticker,
        curr_date,
        "tushare_get_fundamentals",
        {
            "stock_basic": _df_to_records(stock_basic),
            "daily_basic": _df_to_records(daily_basic),
            "fina_indicator": _df_to_records(fina_indicator),
        },
    )

    if stock_basic is not None and not stock_basic.empty:
        sections.append(_dataframe_head_markdown("Stock Basic", stock_basic))
    if daily_basic is not None and not daily_basic.empty:
        if "trade_date" in daily_basic.columns:
            daily_basic = daily_basic.sort_values("trade_date", ascending=False)
        sections.append(_dataframe_head_markdown("Daily Basic", daily_basic))
    if fina_indicator is not None and not fina_indicator.empty:
        if "end_date" in fina_indicator.columns:
            fina_indicator = fina_indicator.sort_values("end_date", ascending=False)
        sections.append(_dataframe_head_markdown("Financial Indicators", fina_indicator))

    if not sections:
        raise ChinaDataUnavailableError(f"Tushare returned no fundamentals data for {ts_code}.")

    return "\n\n".join(
        [
            f"# China A-share fundamentals for {ts_code}",
            "# Source: tushare",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            *sections,
        ]
    )


def get_fundamentals_akshare(ticker: str, curr_date: str = None) -> str:
    """Retrieve a compact A-share fundamentals snapshot from AKShare."""
    ak = _import_optional("akshare", "pip install akshare")
    ak_symbol = _require_a_share_akshare_symbol(ticker)
    sections = []

    # Sina-based financial abstract is the primary source: EastMoney's
    # stock_individual_info_em / stock_zh_a_spot_em are frequently blocked
    # by anti-crawler measures (akfamily/akshare issues #7101, #7103, #6148),
    # while Sina endpoints remain stable for A-share financials.
    financial_abstract = _safe_call(
        lambda: ak.stock_financial_abstract(symbol=ak_symbol)
    )
    individual_info = _safe_call(lambda: ak.stock_individual_info_em(symbol=ak_symbol))

    _save_raw_data(
        ticker,
        curr_date or datetime.now().strftime("%Y-%m-%d"),
        "akshare_get_fundamentals",
        {
            "stock_financial_abstract": _df_to_records(financial_abstract),
            "stock_individual_info_em": _df_to_records(individual_info),
        },
    )

    if isinstance(financial_abstract, pd.DataFrame) and not financial_abstract.empty:
        financial_abstract = _filter_statement_as_of(
            financial_abstract,
            curr_date or datetime.now().strftime("%Y-%m-%d"),
        )
        sections.append(_dataframe_head_markdown("Financial Abstract (Sina)", financial_abstract))
    if isinstance(individual_info, pd.DataFrame) and not individual_info.empty:
        sections.append(_dataframe_head_markdown("Individual Info", individual_info))

    if not sections:
        raise ChinaDataUnavailableError(f"AKShare returned no fundamentals data for {ak_symbol}.")

    return "\n\n".join(
        [
            f"# China A-share fundamentals for {ak_symbol}",
            "# Source: akshare",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            *sections,
        ]
    )


def get_balance_sheet_tushare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _get_tushare_statement(
        ticker,
        curr_date,
        method_name="balancesheet",
        title="Balance Sheet",
        raw_method="tushare_get_balance_sheet",
    )


def get_cashflow_tushare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _get_tushare_statement(
        ticker,
        curr_date,
        method_name="cashflow",
        title="Cash Flow",
        raw_method="tushare_get_cashflow",
    )


def get_income_statement_tushare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _get_tushare_statement(
        ticker,
        curr_date,
        method_name="income",
        title="Income Statement",
        raw_method="tushare_get_income_statement",
    )


def _get_tushare_statement(
    ticker: str,
    curr_date: str | None,
    *,
    method_name: str,
    title: str,
    raw_method: str,
) -> str:
    pro = _get_tushare_pro()
    ts_code = _require_a_share_tushare_symbol(ticker)
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    end_date = _date_to_api(curr_date)
    start_date = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=365 * 5)).strftime("%Y%m%d")
    method = getattr(pro, method_name)
    try:
        df = method(ts_code=ts_code, start_date=start_date, end_date=end_date)
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"Tushare {method_name} request failed for {ts_code}: {exc}"
        ) from exc
    _save_raw_data(ticker, curr_date, raw_method, df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(f"Tushare returned no {title.lower()} data for {ts_code}.")
    if "end_date" in df.columns:
        df = df.sort_values("end_date", ascending=False)
    return _format_dataframe_report(
        df,
        title=f"China A-share {title} data for {ts_code}",
        source="tushare",
        monetary_unit="CNY",
        monetary_scale=100_000_000,
        as_of=curr_date,
    )


def _get_akshare_statement_sina(
    ticker: str,
    curr_date: str | None,
    *,
    report_type: str,
    title: str,
    raw_method: str,
) -> str:
    """Retrieve a single financial statement from Sina via AKShare.

    Sina endpoints are the preferred A-share fallback when EastMoney-based
    akshare calls are blocked by anti-crawler measures and tushare is
    rate-limited (akfamily/akshare issues #7101, #7103, #6148).
    """
    ak = _import_optional("akshare", "pip install akshare")
    sina_symbol = to_akshare_prefixed_symbol(ticker).lower()
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    try:
        df = ak.stock_financial_report_sina(stock=sina_symbol, symbol=report_type)
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"AKShare Sina {title} request failed for {sina_symbol}: {exc}"
        ) from exc
    _save_raw_data(ticker, curr_date, raw_method, df)
    if df is None or df.empty:
        raise ChinaDataUnavailableError(
            f"AKShare Sina returned no {title.lower()} data for {sina_symbol}."
        )
    df = _filter_statement_as_of(df, curr_date)
    if df.empty:
        raise ChinaDataUnavailableError(
            f"AKShare Sina returned no {title.lower()} data on or before {curr_date}."
        )
    if "报告日" in df.columns:
        df = df.sort_values("报告日", ascending=False)
    return _format_dataframe_report(
        df,
        title=f"China A-share {title} for {sina_symbol}",
        source="akshare (sina)",
        monetary_unit="CNY",
        monetary_scale=100_000_000,
        as_of=curr_date,
    )


def get_balance_sheet_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _get_akshare_statement_sina(
        ticker,
        curr_date,
        report_type="资产负债表",
        title="Balance Sheet",
        raw_method="akshare_get_balance_sheet",
    )


def get_cashflow_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _get_akshare_statement_sina(
        ticker,
        curr_date,
        report_type="现金流量表",
        title="Cash Flow",
        raw_method="akshare_get_cashflow",
    )


def get_income_statement_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _get_akshare_statement_sina(
        ticker,
        curr_date,
        report_type="利润表",
        title="Income Statement",
        raw_method="akshare_get_income_statement",
    )


# ---------------------------------------------------------------------------
# Sina direct financial statements (quotes.sina.cn, zero key)
# ---------------------------------------------------------------------------
# Aligned with a-stock-data SKILL.md §6.4: the same Sina source that the old
# akshare ``stock_financial_report_sina`` wrapper called, but requested directly
# over HTTP so the SDK failure plane (akfamily/akshare issues #7101/#7103/#6148)
# is removed. The response structure is ``result.data.report_list`` keyed by
# reporting period; each period's ``data`` is the list of line items.

_SINA_STATEMENT_REPORT_TYPES = {
    "fzb": ("资产负债表", "Balance Sheet"),
    "lrb": ("利润表", "Income Statement"),
    "llb": ("现金流量表", "Cash Flow"),
}


def _sina_statement_prefix(ticker: str) -> str:
    """Pick the exchange prefix Sina's financial report endpoint expects.

    Derived from the normalized exchange (SH/SZ/BJ), mirroring a-stock-data
    ``get_prefix``: SH ETFs (5xx), SH B-shares (900x) and SH mainboard (6xx)
    route to ``sh``, BSE 92/8/4 segments to ``bj``, everything else to ``sz``.
    """
    code = to_akshare_symbol(ticker)
    exchange = infer_a_share_exchange(code)
    return "sh" if exchange == "SH" else "bj" if exchange == "BJ" else "sz"


def _get_sina_statement_direct(
    ticker: str,
    curr_date: str | None,
    *,
    report_type: str,
    title: str,
    raw_method: str,
) -> str:
    """Retrieve one financial statement directly from Sina (zero key).

    Replaces the akshare ``stock_financial_report_sina`` wrapper with a direct
    HTTP call to ``quotes.sina.cn`` so the SDK dependency is removed from the
    statement chain while keeping the same underlying data source.
    """
    code = to_akshare_symbol(ticker)
    if not is_a_share_ticker(ticker):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    paper_code = f"{_sina_statement_prefix(ticker)}{code}"
    curr_date = curr_date or datetime.now().strftime("%Y-%m-%d")
    url = (
        "https://quotes.sina.cn/cn/api/openapi.php/"
        "CompanyFinanceService.getFinanceReport2022"
    )
    params = {
        "paperCode": paper_code,
        "source": report_type,
        "type": "0",
        "page": "1",
        "num": "8",
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - degrade to next vendor
        raise ChinaDataUnavailableError(
            f"Sina {title} request failed for {paper_code}: {exc}"
        ) from exc
    report_list = (
        ((payload.get("result") or {}).get("data") or {}).get("report_list") or {}
    )
    if not report_list:
        raise ChinaDataUnavailableError(
            f"Sina returned no {title.lower()} data for {paper_code}."
        )
    rows = []
    for period in sorted(report_list.keys(), reverse=True):
        period_obj = report_list[period]
        rec = {
            "报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"
        }
        for item in period_obj.get("data", []) or []:
            item_title = item.get("item_title")
            if not item_title or item.get("item_value") is None:
                continue
            rec[item_title] = item.get("item_value")
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        raise ChinaDataUnavailableError(
            f"Sina returned no {title.lower()} data for {paper_code}."
        )
    _save_raw_data(ticker, curr_date, raw_method, df)
    df = _filter_statement_as_of(df, curr_date)
    if df.empty:
        raise ChinaDataUnavailableError(
            f"Sina returned no {title.lower()} data on or before {curr_date}."
        )
    if "报告期" in df.columns:
        df = df.sort_values("报告期", ascending=False)
    return _format_dataframe_report(
        df,
        title=f"China A-share {title} for {paper_code}",
        source="sina direct",
        monetary_unit="CNY",
        monetary_scale=100_000_000,
        as_of=curr_date,
    )


def get_balance_sheet_sina(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    """A-share balance sheet via Sina direct (zero key)."""
    return _get_sina_statement_direct(
        ticker,
        curr_date,
        report_type="fzb",
        title="Balance Sheet",
        raw_method="sina_get_balance_sheet",
    )


def get_cashflow_sina(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    """A-share cash flow statement via Sina direct (zero key)."""
    return _get_sina_statement_direct(
        ticker,
        curr_date,
        report_type="llb",
        title="Cash Flow",
        raw_method="sina_get_cashflow",
    )


def get_income_statement_sina(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    """A-share income statement via Sina direct (zero key)."""
    return _get_sina_statement_direct(
        ticker,
        curr_date,
        report_type="lrb",
        title="Income Statement",
        raw_method="sina_get_income_statement",
    )


def _filter_statement_as_of(df: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Remove reports published after the analysis cutoff date.

    Sina has used both ``报告日`` and ``公告日期`` across statement endpoints;
    when neither exists we retain the raw table rather than inventing a date.
    """
    date_column = next(
        (column for column in ("报告日", "公告日期", "报告期") if column in df.columns),
        None,
    )
    if date_column is None:
        return df
    cutoff = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(cutoff):
        raise ChinaDataUnavailableError(f"invalid financial cutoff date: {curr_date}")
    dates = pd.to_datetime(df[date_column], errors="coerce")
    return df.loc[dates.isna() | (dates <= cutoff)].copy()


def _get_tushare_pro():
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API_KEY")
    if not token:
        raise ChinaDataUnavailableError(
            "TUSHARE_TOKEN or TUSHARE_API_KEY environment variable is not set."
        )
    ts = _import_optional("tushare", "pip install tushare")
    return ts.pro_api(token)


def _get_tushare_module():
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API_KEY")
    if not token:
        raise ChinaDataUnavailableError(
            "TUSHARE_TOKEN or TUSHARE_API_KEY environment variable is not set."
        )
    ts = _import_optional("tushare", "pip install tushare")
    ts.set_token(token)
    return ts


def _import_optional(module_name: str, install_hint: str):
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise ChinaDataUnavailableError(
            f"Optional dependency '{module_name}' is not installed. Install with `{install_hint}`."
        ) from exc


def _require_a_share_tushare_symbol(ticker: str) -> str:
    symbol = to_tushare_symbol(ticker)
    if not is_a_share_ticker(symbol):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return symbol


def _require_a_share_akshare_symbol(ticker: str) -> str:
    if not is_a_share_ticker(ticker):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return to_akshare_symbol(ticker)


def _format_tushare_daily(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "trade_date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "pre_close": "Pre Close",
            "change": "Change",
            "pct_chg": "Pct Change",
            "vol": "Volume",
            "amount": "Amount",
        }
    ).copy()
    if "Date" in renamed.columns:
        renamed["Date"] = pd.to_datetime(renamed["Date"], format="%Y%m%d", errors="coerce")
        renamed = renamed.sort_values("Date")
        renamed["Date"] = renamed["Date"].dt.strftime("%Y-%m-%d")
    return renamed


def _format_akshare_daily(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "日期": "Date",
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
            "成交额": "Amount",
            "振幅": "Amplitude",
            "涨跌幅": "Pct Change",
            "涨跌额": "Change",
            "换手率": "Turnover",
        }
    ).copy()
    if "Date" in renamed.columns:
        renamed["Date"] = pd.to_datetime(renamed["Date"], errors="coerce")
        renamed = renamed.sort_values("Date")
        renamed["Date"] = renamed["Date"].dt.strftime("%Y-%m-%d")
    return renamed


def _format_dataframe_report(
    df: pd.DataFrame,
    *,
    title: str,
    source: str,
    monetary_unit: str | None = None,
    monetary_scale: int | None = None,
    as_of: str | None = None,
) -> str:
    if df is None or df.empty:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")
    if len({str(column) for column in df.columns}) != len(df.columns):
        raise ChinaDataUnavailableError(f"{source} returned duplicate columns for {title}.")
    clean = df.copy()
    for col in clean.select_dtypes(include=["float", "float64"]).columns:
        clean[col] = clean[col].round(4)
    headers = [
        f"# {title}",
        f"# Source: {source}",
        f"# Total records: {len(clean)}",
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if as_of:
        headers.append(f"# Analysis cutoff: {as_of}")
    if monetary_unit and monetary_scale:
        headers.extend([
            f"# Monetary raw unit: {monetary_unit}",
            f"# Monetary display scale: {monetary_unit}_{monetary_scale}",
            f"# Monetary normalization formula: raw_value / {monetary_scale}",
            "# Raw CSV values are preserved; do not infer a different scale.",
        ])
    return "\n".join([*headers, "", clean.to_csv(index=False)])


def _render_adjusted_price_history(
    df: pd.DataFrame,
    *,
    symbol: str,
    start_date: str,
    end_date: str,
    source: str,
    source_id: str,
    price_basis: Literal["qfq", "split_dividend_adjusted"],
    adjustment_source: str,
) -> CoveredText:
    clean = df.copy()
    dates = pd.to_datetime(clean.get("Date"), errors="coerce")
    clean = clean.loc[dates.notna()].copy()
    clean["Date"] = dates.loc[dates.notna()].dt.strftime("%Y-%m-%d")
    clean = clean[
        (clean["Date"] >= start_date) & (clean["Date"] <= end_date)
    ].sort_values("Date")
    if clean.empty:
        raise ChinaDataUnavailableError(
            f"{source} returned no adjusted rows inside {start_date}..{end_date}."
        )
    actual_start = str(clean["Date"].iloc[0])
    actual_end = str(clean["Date"].iloc[-1])
    exact_boundaries = actual_start == start_date and actual_end == end_date
    coverage = PriceSeriesCoverageV1(
        capability="adjusted_price_history",
        source_id=source_id,
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=len(clean),
        completeness="complete" if exact_boundaries else "unknown",
        sources=(source_id,),
        degradations=(
            () if exact_boundaries else ("trading_calendar_boundaries_not_proven",)
        ),
        as_of=end_date,
        price_basis=price_basis,
        adjustment_source=adjustment_source,
        adjustment_verified=True,
        granularity="daily",
    )
    report = _format_dataframe_report(
        clean,
        title=f"Adjusted stock data for {symbol} from {start_date} to {end_date}",
        source=source,
        as_of=end_date,
    )
    rendered = "\n".join(
        [
            f"# Price basis: {price_basis}",
            f"# Adjustment source: {adjustment_source}",
            "# This series is for historical returns, trend, and indicators; "
            "do not use it as an executable current-price quote.",
            report,
        ]
    )
    return CoveredText(rendered, coverage)


def _date_to_api(date_value: str) -> str:
    return datetime.strptime(date_value, "%Y-%m-%d").strftime("%Y%m%d")


def _safe_tushare_call(func: Callable[[], pd.DataFrame]) -> pd.DataFrame | None:
    try:
        return func()
    except Exception:
        return None


def _safe_call(func: Callable[[], Any]) -> Any:
    try:
        return func()
    except Exception:
        return None


def _dataframe_head_markdown(title: str, df: pd.DataFrame, rows: int = 8) -> str:
    return f"## {title}\n\n```csv\n{df.head(rows).to_csv(index=False).strip()}\n```"


def _df_to_records(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    return value


def _save_raw_data(
    ticker: str,
    log_date: str,
    method: str,
    data: Any,
) -> None:
    _capture_vendor_raw(
        _df_to_records(data),
        metadata={
            "provider": "tushare" if method.startswith("tushare") else "akshare",
            "dataset": method,
            "ticker": ticker,
            "as_of": log_date,
        },
    )
    cfg = get_config()
    results_dir = cfg.get("results_dir")
    if not results_dir:
        return
    safe_ticker = str(ticker).replace("/", "_")
    data_dir = Path(results_dir) / safe_ticker / str(log_date) / "data"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = data_dir / f"{method}_{timestamp}.json"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_df_to_records(data), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        return


def _capture_vendor_raw(data: Any, *, metadata: dict[str, Any]) -> None:
    """Load observability only after a provider call succeeds.

    Agent tools import the data router during application startup.  Keeping
    this cross-cutting import lazy prevents a direct China-data import from
    recursively importing that router before this module has defined its typed
    error class.
    """
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(data, metadata=metadata)
