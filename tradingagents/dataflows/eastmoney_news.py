"""EastMoney per-stock news as an A-share company-news fallback.

Tavily remains the primary company-news source. This keyless EastMoney search
endpoint adds a domestic source for A shares when Tavily has no usable result.
Pagination is bounded, analysis dates are enforced, and coverage is public.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from .china_data import ChinaDataUnavailableError
from .coverage import SourceCoverageV1
from .eastmoney import EastMoneyHTTPClient, EastMoneyRequestPolicy
from .ticker_utils import normalize_ticker_symbol, to_akshare_symbol

_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
_CALLBACK = "jQuery_news"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Referer": "https://so.eastmoney.com/"}
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _TAG_RE.sub("", value).strip()


def _published_date(value: Any) -> str | None:
    """Normalize EastMoney's date/time field to a proven ISO calendar date."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()[:10].replace("/", "-")
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _total_pages(payload: dict[str, Any], page_size: int) -> int | None:
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("totalPage", "totalPages", "pageCount", "cmsArticleWebOldTotalPage"):
        try:
            parsed = int(result.get(key))
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    for key in ("total", "totalCount", "cmsArticleWebOldTotalCount"):
        try:
            count = int(result.get(key))
        except (TypeError, ValueError):
            continue
        if count >= 0:
            return (count + page_size - 1) // page_size
    return None


def _capture_page(payload: dict[str, Any], ticker: str, page: int) -> None:
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(
        payload,
        metadata={
            "provider": "eastmoney",
            "dataset": "company_news",
            "ticker": ticker,
            "page": page,
        },
    )


def _request_page(
    http: EastMoneyHTTPClient,
    *,
    canonical: str,
    code: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    inner = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": page,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    params = {"cb": _CALLBACK, "param": json.dumps(inner, separators=(",", ":"))}
    try:
        response = http.get(_SEARCH_URL, params=params, headers=_HEADERS)
        text = response.text
        open_index = text.index("(") + 1
        close_index = text.rindex(")")
        payload = json.loads(text[open_index:close_index])
    except ChinaDataUnavailableError:
        raise
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"EastMoney news request failed for {canonical}: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise ChinaDataUnavailableError(
            f"EastMoney news returned a non-object payload for {canonical}"
        )
    _capture_page(payload, canonical, page)
    return payload


def get_news_eastmoney(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    client: EastMoneyHTTPClient | None = None,
    page_size: int = 20,
    max_pages: int = 3,
) -> dict[str, Any]:
    """Return date-filtered news plus provider-owned coverage metadata."""
    if page_size < 1:
        raise ValueError("page_size must be positive")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    try:
        requested_start = date.fromisoformat(start_date)
        requested_end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("start_date and end_date must use YYYY-MM-DD") from exc
    if requested_start > requested_end:
        raise ValueError("start_date cannot be after end_date")

    canonical = normalize_ticker_symbol(ticker)
    code = to_akshare_symbol(canonical)
    http = client or EastMoneyHTTPClient(
        policy=EastMoneyRequestPolicy(timeout_seconds=12.0)
    )
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    page_count = 0
    pagination_exhausted: bool | None = None
    invalid_published_count = 0

    for page in range(1, max_pages + 1):
        payload = _request_page(
            http,
            canonical=canonical,
            code=code,
            page=page,
            page_size=page_size,
        )
        page_count += 1
        result = payload.get("result") or {}
        articles = result.get("cmsArticleWebOld") or [] if isinstance(result, dict) else []
        if not isinstance(articles, list):
            raise ChinaDataUnavailableError(
                f"EastMoney news returned invalid articles for {canonical}"
            )

        for article in articles:
            if not isinstance(article, dict):
                continue
            title = _strip_tags(article.get("title"))
            published_day = _published_date(article.get("date"))
            if not title or published_day is None:
                if title:
                    invalid_published_count += 1
                continue
            if not start_date <= published_day <= end_date:
                continue
            url = str(article.get("url") or "")
            dedupe_key = (url, title, published_day)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            items.append(
                {
                    "title": title,
                    "url": url,
                    "content": _strip_tags(article.get("content"))[:300],
                    "published": article.get("date") or "",
                    "publisher": article.get("mediaName") or "eastmoney",
                    "source": "eastmoney",
                }
            )

        total_pages = _total_pages(payload, page_size)
        if not articles or (total_pages is not None and page >= total_pages):
            pagination_exhausted = True
            break
    else:
        pagination_exhausted = False

    observed_dates = sorted(
        published_day
        for item in items
        if (published_day := _published_date(item.get("published"))) is not None
    )
    degradations: list[str] = []
    if invalid_published_count:
        degradations.append("invalid_or_missing_published_at")
    if not items:
        completeness = "unavailable"
        degradations.append("no_usable_items")
        actual_start = actual_end = None
    else:
        actual_start, actual_end = observed_dates[0], observed_dates[-1]
        if pagination_exhausted is False:
            completeness = "partial"
            degradations.append("pagination_budget_exhausted")
        elif pagination_exhausted is None:
            completeness = "unknown"
            degradations.append("pagination_unverified")
        elif invalid_published_count:
            completeness = "partial"
        elif actual_start == start_date and actual_end == end_date:
            completeness = "complete"
        else:
            completeness = "partial"
            degradations.append("requested_window_not_fully_observed")

    coverage = SourceCoverageV1(
        capability="company_event_window",
        source_id="eastmoney.company_news",
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=len(items),
        page_count=page_count,
        pagination_exhausted=pagination_exhausted,
        completeness=completeness,
        sources=("eastmoney.company_news",),
        degradations=tuple(degradations),
        as_of=end_date,
    )
    return {
        "source": "eastmoney",
        "items": items,
        "coverage": coverage.model_dump(mode="json"),
    }
