"""EastMoney direct-HTTP A-share specialty data adapters.

Replaces the former akshare-wrapped specialty layer (dragon-tiger, lockups,
block trades, shareholder counts, limit-up pool) with direct EastMoney
datacenter/push2ex calls.  akshare wrapped the same EastMoney endpoints;
talking to them directly removes the SDK failure layer (akfamily/akshare
issues #7101, #7103, #6148) and matches a-stock-data SKILL.md §3/§8.

Each adapter returns a source-labelled markdown report or raises
``ChinaDataUnavailableError``; it never fabricates rows when EastMoney changes
a schema or throttles the IP.  The dragon-tiger board additionally carries an
official exchange backup (``get_a_share_dragon_tiger_official``) on an
independent rate-limit plane, for when EastMoney bans the IP.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .coverage import CoveredText, SourceCoverageV1
from .eastmoney import (
    EASTMONEY_DATACENTER_URL,
    _extract_records,
    em_get,
    em_get_json,
)
from .ticker_utils import (
    is_a_share_ticker,
    normalize_ticker_symbol,
    strict_ticker_code,
    to_akshare_symbol,
)

_EASTMONEY_QUOTE_REFERER = "https://quote.eastmoney.com/"
_ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"
_ZTB_URL = "https://push2ex.eastmoney.com/"
_REPORT_API_URL = "https://reportapi.eastmoney.com/report/list"
_INDUSTRY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_SLIST_URL = "https://push2.eastmoney.com/api/qt/slist/get"


def _eastmoney_datacenter(
    report_name: str,
    *,
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
    columns: str = "ALL",
) -> list[dict[str, Any]]:
    """Query the EastMoney datacenter; return result rows or empty list."""
    payload = em_get(
        EASTMONEY_DATACENTER_URL,
        params={
            "reportName": report_name,
            "columns": columns,
            "filter": filter_str,
            "pageNumber": "1",
            "pageSize": str(page_size),
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
            "source": "WEB",
            "client": "WEB",
        },
    )
    return _extract_records(payload)


def _require_a_share_code(ticker: str) -> str:
    canonical = normalize_ticker_symbol(ticker)
    if not is_a_share_ticker(canonical):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return to_akshare_symbol(canonical)


def _require_strict_a_share_code(ticker: str) -> str:
    """Validate a stock-only A-share code strictly; raise ChinaDataUnavailableError.

    The strict parser rejects malformed or contradictory forms (for example
    ``SZ600519`` or ``SH000001`` on stock-only research endpoints) before the
    generic A-share check runs, so the public contract stays one typed error.
    """
    try:
        code = strict_ticker_code(ticker, stock_only=True)
    except ValueError as exc:
        raise ChinaDataUnavailableError(str(exc)) from exc
    return _require_a_share_code(code)


def _format_report(
    data: pd.DataFrame,
    *,
    title: str,
    caveat: str,
    source: str = "eastmoney",
    as_of: str | None = None,
) -> str:
    if data.empty:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")
    return "\n".join(
        [
            f"# {title}",
            f"# Source: {source}",
            f"# Note: {caveat}",
            f"# Total records: {len(data)}",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            *([f"# Analysis cutoff: {as_of}"] if as_of else []),
            "",
            data.to_csv(index=False),
        ]
    )


def _capture_vendor_raw(data: Any, *, metadata: dict[str, Any]) -> None:
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(data, metadata=dict(metadata))


def get_a_share_dragon_tiger_em(ticker: str, trade_date: str, flag: str = "买入") -> str:
    """A-share dragon-tiger board (个股龙虎榜) via EastMoney datacenter direct.

    Returns appearance records within a 30-day look-back from ``trade_date``
    plus TOP5 buy/sell seats for the latest appearance.  ``flag`` is accepted
    for signature compatibility with the former akshare adapter; EastMoney
    returns both sides in one call.
    """
    code = _require_a_share_code(ticker)
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    records = _eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    if not records:
        raise ChinaDataUnavailableError(f"EastMoney returned no dragon-tiger records for {code}.")
    records_df = pd.DataFrame(
        [
            {
                "Date": str(r.get("TRADE_DATE", ""))[:10],
                "Reason": r.get("EXPLANATION", ""),
                "Net Buy (wan)": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                "Turnover %": round(float(r.get("TURNOVERRATE") or 0), 2),
            }
            for r in records
        ]
    )
    seats_rows: list[dict[str, Any]] = []
    latest_date = records_df["Date"].iloc[0]
    for side, report_name, sort_col in (
        ("buy", "RPT_BILLBOARD_DAILYDETAILSBUY", "BUY"),
        ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL", "SELL"),
    ):
        detail = _eastmoney_datacenter(
            report_name,
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10,
            sort_columns=sort_col,
            sort_types="-1",
        )
        for row in detail[:5]:
            seats_rows.append(
                {
                    "Side": side,
                    "Seat": row.get("OPERATEDEPT_NAME", ""),
                    "Buy (wan)": round((row.get("BUY") or 0) / 10000, 1),
                    "Sell (wan)": round((row.get("SELL") or 0) / 10000, 1),
                    "Net (wan)": round((row.get("NET") or 0) / 10000, 1),
                }
            )
    _capture_vendor_raw(
        {"records": records, "seats": seats_rows},
        metadata={"provider": "eastmoney", "dataset": "dragon_tiger", "ticker": ticker},
    )
    report = _format_report(
        records_df,
        title=f"China A-share dragon-tiger records for {normalize_ticker_symbol(ticker)}",
        caveat=f"EastMoney datacenter; 30-day look-back from {trade_date}; flag '{flag}' accepted but both sides returned.",
    )
    if seats_rows:
        report += f"\n\n## TOP5 buy/sell seats on {latest_date}\n\n" + pd.DataFrame(seats_rows).to_csv(index=False)
    return report


def get_a_share_lockup_releases_em(ticker: str, start_date: str, end_date: str) -> str:
    """A-share lockup-release calendar (限售解禁) via EastMoney datacenter direct."""
    code = _require_a_share_code(ticker)
    history = _eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=15,
        sort_columns="FREE_DATE",
        sort_types="-1",
    )
    upcoming = _eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{start_date}\')(FREE_DATE<=\'{end_date}\')',
        page_size=20,
        sort_columns="FREE_DATE",
        sort_types="1",
    )
    rows: list[dict[str, Any]] = []
    for scope, src in (("history", history), ("upcoming", upcoming)):
        for r in src:
            rows.append(
                {
                    "Scope": scope,
                    "Date": str(r.get("FREE_DATE", ""))[:10],
                    "Type": r.get("FREE_SHARES_TYPE", ""),
                    "Shares (wan)": r.get("FREE_SHARES", 0),
                    "Able Shares (wan)": r.get("ABLE_FREE_SHARES", 0),
                    "Ratio": r.get("FREE_RATIO", 0),
                }
            )
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned no lockup-release rows for {code}.")
    _capture_vendor_raw(
        {"history": history, "upcoming": upcoming},
        metadata={"provider": "eastmoney", "dataset": "lockup_releases", "ticker": ticker},
    )
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share lockup releases for {normalize_ticker_symbol(ticker)}",
        caveat="EastMoney datacenter RPT_LIFT_STAGE; FREE_SHARES_TYPE/FREE_SHARES are the 2026-renamed columns; ABLE_FREE_SHARES is actually-tradable shares.",
    )


def get_a_share_bulk_trades_em(ticker: str, start_date: str, end_date: str) -> str:
    """A-share block trades (大宗交易) via EastMoney datacenter direct."""
    code = _require_a_share_code(ticker)
    data = _eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=30,
        sort_columns="TRADE_DATE",
        sort_types="-1",
    )
    rows = []
    for r in data:
        close = r.get("CLOSE_PRICE") or 0
        deal = r.get("DEAL_PRICE") or 0
        premium = ((deal / close - 1) * 100) if close else 0
        rows.append(
            {
                "Date": str(r.get("TRADE_DATE", ""))[:10],
                "Deal Price": deal,
                "Close": close,
                "Premium %": round(premium, 2),
                "Volume": r.get("DEAL_VOLUME", 0),
                "Amount": r.get("DEAL_AMT", 0),
                "Buyer": r.get("BUYER_NAME", ""),
                "Seller": r.get("SELLER_NAME", ""),
            }
        )
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned no block-trade rows for {code}.")
    _capture_vendor_raw(data, metadata={"provider": "eastmoney", "dataset": "bulk_trades", "ticker": ticker})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share block trades for {normalize_ticker_symbol(ticker)}",
        caveat="EastMoney datacenter RPT_DATA_BLOCKTRADE; premium % is deal price vs close.",
    )


def get_a_share_shareholder_counts_em(ticker: str) -> str:
    """A-share shareholder-count changes (股东户数) via EastMoney datacenter direct."""
    code = _require_a_share_code(ticker)
    data = _eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=10,
        sort_columns="END_DATE",
        sort_types="-1",
    )
    rows = [
        {
            "Date": str(r.get("END_DATE", ""))[:10],
            "Holder Num": r.get("HOLDER_NUM", 0),
            "Change Num": r.get("HOLDER_NUM_CHANGE", 0),
            "Change %": r.get("HOLDER_NUM_RATIO", 0),
            "Avg Hold Num": r.get("AVG_HOLD_NUM", 0),
        }
        for r in data
    ]
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned no shareholder-count rows for {code}.")
    _capture_vendor_raw(data, metadata={"provider": "eastmoney", "dataset": "shareholder_counts", "ticker": ticker})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share shareholder counts for {normalize_ticker_symbol(ticker)}",
        caveat="EastMoney datacenter RPT_HOLDERNUMLATEST; quarterly; declining holder count signals chip concentration.",
    )


def _em_zt_api(endpoint: str, sort: str, date: str) -> list[dict[str, Any]]:
    """Fetch a limit-board pool from EastMoney push2ex (throttled via em_get).

    endpoint: getTopicZTPool / getTopicZBPool / getTopicDTPool / getYesterdayZTPool.
    Returns ``data.pool`` rows; an empty list means non-trading day or
    after-hours not-yet-updated.
    """
    payload = em_get(
        f"{_ZTB_URL}{endpoint}",
        params={
            "ut": _ZTB_UT,
            "dpt": "wz.ztzt",
            "Pageindex": 0,
            "pagesize": 10000,
            "sort": sort,
            "date": date.replace("-", "") if "-" in date else date,
        },
        headers={"Referer": _EASTMONEY_QUOTE_REFERER},
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    pool = data.get("pool")
    return pool if isinstance(pool, list) else []


def _em_zt_pool(date: str) -> list[dict[str, Any]]:
    """Limit-up pool (涨停池) -- named wrapper for the primary pool."""
    return _em_zt_api("getTopicZTPool", "fbt:asc", date)


def get_a_share_limit_up_ladder_em(trade_date: str) -> str:
    """A-share limit-up pool (涨停池) via EastMoney push2ex direct."""
    pool = _em_zt_pool(trade_date)
    if not pool:
        raise ChinaDataUnavailableError(
            f"EastMoney returned no limit-up pool rows for {trade_date} (non-trading day or after-hours not updated)."
        )
    rows = [
        {
            "Code": p.get("c"),
            "Name": p.get("n"),
            "Price": (p.get("p") or 0) / 1000,
            "Pct %": round(p.get("zdp", 0), 2),
            "Limit Days": p.get("lbc"),
            "Seal Fund": p.get("fund"),
            "Break Times": p.get("zbc"),
            "Industry": p.get("hybk", ""),
            "ZT Stat": f'{(p.get("zttj") or {}).get("days", "?")}天{(p.get("zttj") or {}).get("ct", "?")}板',
        }
        for p in pool
    ]
    _capture_vendor_raw(pool, metadata={"provider": "eastmoney", "dataset": "limit_up_ladder", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share limit-up pool for {trade_date}",
        caveat="EastMoney push2ex getTopicZTPool; price is raw/1000; non-trading day returns null.",
    )


def get_a_share_break_board_pool(trade_date: str) -> str:
    """A-share break-board pool (炸板池, 涨停后开板) via EastMoney push2ex direct."""
    pool = _em_zt_api("getTopicZBPool", "fbt:asc", trade_date)
    if not pool:
        raise ChinaDataUnavailableError(
            f"EastMoney returned no break-board pool rows for {trade_date} (non-trading day or after-hours not updated)."
        )
    rows = [
        {
            "Code": p.get("c"),
            "Name": p.get("n"),
            "Price": (p.get("p") or 0) / 1000,
            "Limit Price": (p.get("ztp") or 0) / 1000,
            "Pct %": round(p.get("zdp", 0), 2),
            "Turnover %": round(p.get("hs", 0), 2),
            "Break Times": p.get("zbc"),
            "Amplitude %": round(p.get("zf", 0), 2),
            "Speed %": round(p.get("zs", 0), 2),
            "Industry": p.get("hybk", ""),
        }
        for p in pool
    ]
    _capture_vendor_raw(pool, metadata={"provider": "eastmoney", "dataset": "break_board_pool", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share break-board pool for {trade_date}",
        caveat="EastMoney push2ex getTopicZBPool; stocks that hit limit-up then opened; price/limit_price are raw/1000.",
    )


def get_a_share_limit_down_pool(trade_date: str) -> str:
    """A-share limit-down pool (跌停池) via EastMoney push2ex direct."""
    pool = _em_zt_api("getTopicDTPool", "fund:asc", trade_date)
    if not pool:
        raise ChinaDataUnavailableError(
            f"EastMoney returned no limit-down pool rows for {trade_date} (non-trading day or after-hours not updated)."
        )
    rows = [
        {
            "Code": p.get("c"),
            "Name": p.get("n"),
            "Price": (p.get("p") or 0) / 1000,
            "Pct %": round(p.get("zdp", 0), 2),
            "Turnover %": round(p.get("hs", 0), 2),
            "Seal Fund": p.get("fund"),
            "Limit Down Days": p.get("days"),
            "Open Times": p.get("oc"),
            "Industry": p.get("hybk", ""),
        }
        for p in pool
    ]
    _capture_vendor_raw(pool, metadata={"provider": "eastmoney", "dataset": "limit_down_pool", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share limit-down pool for {trade_date}",
        caveat="EastMoney push2ex getTopicDTPool; price is raw/1000; seal fund in yuan.",
    )


def get_a_share_prev_limit_up_pool(trade_date: str) -> str:
    """A-share previous-day limit-up pool (昨涨停今表现) via EastMoney push2ex direct."""
    pool = _em_zt_api("getYesterdayZTPool", "zs:desc", trade_date)
    if not pool:
        raise ChinaDataUnavailableError(
            f"EastMoney returned no previous-day limit-up pool rows for {trade_date} (non-trading day or after-hours not updated)."
        )
    rows = [
        {
            "Code": p.get("c"),
            "Name": p.get("n"),
            "Price": (p.get("p") or 0) / 1000,
            "Pct %": round(p.get("zdp", 0), 2),
            "Turnover %": round(p.get("hs", 0), 2),
            "Amplitude %": round(p.get("zf", 0), 2),
            "Speed %": round(p.get("zs", 0), 2),
            "Prev Limit Days": p.get("ylbc"),
            "Industry": p.get("hybk", ""),
        }
        for p in pool
    ]
    _capture_vendor_raw(pool, metadata={"provider": "eastmoney", "dataset": "prev_limit_up_pool", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share previous-day limit-up pool for {trade_date}",
        caveat="EastMoney push2ex getYesterdayZTPool; yesterday's limit-up stocks' performance today; price is raw/1000.",
    )


def get_a_share_daily_dragon_tiger(trade_date: str) -> str:
    """Market-wide dragon-tiger board (全市场龙虎榜) for one trade date."""
    data = _eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT",
        sort_types="-1",
    )
    rows = [
        {
            "Code": r.get("SECURITY_CODE", ""),
            "Name": r.get("SECURITY_NAME_ABBR", ""),
            "Reason": r.get("EXPLANATION", ""),
            "Close": r.get("CLOSE_PRICE") or 0,
            "Change %": round(float(r.get("CHANGE_RATE") or 0), 2),
            "Net Buy (wan)": round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "Buy (wan)": round((r.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "Sell (wan)": round((r.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
        }
        for r in data
    ]
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned no market-wide dragon-tiger rows for {trade_date}.")
    _capture_vendor_raw(data, metadata={"provider": "eastmoney", "dataset": "daily_dragon_tiger", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share market-wide dragon-tiger for {trade_date}",
        caveat="EastMoney datacenter RPT_DAILYBILLBOARD_DETAILSNEW; ranked by net buy; non-trading day returns empty.",
    )


def get_a_share_dragon_tiger_official(trade_date: str) -> str:
    """Official dragon-tiger backup (沪深交易所官方) -- backup for EastMoney.

    SZSE returns structured rows; SSE returns raw text (fileContents).  This is
    an independent rate-limit plane from EastMoney, used when EastMoney bans
    the IP.  Used as the ``china_exchange`` fallback vendor in the router.
    """
    rows: list[dict[str, Any]] = []
    # SZSE: structured
    try:
        resp = requests.get(
            "https://www.szse.cn/api/report/ShowReport/data",
            params={
                "SHOWTYPE": "JSON",
                "CATALOGID": "1842_xxpl",
                "TABKEY": "tab1",
                "txtStart": trade_date,
                "txtEnd": trade_date,
                "random": "0.9",
            },
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/disclosure/supervision/dealinfo/index.html"},
            timeout=15,
        )
        szse_data = resp.json()
        if isinstance(szse_data, list) and szse_data:
            for row in (szse_data[0].get("data") or []):
                rows.append(
                    {
                        "Exchange": "SZSE",
                        "Code": row.get("zqdm"),
                        "Name": row.get("zqjc"),
                        "Amount": row.get("cjje"),
                        "Reason": row.get("plyy"),
                    }
                )
    except (requests.RequestException, ValueError):
        pass  # SZSE failed; SSE may still work

    # SSE: raw text (JSONP)
    sse_raw = ""
    try:
        resp = requests.get(
            "https://query.sse.com.cn/infodisplay/showTradePublicFile.do",
            params={"jsonCallBack": "cb", "isPagination": "false", "dateTx": trade_date},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.sse.com.cn/disclosure/diclosure/public/"},
            timeout=15,
        )
        text = resp.text
        if "(" in text and ")" in text:
            try:
                obj = json.loads(text[text.index("(") + 1 : text.rindex(")")])
                sse_raw = "\n".join(obj.get("fileContents", []))
            except (ValueError, json.JSONDecodeError):
                pass
    except requests.RequestException:
        pass

    if not rows and not sse_raw:
        raise ChinaDataUnavailableError(f"Official dragon-tiger backup returned no data for {trade_date}.")
    _capture_vendor_raw(
        {"szse": rows, "sse_raw": sse_raw},
        metadata={"provider": "china_exchange", "dataset": "dragon_tiger_official", "ticker": None},
    )
    report = ""
    if rows:
        report += _format_report(
            pd.DataFrame(rows),
            title=f"China A-share official dragon-tiger (SZSE) for {trade_date}",
            caveat="SZSE official API; independent backup for EastMoney.",
            source="china_exchange",
        )
    if sse_raw:
        report += f"\n\n## SSE official dragon-tiger raw text for {trade_date}\n\n{sse_raw}\n"
    return report


def get_a_share_research_reports(
    ticker: str,
    max_pages: int = 3,
    as_of: str | None = None,
    *,
    start_date: str | None = None,
) -> CoveredText:
    """A-share research reports (个股研报) via EastMoney reportapi direct.

    Returns published report list with org/title/rating/forecast-EPS fields.
    The ``predictThisYearEps``/``predictNextYearEps`` fields are analyst
    forecasts, distinct from tushare's reported fundamentals.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    code = _require_strict_a_share_code(ticker)
    all_records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    page_count = 0
    pagination_exhausted: bool | None = None
    invalid_published_count = 0
    for page in range(1, max_pages + 1):
        payload = em_get(
            _REPORT_API_URL,
            params={
                "industryCode": "*",
                "pageSize": "100",
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": "2000-01-01",
                "endTime": "2030-01-01",
                "pageNo": str(page),
                "fields": "",
                "qType": "0",
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            },
            headers={"Referer": "https://data.eastmoney.com/"},
            timeout=30,
        )
        page_count += 1
        _capture_vendor_raw(
            payload,
            metadata={
                "provider": "eastmoney",
                "dataset": "research_reports",
                "ticker": ticker,
                "page": page,
            },
        )
        rows = payload.get("data") or []
        if not rows:
            pagination_exhausted = True
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            published = str(row.get("publishDate", ""))[:10]
            try:
                published = datetime.strptime(published, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                invalid_published_count += 1
                continue
            if start_date and published < start_date:
                continue
            if as_of and published > as_of:
                continue
            dedupe_key = (
                str(row.get("infoCode") or row.get("title") or ""),
                str(row.get("orgSName") or ""),
                published,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            all_records.append(row)
        try:
            total_pages = int(payload.get("TotalPage"))
        except (TypeError, ValueError):
            total_pages = None
        if total_pages is not None and page >= total_pages:
            pagination_exhausted = True
            break
    else:
        pagination_exhausted = False
    if not all_records:
        raise ChinaDataUnavailableError(f"EastMoney returned no research reports for {code}.")
    rows_df = pd.DataFrame(
        [
            {
                "Date": str(r.get("publishDate", ""))[:10],
                "Org": r.get("orgSName", ""),
                "Title": r.get("title", ""),
                "Rating": r.get("emRatingName", ""),
                "EPS This Year": r.get("predictThisYearEps", ""),
                "EPS Next Year": r.get("predictNextYearEps", ""),
                "Industry": r.get("indvInduName", ""),
            }
            for r in all_records
        ]
    )
    report = _format_report(
        rows_df,
        title=f"China A-share research reports for {normalize_ticker_symbol(ticker)}",
        caveat=(
            "EastMoney reportapi; EPS fields are analyst forecasts "
            f"(predictThisYearEps/predictNextYearEps); analysis cutoff={as_of or 'not supplied'}."
        ),
        as_of=as_of,
    )
    observed_dates = sorted(
        str(record.get("publishDate", ""))[:10]
        for record in all_records
        if str(record.get("publishDate", ""))[:10]
    )
    actual_start = observed_dates[0] if observed_dates else None
    actual_end = observed_dates[-1] if observed_dates else None
    degradations: list[str] = []
    if invalid_published_count:
        degradations.append("invalid_or_missing_published_at")
    if pagination_exhausted is False:
        completeness = "partial"
        degradations.append("pagination_budget_exhausted")
    elif not (start_date and as_of):
        completeness = "unknown"
        degradations.append("requested_window_unproven")
    elif invalid_published_count:
        completeness = "partial"
    elif actual_start == start_date and actual_end == as_of:
        completeness = "complete"
    else:
        completeness = "partial"
        degradations.append("requested_window_not_fully_observed")
    coverage = SourceCoverageV1(
        capability="research_reports",
        source_id="eastmoney.research_reports",
        requested_start=start_date if start_date and as_of else None,
        requested_end=as_of if start_date and as_of else None,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=len(all_records),
        page_count=page_count,
        pagination_exhausted=pagination_exhausted,
        completeness=completeness,
        sources=("eastmoney.research_reports",),
        degradations=tuple(degradations),
        as_of=as_of or datetime.now().strftime("%Y-%m-%d"),
    )
    return CoveredText(report, coverage)


def get_a_share_eps_forecast(ticker: str, as_of: str | None = None) -> str:
    """A-share consensus EPS forecast (机构一致预期EPS) via THS (10jqka).

    Parses the THS worth.html table; the 'mean' column is the institutional
    consensus EPS.  Independent of EastMoney's rate-limit plane.
    """
    code = _require_strict_a_share_code(ticker)
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://basic.10jqka.com.cn/",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ChinaDataUnavailableError(f"THS EPS forecast request failed for {ticker}: {type(exc).__name__}") from exc
    resp.encoding = "gbk"
    from io import StringIO

    try:
        dfs = pd.read_html(StringIO(resp.text))
    except ValueError as exc:
        raise ChinaDataUnavailableError(f"THS returned no parseable EPS table for {code}: {exc}") from exc
    target = None
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            target = df
            break
    if target is None:
        target = dfs[0] if dfs else None
    if target is None or target.empty:
        raise ChinaDataUnavailableError(f"THS returned no EPS forecast rows for {code}.")
    _capture_vendor_raw({"html": resp.text[:2000]}, metadata={"provider": "ths", "dataset": "eps_forecast", "ticker": ticker})
    return _format_report(
        target,
        title=f"China A-share consensus EPS forecast for {normalize_ticker_symbol(ticker)}",
        caveat="THS basic.10jqka.com.cn; 'mean' column = institutional consensus EPS; this is a forecast snapshot, not reported EPS; <3 forecast institutions is low-confidence.",
        source="ths",
        as_of=as_of,
    )


def get_a_share_board_fund_flow(
    board_type: str = "industry",
    period: str = "today",
    top_n: int = 20,
) -> str:
    """Return industry/concept/region board money-flow rankings."""
    board_fs = {"industry": "m:90+t:2", "concept": "m:90+t:3", "region": "m:90+t:1"}
    period_fields = {
        "today": ("f62", "f62", "f184", "f3", "f204"),
        "5d": ("f164", "f164", "f165", "f109", "f257"),
        "10d": ("f174", "f174", "f175", "f160", ""),
    }
    if board_type not in board_fs:
        raise ValueError(f"unsupported board_type: {board_type}")
    if period not in period_fields:
        raise ValueError(f"unsupported board period: {period}")
    if not 1 <= int(top_n) <= 200:
        raise ValueError("top_n must be between 1 and 200")
    fid, main_field, pct_field, change_field, leader_field = period_fields[period]
    fields = ["f12", "f14", change_field, main_field, pct_field]
    if leader_field:
        fields.append(leader_field)
    if period == "today":
        fields.extend(["f66", "f72", "f78", "f84"])
    base_params = {
        "pz": "200",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": board_fs[board_type],
        "fields": ",".join(dict.fromkeys(fields)),
    }
    items: list[dict[str, Any]] = []
    total = 0
    page = 1
    while len(items) < int(top_n):
        payload = em_get(
            _INDUSTRY_CLIST_URL,
            params={**base_params, "pn": str(page)},
            headers={"Referer": _EASTMONEY_QUOTE_REFERER},
        )
        data = payload.get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break
        items.extend(row for row in diff if isinstance(row, dict))
        total = int(data.get("total") or total or len(items))
        if len(diff) < 200 or (total and len(items) >= total):
            break
        page += 1
    if not items:
        raise ChinaDataUnavailableError(f"EastMoney returned no board fund-flow rows for {board_type}/{period}.")
    rows = []
    for index, item in enumerate(items[: int(top_n)], start=1):
        row = {
            "Rank": index,
            "Board": item.get("f14", ""),
            "Code": item.get("f12", ""),
            "Change %": item.get(change_field, 0),
            "Main Net Inflow (CNY)": item.get(main_field, 0),
            "Main Net Ratio %": item.get(pct_field, 0),
            "Leader": item.get(leader_field, "") if leader_field else "",
        }
        if period == "today":
            row.update({
                "Super Large Net (CNY)": item.get("f66", 0),
                "Large Net (CNY)": item.get("f72", 0),
                "Medium Net (CNY)": item.get("f78", 0),
                "Small Net (CNY)": item.get("f84", 0),
            })
        rows.append(row)
    _capture_vendor_raw({"board_type": board_type, "period": period, "total": total, "rows": rows}, metadata={"provider": "eastmoney", "dataset": "board_fund_flow", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share {board_type} board fund flow ({period})",
        caveat="EastMoney push2 clist; amount fields are CNY; period-specific fields are not interchangeable.",
    )


def get_a_share_industry_ranking(top_n: int = 20) -> str:
    """A-share industry-board ranking via EastMoney push2 clist."""

    payload = em_get(
        _INDUSTRY_CLIST_URL,
        params={
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:90+t:2",
            "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
        },
        headers={"Referer": _EASTMONEY_QUOTE_REFERER},
    )
    items = (payload.get("data") or {}).get("diff") or []
    if not items:
        raise ChinaDataUnavailableError("EastMoney returned no industry-board rows.")
    rows = [
        {
            "Rank": i + 1,
            "Name": item.get("f14", ""),
            "Change %": item.get("f3", 0),
            "Code": item.get("f12", ""),
            "Up Count": item.get("f104", 0),
            "Down Count": item.get("f105", 0),
            "Leader": item.get("f140", ""),
            "Leader Change %": item.get("f136", 0),
        }
        for i, item in enumerate(items)
    ]
    _capture_vendor_raw(items, metadata={"provider": "eastmoney", "dataset": "industry_ranking", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title="China A-share industry-board ranking",
        caveat="EastMoney push2 clist (m:90+t:2); sorted by change% desc; ~100 industries.",
    )


def get_a_share_concept_blocks(ticker: str) -> str:
    """A-share board membership (个股板块归属) via EastMoney push2 slist.

    Returns all industry/concept/region boards a stock belongs to, with the
    board code (BK), change%, and leading stock.  Board names are
    self-describing; EastMoney does not separate industry/concept/region.
    """
    code = _require_a_share_code(ticker)
    market_code = 1 if code.startswith("6") else 0
    payload = em_get(
        _SLIST_URL,
        params={
            "fltt": "2",
            "invt": "2",
            "secid": f"{market_code}.{code}",
            "spt": "3",
            "pi": "0",
            "pz": "200",
            "po": "1",
            "fields": "f12,f14,f3,f128",
        },
        headers={"Referer": _EASTMONEY_QUOTE_REFERER},
    )
    diff = (payload.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    rows = [
        {
            "Board": it.get("f14", ""),
            "Code": it.get("f12", ""),
            "Change %": it.get("f3", ""),
            "Leader": it.get("f128", ""),
        }
        for it in items
    ]
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned no board membership for {code}.")
    _capture_vendor_raw({"diff": diff}, metadata={"provider": "eastmoney", "dataset": "concept_blocks", "ticker": ticker})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share board membership for {normalize_ticker_symbol(ticker)}",
        caveat="EastMoney push2 slist; mixed industry/concept/region boards; board names are self-describing.",
    )


# ---------------------------------------------------------------------------
# Key-stock monitor pool + intraday price anomaly (a-stock-data v3.6.0 §8.4/§8.5)
# ---------------------------------------------------------------------------

_CN_TZ = timezone(timedelta(hours=8))
_MONITOR_URL = "https://mobappconfig.securities.eastmoney.com/emcfg/stock_monitor.json"
# MARKET is three-valued and includes the letter "B" for BSE; treating it as
# 0/1 would mislabel every Beijing-listed monitored stock as Shenzhen.
_MONITOR_MARKET = {"1": "SH", "0": "SZ", "B": "BJ"}

_ANOMALY_BASE = "https://dycalchis.eastmoney.com/price-anomaly"
# EastMoney H5 fixed public params; missing ``team`` is rejected by the API
# with {"result":1001,"msg":"unknow team"}.
_ANOMALY_HQ_PARAMS = {
    "team": "h5",
    "product": "EastMoney",
    "client": "WAP",
    "version": "9001",
    "name": "WAP",
    "user": "123",
}
# Anomaly rule codes (e field) -> text; s==6 (STAR) with e in 4..7 maps to the
# stricter e*10 threshold tier.
_ANOMALY_RULES = {
    1: "主板连续10个交易日内4次出现同向异常波动",
    2: "创业板连续10个交易日内3次出现同向异常波动",
    3: "科创板连续10个交易日内3次出现同向异常波动",
    4: "连续十个交易日内日收盘价涨跌幅偏离值累计达到+100%",
    5: "连续十个交易日内日收盘价涨跌幅偏离值累计达到-50%",
    6: "连续三十个交易日内日收盘价涨跌幅偏离值累计达到+200%",
    7: "连续三十个交易日内日收盘价涨跌幅偏离值累计达到-70%",
    8: "北交所连续10个交易日内3次出现同向异常波动",
    40: "连续十个交易日内日收盘价涨跌幅偏离值累计达到+150%",
    50: "连续十个交易日内日收盘价涨跌幅偏离值累计达到-60%",
    60: "连续30个交易日内日收盘价涨跌幅偏离值累计达到+300%",
    70: "连续30个交易日内日收盘价涨跌幅偏离值累计达到-75%",
}


def _cn_today() -> str:
    """Today's date in Beijing time (YYYY-MM-DD)."""
    return datetime.now(_CN_TZ).date().isoformat()


def _anomaly_market(code: object, m: object, board: object = None) -> str:
    """Anomaly record -> exchange.

    BSE and SZSE are both m=0 in EastMoney's scheme, so the code segment must
    win; rule code 8 is BSE-specific and is an additional tie-breaker.
    """
    c = str(code or "")
    if c.startswith("920") or c[:2] in ("43", "83", "87") or board == 8:
        return "BJ"
    return "SH" if m == 1 else "SZ"


def _anomaly_get(path: str, page_size: int, page_no: int, **extra: str) -> dict[str, Any]:
    """Fetch an anomaly endpoint; fail fast when the API rejects the request.

    The endpoint uses ``result != 0`` to express refusal.  Treating that as
    "no anomalies today" would silently hide a contract change.
    """
    payload = em_get(
        f"{_ANOMALY_BASE}/{path}",
        params={
            **_ANOMALY_HQ_PARAMS,
            "pageSize": str(page_size),
            "pageNo": str(page_no),
            **extra,
        },
        headers={"Referer": "https://vipmoney.eastmoney.com/"},
        timeout=20,
    )
    if payload.get("result") != 0:
        raise ChinaDataUnavailableError(
            f"EastMoney price-anomaly endpoint rejected the request: "
            f"result={payload.get('result')} msg={payload.get('msg')!r}"
        )
    return payload


def get_a_share_stock_monitor_em(only_active: bool = True) -> str:
    """A-share key-stock monitor pool (重点监控池) via EastMoney zero-auth JSON.

    Lists exchange risk-warned / key-monitored instruments with their validity
    window.  ``only_active`` keeps only rows whose window covers today (Beijing
    time), so stale monitoring entries are not presented as current.
    """
    rows = em_get_json(
        _MONITOR_URL,
        headers={"Referer": "https://vipmoney.eastmoney.com/"},
        timeout=20,
    )
    if not isinstance(rows, list):
        raise ChinaDataUnavailableError("EastMoney monitor pool returned a non-list payload.")
    today = _cn_today()
    records: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        start = str(item.get("VALIDATESTARTDATE", ""))
        end = str(item.get("VALIDATEENDDATE", ""))
        if only_active and not (start <= today <= end):
            continue
        raw_mkt = str(item.get("MARKET", "")).upper()
        records.append(
            {
                "Code": item.get("STKCODE", ""),
                "Name": item.get("STKNAME", ""),
                "Market": _MONITOR_MARKET.get(raw_mkt, f"?{raw_mkt}"),
                "Start": start,
                "End": end,
                "Link": item.get("LINK_URL", ""),
            }
        )
    if not records:
        raise ChinaDataUnavailableError("EastMoney returned no active key-stock monitor rows.")
    _capture_vendor_raw(rows, metadata={"provider": "eastmoney", "dataset": "stock_monitor", "ticker": None})
    return _format_report(
        pd.DataFrame(records),
        title=f"China A-share key-stock monitor pool (as of {today})",
        caveat="EastMoney emcfg stock_monitor.json; exchange risk-warning / key-monitor list with validity window; MARKET is 1=SH / 0=SZ / B=BJ.",
    )


def get_a_share_price_anomaly_em(page_size: int = 200, page_no: int = 1) -> str:
    """A-share intraday price-anomaly detail (日内异动明细, severe abnormal move)."""
    payload = _anomaly_get("list", page_size, page_no)
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        e = item.get("e")
        key = e * 10 if (item.get("s") == 6 and e in (4, 5, 6, 7)) else e
        rows.append(
            {
                "Code": item.get("c"),
                "Name": item.get("n"),
                "Market": _anomaly_market(item.get("c"), item.get("m"), item.get("s")),
                "Change %": item.get("a"),
                "Deviation %": item.get("x"),
                "Window Days": item.get("d"),
                "Board": item.get("s"),
                "Rule Code": key,
                "Rule": _ANOMALY_RULES.get(key, f"unknown rule code {key}"),
                "Today": item.get("o") != 2,
            }
        )
    if not rows:
        raise ChinaDataUnavailableError("EastMoney returned no price-anomaly rows.")
    _capture_vendor_raw(payload, metadata={"provider": "eastmoney", "dataset": "price_anomaly", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share intraday price anomalies ({payload.get('date', '')})",
        caveat="EastMoney price-anomaly/list; severe abnormal-move criterion; non-trading hours return the previous trading day; rule code 8 is BSE-only.",
    )


def get_a_share_price_anomaly_count_em(page_size: int = 50, page_no: int = 1) -> str:
    """A-share price-anomaly aggregate count per instrument (异动统计)."""
    payload = _anomaly_get("count", page_size, page_no)
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Code": item.get("c"),
                "Name": item.get("n"),
                "Market": _anomaly_market(item.get("c"), item.get("m"), item.get("s")),
                "Price": item.get("p"),
                "Change %": item.get("a"),
                "Times": item.get("t"),
                "Deviation %": item.get("x"),
                "Window Days": item.get("d"),
                "Board": item.get("s"),
            }
        )
    if not rows:
        raise ChinaDataUnavailableError("EastMoney returned no price-anomaly count rows.")
    _capture_vendor_raw(payload, metadata={"provider": "eastmoney", "dataset": "price_anomaly_count", "ticker": None})
    return _format_report(
        pd.DataFrame(rows),
        title=f"China A-share price-anomaly counts ({payload.get('date', '')})",
        caveat="EastMoney price-anomaly/count; aggregated anomaly times per instrument; 'Times' is an integer count (unlike the list endpoint's target-value t).",
    )
