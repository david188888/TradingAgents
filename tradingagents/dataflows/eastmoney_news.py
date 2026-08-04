"""EastMoney per-stock news as an A-share company-news fallback.

Tavily remains the primary company-news source. This keyless EastMoney search
endpoint (search-api-web.eastmoney.com, JSONP) adds a domestic, no-API-key
news source for A shares when Tavily is unavailable or returns nothing. It is
deliberately a simple fallback: one bounded request, source-labelled items,
and a typed error on any transport/parse failure so the router can degrade.

See a-stock-data SKILL.md §5.1 for the endpoint contract.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .china_data import ChinaDataUnavailableError
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


def get_news_eastmoney(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    client: EastMoneyHTTPClient | None = None,
    page_size: int = 20,
) -> dict[str, Any]:
    """Return per-stock EastMoney news in the curated-news dict protocol.

    Returns ``{"source": "eastmoney", "items": [...]}`` where each item has
    title/url/content/published/publisher. An empty article list is returned
    (not raised) so the news router records it as an empty source and continues
    to the next vendor/fallback.
    """
    canonical = normalize_ticker_symbol(ticker)
    code = to_akshare_symbol(canonical)
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
                "pageIndex": 1,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    params = {"cb": _CALLBACK, "param": json.dumps(inner, separators=(",", ":"))}

    http = client or EastMoneyHTTPClient(policy=EastMoneyRequestPolicy(timeout_seconds=12.0))
    try:
        response = http.get(_SEARCH_URL, params=params, headers=_HEADERS)
        text = response.text
        start = text.index("(") + 1
        end = text.rindex(")")
        payload = json.loads(text[start:end])
    except ChinaDataUnavailableError:
        raise
    except Exception as exc:
        raise ChinaDataUnavailableError(
            f"EastMoney news request failed for {canonical}: {type(exc).__name__}"
        ) from exc

    if not isinstance(payload, dict):
        raise ChinaDataUnavailableError(f"EastMoney news returned a non-object payload for {canonical}")

    articles = ((payload.get("result") or {}).get("cmsArticleWebOld")) or []
    items = [
        {
            "title": _strip_tags(article.get("title")),
            "url": article.get("url") or "",
            "content": _strip_tags(article.get("content"))[:300],
            "published": article.get("date") or "",
            "publisher": article.get("mediaName") or "eastmoney",
            "source": "eastmoney",
        }
        for article in articles
        if isinstance(article, dict) and _strip_tags(article.get("title"))
    ]
    return {"source": "eastmoney", "items": items}
