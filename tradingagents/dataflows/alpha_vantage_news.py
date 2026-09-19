import json
from datetime import date

from .alpha_vantage_common import _make_api_request, format_datetime_for_api


def get_news(ticker, start_date, end_date) -> dict[str, str] | str:
    """Returns live and historical market news & sentiment data from premier news outlets worldwide.

    Covers stocks, cryptocurrencies, forex, and topics like fiscal policy, mergers & acquisitions, IPOs.

    Args:
        ticker: Stock symbol for news articles.
        start_date: Start date for news search.
        end_date: End date for news search.

    Returns:
        Dictionary containing news sentiment data or JSON string.
    """

    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        # The window ends at the end of the analysis day, not at its midnight.
        "time_to": format_datetime_for_api(end_date, end_of_day=True),
    }

    return _make_api_request("NEWS_SENTIMENT", params)

def get_global_news(curr_date, look_back_days: int = 7, limit: int = 50) -> dict[str, str] | str:
    """Returns global market news & sentiment data without ticker-specific filtering.

    Covers broad market topics like financial markets, economy, and more.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days to look back (default 7).
        limit: Maximum number of articles (default 50).

    Returns:
        Dictionary containing global news sentiment data or JSON string.
    """
    from datetime import datetime, timedelta

    # Calculate start date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    params = {
        "topics": "financial_markets,economy_macro,economy_monetary",
        "time_from": format_datetime_for_api(start_date),
        # Same rule as the ticker window: include the current day itself.
        "time_to": format_datetime_for_api(curr_date, end_of_day=True),
        "limit": str(limit),
    }

    return _make_api_request("NEWS_SENTIMENT", params)


def get_insider_transactions(
    symbol: str, curr_date: str | None = None
) -> dict[str, str] | str:
    """Returns latest and historical insider transactions by key stakeholders.

    Covers transactions by founders, executives, board members, etc.

    Args:
        symbol: Ticker symbol. Example: "IBM".
        curr_date: When given, retain only transactions on or before this
            analysis date (yyyy-mm-dd).

    Returns:
        Dictionary containing insider transaction data or JSON string.
    """

    params = {
        "symbol": symbol,
    }

    response = _make_api_request("INSIDER_TRANSACTIONS", params)
    if not curr_date:
        return response

    cutoff = date.fromisoformat(curr_date)
    payload = json.loads(response)
    transactions = payload.get("data")
    if not isinstance(transactions, list):
        raise ValueError("INSIDER_TRANSACTIONS response must contain a data list")

    kept = []
    for transaction in transactions:
        if not isinstance(transaction, dict):
            raise ValueError("INSIDER_TRANSACTIONS data entries must be objects")
        transaction_date = transaction.get("transaction_date")
        if not isinstance(transaction_date, str):
            raise ValueError("INSIDER_TRANSACTIONS transaction_date is required")
        try:
            occurred_on = date.fromisoformat(transaction_date)
        except ValueError as exc:
            raise ValueError(
                f"INSIDER_TRANSACTIONS transaction_date is invalid: {transaction_date!r}"
            ) from exc
        if occurred_on <= cutoff:
            kept.append(transaction)
    payload["data"] = kept
    return json.dumps(payload)
