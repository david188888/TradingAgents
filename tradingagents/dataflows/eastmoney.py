"""Small, keyless EastMoney adapters behind one conservative HTTP gateway.

The public endpoints used here are optional supplemental sources.  They never
contain credentials and callers receive a typed vendor error (rather than a
partially fabricated report) when EastMoney changes an endpoint or throttles
us.  The normal router can therefore continue to another provider.
"""

from __future__ import annotations

import json
import math
import random
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .coverage import CoveredText, ScreeningCoverageV1, SourceCoverageV1
from .errors import RateLimitError, VendorAccessDeniedError, VendorError, VendorHTTPError
from .ticker_utils import (
    is_a_share_ticker,
    normalize_ticker_symbol,
    strict_ticker_code,
    to_akshare_symbol,
    to_tushare_symbol,
)

EASTMONEY_PUSH2_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
EASTMONEY_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


@dataclass(frozen=True)
class EastMoneyRequestPolicy:
    """Bounded request policy suitable for a shared public endpoint."""

    min_interval_seconds: float = 1.0
    jitter_seconds: float = 0.2
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    timeout_seconds: float = 10.0


class EastMoneyHTTPClient:
    """Serial, keep-alive HTTP client with explicit retry behavior.

    A single client serializes both the request and the pre-request delay.
    That is intentional: concurrent callers cannot accidentally bypass the
    public endpoint's pacing contract.  Tests can inject clock/sleeper/jitter
    functions and a session without making network calls.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        policy: EastMoneyRequestPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Connection": "keep-alive",
                "User-Agent": "TradingAgents/1.0 (+https://github.com/TauricResearch/TradingAgents)",
            }
        )
        self._policy = policy or EastMoneyRequestPolicy()
        self._clock = clock
        self._sleeper = sleeper
        self._jitter = jitter
        self._lock = threading.Lock()
        self._last_request_at: float | None = None

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response:
        with self._lock:
            self._pace()
            for attempt in range(self._policy.max_retries + 1):
                try:
                    response = self._session.get(
                        url,
                        params=params,
                        timeout=timeout or self._policy.timeout_seconds,
                        headers=headers,
                    )
                except requests.RequestException as exc:
                    if attempt == self._policy.max_retries:
                        raise VendorHTTPError("eastmoney", 0, "network request failed") from exc
                    self._backoff(attempt)
                    continue

                self._last_request_at = self._clock()
                status_code = int(response.status_code)
                if 200 <= status_code < 300:
                    return response
                if status_code == 403:
                    raise VendorAccessDeniedError("eastmoney", status_code)
                if status_code == 429:
                    if attempt == self._policy.max_retries:
                        raise RateLimitError("eastmoney rate limited (HTTP 429)")
                    self._backoff(attempt)
                    continue
                if 500 <= status_code <= 599:
                    if attempt == self._policy.max_retries:
                        raise VendorHTTPError("eastmoney", status_code)
                    self._backoff(attempt)
                    continue
                raise VendorHTTPError("eastmoney", status_code)

        raise AssertionError("unreachable")

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        target = self._policy.min_interval_seconds + self._jitter(0.0, self._policy.jitter_seconds)
        if elapsed < target:
            self._sleeper(target - elapsed)

    def _backoff(self, attempt: int) -> None:
        base = self._policy.retry_backoff_seconds * (2**attempt)
        self._sleeper(base + self._jitter(0.0, self._policy.jitter_seconds))


_default_client = EastMoneyHTTPClient()


def em_get_json(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: float | None = None,
    client: EastMoneyHTTPClient | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """Get and validate one EastMoney JSON response through the shared gateway.

    Unlike :func:`em_get`, the JSON root may be any shape (including a list),
    which some zero-auth endpoints (e.g. the key-stock monitor pool) return.
    """
    response = (client or _default_client).get(url, params=params, timeout=timeout, headers=headers)
    try:
        return response.json()
    except ValueError as exc:
        raise VendorHTTPError("eastmoney", int(response.status_code), "invalid JSON response") from exc


def em_get(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    timeout: float | None = None,
    client: EastMoneyHTTPClient | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Get and validate one EastMoney JSON response through the shared gateway."""
    payload = em_get_json(url, params=params, timeout=timeout, client=client, headers=headers)
    if not isinstance(payload, dict):
        raise VendorHTTPError("eastmoney", 200, "JSON root is not an object")
    return payload


def get_a_share_capital_flow(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Return recent A-share main/retail capital-flow rows from EastMoney.

    Dates are accepted for a consistent capability signature; the public
    endpoint returns its recent day-kline window and may not guarantee an
    arbitrary historical range.  The report makes this limitation explicit.
    """
    _require_complete_window(start_date, end_date)
    secid = _eastmoney_secid(ticker)
    payload = em_get(
        EASTMONEY_PUSH2_URL,
        params={
            "secid": secid,
            "klt": "101",
            "lmt": "120",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        },
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    lines = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(lines, list) or not lines:
        raise ChinaDataUnavailableError(f"EastMoney returned no capital-flow rows for {ticker}.")
    rows = [_capital_flow_row(line) for line in lines if isinstance(line, str)]
    rows = [row for row in rows if row]
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned unreadable capital-flow rows for {ticker}.")
    retained, actual_start, actual_end = _filter_frame_date_window(
        pd.DataFrame(rows),
        date_columns=("Date",),
        start_date=start_date,
        end_date=end_date,
    )
    if retained.empty:
        raise ChinaDataUnavailableError(
            f"EastMoney returned no capital-flow rows for {ticker} in the requested window."
        )
    coverage = _recent_window_coverage(
        capability="capital_flow",
        source_id="eastmoney.capital_flow",
        item_count=len(retained),
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        page_count=None,
        pagination_exhausted=None,
    )
    _capture_vendor_raw(
        payload,
        metadata={
            "provider": "eastmoney",
            "dataset": "capital_flow",
            "ticker": ticker,
            "coverage": coverage.model_dump(mode="json"),
        },
    )
    return CoveredText(
        _format_report(
            retained,
            title=f"China A-share capital flow for {normalize_ticker_symbol(ticker)}",
            caveat="EastMoney public endpoint; optional supplemental source, recent window only.",
            coverage=coverage,
        ),
        coverage,
    )


def get_a_share_margin_financing(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    curr_date: str | None = None,
) -> CoveredText:
    """Return keyless EastMoney margin-financing records for one A-share.

    EastMoney can change report schemas without notice, so the adapter keeps
    returned fields source-labeled instead of inventing a fixed financial
    interpretation.  The query runs through the strict pager: every page the
    source claims is read (or the result is honestly truncated), a page-1 9201
    is a *completed* empty window rather than a failure, and any other error
    code, ignored filter or changed schema raises instead of returning rows.
    """
    requested_as_of: str | None = None
    if curr_date is not None:
        if start_date is not None or end_date is not None:
            raise ValueError("curr_date cannot be combined with start_date or end_date")
        requested_as_of = curr_date
        end_date = curr_date

    # Backward compatibility: the historical two-positional-argument form
    # used the second value as an as-of date, not a range start.
    if start_date is not None and end_date is None:
        requested_as_of = start_date
        end_date = start_date
        start_date = None
    elif start_date is None and end_date is not None and requested_as_of is None:
        raise ValueError("start_date and end_date must be supplied together")

    code = _require_a_share_code(ticker)
    window_start = strict_date_arg(start_date) if start_date else None
    window_end = strict_date_arg(end_date) if end_date else None
    filters = [f'(SCODE="{code}")']
    if window_start:
        filters.append(f"(DATE>='{window_start}')")
    if window_end:
        filters.append(f"(DATE<='{window_end}')")
    report_name = "RPTA_WEB_RZRQ_GGMX"
    # This report keys the security by SCODE, not SECURITY_CODE; the latter
    # silently matches zero rows for every ticker. Sort by DATE (its trade-date
    # column), not TRADE_DATE which does not exist here.
    # Cap: 2000 rows for one instrument (about eight years of daily rows);
    # page_size=min(cap, 500).
    page = em_datacenter_strict(
        report_name,
        filter_str="".join(filters),
        sort_columns="DATE",
        sort_types="-1",
        page_size=min(2000, 500),
        max_rows=2000,
    )
    rows = dedupe_datacenter_rows(page, report_name)
    observed_days: list[str] = []
    for row in rows:
        scode = row.get("SCODE")
        if scode is None or str(scode) != code:
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 请求 SCODE={code}，却返回了 {scode!r}，结果不可信"
            )
        day = strict_source_day(row.get("DATE"))
        if day is None:
            raise ChinaDataUnavailableError(f"东财 {report_name} 返回的行缺少 DATE 字段")
        if (window_start and day < window_start) or (window_end and day > window_end):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 请求 DATE 在 {window_start or ''}~{window_end or ''}，"
                f"却返回了 {day}，结果不可信"
            )
        observed_days.append(day)
    retained = pd.DataFrame(rows)
    actual_start = min(observed_days) if observed_days else None
    actual_end = max(observed_days) if observed_days else None
    # Whether the query is complete is decided by pagination exhaustion, the
    # provider's self-reported count reconciled against the rows read, and the
    # row-level filter re-check above -- not by whether the rows happen to touch
    # both window edges.  An instrument with no margin record on the first or
    # last day of the window simply has no such row; reporting that as
    # ``partial`` would contradict ``query_complete=True``.  The observed span
    # is still rendered (`# Actual window:`), which is where a short window
    # belongs.
    scope = (
        f"ticker={to_tushare_symbol(ticker)} "
        f"window={window_start or '*'}..{window_end or '*'}"
    )
    coverage = datacenter_screening_coverage(
        capability="margin_financing",
        source_id="eastmoney.margin_financing",
        scope=scope,
        page=page,
        as_of=window_end or requested_as_of or date.today().isoformat(),
    )
    _capture_vendor_raw(
        {"rows": rows},
        metadata={
            "provider": "eastmoney",
            "dataset": "margin_financing",
            "ticker": ticker,
            "coverage": coverage.model_dump(mode="json"),
        },
    )
    return CoveredText(
        _format_report(
            retained,
            title=f"China A-share margin financing for {normalize_ticker_symbol(ticker)}",
            caveat="EastMoney public endpoint; optional supplemental source.",
            as_of=requested_as_of,
            coverage=coverage,
            requested_window=(
                (window_start, window_end) if requested_as_of is None and window_start else None
            ),
            actual_window=(actual_start, actual_end),
        ),
        coverage,
    )


def get_a_share_capital_flow_sina(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Return A-share daily capital-flow rows from Sina (backup for EastMoney).

    Sina's MoneyFlow endpoint is on a different domain and rate-limit plane
    than EastMoney push2, so it stays usable when EastMoney bans an IP.  The
    field schema differs from the EastMoney primary source: Sina exposes net
    inflow + turnover rather than the four-tier main/large/medium/small
    breakdown, so the report labels the source explicitly rather than
    pretending the two are interchangeable.
    """
    _require_complete_window(start_date, end_date)
    code = _require_a_share_code(ticker)
    prefix = _sina_prefix(ticker)
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"MoneyFlow.ssl_qsfx_zjlrqs?page=1&num=120&sort=opendate&asc=0&daima={prefix}{code}"
    )
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise ChinaDataUnavailableError(f"Sina capital-flow request failed for {ticker}: {exc}") from exc
    text = response.text
    try:
        start = text.index("[")
        end = text.rindex("]")
        rows = json.loads(text[start : end + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        raise ChinaDataUnavailableError(f"Sina returned unparseable capital-flow data for {ticker}: {exc}") from exc
    if not rows:
        raise ChinaDataUnavailableError(f"Sina returned no capital-flow rows for {ticker}.")
    data = pd.DataFrame(
        [
            {
                "Date": row.get("opendate"),
                "Close": row.get("trade"),
                "Net Inflow": row.get("netamount"),
                "Turnover": row.get("turnover"),
            }
            for row in rows
        ]
    )
    retained, actual_start, actual_end = _filter_frame_date_window(
        data,
        date_columns=("Date",),
        start_date=start_date,
        end_date=end_date,
    )
    if retained.empty:
        raise ChinaDataUnavailableError(
            f"Sina returned no capital-flow rows for {ticker} in the requested window."
        )
    coverage = _recent_window_coverage(
        capability="capital_flow",
        source_id="sina.capital_flow",
        item_count=len(retained),
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        page_count=1,
        pagination_exhausted=None,
    )
    _capture_vendor_raw(
        {"rows": rows},
        metadata={
            "provider": "sina",
            "dataset": "capital_flow",
            "ticker": ticker,
            "coverage": coverage.model_dump(mode="json"),
        },
    )
    return CoveredText(
        _format_report(
            retained,
            title=(
                f"China A-share capital flow for {normalize_ticker_symbol(ticker)} "
                "(Sina backup)"
            ),
            caveat=(
                "Sina daily capital-flow backup source; field schema differs from "
                "EastMoney push2 (net inflow + turnover only)."
            ),
            source="sina",
            coverage=coverage,
        ),
        coverage,
    )


def _sina_prefix(ticker: str) -> str:
    """Sina quote prefix: sh for Shanghai, bj for Beijing, sz otherwise."""
    canonical = normalize_ticker_symbol(ticker)
    if canonical.endswith((".SS", ".SH")):
        return "sh"
    if canonical.endswith(".BJ"):
        return "bj"
    return "sz"


def _eastmoney_secid(ticker: str) -> str:
    code = _require_a_share_code(ticker)
    canonical = normalize_ticker_symbol(ticker)
    # EastMoney's secid convention: Shanghai=1, Shenzhen/Beijing=0.
    market = "1" if canonical.endswith((".SS", ".SH")) else "0"
    return f"{market}.{code}"


def _require_a_share_code(ticker: str) -> str:
    if not is_a_share_ticker(ticker):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return to_akshare_symbol(ticker)


def _capital_flow_row(line: str) -> dict[str, str] | None:
    fields = [part.strip() for part in line.split(",")]
    if len(fields) < 2 or not fields[0]:
        return None
    names = (
        "Date", "Main Net Inflow", "Small Net Inflow", "Medium Net Inflow",
        "Large Net Inflow", "Extra Large Net Inflow", "Close", "Pct Change",
    )
    return {name: fields[index] for index, name in enumerate(names) if index < len(fields)}


def _require_complete_window(start_date: str | None, end_date: str | None) -> None:
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be supplied together")


def _filter_frame_date_window(
    data: pd.DataFrame,
    *,
    date_columns: tuple[str, ...],
    start_date: str | None,
    end_date: str | None,
) -> tuple[pd.DataFrame, str | None, str | None]:
    date_column = next((column for column in date_columns if column in data.columns), None)
    if date_column is None:
        return data.copy(), None, None

    parsed = pd.to_datetime(data[date_column], errors="coerce")
    mask = parsed.notna()
    if start_date is not None:
        mask &= parsed.dt.date >= date.fromisoformat(start_date[:10])
    if end_date is not None:
        mask &= parsed.dt.date <= date.fromisoformat(end_date[:10])
    retained = data.loc[mask].copy()
    retained_dates = parsed.loc[mask]
    if retained.empty:
        return retained, None, None
    return (
        retained,
        retained_dates.min().date().isoformat(),
        retained_dates.max().date().isoformat(),
    )


def _recent_window_coverage(
    *,
    capability: str,
    source_id: str,
    item_count: int,
    requested_start: str | None,
    requested_end: str | None,
    actual_start: str | None,
    actual_end: str | None,
    page_count: int | None,
    pagination_exhausted: bool | None,
) -> SourceCoverageV1:
    degradations: list[str] = []
    if pagination_exhausted is False:
        completeness = "partial"
        degradations.append("pagination_not_exhausted")
    elif requested_start and actual_start and actual_start > requested_start:
        completeness = "partial"
        degradations.append("requested_start_not_observed")
    elif requested_end and actual_end and actual_end < requested_end:
        completeness = "partial"
        degradations.append("requested_end_not_observed")
    elif (requested_start or requested_end) and (actual_start is None or actual_end is None):
        completeness = "unknown"
        degradations.append("actual_window_unavailable")
    elif page_count is not None and pagination_exhausted is True:
        completeness = "complete"
    else:
        completeness = "unknown"
        degradations.append("coverage_not_proven")

    as_of = requested_end or actual_end or date.today().isoformat()
    return SourceCoverageV1(
        capability=capability,
        source_id=source_id,
        requested_start=requested_start if requested_end is not None else None,
        requested_end=requested_end if requested_start is not None else None,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=item_count,
        page_count=page_count,
        pagination_exhausted=pagination_exhausted,
        completeness=completeness,
        sources=(source_id,),
        degradations=tuple(degradations),
        as_of=as_of,
    )


def _format_report(
    data: pd.DataFrame,
    *,
    title: str,
    caveat: str,
    source: str = "eastmoney",
    start_date: str | None = None,
    end_date: str | None = None,
    as_of: str | None = None,
    coverage: SourceCoverageV1 | None = None,
    requested_window: tuple[str | None, str | None] | None = None,
    actual_window: tuple[str | None, str | None] | None = None,
) -> str:
    """Render the legacy-compatible report.

    A screening adapter can legitimately have zero rows; when it carries
    coverage, the header says so (``# Coverage: complete (0 matching records)``
    plus an explicit note) instead of raising, so a completed empty query cannot
    be read as a failed one.
    """
    if data.empty and coverage is None:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")

    requested = requested_window
    if requested is None and coverage is not None and coverage.requested_start:
        requested = (coverage.requested_start, coverage.requested_end)
    if requested is None and coverage is None and (start_date or end_date):
        requested = (start_date, end_date)
    actual = actual_window
    if actual is None and coverage is not None and coverage.actual_start:
        actual = (coverage.actual_start, coverage.actual_end)

    note = caveat
    coverage_lines: list[str] = []
    if requested and requested[0] and requested[1]:
        coverage_lines.append(f"# Requested window: {requested[0]} to {requested[1]}")
    if actual and actual[0] and actual[1]:
        coverage_lines.append(f"# Actual window: {actual[0]} to {actual[1]}")
    if coverage is not None:
        if isinstance(coverage, ScreeningCoverageV1):
            coverage_lines.append(
                f"# Coverage: {coverage.completeness} ({coverage.item_count} matching records)"
            )
            coverage_lines.append(f"# Scope: {coverage.requested_scope}")
        coverage_lines.append(f"# Coverage completeness: {coverage.completeness}")
        if as_of and not requested and not coverage.requested_start:
            coverage_lines.append(f"# Requested as-of: {as_of}")
        if coverage.page_count is not None:
            exhausted = (
                "unknown"
                if coverage.pagination_exhausted is None
                else str(coverage.pagination_exhausted).lower()
            )
            coverage_lines.append(
                f"# Pagination: pages={coverage.page_count}; exhausted={exhausted}"
            )
        if coverage.degradations:
            coverage_lines.append(f"# Degradations: {', '.join(coverage.degradations)}")
        if data.empty and coverage.completeness == "complete":
            note = (
                f"{caveat} The source completed the query and reported 0 matching "
                "records; this is not a fetch failure."
            )
    elif as_of:
        coverage_lines.append(f"# Requested as-of: {as_of}")
    return "\n".join(
        [
            f"# {title}",
            f"# Source: {source}",
            f"# Note: {note}",
            f"# Total records: {len(data)}",
            *coverage_lines,
            "",
            data.to_csv(index=False),
        ]
    )


def _capture_vendor_raw(payload: Any, *, metadata: Mapping[str, Any]) -> None:
    """Load observability after the provider has returned a usable payload."""
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(payload, metadata=dict(metadata))


# ---------------------------------------------------------------------------
# Strict datacenter pager
# ---------------------------------------------------------------------------
#
# The legacy ``_eastmoney_datacenter()`` helper asks for one page and returns
# whatever rows it finds, so a throttle, a wrong filter column or a rejected
# sort turns into an empty list -- indistinguishable from "this instrument has
# no such records".  Every adapter that queries a datacenter ``reportName`` uses
# the pager below instead, which either returns rows the source vouched for or
# raises.
#
# Rules (a-stock-data v3.9.0, issue-driven; each one is pinned by a test):
# * ``code == 9201`` on page 1 means "the source answered and there is nothing",
#   and is the ONLY empty result that is not an error.  Any other non-zero code
#   raises with both the code and the provider's message.
# * A 9201 after page 1, an empty page, a short non-final page, a changed
#   ``pages``/``count`` between pages, or a final row count that disagrees with
#   ``count`` all raise: a partial page set must never look complete.
# * ``sortColumns`` and ``sortTypes`` must have equal element counts, or
#   EastMoney answers 9501; that is checked before a request is spent.
# * ``max_rows`` truncates only when the source's own ``count`` exceeds it.
#   Otherwise pagination runs to the end and the total is reconciled, so
#   "data longer than count" cannot slip through as a legitimate cap.

_DATACENTER_SORT_ERROR = 9501


def strict_limit(limit: Any, upper: int = 5000) -> int:
    """Validate a caller-supplied row limit (1..upper)."""
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit 必须是整数，收到 {limit!r}") from exc
    if not 1 <= value <= upper:
        raise ValueError(f"limit 范围 1–{upper}")
    return value


def strict_number(value: Any) -> float | None:
    """Parse a provider numeric field, refusing to guess.

    ``None`` / ``''`` / ``'-'`` / ``'--'`` mean "the source left it blank" and
    return ``None``; a JSON boolean, a non-finite float or unrecognised text is
    a source-format change and raises.  ``float(True) == 1.0`` is exactly why
    booleans are rejected rather than coerced.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ChinaDataUnavailableError(f"来源在数值字段给了布尔值 {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).replace(",", "").strip()
    if text in ("", "-", "--", "None", "null"):
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ChinaDataUnavailableError(f"来源返回了无法识别的数值 {value!r}") from exc
    return number if math.isfinite(number) else None


def strict_source_date(value: Any) -> str:
    """A date the provider returned; an unrecognised spelling raises.

    Truncating to the first ten characters instead would let ``2026/09/18``
    through as a "date" and then compare unequal to every ISO date.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    fmt = "%Y%m%d" if re.fullmatch(r"[0-9]{8}", text) else "%Y-%m-%d"
    try:
        return datetime.strptime(text, fmt).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ChinaDataUnavailableError(f"来源返回了无法识别的日期 {value!r}") from exc


def strict_date_arg(value: Any) -> str:
    """A caller-supplied date argument; a bad argument stays a ``ValueError``."""
    try:
        return strict_source_date(value)
    except ChinaDataUnavailableError as exc:
        raise ValueError(str(exc)) from exc


def strict_source_day(value: Any) -> str | None:
    """EastMoney's ``'2026-09-18 00:00:00'`` -> ``'2026-09-18'``; blank -> None."""
    if not value:
        return None
    text = str(value).strip()
    if text[:10] in ("", "0000-00-00"):
        return None
    return strict_source_date(text[:10])


def strict_count(value: Any, what: str) -> int:
    """A provider self-reported page/row total; booleans are not integers."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ChinaDataUnavailableError(f"{what} 不是非负整数: {value!r}")
    return value


def strict_rows(value: Any, what: str) -> list[dict[str, Any]]:
    """A provider row list.  ``or []`` would wash a structure change into "empty"."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ChinaDataUnavailableError(f"{what} 不是由对象组成的列表，格式可能已变")
    return [dict(row) for row in value]


def strict_stock_code(ticker: Any) -> str:
    """A bare six-digit stock code, or a typed unavailability."""
    try:
        return strict_ticker_code(ticker, stock_only=True)
    except ValueError as exc:
        raise ChinaDataUnavailableError(str(exc)) from exc


@dataclass(frozen=True)
class DatacenterPage:
    """Rows plus the pagination facts needed to make an honest coverage claim."""

    rows: list[dict[str, Any]]
    pages: int
    count: int
    pages_fetched: int
    truncated: bool

    @property
    def pagination_exhausted(self) -> bool:
        """Every page the source claimed was read, and the total reconciled.

        A truncated result fails this by construction: ``max_rows`` only
        truncates when the source's ``count`` exceeds it, so the retained rows
        can never equal ``count``.
        """
        return self.pages_fetched >= self.pages and len(self.rows) == self.count


def em_datacenter_strict(
    report_name: str,
    filter_str: str = "",
    sort_columns: str = "",
    sort_types: str = "",
    page_size: int = 500,
    max_rows: int = 5000,
    columns: str = "ALL",
    extra: Mapping[str, Any] | None = None,
) -> DatacenterPage:
    """Page an EastMoney datacenter report, or raise.

    See the module section comment above for the error contract.  Only a page-1
    ``9201`` yields an empty ``rows`` list; it is a positive statement from the
    source ("no matching rows"), which is why it is returned rather than raised.
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
            payload = em_get(EASTMONEY_DATACENTER_URL, params=params, timeout=20)
        except VendorError as exc:
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 请求失败: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 返回的不是 JSON 对象: {str(payload)[:100]}"
            )
        if payload.get("code") == 9201:
            if page == 1:
                return DatacenterPage(rows=[], pages=1, count=0, pages_fetched=1, truncated=False)
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 第 {page} 页返回「数据为空」，"
                f"前面已取 {len(rows)} 条，结果不完整"
            )
        if payload.get("code") != 0 or not payload.get("result"):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 返回错误: {payload.get('code')} {payload.get('message')}"
            )
        result = payload["result"]
        if not isinstance(result, Mapping):
            raise ChinaDataUnavailableError(
                f"东财 {report_name} 的 result 不是对象: {str(result)[:100]}"
            )
        pages = strict_count(result.get("pages"), f"东财 {report_name} 的 pages")
        count = strict_count(result.get("count"), f"东财 {report_name} 的 count")
        data = strict_rows(result.get("data"), f"东财 {report_name} 的 data")
        if pages < 1:
            raise ChinaDataUnavailableError(f"东财 {report_name} 的 pages={pages} 非法")
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
            return DatacenterPage(
                rows=rows[:max_rows], pages=pages, count=count, pages_fetched=page, truncated=True
            )
        if page >= pages:
            if len(rows) != count:
                raise ChinaDataUnavailableError(
                    f"东财 {report_name} 翻页后 {len(rows)} 条，与总数 {count} 不符"
                )
            return DatacenterPage(
                rows=rows, pages=pages, count=count, pages_fetched=page, truncated=False
            )
        page += 1


def dedupe_datacenter_rows(
    page: DatacenterPage, report_name: str
) -> list[dict[str, Any]]:
    """Reject exact duplicate rows: they mean the sort key was not unique.

    EastMoney pages by offset, so a non-unique sort returns one row twice and
    silently drops another.  ``strict_rows`` cannot see this and the row count
    still reconciles, so it is checked separately.
    """
    fingerprints = {
        json.dumps(row, sort_keys=True, ensure_ascii=False) for row in page.rows
    }
    if len(fingerprints) != len(page.rows):
        raise ChinaDataUnavailableError(
            f"东财 {report_name} 翻页返回了重复行（排序不唯一），结果不完整"
        )
    return page.rows


def datacenter_screening_coverage(
    *,
    capability: str,
    source_id: str,
    scope: str,
    page: DatacenterPage,
    as_of: str,
    degradations: tuple[str, ...] = (),
) -> ScreeningCoverageV1:
    """Coverage for a datacenter query whose honest answer may be "no match".

    A completed query with zero rows is ``complete`` -- see
    :class:`~tradingagents.dataflows.coverage.ScreeningCoverageV1`.  Anything
    less than a reconciled full scan is ``partial`` (rows retained) or
    ``unknown`` (nothing retained) and always carries a degradation code, so no
    consumer can read a truncated or unproven scan as a negative finding.
    """
    exhausted = page.pagination_exhausted
    codes = list(degradations)
    if not exhausted:
        codes.append("row_cap_truncated" if page.truncated else "pagination_not_proven")
    if exhausted and not codes:
        completeness = "complete"
    elif page.rows:
        completeness = "partial"
    else:
        completeness = "unknown"
    return ScreeningCoverageV1(
        capability=capability,
        source_id=source_id,
        item_count=len(page.rows),
        page_count=max(page.pages_fetched, 1),
        pagination_exhausted=exhausted,
        completeness=completeness,
        sources=(source_id,),
        degradations=tuple(dict.fromkeys(codes)),
        as_of=as_of,
        query_complete=exhausted,
        requested_scope=scope,
    )
