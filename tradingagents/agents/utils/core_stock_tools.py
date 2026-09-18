from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.date_window import as_of_window, trade_date_from_state
from tradingagents.dataflows.interface import route_to_vendor


@tool
@guard_target_ticker("symbol")
def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> str:
    """
    Retrieve stock price data (OHLCV) for a given ticker symbol.
    Uses the configured core_stock_apis vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted dataframe containing the stock price data for the specified ticker symbol in the specified date range.
    """
    start_date, end_date = as_of_window(
        start_date, end_date, trade_date_from_state(state)
    )
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)
