"""Doubao (豆包搜索 Global 版) backed news search.

Doubao search is a ByteDance / Volcengine web-search API.  The Global
edition used here returns ranked web documents with title, URL, snippets,
host information and an optional published timestamp.  It does **not**
support server-side date-range filtering, so results are filtered
client-side by ``PublishTime`` and the query templates include the
requested date window as natural-language anchors to improve recall.

The provider follows the same contract as ``tavily_news``:
* ``get_news_doubao(ticker, start_date, end_date) -> dict`` for company news
* ``get_global_news_doubao(curr_date, look_back_days, limit) -> dict`` for macro news
* result shape: ``{"source": "doubao", "query": str, "payload": dict,
  "response": dict, "items": list[item], "coverage": dict?}``
* multi-key rotation via :class:`NewsProviderKeyPool`
* raw vendor payload captured by :func:`capture_vendor_raw`
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from tradingagents.observability.provenance import capture_vendor_raw

from .config import get_config
from .coverage import SourceCoverageV1
from .news_key_health import (
    RATE_LIMIT_COOLDOWN_SECONDS,
    TRANSIENT_FAILURE_COOLDOWN_SECONDS,
    NewsProviderKeyPool,
)
from .target_context import get_target_ticker
from .ticker_utils import is_a_share_ticker, to_akshare_symbol

API_URL = "https://open.feedcoopapi.com/search_api/global_search"


class DoubaoUnavailableError(Exception):
    """Raised when Doubao search is not configured or cannot satisfy a news request."""


class _DoubaoHTTPError(DoubaoUnavailableError):
    """Transport failure with a structured status for key health policy."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        super().__init__(f"Doubao search failed with HTTP {status_code}: {detail}")


_doubao_key_pool = NewsProviderKeyPool("doubao")


def clear_doubao_key_health() -> None:
    """Clear in-process key cooldowns (mainly useful to deterministic tests)."""
    _doubao_key_pool.clear()


def get_news_doubao(ticker: str, start_date: str, end_date: str) -> dict[str, Any]:
    """Retrieve company-specific market news through Doubao Search."""
    cfg = get_config()
    query = _build_company_news_query(ticker, start_date, end_date, cfg)
    return _search_doubao(
        query=query,
        start_date=start_date,
        end_date=end_date,
        log_key=ticker,
        log_date=end_date,
        method="get_news",
        cfg=cfg,
    )


def get_global_news_doubao(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Retrieve broad macro and market news through Doubao Search."""
    cfg = get_config()
    if look_back_days is None:
        look_back_days = int(cfg.get("global_news_lookback_days", 7))
    if limit is None:
        limit = int(cfg.get("global_news_article_limit", 5))
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    query_template = str(
        cfg.get(
            "doubao_global_news_query",
            "global financial markets macro economy central bank inflation interest rate "
            "earnings commodities geopolitical risk outlook",
        )
    )
    # Embed the time window into the query since the API has no server-side filter.
    query = f"{query_template} {start_date} to {curr_date}"
    return _search_doubao(
        query=query,
        start_date=start_date,
        end_date=curr_date,
        log_key="GLOBAL",
        log_date=curr_date,
        method="get_global_news",
        limit=limit,
        cfg=cfg,
    )


def _search_doubao(
    *,
    query: str,
    start_date: str,
    end_date: str,
    log_key: str,
    log_date: str,
    method: str,
    limit: int | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_keys = _configured_api_keys()
    if not api_keys:
        raise DoubaoUnavailableError(
            "No Doubao search API key is configured. "
            "Set DOUBAO_SEARCH_API_KEY or the comma-separated DOUBAO_SEARCH_API_KEYS."
        )
    _doubao_key_pool.configure(api_keys)

    cfg = cfg or get_config()
    configured_max = int(cfg.get("doubao_max_results", 5))
    max_results = min(int(limit), configured_max) if limit else configured_max
    # Ask for more than requested so client-side date filtering still leaves
    # enough in-window results.  Cap at 20 (API maximum).
    requested_doc_count = min(max(max_results * 2, max_results + 3), 20)

    payload: dict[str, Any] = {
        "Query": query,
        "SearchType": "web",
        "DocCount": requested_doc_count,
        "MaxSnippetLength": int(cfg.get("doubao_max_snippet_length", 800)),
        "MaxImageCountPerDoc": 0,
    }
    if _config_bool(cfg.get("doubao_icp_host_only", False)):
        payload["Filter"] = {"IcpHostOnly": True}

    response_data = _post_with_healthy_key(payload)
    capture_vendor_raw(
        response_data,
        metadata={
            "provider": "doubao",
            "transport_attempt": 1,
        },
    )
    _save_raw_response(log_key, log_date, method, payload, response_data)
    items = _items_from_response(response_data, cfg, start_date, end_date, requested=max_results)
    result: dict[str, Any] = {
        "source": "doubao",
        "query": query,
        "payload": payload,
        "response": response_data,
        "items": items,
    }
    if method == "get_news":
        result["coverage"] = _company_news_coverage(
            items=items,
            start_date=start_date,
            end_date=end_date,
        ).model_dump(mode="json")
    return result


def _company_news_coverage(
    *,
    items: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> SourceCoverageV1:
    """Describe Doubao news observability without overstating search recall.

    Doubao has no server-side date filter, so even dated items cannot
    guarantee full window coverage — the result is at best ``partial``.
    """
    dated_items = [
        (item, _published_date_iso(str(item.get("published") or "")))
        for item in items
    ]
    dated_items = [
        (item, published)
        for item, published in dated_items
        if published and start_date <= published <= end_date
    ]
    if not dated_items:
        return SourceCoverageV1(
            capability="company_event_window",
            source_id="doubao.company_news",
            requested_start=start_date,
            requested_end=end_date,
            item_count=0,
            completeness="unavailable",
            sources=("doubao.company_news",),
            degradations=(
                "no_time_verifiable_items",
                "no_server_side_date_filter",
            ),
            as_of=end_date,
        )
    observed_dates = sorted(published for _item, published in dated_items)
    return SourceCoverageV1(
        capability="company_event_window",
        source_id="doubao.company_news",
        requested_start=start_date,
        requested_end=end_date,
        actual_start=observed_dates[0],
        actual_end=observed_dates[-1],
        item_count=len(dated_items),
        completeness="partial",
        sources=("doubao.company_news",),
        degradations=(
            "search_recall_not_verifiable",
            "no_server_side_date_filter",
        ),
        as_of=end_date,
    )


def _published_date_iso(value: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None


def _configured_api_keys() -> tuple[str, ...]:
    """Read multi-key configuration without logging or returning it to callers."""
    multi = os.getenv("DOUBAO_SEARCH_API_KEYS", "")
    values = [part.strip() for part in multi.split(",") if part.strip()]
    legacy = os.getenv("DOUBAO_SEARCH_API_KEY", "").strip()
    if legacy:
        values.append(legacy)
    # ``dict.fromkeys`` preserves operator-supplied priority while removing
    # duplicate credentials that would otherwise waste a rotation attempt.
    return tuple(dict.fromkeys(values))


def _post_with_healthy_key(payload: dict[str, Any]) -> dict[str, Any]:
    """Try each healthy key exactly once for transient failures."""
    attempted = 0
    last_error: Exception | None = None
    while (api_key := _doubao_key_pool.acquire()) is not None:
        attempted += 1
        try:
            data = _post_search(payload, api_key)
        except _DoubaoHTTPError as exc:
            last_error = exc
            cooldown_seconds, reason = _key_cooldown_for_status(exc.status_code)
            if cooldown_seconds <= 0:
                raise DoubaoUnavailableError(
                    f"Doubao rejected the configured request with HTTP {exc.status_code}; "
                    "key rotation was not attempted."
                ) from exc
            _doubao_key_pool.record_failure(
                api_key,
                cooldown_seconds=cooldown_seconds,
                reason=reason,
            )
            continue
        except requests.RequestException as exc:
            last_error = exc
            _doubao_key_pool.record_failure(
                api_key,
                cooldown_seconds=TRANSIENT_FAILURE_COOLDOWN_SECONDS,
                reason="network",
            )
            continue
        _doubao_key_pool.record_success(api_key)
        return data

    if attempted:
        raise DoubaoUnavailableError(
            "Doubao search is temporarily unavailable: every configured key is cooling down "
            "after a transient provider failure."
        ) from last_error
    raise DoubaoUnavailableError(
        "Doubao search is temporarily unavailable: every configured key is in cooldown."
    )


def _key_cooldown_for_status(status_code: int) -> tuple[float, str]:
    if status_code == 429:
        return RATE_LIMIT_COOLDOWN_SECONDS, "rate_limit"
    if 500 <= status_code <= 599:
        return TRANSIENT_FAILURE_COOLDOWN_SECONDS, f"http_{status_code}"
    return 0.0, f"http_{status_code}"


def _build_company_news_query(
    ticker: str,
    start_date: str,
    end_date: str,
    cfg: dict[str, Any],
) -> str:
    plain_ticker = to_akshare_symbol(ticker) if is_a_share_ticker(ticker) else ticker
    target = get_target_ticker()
    company_name = (target.company_name if target else None) or ""
    template_key = (
        "doubao_a_share_news_query_template"
        if is_a_share_ticker(ticker)
        else "doubao_company_news_query_template"
    )
    default_template = (
        '"{ticker}" "{plain_ticker}" "{company_name}" 股票 公告 业绩 财报 经营 市场 新闻'
        if is_a_share_ticker(ticker)
        else '"{ticker}" "{company_name}" stock market news earnings revenue guidance analyst rating'
    )
    template = str(cfg.get(template_key) or default_template)
    query = template.format(
        ticker=ticker,
        plain_ticker=plain_ticker,
        company_name=company_name,
    )
    # Drop empty quoted placeholders (company name unavailable) and collapse
    # whitespace so the query stays well-formed for either market.
    query = re.sub(r'""', "", query)
    query = re.sub(r"\s+", " ", query).strip()
    # Embed date window — Doubao Global 版 has no server-side date filter,
    # so anchoring the query with the requested range improves recall.
    if start_date and end_date:
        query = f"{query} {start_date} to {end_date}"
    return query


def _post_search(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {"raw_text": response.text}

    if response.status_code >= 400:
        raise _DoubaoHTTPError(
            response.status_code,
            "provider returned an error response",
        )
    # The API returns HTTP 200 with a structured Error field on some failures
    # (e.g. query empty → CodeN 10400).  Treat those as caller errors too.
    meta = data.get("ResponseMetadata") if isinstance(data.get("ResponseMetadata"), dict) else {}
    error = meta.get("Error") if isinstance(meta.get("Error"), dict) else {}
    if error:
        code_n = error.get("CodeN")
        message = error.get("Message") or ""
        if isinstance(code_n, int) and 400 <= code_n < 500:
            raise _DoubaoHTTPError(400, f"doubao error {code_n}: {message}")
        if isinstance(code_n, int) and code_n >= 500:
            raise _DoubaoHTTPError(502, f"doubao error {code_n}: {message}")
    return data


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _items_from_response(
    response_data: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    requested: int = 5,
) -> list[dict[str, Any]]:
    result = response_data.get("Result") if isinstance(response_data.get("Result"), dict) else {}
    documents = result.get("Documents") or []
    items: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        url = doc.get("Url") or ""
        title = doc.get("Title") or "Untitled"
        doc_info = doc.get("DocumentInfo") if isinstance(doc.get("DocumentInfo"), dict) else {}
        host_info = doc.get("HostInfo") if isinstance(doc.get("HostInfo"), dict) else {}
        published = doc_info.get("PublishTime") or ""
        publisher = host_info.get("Hostname") or _publisher_from_url(url)
        content = _join_text_snippets(doc.get("Snippet") or [])
        item = {
            "title": title,
            "url": url,
            "content": content,
            "published": published,
            "score": None,  # Doubao does not expose a relevance score
            "publisher": publisher,
            "source": "doubao",
            "authority_level": host_info.get("AuthorityLevel"),
        }
        if start_date and end_date and published:
            item["stale"] = _is_published_outside_window(published, start_date, end_date)
        items.append(item)
    # Keep only the first ``requested`` non-stale items (or fewer if too few).
    # We asked for more from the API so date filtering has headroom.
    non_stale = [item for item in items if not item.get("stale")]
    stale = [item for item in items if item.get("stale")]
    kept = non_stale[:requested]
    # If not enough in-window results, pad with stale items so the caller
    # still gets something to work with (curator will mark them properly).
    if len(kept) < requested:
        kept.extend(stale[: requested - len(kept)])
    return kept


def _join_text_snippets(snippets: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        if snippet.get("Type") == "text" and snippet.get("Text"):
            parts.append(str(snippet["Text"]).strip())
    return " ".join(parts).strip()


_KNOWN_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y年%m月%d日",
    "%Y%m%dT%H%M%S",
    "%Y%m%d",
)


def _parse_published_date(raw: str) -> datetime | None:
    """Best-effort parse of a published date string into a naive datetime."""
    text = str(raw or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"\s+[A-Z]{2,4}$", "", text)
    for fmt in _KNOWN_DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    # Try ISO format as last resort
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _is_published_outside_window(published: str, start_date: str, end_date: str) -> bool:
    """Return True if the published date is clearly outside the [start, end] window."""
    dt = _parse_published_date(published)
    if dt is None:
        return False  # can't determine → don't flag as stale
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        return False
    return dt < start or dt >= end


def _publisher_from_url(url: str) -> str:
    domain = urlparse(str(url or "")).netloc.lower()
    return domain.removeprefix("www.") or "unknown"


def _save_raw_response(
    log_key: str,
    log_date: str,
    method: str,
    payload: dict[str, Any],
    response_data: dict[str, Any],
) -> None:
    cfg = get_config()
    results_dir = cfg.get("results_dir")
    if not results_dir:
        return

    request_id = ""
    meta = response_data.get("ResponseMetadata")
    if isinstance(meta, dict):
        request_id = str(meta.get("RequestId") or "no-request-id")
    else:
        request_id = "no-request-id"
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", log_key)
    safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", request_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_dir = Path(results_dir) / safe_key / str(log_date) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"doubao_{method}_{timestamp}_{safe_request_id}.json"
    path.write_text(
        json.dumps(
            {
                "payload": payload,
                "response": response_data,
                "request_id": request_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
