import json
from datetime import date, timedelta
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.ticker_utils import is_a_share_ticker


@tool
@guard_target_ticker("ticker")
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
@guard_target_ticker("ticker")
def get_news_windows(
    ticker: Annotated[str, "Target A-share ticker symbol"],
    curr_date: Annotated[str, "Analysis cutoff date in yyyy-mm-dd format"],
) -> str:
    """Fetch fixed event/theme/official windows for an A-share target.

    The function owns the date boundaries so a model cannot silently turn a
    seven-day event query into a claim that the longer-term theme is absent.
    """
    try:
        end = date.fromisoformat(curr_date)
    except ValueError:
        return "Invalid analysis cutoff date."
    windows = {
        "event": 7,
        "theme": 180,
        "official": 1460,
    }
    result: dict[str, object] = {"ticker": ticker, "as_of": curr_date, "windows": {}}
    for name, days in windows.items():
        start = (end - timedelta(days=days)).isoformat()
        try:
            if name == "official" and is_a_share_ticker(ticker):
                payload = route_to_vendor("get_a_share_cninfo_announcements", ticker, start, curr_date)
            else:
                payload = route_to_vendor("get_news", ticker, start, curr_date)
        except Exception as exc:
            payload = f"unavailable: {type(exc).__name__}"
        result["windows"][name] = {
            "start_date": start,
            "end_date": curr_date,
            "lookback_days": days,
            "source_policy": "company news; official window requires separate公告核验",
            "data": payload,
        }
    return json.dumps(result, ensure_ascii=False)


@tool
@guard_target_ticker("ticker")
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
