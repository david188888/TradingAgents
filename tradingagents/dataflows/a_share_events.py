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

Degradation contract: a changed schema, an unavailable optional dependency
(baostock for the ST fallback), a provider error, a truncated scan, or an
unproven pagination raises a typed ``ChinaDataUnavailableError`` /
``AshareCapabilityUnavailableError``.  A *narrowed* query the provider completed
with no match is not a degradation: it is returned as a ``CoveredText`` whose
report header says so and whose ``ScreeningCoverageV1`` carries
``completeness="complete"`` with ``item_count=0``.  A whole-market query that
returns nothing still raises, because "the whole market had no such event" is
not something this interface can answer.

The pagination primitives (``strict_limit`` / ``strict_rows`` /
``em_datacenter_strict`` / ``datacenter_screening_coverage`` …) live in
:mod:`tradingagents.dataflows.eastmoney`; this module imports them so every
EastMoney datacenter adapter shares one pager and one coverage vocabulary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date_cls, datetime
from functools import wraps
from typing import Any

import pandas as pd

from .china_capabilities import AshareCapabilityUnavailableError
from .china_data import ChinaDataUnavailableError
from .coverage import CoveredText, ScreeningCoverageV1
from .eastmoney import (
    DatacenterPage,
    datacenter_screening_coverage,
    dedupe_datacenter_rows,
    em_datacenter_strict,
    em_get,
    strict_count,
    strict_date_arg,
    strict_limit,
    strict_number,
    strict_rows,
    strict_source_date,
    strict_source_day,
    strict_stock_code,
)
from .errors import VendorHTTPError, VendorRateLimitError
from .ticker_utils import infer_a_share_exchange, normalize_ticker_symbol

__all__ = [
    "get_a_share_earnings_forecast",
    "get_a_share_equity_pledge",
    "get_a_share_institution_survey",
    "get_a_share_ipo_calendar",
    "get_a_share_share_buyback",
    "get_a_share_st_stock_list",
]

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
# Shared reporting helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    """The analysis date for an adapter that has no report date of its own."""
    return _date_cls.today().isoformat()


@dataclass(frozen=True)
class EventQuery:
    """Rows plus the pagination facts needed to make an honest coverage claim.

    ``_em_event_rows`` used to return a bare ``list``, which threw away the
    pager's ``pages`` / ``count`` / ``truncated`` facts exactly where the
    adapter needed them to distinguish "the provider answered nothing" from
    "the cap cut the answer short".
    """

    rows: list[dict[str, Any]]
    page: DatacenterPage


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
    empty_note: str | None = None,
) -> str:
    """House-style source-labelled markdown report; empty rows degrade loudly.

    An empty table is only rendered when the caller supplies ``empty_note``,
    which is the one case where the emptiness is a proven provider answer rather
    than a failed fetch.
    """
    if data.empty and empty_note is None:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")
    note = f"{caveat} {empty_note}" if empty_note else caveat
    return "\n".join(
        [
            f"# {title}",
            f"# Source: {source}",
            f"# Note: {note}",
            f"# Total records: {len(data)}",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            *extra_lines,
            "",
            data.to_csv(index=False),
        ]
    )


def _screening_scope(**parts: str | None) -> str:
    """Describe what was screened in the provider's own terms."""
    described = " ".join(f"{key}={value}" for key, value in parts.items() if value)
    return described or "market-wide"


def _coverage_line(coverage: ScreeningCoverageV1) -> str:
    """A header line a reader cannot mistake for a fetch failure.

    ``complete`` with zero rows is rendered as ``complete (0 matching records)``
    so the report itself states that the provider answered; every unproven or
    truncated scan names its degradation code instead.
    """
    detail: list[str] = []
    if coverage.completeness == "complete" and coverage.item_count == 0:
        detail.append("0 matching records")
    detail.extend(coverage.degradations)
    suffix = f" ({'; '.join(detail)})" if detail else ""
    return f"# Coverage: {coverage.completeness}{suffix}"


def _screening_report(
    data: pd.DataFrame,
    coverage: ScreeningCoverageV1,
    *,
    title: str,
    caveat: str,
    empty_note: str | None = None,
) -> CoveredText:
    """Render an event report and carry its ``ScreeningCoverageV1``.

    Only ``complete`` coverage may render an empty table: a zero-row scan whose
    pagination was not proven still raises, so "throttled" can never be read as
    "no such event".
    """
    if not data.empty:
        empty_note = None
    elif coverage.completeness != "complete":
        raise ChinaDataUnavailableError(
            f"eastmoney returned no rows and did not prove the query completed for {title}."
        )
    elif empty_note is None:
        empty_note = (
            "The provider completed the query and no matching record exists "
            f"({coverage.requested_scope})."
        )
    report = _format_report(
        data,
        title=title,
        caveat=caveat,
        extra_lines=(_coverage_line(coverage),),
        empty_note=empty_note,
    )
    return CoveredText(report, coverage)


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
    if start and end and strict_date_arg(start) > strict_date_arg(end):
        raise ValueError("start 不能晚于 end")
    parts = [extra] if extra else []
    if ticker is not None:
        parts.append(f'(SECURITY_CODE="{strict_stock_code(ticker)}")')
    if start:
        parts.append(f"({date_field}>='{strict_date_arg(start)}')")
    if end:
        parts.append(f"({date_field}<='{strict_date_arg(end)}')")
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
) -> EventQuery:
    """Fetch event rows and prove the answer is complete and truly the requested slice.

    ``narrowed=False`` (whole market, no condition at all) with zero rows means
    the interface broke and raises; with a ticker/date condition zero rows is
    "genuinely none" and returns an empty ``EventQuery`` whose ``page`` proves
    the query finished.

    The sort key must uniquely identify a row: EastMoney slices by page, so a
    tie repeats one row and drops another (measured on the pledge table: sorted
    by ratio alone, 2212 rows repeated 1 and lost 1).  Identical rows -> raise
    (``dedupe_datacenter_rows``).

    Server-side filtering is only a request: ``equal={field: value}`` and
    ``dates={date_field: (lo, hi)}`` are re-checked row by row, so a filter the
    interface ignored, or a stale cache page for another instrument/period,
    raises instead of being returned as the answer.
    """
    page = em_datacenter_strict(
        report,
        filter_str,
        sort_columns,
        sort_types,
        page_size=min(limit, 500),
        max_rows=limit,
        extra=extra,
    )
    if not page.rows and not narrowed:
        raise ChinaDataUnavailableError(f"东财 {report} 全市场返回 0 行，接口可能改了")
    rows = dedupe_datacenter_rows(page, report)
    for r in rows:
        for field, value in (equal or {}).items():
            if r.get(field) != value:
                raise ChinaDataUnavailableError(
                    f"东财 {report} 请求 {field}={value}，却返回了 {r.get(field)!r}，结果不可信"
                )
        for field, (lo, hi) in (dates or {}).items():
            day = strict_source_date(str(r.get(field) or "")[:10])
            if (lo and day < lo) or (hi and day > hi):
                raise ChinaDataUnavailableError(
                    f"东财 {report} 请求 {field} 在 {lo or ''}~{hi or ''}，却返回了 {day}，结果不可信"
                )
    return EventQuery(rows=rows, page=page)


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
def get_a_share_earnings_forecast(ticker=None, report_date=None, limit=500) -> CoveredText:
    """业绩预告 (earnings pre-announcement), EastMoney datacenter, SH/SZ/BJ.

    No ``ticker`` = the whole market, newest ``limit`` rows by notice date.
    ``report_date`` is the reporting period, e.g. ``'2026-09-30'`` (``'20260930'``
    is accepted too).  One pre-announcement is split across indicators
    (``indicator`` = 归母净利润 / 扣非净利润 / 营业收入 …).  Amounts are in yuan,
    ``change_pct_*`` is the year-on-year change in %.

    A ``ticker`` / ``report_date`` query the provider completed with no match is
    returned as a ``CoveredText`` whose header says so, not raised.
    """
    limit = strict_limit(limit)
    period = strict_date_arg(report_date) if report_date else None
    extra = f"(REPORT_DATE='{period}')" if period else ""
    filter_str = _em_event_filter(ticker, extra=extra)
    code = strict_stock_code(ticker) if ticker is not None else None
    query = _em_event_rows(
        "RPT_PUBLIC_OP_NEWPREDICT",
        filter_str,
        "NOTICE_DATE,SECURITY_CODE,REPORT_DATE,PREDICT_FINANCE_CODE",
        "-1,1,-1,1",
        limit,
        narrowed=bool(ticker or report_date),
        equal={} if code is None else {"SECURITY_CODE": code},
        dates={"REPORT_DATE": (period, period)} if period else None,
    )
    rows = query.rows
    out = [
        {
            "code": r["SECURITY_CODE"],
            "name": r.get("SECURITY_NAME_ABBR"),
            "notice_date": strict_source_day(r.get("NOTICE_DATE")),
            "report_date": strict_source_day(r.get("REPORT_DATE")),
            "indicator": r.get("PREDICT_FINANCE"),
            "forecast_type": r.get("PREDICT_TYPE"),
            "amount_lower": strict_number(r.get("PREDICT_AMT_LOWER")),
            "amount_upper": strict_number(r.get("PREDICT_AMT_UPPER")),
            "change_pct_lower": strict_number(r.get("ADD_AMP_LOWER")),
            "change_pct_upper": strict_number(r.get("ADD_AMP_UPPER")),
            "prior_year_amount": strict_number(r.get("PREYEAR_SAME_PERIOD")),
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
    coverage = datacenter_screening_coverage(
        capability="earnings_forecast",
        source_id="eastmoney.earnings_forecast",
        scope=_screening_scope(
            ticker=normalize_ticker_symbol(ticker) if ticker is not None else None,
            report_date=period,
        ),
        page=query.page,
        as_of=period or _today(),
    )
    return _screening_report(
        pd.DataFrame(out, columns=_FORECAST_COLUMNS),
        coverage,
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
) -> CoveredText:
    """机构调研 (institution survey), EastMoney datacenter.

    ``detail=False``: one row per survey with ``org_count`` participating
    institutions.  ``detail=True``: one row per institution, adding
    ``org_name`` / ``org_type`` / ``investigators`` (many record sheets omit the
    type and the attendee names, so those stay ``None``).
    ``start`` / ``end`` filter the notice date (``notice_date``); ``survey_date``
    is the actual reception day, usually a few days before the notice.

    A ticker/date query the provider completed with no match is returned as a
    ``CoveredText`` whose header says so, not raised.
    """
    limit = strict_limit(limit)
    extra = '(IS_SOURCE="1")' + ("" if detail else '(NUMBERNEW="1")')
    filter_str = _em_event_filter(ticker, "NOTICE_DATE", start, end, extra)
    sort = (
        ("NOTICE_DATE,SECURITY_CODE,RECEIVE_START_DATE,NUMBERNEW", "-1,1,-1,1")
        if detail
        else ("NOTICE_DATE,SECURITY_CODE,RECEIVE_START_DATE", "-1,1,-1")
    )
    equal: dict[str, Any] = {"IS_SOURCE": "1"} if detail else {"IS_SOURCE": "1", "NUMBERNEW": "1"}
    window = (strict_date_arg(start) if start else None, strict_date_arg(end) if end else None)
    if ticker is not None:
        equal["SECURITY_CODE"] = strict_stock_code(ticker)
    query = _em_event_rows(
        "RPT_ORG_SURVEYNEW",
        filter_str,
        sort[0],
        sort[1],
        limit,
        narrowed=bool(ticker or start or end),
        equal=equal,
        dates={"NOTICE_DATE": window} if start or end else None,
    )
    rows = query.rows
    out = []
    for r in rows:
        row = {
            "code": r["SECURITY_CODE"],
            "name": r.get("SECURITY_NAME_ABBR"),
            "notice_date": strict_source_day(r.get("NOTICE_DATE")),
            "survey_date": strict_source_day(r.get("RECEIVE_START_DATE")),
            "survey_end": strict_source_day(r.get("RECEIVE_END_DATE")),
            "org_count": strict_number(r.get("SUM")),
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
    coverage = datacenter_screening_coverage(
        capability="institution_survey",
        source_id="eastmoney.institution_survey",
        scope=_screening_scope(
            ticker=normalize_ticker_symbol(ticker) if ticker is not None else None,
            notice_start=window[0],
            notice_end=window[1],
            level="detail" if detail else "summary",
        ),
        page=query.page,
        as_of=window[1] or _today(),
    )
    return _screening_report(
        pd.DataFrame(out, columns=columns),
        coverage,
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
def get_a_share_share_buyback(ticker=None, progress=None, limit=500) -> CoveredText:
    """股票回购 (share buyback) — plan and execution progress, one plan per row.

    Sorted by latest notice date descending.  ``progress`` is ``None`` or one of
    ``'董事会预案' / '股东大会通过' / '股东大会否决' / '实施中' / '停止实施' / '完成实施'``.
    Shares are in shares, amounts in yuan, ``pct_total_*`` is the percent of the
    total share capital on the day before the notice.  ``done_*`` is the executed
    part (``None`` before execution starts).  EastMoney has two further progress
    codes (007 / 008; 13 of 5516 rows on 2026-09-20) whose names even its own
    page does not show: ``progress`` stays ``None`` and ``progress_code`` keeps
    the raw code.

    A ticker/progress query the provider completed with no match is returned as
    a ``CoveredText`` whose header says so, not raised.
    """
    limit = strict_limit(limit)
    codes = {v: k for k, v in _BUYBACK_PROGRESS.items()}
    if progress is not None and progress not in codes:
        raise ValueError("progress 只能是 " + " / ".join(codes))
    equal: dict[str, Any] = {}
    if ticker is not None:
        equal["DIM_SCODE"] = strict_stock_code(ticker)  # this table's code field is DIM_SCODE
    if progress:
        equal["REPURPROGRESS"] = codes[progress]
    filter_str = "".join(f'({field}="{value}")' for field, value in equal.items())
    query = _em_event_rows(
        "RPTA_WEB_GETHGLIST_NEW",
        filter_str,
        "UPD,DIM_SCODE,REPURCODE",
        "-1,1,1",
        limit,
        narrowed=bool(equal),
        equal=equal,
    )
    rows = query.rows
    out = [
        {
            "code": r["DIM_SCODE"],
            "name": r.get("SECURITYSHORTNAME"),
            "progress": _BUYBACK_PROGRESS.get(r.get("REPURPROGRESS")),
            "progress_code": r.get("REPURPROGRESS"),
            "plan_start": strict_source_day(r.get("REPURSTARTDATE")),
            "plan_end": strict_source_day(r.get("REPURENDDATE")),
            "price_cap": strict_number(r.get("REPURPRICECAP")),
            "shares_lower": strict_number(r.get("REPURNUMLOWER")),
            "shares_upper": strict_number(r.get("REPURNUMCAP")),
            "amount_lower": strict_number(r.get("REPURAMOUNTLOWER")),
            "amount_upper": strict_number(r.get("REPURAMOUNTLIMIT")),
            "pct_total_lower": strict_number(r.get("ZSZXX")),
            "pct_total_upper": strict_number(r.get("ZSZSX")),
            "done_shares": strict_number(r.get("REPURNUM")),
            "done_amount": strict_number(r.get("REPURAMOUNT")),
            "done_price_low": strict_number(r.get("REPURPRICELOWER1")),
            "done_price_high": strict_number(r.get("REPURPRICECAP1")),
            "latest_notice": strict_source_day(r.get("UPDATEDATE")),
            "objective": r.get("REPUROBJECTIVE"),
        }
        for r in rows
    ]
    target = normalize_ticker_symbol(ticker) if ticker is not None else progress or "market-wide"
    _capture_vendor_raw(
        rows,
        metadata={"provider": "eastmoney", "dataset": "share_buyback", "ticker": ticker},
    )
    coverage = datacenter_screening_coverage(
        capability="share_buyback",
        source_id="eastmoney.share_buyback",
        scope=_screening_scope(
            ticker=normalize_ticker_symbol(ticker) if ticker is not None else None,
            progress=progress,
        ),
        page=query.page,
        as_of=_today(),
    )
    return _screening_report(
        pd.DataFrame(out, columns=_BUYBACK_COLUMNS),
        coverage,
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
def get_a_share_equity_pledge(ticker=None, date=None, limit=5000) -> CoveredText:
    """股权质押比例 (equity pledge ratio) — ChinaClear weekly statistics via EastMoney.

    ``ticker`` given: that stock's history, newest date first.  ``date`` given:
    the whole market on that statistical day.  Neither: the whole market on the
    latest statistical day.  Both together raise ``ValueError`` (one is never
    silently dropped).  ChinaClear publishes weekly (usually Friday), so a date
    that is not a statistical day is reported as ``complete`` coverage with zero
    rows and a note explaining the weekly cadence; the caller can tell that apart
    from a failed fetch from the report header and the coverage object.

    ``pledge_ratio_pct`` is pledged shares as a percent of total share capital;
    shares are in 10k shares and market cap in 10k yuan.  ChinaClear covers
    SH/SZ only (the full market held 2212 rows on 2026-09-20 with no BSE row), so
    a BSE code raises ``ValueError`` instead of returning an empty table.
    """
    limit = strict_limit(limit)
    if ticker is not None and date is not None:
        raise ValueError("ticker 与 date 只能给一个：ticker 取该股历次统计，date 取该统计日全市场")
    code = strict_stock_code(ticker) if ticker is not None else None
    if code is not None and infer_a_share_exchange(code) == "BJ":
        raise ValueError(f"{ticker} 是北交所证券；中国结算质押统计只覆盖沪深，没有北交所数据")
    report = "RPT_CSDC_LIST"
    empty_note = None
    day: str | None = None
    if code is not None:
        query = _em_event_rows(
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
            date = latest.rows[0]["TRADE_DATE"]
        day = strict_date_arg(str(date)[:10])
        query = _em_event_rows(
            report,
            f"(TRADE_DATE='{day}')",
            "PLEDGE_RATIO,SECURITY_CODE",
            "-1,1",
            limit,
            narrowed=True,
            dates={"TRADE_DATE": (day, day)},
        )
        if not query.rows:
            empty_note = (
                f"{day} 不是中国结算质押统计日（按周发布，通常为周五）："
                "the provider completed the query and no matching record exists."
            )
    rows = query.rows
    out = []
    for r in rows:
        total = strict_number(r.get("REPURCHASE_BALANCE"))
        free, locked = (
            strict_number(r.get("REPURCHASE_UNLIMITED_BALANCE")),
            strict_number(r.get("REPURCHASE_LIMITED_BALANCE")),
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
                "date": strict_source_day(r.get("TRADE_DATE")),
                "code": r["SECURITY_CODE"],
                "name": r.get("SECURITY_NAME_ABBR"),
                "industry": r.get("INDUSTRY"),
                "pledge_ratio_pct": strict_number(r.get("PLEDGE_RATIO")),
                "pledged_shares_10k": total,
                "pledged_mktcap_10k": strict_number(r.get("PLEDGE_MARKET_CAP")),
                "pledge_count": strict_number(r.get("PLEDGE_DEAL_NUM")),
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
    coverage = datacenter_screening_coverage(
        capability="equity_pledge",
        source_id="eastmoney.equity_pledge",
        scope=(
            f"ticker={normalize_ticker_symbol(ticker)}"
            if code is not None
            else _screening_scope(trade_date=day)
        ),
        page=query.page,
        as_of=day or _today(),
    )
    return _screening_report(
        data,
        coverage,
        title=f"China A-share equity pledge ratios for {target}",
        caveat=(
            "EastMoney datacenter RPT_CSDC_LIST; ChinaClear weekly statistics (usually Friday); "
            "SH/SZ only (no BSE); shares in 10k shares, market cap in 10k yuan; "
            "pledge_ratio_pct is % of total share capital."
        ),
        empty_note=empty_note,
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
def get_a_share_ipo_calendar(limit=100) -> CoveredText:
    """新股申购日历 (new-issue subscription calendar), SH/SZ/BJ, apply date descending.

    Includes subscriptions that have not happened yet.  ``issue_price`` is
    ``None`` before pricing.  ``issue_shares_10k`` is in 10k shares;
    ``online_shares`` / ``apply_upper_shares`` are in shares;
    ``top_apply_mktcap_10k`` is the market value required to subscribe at the
    ceiling (10k yuan); ``win_rate_pct`` is the online winning rate in %;
    ``first_close_chg_pct`` is the first-day close gain in % (``None`` before
    listing).

    This is a whole-market query, so an empty answer is still an interface
    failure (raised); a ``limit`` that cut the list short is reported as
    ``partial`` coverage with the ``row_cap_truncated`` degradation.
    """
    limit = strict_limit(limit)
    query = _em_event_rows(
        "RPTA_APP_IPOAPPLY", "", "APPLY_DATE,SECURITY_CODE", "-1,-1", limit, narrowed=False
    )
    rows = query.rows
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
            "apply_date": strict_source_day(r.get("APPLY_DATE")),
            "ballot_date": strict_source_day(r.get("BALLOT_NUM_DATE")),
            "pay_date": strict_source_day(r.get("BALLOT_PAY_DATE")),
            "listing_date": strict_source_day(r.get("LISTING_DATE")),
            "issue_price": strict_number(r.get("ISSUE_PRICE")) or None,  # null or 0 before pricing
            "issue_pe": strict_number(r.get("AFTER_ISSUE_PE")),
            "industry_pe": strict_number(r.get("INDUSTRY_PE")),
            "issue_shares_10k": strict_number(r.get("ISSUE_NUM")),
            "online_shares": strict_number(r.get("ONLINE_ISSUE_NUM")),
            "apply_upper_shares": strict_number(r.get("ONLINE_APPLY_UPPER")),
            "top_apply_mktcap_10k": strict_number(r.get("TOP_APPLY_MARKETCAP")),
            "win_rate_pct": strict_number(r.get("ONLINE_ISSUE_LWR")),
            "first_close": strict_number(r.get("CLOSE_PRICE")),
            "first_close_chg_pct": strict_number(r.get("LD_CLOSE_CHANGE")),
        }
        for r in rows
    ]
    data = pd.DataFrame(out, columns=_IPO_COLUMNS)
    if data.duplicated(["code"]).any():
        raise ChinaDataUnavailableError("东财新股日历代码重复")
    _capture_vendor_raw(
        rows, metadata={"provider": "eastmoney", "dataset": "ipo_calendar", "ticker": None}
    )
    coverage = datacenter_screening_coverage(
        capability="ipo_calendar",
        source_id="eastmoney.ipo_calendar",
        scope="market-wide",
        page=query.page,
        as_of=_today(),
    )
    return _screening_report(
        data,
        coverage,
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
) -> tuple[list[dict[str, Any]], str, int]:
    """EastMoney clist full pagination; falls back to push2delay on transport failure.

    Network-level failures try the next host.  A server-side abnormal payload
    (including a non-JSON error page) raises without switching hosts, so it can
    never be mistaken for a smaller but valid list.  Returns the rows, the host
    URL that answered, and how many pages were read, so the caller can claim
    pagination exhaustion honestly.
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
                page_total = strict_count(data.get("total"), f"东财 clist total（fs={fs}）")
                diff = strict_rows(data.get("diff"), f"东财 clist 的 diff（fs={fs}）")
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
        return rows, url, page
    raise _ClistUnreachableError("东财 push2 / push2delay 均不可达: " + "; ".join(errors))


def _st_list_baostock(reason: str) -> CoveredText:
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
    # baostock answers in one unpaginated table, but it is an SH/SZ roster: the
    # market-wide snapshot request is only partially covered, and saying
    # "complete" here would silently drop the BSE from a "market-wide" claim.
    coverage = ScreeningCoverageV1(
        capability="st_stock_list",
        source_id="baostock.st_stock_list",
        item_count=len(data),
        page_count=None,
        pagination_exhausted=None,
        completeness="partial",
        sources=("baostock.st_stock_list",),
        degradations=("fallback_sh_sz_only",),
        as_of=_today(),
        query_complete=False,
        requested_scope="market-wide ST roster snapshot",
    )
    note = "沪深（东财不可达，baostock 不含北交所）"
    return CoveredText(
        _format_report(
            data,
            title="China A-share ST / *ST list (baostock fallback)",
            caveat=f"SH/SZ only, no price; coverage={note}",
            source="baostock",
            extra_lines=(
                f"# Coverage: {note} ({coverage.completeness}: fallback_sh_sz_only)",
                f"# Fallback reason: {reason}",
            ),
        ),
        coverage,
    )


@_source_contract
def get_a_share_st_stock_list() -> CoveredText:
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
        shsz, url, shsz_pages = _em_clist_all(_CLIST_SHSZ_RISK, _CLIST_FIELDS)
        bj, bj_url, bj_pages = _em_clist_all(_CLIST_BSE_ALL, _CLIST_FIELDS)
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
                "price": strict_number(rec.get("f2")),
                "pct_change": strict_number(rec.get("f3")),
            }
        )
    data = pd.DataFrame(rows, columns=_ST_COLUMNS)
    if data.empty or data.duplicated(["code"]).any():
        raise ChinaDataUnavailableError("ST 名单为空或代码重复，不能当成完整快照")
    _capture_vendor_raw(
        rows, metadata={"provider": "eastmoney", "dataset": "st_stock_list", "ticker": None}
    )
    # Both halves are read to the end of their own pagination and reconciled
    # against the source's total before this point, so the roster claim is
    # "complete" -- unlike a datacenter query it has no row cap.
    coverage = ScreeningCoverageV1(
        capability="st_stock_list",
        source_id="eastmoney.st_stock_list",
        item_count=len(data),
        page_count=shsz_pages + bj_pages,
        pagination_exhausted=True,
        completeness="complete",
        sources=("eastmoney.st_stock_list",),
        degradations=(),
        as_of=_today(),
        query_complete=True,
        requested_scope="market-wide ST roster snapshot",
    )
    report = _format_report(
        data,
        title="China A-share ST / *ST list (risk-warning board, SH/SZ/BJ)",
        caveat=(
            "EastMoney clist 风险警示板 (沪深, includes B shares) + BSE full table filtered by "
            "name; BSE rows are kept only when the name contains ST; price/pct_change are "
            f"~15-minute delayed on push2delay; source_url={url}"
        ),
        extra_lines=("# Coverage: 沪深京",),
    )
    return CoveredText(report, coverage)
