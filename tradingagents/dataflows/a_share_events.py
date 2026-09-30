"""EastMoney event-driven A-share adapters (a-stock-data v3.10.0 §14 + §6.8).

Six direct-HTTP adapters cover the company-event layer:

- ``get_a_share_earnings_forecast``   业绩预告      RPT_PUBLIC_OP_NEWPREDICT
- ``get_a_share_institution_survey``  机构调研      RPT_ORG_SURVEYNEW
- ``get_a_share_share_buyback``       股票回购      RPTA_WEB_GETHGLIST_NEW
- ``get_a_share_equity_pledge``       股权质押比例  RPT_CSDC_LIST (ChinaClear weekly)
- ``get_a_share_ipo_calendar``        新股申购日历  RPTA_APP_IPOAPPLY
- ``get_a_share_st_stock_list``       ST/*ST 名单    EastMoney clist 风险警示板 + BSE full table

``holder_trades`` is intentionally *not* re-implemented here: the same
``RPT_SHARE_HOLDER_INCREASE`` report already backs
``china_capital_flow.get_a_share_insider_trades``.

Every EastMoney request goes through the shared throttled gateway
(:func:`eastmoney.em_get`): the rate limit and the reused session live there, and
no adapter opens its own connection.  The pagination contract is deliberately
strict, because a partial page set that looks complete is worse than a failure:

- ``code == 9201`` on page 1 means "genuinely no rows" and returns an empty list;
  any other non-zero code raises with the code *and* the provider message.
- A 9201 after page 1, an empty page, a short non-final page, a changed
  ``pages``/``count`` between pages, or a final row count that disagrees with
  ``count`` all raise, so a partial fetch is never presented as complete.
- ``columns="ALL"`` always; ``sortColumns`` and ``sortTypes`` must have equal
  element counts (EastMoney answers 9501 otherwise), validated before requesting.
- ``max_rows`` truncation is allowed only when the source's self-reported
  ``count`` exceeds ``max_rows``.
- A full-market query (no ticker and no date filter) that returns zero rows is
  an interface failure and raises; a query narrowed by ticker/date that returns
  zero rows is legitimately empty.
- Returned rows are re-checked against the requested ``equal``/``dates`` filters,
  and exact duplicate rows across pages mean the sort key was not unique: both
  raise instead of returning another instrument's or another period's rows.

Degradation contract: an empty response, a changed schema, an unavailable
optional dependency (baostock for the ST fallback), or a provider error raises a
typed ``ChinaDataUnavailableError`` / ``AshareCapabilityUnavailableError``; it
never returns an empty table that a caller could read as "there were no such
events".
"""

from __future__ import annotations

import json
import math
import re
from datetime import date as _date_cls, datetime
from functools import wraps
from typing import Any

import pandas as pd

from .china_capabilities import AshareCapabilityUnavailableError
from .china_data import ChinaDataUnavailableError
from .eastmoney import EASTMONEY_DATACENTER_URL, em_get
from .errors import VendorError, VendorHTTPError, VendorRateLimitError
from .ticker_utils import infer_a_share_exchange, normalize_ticker_symbol, strict_ticker_code

__all__ = [
    "get_a_share_earnings_forecast",
    "get_a_share_equity_pledge",
    "get_a_share_institution_survey",
    "get_a_share_ipo_calendar",
    "get_a_share_share_buyback",
    "get_a_share_st_stock_list",
]

_DATACENTER_URL = EASTMONEY_DATACENTER_URL

# EastMoney quote-list hosts.  push2delay is the same interface with ~15-minute
# delayed quotes, used only when the primary host fails at the transport layer.
EM_CLIST_HOSTS = ("https://push2.eastmoney.com", "https://push2delay.eastmoney.com")

# Shanghai/Shenzhen risk-warning board (沪深风险警示板, includes B shares).  The
# BSE is not part of this filter, so it needs the separate full-market table.
_CLIST_SHSZ_RISK = "m:0+f:4,m:1+f:4"
_CLIST_BSE_ALL = "m:0+t:81+s:2048"
_CLIST_FIELDS = "f12,f13,f14,f2,f3"

_ST_COLUMNS = ["code", "market", "name", "st_type", "price", "pct_change"]


# ---------------------------------------------------------------------------
# Strict helper contract (ported from a-stock-data v3.10.0 ``_v39_*``)
# ---------------------------------------------------------------------------

def _v39_limit(limit: Any, upper: int = 5000) -> int:
    """Validate a row limit; a caller error stays a ``ValueError``."""
    limit = int(limit)
    if not 1 <= limit <= upper:
        raise ValueError(f"limit 范围 1–{upper}")
    return limit


def _v39_num(value: Any) -> float | None:
    """``'1,234.50'`` -> ``1234.5``; ``''`` / ``'-'`` / ``'--'`` / ``None`` -> ``None``.

    Anything else that cannot be parsed raises ``ChinaDataUnavailableError``
    (the source produced a value we do not recognize -- a format change, not a
    caller error).  A JSON boolean is an error too: ``float(True) == 1.0`` would
    silently turn a format mistake into a price or volume.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ChinaDataUnavailableError(f"来源在数值字段给了布尔值 {value!r}")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return float(value)
    text = str(value).replace(",", "").strip()
    if text in ("", "-", "--", "None", "null"):
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ChinaDataUnavailableError(f"来源返回了无法识别的数值 {value!r}") from exc
    return number if math.isfinite(number) else None


def _v39_date(value: Any) -> str:
    """``'2026-09-18'`` / ``'20260918'`` / a date object -> ``'2026-09-18'``.

    Any other spelling raises ``ValueError``: a caller-supplied date that cannot
    be parsed must not be guessed at.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, _date_cls):
        return value.isoformat()
    text = str(value).strip()
    fmt = "%Y%m%d" if re.fullmatch(r"[0-9]{8}", text) else "%Y-%m-%d"
    return datetime.strptime(text, fmt).date().isoformat()


def _v39_src_date(value: Any) -> str:
    """A date that came *from the source*: unrecognized -> typed source error."""
    try:
        return _v39_date(value)
    except ValueError as exc:
        raise ChinaDataUnavailableError(f"来源返回了无法识别的日期 {value!r}") from exc


def _em_day(value: Any) -> str | None:
    """EastMoney day string ``'2026-09-18 00:00:00'`` -> ``'2026-09-18'``; empty -> ``None``.

    The 10-character truncation is followed by strict ISO validation, so a
    non-ISO spelling such as ``'2026/09/18'`` raises instead of passing through
    and later comparing wrong against a date window.
    """
    return _v39_src_date(str(value)[:10]) if value else None


def _strict_stock_code(ticker: Any) -> str:
    """Bare six-digit code for a stock-only endpoint.

    ``strict_ticker_code`` raises ``ValueError``; the public contract is a
    typed degradation, so it is wrapped here.
    """
    try:
        return strict_ticker_code(ticker, stock_only=True)
    except ValueError as exc:
        raise ChinaDataUnavailableError(str(exc)) from exc


def _v39_count(value: Any, what: str) -> int:
    """A source's self-reported page/total count -> non-negative int.

    Only int or a digits-only string qualify; a boolean raises because
    ``int(True) == 1`` would let "only one row returned" pass the completeness
    check.
    """
    numeric = isinstance(value, (int, str)) and not isinstance(value, bool)
    text = str(value).strip() if numeric else ""
    if not re.fullmatch(r"[0-9]+", text):
        raise ChinaDataUnavailableError(f"{what} 不是非负整数: {value!r}")
    return int(text)


def _v39_rows(value: Any, what: str) -> list[dict[str, Any]]:
    """A possibly-absent row list: ``None`` -> empty, anything else must be objects.

    Writing ``value or []`` would treat ``{}`` / ``''`` / ``0`` as an empty list
    and silently drop a whole payload section.
    """
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ChinaDataUnavailableError(
            f"{what} 应为对象列表，实际是 {type(value).__name__}: {str(value)[:120]}"
        )
    return value


def _source_contract(func):
    """A missing source field is a schema change, not a caller error.

    ``row["X"]`` on a changed payload would otherwise leak a bare ``KeyError``
    that a caller reads as "bad argument / no data"; here it becomes a typed
    ``ChinaDataUnavailableError`` naming the function and the field.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyError as exc:
            raise ChinaDataUnavailableError(
                f"{func.__name__}: 来源数据缺少字段 {exc}，格式可能已变"
            ) from exc

    return wrapper


def _capture_vendor_raw(data: Any, *, metadata: dict[str, Any]) -> None:
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(data, metadata=dict(metadata))


def _format_report(
    data: pd.DataFrame,
    *,
    title: str,
    caveat: str,
    source: str = "eastmoney",
    extra_lines: tuple[str, ...] = (),
) -> str:
    """House-style source-labelled markdown report; empty rows degrade loudly."""
    if data.empty:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")
    return "\n".join(
        [
            f"# {title}",
            f"# Source: {source}",
            f"# Note: {caveat}",
            f"# Total records: {len(data)}",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            *extra_lines,
            "",
            data.to_csv(index=False),
        ]
    )


def _em_datacenter_strict(
    report_name: str,
    filter_str: str = "",
    sort_columns: str = "",
    sort_types: str = "",
    page_size: int = 500,
    max_rows: int = 5000,
    columns: str = "ALL",
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Strict EastMoney datacenter pager: page-1 9201 -> ``[]``, everything else raises.

    Unlike the legacy ``eastmoney_datacenter()`` helper, this version paginates
    and surfaces error codes.  ``sortTypes`` must have as many elements as
    ``sortColumns`` or EastMoney answers 9501.  A mid-pagination failure
    (page 2+ 9201, an empty page, a short non-final page, missing ``pages`` /
    ``count``, changed page total / row total, or a final count disagreeing with
    ``count``) raises instead of returning a partial set.  ``max_rows``
    truncates only when the source's own ``count`` exceeds it; otherwise the
    whole pagination runs and the total is verified.
    """
    n_cols = len([c for c in sort_columns.split(",") if c]) if sort_columns else 0
    n_types = len([t for t in sort_types.split(",") if t]) if sort_types else 0
    if n_cols != n_types:
        raise ValueError(f"sortColumns({n_cols}) 与 sortTypes({n_types}) 个数不一致")
    rows: list[dict[str, Any]] = []
    page, first = 1, None
    while True:
        params = {
            "reportName": report_name,
            "columns": columns,
            "filter": filter_str,
            "pageNumber": str(page),
            "pageSize": str(page_size),
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
            "source": "WEB",
            "client": "WEB",
        }
        params.update(extra or {})
        try:
            payload = em_get(_DATACENTER_URL, params=params, timeout=20)
        except VendorError as exc:
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 请求失败: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 返回的不是 JSON 对象: {str(payload)[:100]}"
            )
        if payload.get("code") == 9201:
            if page == 1:
                return []
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 第 {page} 页返回「数据为空」，"
                f"前面已取 {len(rows)} 条，结果不完整"
            )
        if payload.get("code") != 0 or not payload.get("result"):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 返回错误: {payload.get('code')} {payload.get('message')}"
            )
        result = payload["result"]
        if not isinstance(result, dict):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 的 result 不是对象: {str(result)[:100]}"
            )
        pages, count, data = result.get("pages"), result.get("count"), result.get("data")
        if data is None:
            data = []
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 第 {page} 页的 data 不是由对象组成的列表，格式可能已变"
            )
        if (
            any(isinstance(v, bool) or not isinstance(v, int) for v in (pages, count))
            or pages < 1
            or count < 0
        ):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 缺少分页信息（pages={pages!r}, count={count!r}）"
            )
        if first is None:
            first = (pages, count)
        elif (pages, count) != first:
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 翻页时总页数 / 总条数从 {first} 变成 {(pages, count)}，"
                "结果可能错位，请重试"
            )
        if not data and (page > 1 or pages > 1):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 第 {page}/{pages} 页是空的，结果不完整"
            )
        if page < pages and len(data) != int(page_size):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 第 {page}/{pages} 页只有 {len(data)} 条"
                f"（非末页应为 {page_size} 条），结果不完整"
            )
        rows.extend(data)
        # Only truncate when the source's own count exceeds the cap; otherwise
        # (count <= max_rows yet more rows arrived) the whole pagination must
        # finish and the total must be checked, so "data longer than count" is
        # not passed off as a legitimate truncation.
        if len(rows) >= max_rows and count > max_rows:
            return rows[:max_rows]
        if page >= pages:
            if len(rows) != count:
                raise ChinaDataUnavailableError(
                    f"东财 {report_name} 翻页后 {len(rows)} 条，与总数 {count} 不符"
                )
            return rows
        page += 1


def _em_event_filter(
    ticker: Any = None,
    date_field: str | None = None,
    start: Any = None,
    end: Any = None,
    extra: str = "",
) -> str:
    """Build the EastMoney datacenter filter: ticker + notice-date window + extra.

    ``start`` later than ``end`` raises ``ValueError`` before any request.
    """
    if start and end and _v39_date(start) > _v39_date(end):
        raise ValueError("start 不能晚于 end")
    parts = [extra] if extra else []
    if ticker is not None:
        parts.append(f'(SECURITY_CODE="{_strict_stock_code(ticker)}")')
    if start:
        parts.append(f"({date_field}>='{_v39_date(start)}')")
    if end:
        parts.append(f"({date_field}<='{_v39_date(end)}')")
    return "".join(parts)


def _em_event_rows(
    report: str,
    filter_str: str,
    sort_columns: str,
    sort_types: str,
    limit: int,
    narrowed: bool,
    extra: dict[str, Any] | None = None,
    equal: dict[str, Any] | None = None,
    dates: dict[str, tuple[str | None, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch event rows and prove the answer is complete and truly the requested slice.

    ``narrowed=False`` (whole market, no condition at all) with zero rows means
    the interface broke and raises; with a ticker/date condition zero rows is
    "genuinely none" and returns an empty list.

    The sort key must uniquely identify a row: EastMoney slices by page, so a
    tie repeats one row and drops another (measured on the pledge table: sorted
    by ratio alone, 2212 rows repeated 1 and lost 1).  Identical rows -> raise.

    Server-side filtering is only a request: ``equal={field: value}`` and
    ``dates={date_field: (lo, hi)}`` are re-checked row by row, so a filter the
    interface ignored, or a stale cache page for another instrument/period,
    raises instead of being returned as the answer.
    """
    rows = _em_datacenter_strict(
        report,
        filter_str,
        sort_columns,
        sort_types,
        page_size=min(limit, 500),
        max_rows=limit,
        extra=extra,
    )
    if not rows and not narrowed:
        raise ChinaDataUnavailableError(f"东财 {report} 全市场返回 0 行，接口可能改了")
    if len({json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows}) != len(rows):
        raise ChinaDataUnavailableError(f"东财 {report} 翻页返回了重复行（排序不唯一），结果不完整")
    for r in rows:
        for field, value in (equal or {}).items():
            if r.get(field) != value:
                raise ChinaDataUnavailableError(
                    f"东财 {report} 请求 {field}={value}，却返回了 {r.get(field)!r}，结果不可信"
                )
        for field, (lo, hi) in (dates or {}).items():
            day = _v39_src_date(str(r.get(field) or "")[:10])
            if (lo and day < lo) or (hi and day > hi):
                raise ChinaDataUnavailableError(
                    f"东财 {report} 请求 {field} 在 {lo or ''}~{hi or ''}，却返回了 {day}，结果不可信"
                )
    return rows


# ---------------------------------------------------------------------------
# §14.1 业绩预告 RPT_PUBLIC_OP_NEWPREDICT
# ---------------------------------------------------------------------------

_FORECAST_COLUMNS = [
    "code",
    "name",
    "notice_date",
    "report_date",
    "indicator",
    "forecast_type",
    "amount_lower",
    "amount_upper",
    "change_pct_lower",
    "change_pct_upper",
    "prior_year_amount",
    "content",
    "reason",
]


@_source_contract
def get_a_share_earnings_forecast(ticker=None, report_date=None, limit=500) -> str:
    """业绩预告 (earnings pre-announcement), EastMoney datacenter, SH/SZ/BJ.

    No ``ticker`` = the whole market, newest ``limit`` rows by notice date.
    ``report_date`` is the reporting period, e.g. ``'2026-09-30'`` (``'20260930'``
    is accepted too).  One pre-announcement is split across indicators
    (``indicator`` = 归母净利润 / 扣非净利润 / 营业收入 …).  Amounts are in yuan,
    ``change_pct_*`` is the year-on-year change in %.
    """
    limit = _v39_limit(limit)
    period = _v39_date(report_date) if report_date else None
    extra = f"(REPORT_DATE='{period}')" if period else ""
    filter_str = _em_event_filter(ticker, extra=extra)
    code = _strict_stock_code(ticker) if ticker is not None else None
    rows = _em_event_rows(
        "RPT_PUBLIC_OP_NEWPREDICT",
        filter_str,
        "NOTICE_DATE,SECURITY_CODE,REPORT_DATE,PREDICT_FINANCE_CODE",
        "-1,1,-1,1",
        limit,
        narrowed=bool(ticker or report_date),
        equal={} if code is None else {"SECURITY_CODE": code},
        dates={"REPORT_DATE": (period, period)} if period else None,
    )
    out = [
        {
            "code": r["SECURITY_CODE"],
            "name": r.get("SECURITY_NAME_ABBR"),
            "notice_date": _em_day(r.get("NOTICE_DATE")),
            "report_date": _em_day(r.get("REPORT_DATE")),
            "indicator": r.get("PREDICT_FINANCE"),
            "forecast_type": r.get("PREDICT_TYPE"),
            "amount_lower": _v39_num(r.get("PREDICT_AMT_LOWER")),
            "amount_upper": _v39_num(r.get("PREDICT_AMT_UPPER")),
            "change_pct_lower": _v39_num(r.get("ADD_AMP_LOWER")),
            "change_pct_upper": _v39_num(r.get("ADD_AMP_UPPER")),
            "prior_year_amount": _v39_num(r.get("PREYEAR_SAME_PERIOD")),
            "content": r.get("PREDICT_CONTENT"),
            "reason": r.get("CHANGE_REASON_EXPLAIN"),
        }
        for r in rows
    ]
    target = normalize_ticker_symbol(ticker) if ticker is not None else "market-wide"
    _capture_vendor_raw(
        rows,
        metadata={"provider": "eastmoney", "dataset": "earnings_forecast", "ticker": ticker},
    )
    return _format_report(
        pd.DataFrame(out, columns=_FORECAST_COLUMNS),
        title=f"China A-share earnings pre-announcements for {target}",
        caveat=(
            "EastMoney datacenter RPT_PUBLIC_OP_NEWPREDICT; one forecast is split across "
            "indicators (归母净利润 / 扣非净利润 / 营业收入 …); amounts in yuan, "
            "change_pct_* is the year-on-year change in %."
        ),
    )


# ---------------------------------------------------------------------------
# §14.2 机构调研 RPT_ORG_SURVEYNEW
# ---------------------------------------------------------------------------

_SURVEY_COLUMNS = [
    "code",
    "name",
    "notice_date",
    "survey_date",
    "survey_end",
    "org_count",
    "survey_way",
    "place",
    "receptionist",
]


@_source_contract
def get_a_share_institution_survey(
    ticker=None, start=None, end=None, detail=False, limit=500
) -> str:
    """机构调研 (institution survey), EastMoney datacenter.

    ``detail=False``: one row per survey with ``org_count`` participating
    institutions.  ``detail=True``: one row per institution, adding
    ``org_name`` / ``org_type`` / ``investigators`` (many record sheets omit the
    type and the attendee names, so those stay ``None``).
    ``start`` / ``end`` filter the notice date (``notice_date``); ``survey_date``
    is the actual reception day, usually a few days before the notice.
    """
    limit = _v39_limit(limit)
    extra = '(IS_SOURCE="1")' + ("" if detail else '(NUMBERNEW="1")')
    filter_str = _em_event_filter(ticker, "NOTICE_DATE", start, end, extra)
    sort = (
        ("NOTICE_DATE,SECURITY_CODE,RECEIVE_START_DATE,NUMBERNEW", "-1,1,-1,1")
        if detail
        else ("NOTICE_DATE,SECURITY_CODE,RECEIVE_START_DATE", "-1,1,-1")
    )
    equal: dict[str, Any] = {"IS_SOURCE": "1"} if detail else {"IS_SOURCE": "1", "NUMBERNEW": "1"}
    if ticker is not None:
        equal["SECURITY_CODE"] = _strict_stock_code(ticker)
    rows = _em_event_rows(
        "RPT_ORG_SURVEYNEW",
        filter_str,
        sort[0],
        sort[1],
        limit,
        narrowed=bool(ticker or start or end),
        equal=equal,
        dates={"NOTICE_DATE": (start and _v39_date(start), end and _v39_date(end))}
        if start or end
        else None,
    )
    out = []
    for r in rows:
        row = {
            "code": r["SECURITY_CODE"],
            "name": r.get("SECURITY_NAME_ABBR"),
            "notice_date": _em_day(r.get("NOTICE_DATE")),
            "survey_date": _em_day(r.get("RECEIVE_START_DATE")),
            "survey_end": _em_day(r.get("RECEIVE_END_DATE")),
            "org_count": _v39_num(r.get("SUM")),
            "survey_way": r.get("RECEIVE_WAY_EXPLAIN"),
            "place": r.get("RECEIVE_PLACE"),
            "receptionist": r.get("RECEPTIONIST"),
        }
        if detail:
            row.update(
                {
                    "org_name": r.get("RECEIVE_OBJECT"),
                    "org_type": r.get("ORG_TYPE"),
                    "investigators": r.get("INVESTIGATORS"),
                }
            )
        out.append(row)
    columns = _SURVEY_COLUMNS + (["org_name", "org_type", "investigators"] if detail else [])
    target = normalize_ticker_symbol(ticker) if ticker is not None else "market-wide"
    _capture_vendor_raw(
        rows,
        metadata={
            "provider": "eastmoney",
            "dataset": "institution_survey",
            "ticker": ticker,
            "detail": detail,
        },
    )
    return _format_report(
        pd.DataFrame(out, columns=columns),
        title=f"China A-share institution surveys for {target}",
        caveat=(
            "EastMoney datacenter RPT_ORG_SURVEYNEW; aggregated from the investor-relations "
            "record sheets; org_count is the number of participating institutions; "
            "survey_date is the reception day, notice_date is the disclosure day."
        ),
    )


# ---------------------------------------------------------------------------
# §14.3 股票回购 RPTA_WEB_GETHGLIST_NEW
# ---------------------------------------------------------------------------

_BUYBACK_PROGRESS = {
    "001": "董事会预案",
    "002": "股东大会通过",
    "003": "股东大会否决",
    "004": "实施中",
    "005": "停止实施",
    "006": "完成实施",
}
_BUYBACK_COLUMNS = [
    "code",
    "name",
    "progress",
    "progress_code",
    "plan_start",
    "plan_end",
    "price_cap",
    "shares_lower",
    "shares_upper",
    "amount_lower",
    "amount_upper",
    "pct_total_lower",
    "pct_total_upper",
    "done_shares",
    "done_amount",
    "done_price_low",
    "done_price_high",
    "latest_notice",
    "objective",
]


@_source_contract
def get_a_share_share_buyback(ticker=None, progress=None, limit=500) -> str:
    """股票回购 (share buyback) — plan and execution progress, one plan per row.

    Sorted by latest notice date descending.  ``progress`` is ``None`` or one of
    ``'董事会预案' / '股东大会通过' / '股东大会否决' / '实施中' / '停止实施' / '完成实施'``.
    Shares are in shares, amounts in yuan, ``pct_total_*`` is the percent of the
    total share capital on the day before the notice.  ``done_*`` is the executed
    part (``None`` before execution starts).  EastMoney has two further progress
    codes (007 / 008; 13 of 5516 rows on 2026-09-20) whose names even its own
    page does not show: ``progress`` stays ``None`` and ``progress_code`` keeps
    the raw code.
    """
    limit = _v39_limit(limit)
    codes = {v: k for k, v in _BUYBACK_PROGRESS.items()}
    if progress is not None and progress not in codes:
        raise ValueError("progress 只能是 " + " / ".join(codes))
    equal: dict[str, Any] = {}
    if ticker is not None:
        equal["DIM_SCODE"] = _strict_stock_code(ticker)  # this table's code field is DIM_SCODE
    if progress:
        equal["REPURPROGRESS"] = codes[progress]
    filter_str = "".join(f'({field}="{value}")' for field, value in equal.items())
    rows = _em_event_rows(
        "RPTA_WEB_GETHGLIST_NEW",
        filter_str,
        "UPD,DIM_SCODE,REPURCODE",
        "-1,1,1",
        limit,
        narrowed=bool(equal),
        equal=equal,
    )
    out = [
        {
            "code": r["DIM_SCODE"],
            "name": r.get("SECURITYSHORTNAME"),
            "progress": _BUYBACK_PROGRESS.get(r.get("REPURPROGRESS")),
            "progress_code": r.get("REPURPROGRESS"),
            "plan_start": _em_day(r.get("REPURSTARTDATE")),
            "plan_end": _em_day(r.get("REPURENDDATE")),
            "price_cap": _v39_num(r.get("REPURPRICECAP")),
            "shares_lower": _v39_num(r.get("REPURNUMLOWER")),
            "shares_upper": _v39_num(r.get("REPURNUMCAP")),
            "amount_lower": _v39_num(r.get("REPURAMOUNTLOWER")),
            "amount_upper": _v39_num(r.get("REPURAMOUNTLIMIT")),
            "pct_total_lower": _v39_num(r.get("ZSZXX")),
            "pct_total_upper": _v39_num(r.get("ZSZSX")),
            "done_shares": _v39_num(r.get("REPURNUM")),
            "done_amount": _v39_num(r.get("REPURAMOUNT")),
            "done_price_low": _v39_num(r.get("REPURPRICELOWER1")),
            "done_price_high": _v39_num(r.get("REPURPRICECAP1")),
            "latest_notice": _em_day(r.get("UPDATEDATE")),
            "objective": r.get("REPUROBJECTIVE"),
        }
        for r in rows
    ]
    target = normalize_ticker_symbol(ticker) if ticker is not None else progress or "market-wide"
    _capture_vendor_raw(
        rows,
        metadata={"provider": "eastmoney", "dataset": "share_buyback", "ticker": ticker},
    )
    return _format_report(
        pd.DataFrame(out, columns=_BUYBACK_COLUMNS),
        title=f"China A-share share buybacks for {target}",
        caveat=(
            "EastMoney datacenter RPTA_WEB_GETHGLIST_NEW; code field is DIM_SCODE; "
            "shares in shares, amounts in yuan, pct_total_* is % of total shares before the "
            "notice; progress_code 007/008 has no published name and maps to None."
        ),
    )


# ---------------------------------------------------------------------------
# §14.4 股权质押比例 RPT_CSDC_LIST
# ---------------------------------------------------------------------------

_PLEDGE_COLUMNS = [
    "date",
    "code",
    "name",
    "industry",
    "pledge_ratio_pct",
    "pledged_shares_10k",
    "pledged_mktcap_10k",
    "pledge_count",
    "unrestricted_pledged_10k",
    "restricted_pledged_10k",
]


@_source_contract
def get_a_share_equity_pledge(ticker=None, date=None, limit=5000) -> str:
    """股权质押比例 (equity pledge ratio) — ChinaClear weekly statistics via EastMoney.

    ``ticker`` given: that stock's history, newest date first.  ``date`` given:
    the whole market on that statistical day.  Neither: the whole market on the
    latest statistical day.  Both together raise ``ValueError`` (one is never
    silently dropped).  ChinaClear publishes weekly (usually Friday), so a date
    that is not a statistical day raises ``ValueError``.

    ``pledge_ratio_pct`` is pledged shares as a percent of total share capital;
    shares are in 10k shares and market cap in 10k yuan.  ChinaClear covers
    SH/SZ only (the full market held 2212 rows on 2026-09-20 with no BSE row), so
    a BSE code raises ``ValueError`` instead of returning an empty table.
    """
    limit = _v39_limit(limit)
    if ticker is not None and date is not None:
        raise ValueError("ticker 与 date 只能给一个：ticker 取该股历次统计，date 取该统计日全市场")
    code = _strict_stock_code(ticker) if ticker is not None else None
    if code is not None and infer_a_share_exchange(code) == "BJ":
        raise ValueError(f"{ticker} 是北交所证券；中国结算质押统计只覆盖沪深，没有北交所数据")
    report = "RPT_CSDC_LIST"
    if code is not None:
        rows = _em_event_rows(
            report,
            _em_event_filter(code),
            "TRADE_DATE",
            "-1",
            limit,
            narrowed=True,
            equal={"SECURITY_CODE": code},
        )
    else:
        if date is None:
            latest = _em_event_rows(report, "", "TRADE_DATE", "-1", 1, narrowed=False)
            date = latest[0]["TRADE_DATE"]
        day = _v39_date(str(date)[:10])
        rows = _em_event_rows(
            report,
            f"(TRADE_DATE='{day}')",
            "PLEDGE_RATIO,SECURITY_CODE",
            "-1,1",
            limit,
            narrowed=True,
            dates={"TRADE_DATE": (day, day)},
        )
        if not rows:
            raise ValueError(f"{day} 不是中国结算质押统计日（按周发布，通常为周五）")
    out = []
    for r in rows:
        total = _v39_num(r.get("REPURCHASE_BALANCE"))
        free, locked = (
            _v39_num(r.get("REPURCHASE_UNLIMITED_BALANCE")),
            _v39_num(r.get("REPURCHASE_LIMITED_BALANCE")),
        )
        if (
            None not in (total, free, locked)
            and abs(free + locked - total) > max(1.0, total * 0.001)
        ):
            raise ChinaDataUnavailableError(
                f"东财质押数据 无限售 + 限售 ≠ 合计: {r['SECURITY_CODE']} {r['TRADE_DATE']}"
            )
        out.append(
            {
                "date": _em_day(r.get("TRADE_DATE")),
                "code": r["SECURITY_CODE"],
                "name": r.get("SECURITY_NAME_ABBR"),
                "industry": r.get("INDUSTRY"),
                "pledge_ratio_pct": _v39_num(r.get("PLEDGE_RATIO")),
                "pledged_shares_10k": total,
                "pledged_mktcap_10k": _v39_num(r.get("PLEDGE_MARKET_CAP")),
                "pledge_count": _v39_num(r.get("PLEDGE_DEAL_NUM")),
                "unrestricted_pledged_10k": free,
                "restricted_pledged_10k": locked,
            }
        )
    data = pd.DataFrame(out, columns=_PLEDGE_COLUMNS)
    if data.duplicated(["date", "code"]).any():
        raise ChinaDataUnavailableError("东财质押数据 日期+代码 重复")
    target = (
        normalize_ticker_symbol(ticker)
        if ticker is not None
        else (str(date) if date is not None else "market-wide")
    )
    _capture_vendor_raw(
        rows,
        metadata={"provider": "eastmoney", "dataset": "equity_pledge", "ticker": ticker},
    )
    return _format_report(
        data,
        title=f"China A-share equity pledge ratios for {target}",
        caveat=(
            "EastMoney datacenter RPT_CSDC_LIST; ChinaClear weekly statistics (usually Friday); "
            "SH/SZ only (no BSE); shares in 10k shares, market cap in 10k yuan; "
            "pledge_ratio_pct is % of total share capital."
        ),
    )


# ---------------------------------------------------------------------------
# §14.5 新股申购日历 RPTA_APP_IPOAPPLY
# ---------------------------------------------------------------------------

_IPO_COLUMNS = [
    "code",
    "name",
    "apply_code",
    "exchange",
    "board",
    "apply_date",
    "ballot_date",
    "pay_date",
    "listing_date",
    "issue_price",
    "issue_pe",
    "industry_pe",
    "issue_shares_10k",
    "online_shares",
    "apply_upper_shares",
    "top_apply_mktcap_10k",
    "win_rate_pct",
    "first_close",
    "first_close_chg_pct",
]


@_source_contract
def get_a_share_ipo_calendar(limit=100) -> str:
    """新股申购日历 (new-issue subscription calendar), SH/SZ/BJ, apply date descending.

    Includes subscriptions that have not happened yet.  ``issue_price`` is
    ``None`` before pricing.  ``issue_shares_10k`` is in 10k shares;
    ``online_shares`` / ``apply_upper_shares`` are in shares;
    ``top_apply_mktcap_10k`` is the market value required to subscribe at the
    ceiling (10k yuan); ``win_rate_pct`` is the online winning rate in %;
    ``first_close_chg_pct`` is the first-day close gain in % (``None`` before
    listing).
    """
    limit = _v39_limit(limit)
    rows = _em_event_rows(
        "RPTA_APP_IPOAPPLY", "", "APPLY_DATE,SECURITY_CODE", "-1,-1", limit, narrowed=False
    )
    out = [
        {
            "code": r["SECURITY_CODE"],
            "name": r.get("SECURITY_NAME"),
            "apply_code": r.get("APPLY_CODE"),
            "exchange": r.get("TRADE_MARKET"),
            # MARKET carries the precise board ("深交所主板 / 深交所创业板");
            # MARKET_TYPE_NEW labels not-yet-listed names "深交所其他", but BSE
            # new issues only have the latter.
            "board": r.get("MARKET") or r.get("MARKET_TYPE_NEW"),
            "apply_date": _em_day(r.get("APPLY_DATE")),
            "ballot_date": _em_day(r.get("BALLOT_NUM_DATE")),
            "pay_date": _em_day(r.get("BALLOT_PAY_DATE")),
            "listing_date": _em_day(r.get("LISTING_DATE")),
            "issue_price": _v39_num(r.get("ISSUE_PRICE")) or None,  # null or 0 before pricing
            "issue_pe": _v39_num(r.get("AFTER_ISSUE_PE")),
            "industry_pe": _v39_num(r.get("INDUSTRY_PE")),
            "issue_shares_10k": _v39_num(r.get("ISSUE_NUM")),
            "online_shares": _v39_num(r.get("ONLINE_ISSUE_NUM")),
            "apply_upper_shares": _v39_num(r.get("ONLINE_APPLY_UPPER")),
            "top_apply_mktcap_10k": _v39_num(r.get("TOP_APPLY_MARKETCAP")),
            "win_rate_pct": _v39_num(r.get("ONLINE_ISSUE_LWR")),
            "first_close": _v39_num(r.get("CLOSE_PRICE")),
            "first_close_chg_pct": _v39_num(r.get("LD_CLOSE_CHANGE")),
        }
        for r in rows
    ]
    data = pd.DataFrame(out, columns=_IPO_COLUMNS)
    if data.duplicated(["code"]).any():
        raise ChinaDataUnavailableError("东财新股日历代码重复")
    _capture_vendor_raw(
        rows, metadata={"provider": "eastmoney", "dataset": "ipo_calendar", "ticker": None}
    )
    return _format_report(
        data,
        title="China A-share new-issue subscription calendar",
        caveat=(
            "EastMoney datacenter RPTA_APP_IPOAPPLY; apply date descending, includes upcoming "
            "subscriptions; issue_price is null before pricing; issue_shares_10k in 10k shares, "
            "online_shares / apply_upper_shares in shares, top_apply_mktcap_10k in 10k yuan."
        ),
    )


# ---------------------------------------------------------------------------
# §6.8 ST / *ST 名单 (clist 风险警示板 + BSE full table, baostock fallback)
# ---------------------------------------------------------------------------

class _ClistUnreachableError(ChinaDataUnavailableError):
    """Both push2 hosts failed at the transport layer, so a fallback is legitimate.

    A server-side abnormal payload is *not* this error: it must propagate rather
    than let the ST list fall back to a SH/SZ-only roster.
    """


def _em_clist_all(
    fs: str, fields: str, page_size: int = 100
) -> tuple[list[dict[str, Any]], str]:
    """EastMoney clist full pagination; falls back to push2delay on transport failure.

    Network-level failures try the next host.  A server-side abnormal payload
    (including a non-JSON error page) raises without switching hosts, so it can
    never be mistaken for a smaller but valid list.
    """
    errors: list[str] = []
    for host in EM_CLIST_HOSTS:
        url = host + "/api/qt/clist/get"
        rows: list[dict[str, Any]] = []
        page, total = 1, None
        try:
            while True:
                payload = em_get(
                    url,
                    params={
                        "pn": page,
                        "pz": page_size,
                        "po": 1,
                        "np": 1,
                        "fltt": 2,
                        "invt": 2,
                        "fid": "f12",
                        "fs": fs,
                        "fields": fields,
                    },
                    timeout=15,
                )
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict) or payload.get("rc") != 0 or not data:
                    raise ChinaDataUnavailableError(
                        f"东财 clist 返回异常或无数据（fs={fs}）: {str(payload)[:100]}"
                    )
                page_total = _v39_count(data.get("total"), f"东财 clist total（fs={fs}）")
                diff = _v39_rows(data.get("diff"), f"东财 clist 的 diff（fs={fs}）")
                if total is None:
                    total = page_total
                elif page_total != total:
                    # The roster changed mid-pagination: stitching the pages
                    # would mix two different lists.
                    raise ChinaDataUnavailableError(
                        f"东财 clist 翻页时 total 从 {total} 变成 {page_total}，请重试"
                    )
                rows.extend(diff)
                if not diff or len(rows) >= total:
                    break
                page += 1
        except (VendorHTTPError, VendorRateLimitError) as exc:
            # status 200 means the host answered with unusable content; that is
            # a contract failure, not a host outage, so it must not be retried
            # on the delayed mirror.
            if getattr(exc, "status_code", 0) == 200:
                raise ChinaDataUnavailableError(f"东财 clist 请求失败（fs={fs}）: {exc}") from exc
            errors.append(f"{host}: {type(exc).__name__}")
            continue
        if len(rows) != total:
            raise ChinaDataUnavailableError(
                f"东财 clist 翻页后 {len(rows)} 条，与 total={total} 不符"
            )
        return rows, url
    raise _ClistUnreachableError("东财 push2 / push2delay 均不可达: " + "; ".join(errors))


def _st_list_baostock(reason: str) -> str:
    """Fallback ST snapshot from baostock (SH/SZ only, no price) when EastMoney is down."""
    try:
        import baostock as bs
    except ImportError as exc:
        raise AshareCapabilityUnavailableError(
            "st_stock_list", "baostock", f"baostock 未安装，且东财不可达：{reason}"
        ) from exc
    login = bs.login()
    if getattr(login, "error_code", "0") != "0":
        raise AshareCapabilityUnavailableError(
            "st_stock_list",
            "baostock",
            f"login failed: {getattr(login, 'error_code', '?')} {getattr(login, 'error_msg', '')}",
        )
    try:
        result = bs.query_stock_basic(code_name="ST")
        if getattr(result, "error_code", "0") != "0":
            raise AshareCapabilityUnavailableError(
                "st_stock_list", "baostock", f"query failed: {result.error_code} {result.error_msg}"
            )
        raw_rows = []
        while result.next():
            raw_rows.append(result.get_row_data())
        basic = pd.DataFrame(raw_rows, columns=result.fields)
    finally:
        bs.logout()
    required = {"code", "code_name", "type", "status"}
    if basic.empty or not required.issubset(basic.columns):
        raise AshareCapabilityUnavailableError(
            "st_stock_list", "baostock", "证券列表为空或结构已变（缺少 code/code_name/type/status）"
        )
    # type 1 = stock, status 1 = listed
    picked = basic[
        (basic["type"] == "1")
        & (basic["status"] == "1")
        & basic["code_name"].str.upper().str.contains("ST")
    ]
    out = []
    for code, name in zip(picked["code"], picked["code_name"], strict=False):
        exchange, _, digits = str(code).partition(".")
        out.append(
            {
                "code": digits,
                "market": exchange,
                "name": name,
                "st_type": "*ST" if str(name).startswith("*") else "ST",
                "price": None,
                "pct_change": None,
            }
        )
    data = pd.DataFrame(out, columns=_ST_COLUMNS)
    if data.empty:
        raise AshareCapabilityUnavailableError(
            "st_stock_list", "baostock", "证券列表里没有筛出 ST，结果不可信"
        )
    _capture_vendor_raw(
        raw_rows, metadata={"provider": "baostock", "dataset": "st_stock_list", "ticker": None}
    )
    coverage = "沪深（东财不可达，baostock 不含北交所）"
    return _format_report(
        data,
        title="China A-share ST / *ST list (baostock fallback)",
        caveat=f"SH/SZ only, no price; coverage={coverage}",
        source="baostock",
        extra_lines=(f"# Coverage: {coverage}", f"# Fallback reason: {reason}"),
    )


@_source_contract
def get_a_share_st_stock_list() -> str:
    """全市场 ST / *ST 名单 (risk-warning snapshot) for the current day.

    SH/SZ come from EastMoney's 风险警示板 filter (includes B shares); the BSE is
    not part of that filter, so its full table is fetched and filtered by name.
    When both EastMoney domains are unreachable the adapter falls back to
    baostock's security list filtered by name (SH/SZ only, no price), and says so
    in the report header.  ``price`` / ``pct_change`` carry ~15-minute delay when
    served by push2delay; the chosen host is recorded in the note.

    Both halves must be non-empty: an empty BSE table would be mislabelled as a
    complete 沪深京 roster, so it raises instead.
    """
    try:
        shsz, url = _em_clist_all(_CLIST_SHSZ_RISK, _CLIST_FIELDS)
        bj, bj_url = _em_clist_all(_CLIST_BSE_ALL, _CLIST_FIELDS)
    except _ClistUnreachableError as exc:
        return _st_list_baostock(str(exc))
    if not shsz or not bj:
        raise ChinaDataUnavailableError(
            f"东财风险警示板 {len(shsz)} 条、北交所全表 {len(bj)} 条，"
            "有一边为空，不能当成沪深京完整名单"
        )
    if bj_url != url:
        url = url + " | " + bj_url  # the two calls can land on different hosts
    rows = []
    for rec, is_bj in [(r, False) for r in shsz] + [(r, True) for r in bj]:
        # Code / market id / name are identity fields: a missing or changed f13
        # treated as Shenzhen would name the wrong market, and a blank name would
        # silently drop the BSE half while the result still says 沪深京.
        code, market_id, name = rec["f12"], rec["f13"], str(rec["f14"]).strip()
        if (
            not re.fullmatch(r"[0-9]{6}", str(code))
            or isinstance(market_id, bool)
            or market_id not in (0, 1)
        ):
            raise ChinaDataUnavailableError(
                f"东财 clist 返回了认不出的代码 / 市场号: f12={code!r} f13={market_id!r}"
            )
        if not name:
            raise ChinaDataUnavailableError(
                f"东财 clist 里 {code} 没有名称，ST 判定要靠名称，不能当成完整名单"
            )
        if is_bj and "ST" not in name.upper():
            continue
        rows.append(
            {
                "code": code,
                "market": "bj" if is_bj else ("sh" if market_id == 1 else "sz"),
                "name": name,
                "st_type": "*ST" if name.startswith("*") else "ST",
                "price": _v39_num(rec.get("f2")),
                "pct_change": _v39_num(rec.get("f3")),
            }
        )
    data = pd.DataFrame(rows, columns=_ST_COLUMNS)
    if data.empty or data.duplicated(["code"]).any():
        raise ChinaDataUnavailableError("ST 名单为空或代码重复，不能当成完整快照")
    _capture_vendor_raw(
        rows, metadata={"provider": "eastmoney", "dataset": "st_stock_list", "ticker": None}
    )
    return _format_report(
        data,
        title="China A-share ST / *ST list (risk-warning board, SH/SZ/BJ)",
        caveat=(
            "EastMoney clist 风险警示板 (沪深, includes B shares) + BSE full table filtered by "
            "name; BSE rows are kept only when the name contains ST; price/pct_change are "
            f"~15-minute delayed on push2delay; source_url={url}"
        ),
        extra_lines=("# Coverage: 沪深京",),
    )
