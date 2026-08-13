"""Safe, degradable A-share specialty-data capability adapters.

The specialty layer intentionally exposes *facts returned by a named source*,
not inferred trading signals.  Exchange announcements are a useful example:
the Shanghai and Shenzhen exchanges are the primary records, while EastMoney's
public bulletin feed is only a keyless fallback when an official endpoint is
unavailable or changes shape.  A failed source never becomes an empty or
invented announcement report.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .coverage import CoveredText, SourceCoverageV1
from .eastmoney import EASTMONEY_DATACENTER_URL, em_get
from .errors import NoMarketDataError, VendorHTTPError
from .ticker_utils import is_a_share_ticker, normalize_ticker_symbol, to_akshare_symbol

SSE_ANNOUNCEMENT_URL = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
SZSE_ANNOUNCEMENT_URL = "https://www.szse.cn/api/disc/announcement/annList"
CNINFO_ANNOUNCEMENT_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCK_LIST_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
_CNINFO_ORGID_MAP: dict[str, str] = {}


@dataclass(frozen=True)
class AnnouncementRecord:
    """One source-labeled announcement without interpreted investment meaning."""

    title: str
    published_at: str | None
    source_provider: str
    source_uri: str | None = None
    announcement_id: str | None = None


class AnnouncementProvider(Protocol):
    """Capability contract for a keyless A-share announcement source."""

    name: str

    def fetch(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Sequence[AnnouncementRecord]: ...


class SSEAnnouncementProvider:
    """Shanghai Stock Exchange primary announcement provider (zero key)."""

    name = "sse"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def fetch(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Sequence[AnnouncementRecord]:
        code = _require_exchange(ticker, allowed_suffixes=(".SS", ".SH"))
        response = self._session.get(
            SSE_ANNOUNCEMENT_URL,
            params={
                "isPagination": "true",
                "productId": code,
                "securityType": "0101",
                "reportType": "ALL",
                "beginDate": start_date or "",
                "endDate": end_date or "",
                "pageHelp.pageSize": "50",
                "pageHelp.pageNo": "1",
            },
            headers={"Referer": "https://www.sse.com.cn/", "Accept": "application/json"},
            timeout=10,
        )
        payload = _json_object(response, self.name)
        records = _parse_sse_records(payload)
        if not records:
            raise ChinaDataUnavailableError(f"SSE returned no announcement records for {ticker}.")
        _capture_vendor_raw(payload, metadata={"provider": self.name, "dataset": "announcements", "ticker": ticker})
        return records


class SZSEAnnouncementProvider:
    """Shenzhen Stock Exchange primary announcement provider (zero key)."""

    name = "szse"

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def fetch(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Sequence[AnnouncementRecord]:
        code = _require_exchange(ticker, allowed_suffixes=(".SZ",))
        response = self._session.get(
            SZSE_ANNOUNCEMENT_URL,
            params={
                "secCode": code,
                "channelCode": "fixed_disc",
                "pageSize": "50",
                "pageNum": "1",
                "seDate": _date_window(start_date, end_date),
            },
            headers={"Referer": "https://www.szse.cn/", "Accept": "application/json"},
            timeout=10,
        )
        payload = _json_object(response, self.name)
        records = _parse_szse_records(payload)
        if not records:
            raise ChinaDataUnavailableError(f"SZSE returned no announcement records for {ticker}.")
        _capture_vendor_raw(payload, metadata={"provider": self.name, "dataset": "announcements", "ticker": ticker})
        return records


class EastMoneyAnnouncementFallback:
    """Keyless public fallback; never presented as an exchange primary record."""

    name = "eastmoney"

    def fetch(
        self,
        ticker: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Sequence[AnnouncementRecord]:
        code = _require_a_share_code(ticker)
        payload = em_get(
            EASTMONEY_DATACENTER_URL,
            params={
                "reportName": "RPT_PUBLIC_BULLETIN",
                "columns": "SECURITY_CODE,SECURITY_NAME,NOTICE_DATE,TITLE,ARTICLE_CODE,INFO_CODE",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageNumber": "1",
                "pageSize": "50",
                "sortColumns": "NOTICE_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB",
            },
        )
        records = _parse_eastmoney_records(payload)
        records = _filter_records(records, start_date=start_date, end_date=end_date)
        if not records:
            raise ChinaDataUnavailableError(f"EastMoney returned no announcement records for {ticker}.")
        _capture_vendor_raw(payload, metadata={"provider": self.name, "dataset": "announcements", "ticker": ticker})
        return records


def get_a_share_cninfo_announcements(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 30,
    max_pages: int = 10,
) -> CoveredText:
    """Fetch CNINFO company disclosures with dynamic orgId resolution.

    CNINFO is kept separate from exchange bulletin metadata because it exposes
    disclosure type, full-text detail URL, and (when present) the PDF attachment.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    code = _require_a_share_code(ticker)
    org_id = _cninfo_orgid(code)
    bounded_page_size = max(1, min(page_size, 100))
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    invalid_published_count = 0
    page_count = 0
    pagination_exhausted: bool | None = None
    for page in range(1, max_pages + 1):
        response = requests.post(
            CNINFO_ANNOUNCEMENT_URL,
            data={
                "stock": f"{code},{org_id}",
                "tabName": "fulltext",
                "pageSize": str(bounded_page_size),
                "pageNum": str(page),
                "column": "",
                "category": "",
                "plate": "",
                "seDate": (
                    f"{start_date or ''}~{end_date or ''}"
                    if start_date or end_date
                    else ""
                ),
                "searchkey": "",
                "secid": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
            headers={
                "User-Agent": "TradingAgents/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cninfo.com.cn/new/disclosure",
                "Origin": "https://www.cninfo.com.cn",
            },
            timeout=15,
        )
        if not 200 <= int(response.status_code) < 300:
            raise ChinaDataUnavailableError(
                f"CNINFO returned HTTP {response.status_code} for {code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ChinaDataUnavailableError(
                f"CNINFO returned invalid JSON for {code}."
            ) from exc
        if not isinstance(payload, dict):
            raise ChinaDataUnavailableError(
                f"CNINFO returned a non-object payload for {code}."
            )
        page_count += 1
        _capture_cninfo_raw(payload, ticker=ticker)
        announcements = payload.get("announcements") or []
        if not isinstance(announcements, list):
            raise ChinaDataUnavailableError(
                f"CNINFO returned invalid announcements for {code}."
            )
        for item in announcements:
            if not isinstance(item, dict):
                continue
            published = _cninfo_ts_to_date(item.get("announcementTime"))
            if not published:
                invalid_published_count += 1
                continue
            if start_date and published < start_date:
                continue
            if end_date and published > end_date:
                continue
            announcement_id = str(item.get("announcementId") or "")
            dedupe_id = announcement_id or "|".join(
                (published, str(item.get("announcementTitle") or ""))
            )
            if dedupe_id in seen_ids:
                continue
            seen_ids.add(dedupe_id)
            records.append(
                {
                    "Published": published,
                    "Type": item.get("announcementTypeName") or "",
                    "Title": item.get("announcementTitle") or "",
                    "Announcement ID": announcement_id,
                    "Detail URL": (
                        "https://www.cninfo.com.cn/new/disclosure/detail"
                        f"?annoId={announcement_id}"
                    ),
                    "PDF URL": item.get("adjunctUrl")
                    or item.get("adjunctUrlName")
                    or "",
                }
            )

        total_pages = _cninfo_total_pages(payload)
        has_more = payload.get("hasMore")
        if (
            not announcements
            or (total_pages is not None and page >= total_pages)
            or has_more is False
            or (total_pages is None and has_more is None and len(announcements) < bounded_page_size)
        ):
            pagination_exhausted = True
            break
    else:
        pagination_exhausted = False

    if not records:
        raise NoMarketDataError(
            ticker,
            code,
            "CNINFO completed the requested announcement query with no records.",
        )
    observed_dates = sorted(record["Published"] for record in records if record["Published"])
    actual_start = observed_dates[0] if observed_dates else None
    actual_end = observed_dates[-1] if observed_dates else None
    degradations: list[str] = []
    if invalid_published_count:
        degradations.append("invalid_or_missing_published_at")
    if pagination_exhausted is False:
        completeness = "partial"
        degradations.append("pagination_budget_exhausted")
    elif not (start_date and end_date):
        completeness = "unknown"
        degradations.append("requested_window_unproven")
    elif invalid_published_count:
        completeness = "partial"
    elif start_date and end_date and pagination_exhausted:
        completeness = "complete"
        # For a sparse event dataset, full coverage means the provider query
        # exhausted the requested interval; it does not require an event on
        # both boundary dates.
        actual_start = start_date
        actual_end = end_date
    else:
        completeness = "partial"
        degradations.append("requested_window_not_fully_observed")
    coverage = SourceCoverageV1(
        capability="official_disclosures",
        source_id="cninfo.announcements",
        requested_start=start_date if start_date and end_date else None,
        requested_end=end_date if start_date and end_date else None,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=len(records),
        page_count=page_count,
        pagination_exhausted=pagination_exhausted,
        completeness=completeness,
        sources=("cninfo.announcements",),
        degradations=tuple(degradations),
        as_of=end_date or datetime.now().strftime("%Y-%m-%d"),
    )
    report = "\n".join([
        f"# China A-share CNINFO disclosures for {normalize_ticker_symbol(ticker)}",
        "# Source: cninfo.com.cn",
        "# Evidence level: primary company disclosure",
        f"# Requested window: {start_date or '?'} to {end_date or '?'}",
        f"# Total records: {len(records)}",
        "",
        pd.DataFrame(records).to_csv(index=False),
    ])
    return CoveredText(report, coverage)


def _cninfo_total_pages(payload: Mapping[str, Any]) -> int | None:
    for key in ("totalpages", "totalPages", "pageCount"):
        try:
            parsed = int(payload.get(key))
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def _cninfo_ts_to_date(value: object) -> str:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                float(value) / 1000,
                tz=ZoneInfo("Asia/Shanghai"),
            ).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return ""
    candidate = str(value or "")[:10].replace("/", "-")
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return ""


def _cninfo_orgid(code: str) -> str:
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        try:
            response = requests.get(CNINFO_STOCK_LIST_URL, headers={"User-Agent": "TradingAgents/1.0"}, timeout=15)
            payload = response.json()
            _CNINFO_ORGID_MAP = {
                str(row.get("code")): str(row.get("orgId"))
                for row in payload.get("stockList", [])
                if isinstance(row, dict) and row.get("code") and row.get("orgId")
            }
        except Exception:
            _CNINFO_ORGID_MAP = {}
    if code in _CNINFO_ORGID_MAP:
        return _CNINFO_ORGID_MAP[code]
    if code.startswith("6"):
        return f"gssh0{code}"
    if code.startswith(("8", "9", "4")):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def _capture_cninfo_raw(payload: object, *, ticker: str) -> None:
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(payload, metadata={"provider": "cninfo", "dataset": "announcements", "ticker": ticker})
def get_a_share_exchange_announcements(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    providers: Iterable[AnnouncementProvider] | None = None,
) -> str:
    """Fetch announcements via primary exchange then keyless public fallback.

    The returned report identifies the provider used.  If every eligible
    provider fails, a typed ``ChinaDataUnavailableError`` carries the attempted
    provider names; callers can safely continue their wider research workflow.
    """
    canonical = normalize_ticker_symbol(ticker)
    records = fetch_a_share_exchange_announcements(
        canonical,
        start_date=start_date,
        end_date=end_date,
        providers=providers,
    )
    return render_announcement_report(canonical, records, start_date=start_date, end_date=end_date)


def fetch_a_share_exchange_announcements(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    providers: Iterable[AnnouncementProvider] | None = None,
) -> Sequence[AnnouncementRecord]:
    """Return source-labelled official announcement facts for a public fallback."""
    canonical = normalize_ticker_symbol(ticker)
    candidates = tuple(providers or _providers_for(canonical))
    failures: list[str] = []
    for provider in candidates:
        try:
            records = provider.fetch(canonical, start_date=start_date, end_date=end_date)
        except (ChinaDataUnavailableError, VendorHTTPError, requests.RequestException) as exc:
            failures.append(f"{provider.name}: {type(exc).__name__}")
            continue
        if records:
            return records
        failures.append(f"{provider.name}: empty")
    attempted = ", ".join(failures) or "no eligible provider"
    raise ChinaDataUnavailableError(f"No announcement source available for {canonical} ({attempted}).")


def get_a_share_official_news(
    ticker: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Present exchange announcements in the common curated-news item format.

    This is intentionally a fallback-only, public official-record adapter.  It
    does not scrape a commercial news site or make the unsupported claim that
    an announcement is a complete replacement for market news.
    """
    records = fetch_a_share_exchange_announcements(
        ticker,
        start_date=start_date,
        end_date=end_date,
    )
    return {
        "source": "china_exchange",
        "items": [
            {
                "title": record.title,
                "url": record.source_uri or "",
                "content": "Official exchange announcement",
                "published": record.published_at or "",
                "publisher": record.source_provider,
                "source": "china_exchange",
                "announcement_id": record.announcement_id,
            }
            for record in records
        ],
    }


def render_announcement_report(
    ticker: str,
    records: Sequence[AnnouncementRecord],
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Render only source facts; absent dates/links remain explicitly absent."""
    if not records:
        raise ChinaDataUnavailableError(f"No announcement records available for {ticker}.")
    source = records[0].source_provider
    lines = [
        f"# China A-share announcements for {normalize_ticker_symbol(ticker)}",
        f"# Source: {source}",
        "# Primary records are exchange announcements; EastMoney is a public fallback.",
        f"# Requested window: {start_date or '?'} to {end_date or '?'}",
        "",
        "| Published at | Title | Source URI | Announcement ID |",
        "|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            "| {date} | {title} | {uri} | {announcement_id} |".format(
                date=_markdown_cell(record.published_at or "N/A"),
                title=_markdown_cell(record.title),
                uri=_markdown_cell(record.source_uri or "N/A"),
                announcement_id=_markdown_cell(record.announcement_id or "N/A"),
            )
        )
    return "\n".join(lines)


def _providers_for(canonical: str) -> tuple[AnnouncementProvider, ...]:
    if canonical.endswith((".SS", ".SH")):
        return (SSEAnnouncementProvider(), EastMoneyAnnouncementFallback())
    if canonical.endswith(".SZ"):
        return (SZSEAnnouncementProvider(), EastMoneyAnnouncementFallback())
    # Beijing listings do not share either of the two official endpoint
    # contracts above, so only expose the explicit public fallback for now.
    if canonical.endswith(".BJ"):
        return (EastMoneyAnnouncementFallback(),)
    raise ChinaDataUnavailableError(f"{canonical} is not recognized as an A-share ticker.")


def _require_a_share_code(ticker: str) -> str:
    if not is_a_share_ticker(ticker):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return to_akshare_symbol(ticker)


def _require_exchange(ticker: str, *, allowed_suffixes: tuple[str, ...]) -> str:
    canonical = normalize_ticker_symbol(ticker)
    if not canonical.endswith(allowed_suffixes):
        raise ChinaDataUnavailableError(f"{canonical} is not served by this exchange announcement provider.")
    return _require_a_share_code(canonical)


def _json_object(response: requests.Response, provider: str) -> Mapping[str, Any]:
    if not 200 <= int(response.status_code) < 300:
        raise VendorHTTPError(provider, int(response.status_code))
    try:
        payload = response.json()
    except ValueError as exc:
        raise VendorHTTPError(provider, int(response.status_code), "invalid JSON response") from exc
    if not isinstance(payload, Mapping):
        raise VendorHTTPError(provider, int(response.status_code), "JSON root is not an object")
    return payload


def _parse_sse_records(payload: Mapping[str, Any]) -> list[AnnouncementRecord]:
    rows = payload.get("result") or payload.get("data") or []
    if isinstance(rows, Mapping):
        rows = rows.get("data") or rows.get("list") or []
    if not isinstance(rows, list):
        return []
    return [_record_from_mapping(row, "sse") for row in rows if isinstance(row, Mapping) and _title(row)]


def _parse_szse_records(payload: Mapping[str, Any]) -> list[AnnouncementRecord]:
    rows = payload.get("data") or []
    if isinstance(rows, Mapping):
        rows = rows.get("list") or rows.get("data") or []
    if not isinstance(rows, list):
        return []
    return [_record_from_mapping(row, "szse") for row in rows if isinstance(row, Mapping) and _title(row)]


def _parse_eastmoney_records(payload: Mapping[str, Any]) -> list[AnnouncementRecord]:
    result = payload.get("result")
    rows = result.get("data") if isinstance(result, Mapping) else payload.get("data")
    if not isinstance(rows, list):
        return []
    return [_record_from_mapping(row, "eastmoney") for row in rows if isinstance(row, Mapping) and _title(row)]


def _record_from_mapping(row: Mapping[str, Any], provider: str) -> AnnouncementRecord:
    announcement_id = _first_text(row, "ARTICLE_CODE", "announcementId", "id", "bulletinId")
    uri = _first_text(row, "URL", "url", "adjunctUrl", "pdfUrl", "attachPath")
    # SZSE annList returns attachPath as a server-relative path; prepend the
    # static CDN prefix so the record carries a directly downloadable PDF link.
    if provider == "szse" and uri and not uri.startswith("http"):
        uri = "https://disc.static.szse.cn/download" + uri
    return AnnouncementRecord(
        title=_title(row) or "N/A",
        published_at=_first_text(row, "NOTICE_DATE", "publishTime", "publishDate", "SSEDATE", "disclosureTime"),
        source_provider=provider,
        source_uri=uri,
        announcement_id=announcement_id,
    )


def _title(row: Mapping[str, Any]) -> str | None:
    return _first_text(row, "TITLE", "title", "bulletinTitle", "announcementTitle")


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _filter_records(
    records: Sequence[AnnouncementRecord], *, start_date: str | None, end_date: str | None
) -> list[AnnouncementRecord]:
    if not start_date and not end_date:
        return list(records)
    return [record for record in records if not record.published_at or _in_window(record.published_at, start_date, end_date)]


def _in_window(value: str, start_date: str | None, end_date: str | None) -> bool:
    observed = value[:10]
    try:
        date.fromisoformat(observed)
    except ValueError:
        return True  # unknown provider format: retain it rather than falsifying a date filter.
    return (not start_date or observed >= start_date) and (not end_date or observed <= end_date)


def _date_window(start_date: str | None, end_date: str | None) -> str:
    if not start_date and not end_date:
        return ""
    return f"{start_date or ''}~{end_date or ''}"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _capture_vendor_raw(payload: Any, *, metadata: Mapping[str, str]) -> None:
    """Load cross-cutting observability after a successful data call only."""
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(payload, metadata=dict(metadata))
