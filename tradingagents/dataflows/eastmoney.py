"""Small, keyless EastMoney adapters behind one conservative HTTP gateway.

The public endpoints used here are optional supplemental sources.  They never
contain credentials and callers receive a typed vendor error (rather than a
partially fabricated report) when EastMoney changes an endpoint or throttles
us.  The normal router can therefore continue to another provider.
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .coverage import CoveredText, SourceCoverageV1
from .errors import RateLimitError, VendorAccessDeniedError, VendorHTTPError
from .ticker_utils import is_a_share_ticker, normalize_ticker_symbol, to_akshare_symbol

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
) -> str:
    """Return keyless EastMoney margin-financing records for one A-share.

    EastMoney can change report schemas without notice, so the adapter keeps
    returned fields source-labeled instead of inventing a fixed financial
    interpretation.  Empty or changed responses degrade through the router.
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
    payload = em_get(
        EASTMONEY_DATACENTER_URL,
        params={
            "reportName": "RPTA_WEB_RZRQ_GGMX",
            "columns": "ALL",
            # This report keys the security by SCODE, not SECURITY_CODE; the
            # latter silently matches zero rows for every ticker. Sort by DATE
            # (its trade-date column), not TRADE_DATE which does not exist here.
            "filter": f'(SCODE="{code}")',
            "pageNumber": "1",
            "pageSize": "20",
            "sortColumns": "DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
        },
    )
    rows = _extract_records(payload)
    if not rows:
        raise ChinaDataUnavailableError(f"EastMoney returned no margin-financing records for {ticker}.")
    retained, actual_start, actual_end = _filter_frame_date_window(
        pd.DataFrame(rows),
        date_columns=("DATE", "TRADE_DATE", "日期"),
        start_date=start_date,
        end_date=end_date,
    )
    if retained.empty:
        raise ChinaDataUnavailableError(
            f"EastMoney returned no margin-financing records for {ticker} in the requested window."
        )
    total_pages = _extract_total_pages(payload)
    pagination_exhausted = None if total_pages is None else total_pages <= 1
    coverage = _recent_window_coverage(
        capability="margin_financing",
        source_id="eastmoney.margin_financing",
        item_count=len(retained),
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        page_count=1,
        pagination_exhausted=pagination_exhausted,
    )
    _capture_vendor_raw(
        payload,
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


def _extract_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = [payload.get("data")]
    result = payload.get("result")
    if isinstance(result, Mapping):
        candidates.append(result.get("data"))
    for value in candidates:
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _require_complete_window(start_date: str | None, end_date: str | None) -> None:
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be supplied together")


def _extract_total_pages(payload: Mapping[str, Any]) -> int | None:
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("result", "data"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    for candidate in candidates:
        for key in ("pages", "totalPage", "TotalPage", "total_pages"):
            value = candidate.get(key)
            try:
                pages = int(value)
            except (TypeError, ValueError):
                continue
            if pages >= 1:
                return pages
    return None


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
) -> str:
    if data.empty:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")
    coverage_lines: list[str] = []
    if coverage is not None:
        if coverage.requested_start and coverage.requested_end:
            coverage_lines.append(
                f"# Requested window: {coverage.requested_start} to {coverage.requested_end}"
            )
        if coverage.actual_start and coverage.actual_end:
            coverage_lines.append(
                f"# Actual window: {coverage.actual_start} to {coverage.actual_end}"
            )
        coverage_lines.append(f"# Coverage completeness: {coverage.completeness}")
        if as_of and not coverage.requested_start:
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
    else:
        if start_date or end_date:
            coverage_lines.append(f"# Requested window: {start_date or '?'} to {end_date or '?'}")
        if as_of:
            coverage_lines.append(f"# Requested as-of: {as_of}")
    return "\n".join(
        [
            f"# {title}",
            f"# Source: {source}",
            f"# Note: {caveat}",
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
