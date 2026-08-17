"""Bocha (博查) Web Search backed news search.

Bocha is a domestic Chinese web-search API (https://open.bocha.cn) with a
Bing-compatible response schema.  It supports server-side date-range
filtering via ``freshness``, domain include/exclude lists, and returns
``name``/``url``/``snippet``/``summary``/``siteName``/``datePublished`` per
web page.

Two provider-specific gotchas are handled here:

* ``dateLastCrawled`` values look like ``"2024-07-22T00:00:00Z"`` but are
  actually UTC+8 wall-clock time (acknowledged vendor quirk).  The parser
  strips the bogus ``Z`` and treats the value as Asia/Shanghai.  Prefer
  ``datePublished`` (which carries an explicit ``+08:00`` offset) whenever
  present.
* The vendor recommends ``freshness=noLimit`` (their ranking rewrites the
  query with time context automatically) because explicit date windows can
  return zero results.  The default therefore keeps ``noLimit`` and filters
  client-side; an explicit window mode remains available via config.

The provider follows the same contract as ``tavily_news`` / ``doubao_news``:
* ``get_news_bocha(ticker, start_date, end_date) -> dict`` for company news
* ``get_global_news_bocha(curr_date, look_back_days, limit) -> dict``
* result shape: ``{"source": "bocha", "query": str, "payload": dict,
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

API_URL = "https://api.bocha.cn/v1/web-search"


class BochaUnavailableError(Exception):
    """Raised when Bocha search is not configured or cannot satisfy a news request."""


class _BochaHTTPError(BochaUnavailableError):
    """Transport failure with a structured status for key health policy."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        super().__init__(f"Bocha search failed with HTTP {status_code}: {detail}")


_bocha_key_pool = NewsProviderKeyPool("bocha")


def clear_bocha_key_health() -> None:
    """Clear in-process key cooldowns (mainly useful to deterministic tests)."""
    _bocha_key_pool.clear()


def get_news_bocha(ticker: str, start_date: str, end_date: str) -> dict[str, Any]:
    """Retrieve company-specific market news through Bocha Web Search."""
    cfg = get_config()
    query = _build_company_news_query(ticker, start_date, end_date, cfg)
    return _search_bocha(
        query=query,
        start_date=start_date,
        end_date=end_date,
        log_key=ticker,
        log_date=end_date,
        method="get_news",
        cfg=cfg,
    )


def get_global_news_bocha(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Retrieve broad macro and market news through Bocha Web Search."""
    cfg = get_config()
    if look_back_days is None:
        look_back_days = int(cfg.get("global_news_lookback_days", 7))
    if limit is None:
        limit = int(cfg.get("global_news_article_limit", 5))
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    query_template = str(
        cfg.get(
            "bocha_global_news_query",
            "global financial markets macro economy central bank inflation interest rate "
            "earnings commodities geopolitical risk outlook",
        )
    )
    # Embed the time window into the query since the default freshness mode is
    # noLimit (vendor-recommended); the ranking layer rewrites time context.
    query = f"{query_template} {start_date} to {curr_date}"
    return _search_bocha(
        query=query,
        start_date=start_date,
        end_date=curr_date,
        log_key="GLOBAL",
        log_date=curr_date,
        method="get_global_news",
        limit=limit,
        cfg=cfg,
    )


def _search_bocha(
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
        raise BochaUnavailableError(
            "No Bocha search API key is configured. "
            "Set BOCHA_API_KEY or the comma-separated BOCHA_API_KEYS."
        )
    _bocha_key_pool.configure(api_keys)

    cfg = cfg or get_config()
    configured_max = int(cfg.get("bocha_max_results", 8))
    max_results = min(int(limit), configured_max) if limit else configured_max
    # Ask for more than requested so client-side date filtering still leaves
    # enough in-window results.  Cap at 50 (API maximum).
    requested_count = min(max(max_results * 2, max_results + 3), 50)

    payload: dict[str, Any] = {
        "query": query,
        "summary": _config_bool(cfg.get("bocha_summary", True)),
        "count": requested_count,
        "freshness": _freshness_value(cfg, start_date, end_date),
    }
    include_domains = _domain_config(cfg.get("bocha_include_domains"))
    exclude_domains = _domain_config(cfg.get("bocha_exclude_domains"))
    if method == "get_news":
        include_domains += _domain_config(cfg.get("bocha_company_include_domains"))
        exclude_domains += _domain_config(cfg.get("bocha_company_exclude_domains"))
    elif method == "get_global_news":
        include_domains += _domain_config(cfg.get("bocha_global_include_domains"))
        exclude_domains += _domain_config(cfg.get("bocha_global_exclude_domains"))
    if include_domains:
        payload["include"] = "|".join(dict.fromkeys(include_domains))
    if exclude_domains:
        payload["exclude"] = "|".join(dict.fromkeys(exclude_domains))

    response_data = _post_with_healthy_key(payload)
    capture_vendor_raw(
        response_data,
        metadata={
            "provider": "bocha",
            "transport_attempt": 1,
        },
    )
    _save_raw_response(log_key, log_date, method, payload, response_data)
    items = _items_from_response(response_data, cfg, start_date, end_date, requested=max_results)
    result: dict[str, Any] = {
        "source": "bocha",
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


def _freshness_value(cfg: dict[str, Any], start_date: str, end_date: str) -> str:
    """Resolve the server-side freshness filter.

    Vendor guidance: ``noLimit`` lets their ranking rewrite time context and
    is less likely to return zero results; explicit windows are still exposed
    for operators who prefer strict server-side recency.
    """
    mode = str(cfg.get("bocha_freshness", "noLimit")).strip().lower()
    if mode == "window" and start_date and end_date:
        return f"{start_date}..{end_date}"
    if mode in {"oneday", "one_day"}:
        return "oneDay"
    if mode in {"oneweek", "one_week"}:
        return "oneWeek"
    if mode in {"onemonth", "one_month"}:
        return "oneMonth"
    if mode in {"oneyear", "one_year"}:
        return "oneYear"
    return "noLimit"


def _company_news_coverage(
    *,
    items: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> SourceCoverageV1:
    """Describe Bocha news observability without overstating search recall."""
    dated_items = [
        (item, _published_date_iso(str(item.get("published") or "")))
        for item in items
    ]
    dated_items = [
        (item, published)
        for item, published in dated_items
        if published and start_date <= published <= end_date
    ]
    no_limit = str(get_config().get("bocha_freshness", "noLimit")).strip().lower() != "window"
    degradations = (
        ("search_recall_not_verifiable", "no_server_side_date_filter")
        if no_limit
        else ("search_recall_not_verifiable",)
    )
    if not dated_items:
        return SourceCoverageV1(
            capability="company_event_window",
            source_id="bocha.company_news",
            requested_start=start_date,
            requested_end=end_date,
            item_count=0,
            completeness="unavailable",
            sources=("bocha.company_news",),
            degradations=("no_time_verifiable_items", *degradations[1:]),
            as_of=end_date,
        )
    observed_dates = sorted(published for _item, published in dated_items)
    return SourceCoverageV1(
        capability="company_event_window",
        source_id="bocha.company_news",
        requested_start=start_date,
        requested_end=end_date,
        actual_start=observed_dates[0],
        actual_end=observed_dates[-1],
        item_count=len(dated_items),
        completeness="partial",
        sources=("bocha.company_news",),
        degradations=degradations,
        as_of=end_date,
    )


def _published_date_iso(value: str) -> str | None:
    if not value:
        return None
    normalized = _normalize_bocha_timestamp(value)
    if normalized is None:
        return None
    return normalized.date().isoformat()


def _normalize_bocha_timestamp(raw: str) -> datetime | None:
    """Parse a Bocha timestamp into a timezone-aware UTC datetime.

    ``datePublished`` carries an explicit ``+08:00`` offset and parses
    directly.  ``dateLastCrawled`` values end in ``Z`` but are actually
    UTC+8 wall-clock (documented vendor quirk), so the bogus ``Z`` is
    replaced with ``+08:00`` before parsing.
    """
    from datetime import timezone as _tz

    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+08:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_tz.utc)


def _configured_api_keys() -> tuple[str, ...]:
    """Read multi-key configuration without logging or returning it to callers."""
    multi = os.getenv("BOCHA_API_KEYS", "")
    values = [part.strip() for part in multi.split(",") if part.strip()]
    legacy = os.getenv("BOCHA_API_KEY", "").strip()
    if legacy:
        values.append(legacy)
    # ``dict.fromkeys`` preserves operator-supplied priority while removing
    # duplicate credentials that would otherwise waste a rotation attempt.
    return tuple(dict.fromkeys(values))


def _post_with_healthy_key(payload: dict[str, Any]) -> dict[str, Any]:
    """Try each healthy key exactly once for transient failures."""
    attempted = 0
    last_error: Exception | None = None
    while (api_key := _bocha_key_pool.acquire()) is not None:
        attempted += 1
        try:
            data = _post_search(payload, api_key)
        except _BochaHTTPError as exc:
            last_error = exc
            cooldown_seconds, reason = _key_cooldown_for_status(exc.status_code)
            if cooldown_seconds <= 0:
                raise BochaUnavailableError(
                    f"Bocha rejected the configured request with HTTP {exc.status_code}; "
                    "key rotation was not attempted."
                ) from exc
            _bocha_key_pool.record_failure(
                api_key,
                cooldown_seconds=cooldown_seconds,
                reason=reason,
            )
            continue
        except requests.RequestException as exc:
            last_error = exc
            _bocha_key_pool.record_failure(
                api_key,
                cooldown_seconds=TRANSIENT_FAILURE_COOLDOWN_SECONDS,
                reason="network",
            )
            continue
        _bocha_key_pool.record_success(api_key)
        return data

    if attempted:
        raise BochaUnavailableError(
            "Bocha search is temporarily unavailable: every configured key is cooling down "
            "after a transient provider failure."
        ) from last_error
    raise BochaUnavailableError(
        "Bocha search is temporarily unavailable: every configured key is in cooldown."
    )


def _key_cooldown_for_status(status_code: int) -> tuple[float, str]:
    if status_code == 429:
        return RATE_LIMIT_COOLDOWN_SECONDS, "rate_limit"
    if status_code == 403:
        # 403 = insufficient balance; rotating to another key is legitimate,
        # but a short cooldown avoids hammering a broke account.
        return TRANSIENT_FAILURE_COOLDOWN_SECONDS, "insufficient_balance"
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
        "bocha_a_share_news_query_template"
        if is_a_share_ticker(ticker)
        else "bocha_company_news_query_template"
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
    # Embed date window - the default freshness mode is noLimit, so anchoring
    # the query with the requested range improves time recall.
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
        raise _BochaHTTPError(
            response.status_code,
            "provider returned an error response",
        )
    # Bocha returns HTTP 200 with a non-200 ``code`` field on business errors.
    code = data.get("code")
    if code is not None and int(code) != 200:
        raise _BochaHTTPError(
            int(code) if isinstance(code, int) or (isinstance(code, str) and code.isdigit()) else 500,
            str(data.get("msg") or "provider returned a business error"),
        )
    return data


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _domain_config(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[|,]", value) if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _items_from_response(
    response_data: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    requested: int = 8,
) -> list[dict[str, Any]]:
    data = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}
    web_pages = data.get("webPages") if isinstance(data.get("webPages"), dict) else {}
    pages = web_pages.get("value") or []
    items: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        url = page.get("url") or ""
        title = page.get("name") or "Untitled"
        # Prefer datePublished (explicit +08:00); fall back to dateLastCrawled
        # (bogus-Z UTC+8 wall clock, normalized in _normalize_bocha_timestamp).
        published = page.get("datePublished") or page.get("dateLastCrawled") or ""
        publisher = page.get("siteName") or _publisher_from_url(url)
        content = str(page.get("summary") or page.get("snippet") or "").strip()
        item = {
            "title": title,
            "url": url,
            "content": content,
            "published": published,
            "score": None,  # Bocha does not expose a relevance score
            "publisher": publisher,
            "source": "bocha",
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


_KNOWN_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y%m%d",
)


def _parse_published_date(raw: str) -> datetime | None:
    """Best-effort parse of a published date string into a naive datetime."""
    text = str(raw or "").strip()
    if not text:
        return None
    # Bocha timestamps are UTC+8 wall clock; normalize the bogus Z suffix and
    # compare in naive local terms by stripping the offset after conversion.
    if text.endswith("Z"):
        text = text[:-1] + "+08:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _KNOWN_DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    # Convert UTC+8 wall-clock intent to a naive Beijing datetime: treat the
    # wall time as-is (Bocha expresses publish time in Beijing time).
    return parsed.replace(tzinfo=None)


def _is_published_outside_window(published: str, start_date: str, end_date: str) -> bool:
    """Return True if the published date is clearly outside the [start, end] window."""
    dt = _parse_published_date(published)
    if dt is None:
        return False  # can't determine -> don't flag as stale
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

    request_id = str(response_data.get("log_id") or "no-request-id")
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", log_key)
    safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", request_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_dir = Path(results_dir) / safe_key / str(log_date) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"bocha_{method}_{timestamp}_{safe_request_id}.json"
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
