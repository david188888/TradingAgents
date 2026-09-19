"""yfinance-based news data fetching functions."""

import contextlib
from datetime import datetime, timezone

import yfinance as yf
from dateutil.relativedelta import relativedelta

from tradingagents.observability.provenance import capture_vendor_raw

from .config import get_config
from .date_window import coverage_gap, in_window
from .errors import VendorError, VendorRequestError
from .stockstats_utils import raise_if_yahoo_unreachable, yf_retry
from .symbol_utils import normalize_symbol


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure)."""
    # Handle nested content structure
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL from canonicalUrl or clickThroughUrl
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # Get publish date
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # Fallback for flat structure. Parse the epoch publish time so flat
        # articles are date-filterable too (otherwise they bypass the
        # historical window and leak future news, #992/#1007).
        pub_date = None
        ts = article.get("providerPublishTime")
        if ts:
            # Epoch seconds are UTC; parse them as UTC-aware so filtering does
            # not shift with the host timezone (#1126).
            with contextlib.suppress(ValueError, OSError, TypeError):
                pub_date = datetime.fromtimestamp(ts, tz=timezone.utc)
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": pub_date,
        }


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker using yfinance.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    article_limit = get_config()["news_article_limit"]
    # Query Yahoo with the canonical symbol, like every other yfinance path —
    # a raw broker/forex/crypto alias (XAUUSD, BTCUSD) otherwise silently
    # returns no news. Keep the user's ticker in the report header.
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    try:
        stock = yf.Ticker(canonical)
        news = yf_retry(lambda: stock.get_news(count=article_limit)) or []
        capture_vendor_raw(
            news,
            metadata={"provider": "yfinance", "dataset": "company_news", "symbol": canonical},
        )

        # Parse date range for filtering
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        filtered_count = 0

        for article in news:
            data = _extract_article_data(article)

            # Keep only articles within the requested window (look-ahead safe).
            if not in_window(data["pub_date"], start_dt, end_dt):
                continue

            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            filtered_count += 1

        if filtered_count == 0:
            if not news:
                # Nothing came back at all: an outage is not an absence.
                raise_if_yahoo_unreachable("company news", ticker, canonical)
            # Yahoo serves only recent articles, so an empty window it does not
            # reach is "cannot answer", not "no news happened".
            gap = coverage_gap(
                (_extract_article_data(a)["pub_date"] for a in news),
                start_date, end_date, "Yahoo Finance news",
                f"news for {ticker}{resolved}",
            )
            return gap or (
                f"No news found for {ticker}{resolved} between {start_date} and {end_date}"
            )

        return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{news_str}"

    except VendorError:
        raise
    except Exception as e:
        raise VendorRequestError(
            "yfinance", f"news for {canonical} could not be retrieved: {e}"
        ) from e


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news using yfinance Search.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    search_queries = config["global_news_queries"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    in_window_news = []
    seen_titles = set()
    returned_any = False

    try:
        for query in search_queries:
            search = yf_retry(lambda q=query: yf.Search(
                query=q,
                news_count=limit,
                enable_fuzzy_query=True,
            ))
            capture_vendor_raw(
                search.news or [],
                metadata={
                    "provider": "yfinance",
                    "dataset": "global_news",
                    "query": query,
                },
            )

            for article in search.news or []:
                returned_any = True
                # Window first: the limit counts what the run may read, so an
                # out-of-window article must not spend the budget or cut the
                # remaining searches short (#1356). Flat articles are filtered on
                # the same rule, so none can leak future news (#1007).
                data = _extract_article_data(article)
                if not in_window(data["pub_date"], start_dt, curr_dt):
                    continue
                if data["title"] and data["title"] not in seen_titles:
                    seen_titles.add(data["title"])
                    in_window_news.append(data)

            if len(in_window_news) >= limit:
                break

        if not in_window_news:
            if not returned_any:
                # Nothing came back at all: an outage is not "no news".
                raise_if_yahoo_unreachable("global news")
                fallback = f"No global news found for {curr_date}"
            else:
                # Candidates came back but none fell inside the window -> say so
                # rather than return an empty-bodied report (#993).
                fallback = f"No global news found between {start_date} and {curr_date}"
            # Results merge several fuzzy searches, so their timestamps prove no
            # continuous coverage; judge the window against the present only.
            gap = coverage_gap(
                (),
                start_date,
                curr_date,
                "Yahoo Finance global news",
                "market news",
                contiguous=False,
            )
            return gap or fallback

        news_str = ""
        for data in in_window_news[:limit]:
            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"

        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except VendorError:
        raise
    except Exception as e:
        raise VendorRequestError(
            "yfinance", f"global news could not be retrieved: {e}"
        ) from e
