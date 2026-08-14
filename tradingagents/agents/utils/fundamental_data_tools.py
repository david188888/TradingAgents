from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.research.fundamentals_prefetch import (
    fundamentals_from_prefetch_bundle,
    statement_from_prefetch_bundle,
)


@tool
@guard_target_ticker("ticker")
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol.
    Uses the configured fundamental_data vendor unless the run already has a
    frozen, horizon-bounded fundamentals prefetch bundle.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing comprehensive fundamental data
    """
    prefetched = fundamentals_from_prefetch_bundle(
        state.get("fundamentals_prefetch_bundle") if isinstance(state, dict) else None
    )
    return prefetched or route_to_vendor("get_fundamentals", ticker, curr_date)


@tool
@guard_target_ticker("ticker")
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> str:
    """
    Retrieve balance sheet data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing balance sheet data
    """
    prefetched = _prefetched_statement(state, "balance_sheet", freq)
    return prefetched or route_to_vendor("get_balance_sheet", ticker, freq, curr_date)


@tool
@guard_target_ticker("ticker")
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> str:
    """
    Retrieve cash flow statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing cash flow statement data
    """
    prefetched = _prefetched_statement(state, "cash_flow", freq)
    return prefetched or route_to_vendor("get_cashflow", ticker, freq, curr_date)


@tool
@guard_target_ticker("ticker")
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> str:
    """
    Retrieve income statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing income statement data
    """
    prefetched = _prefetched_statement(state, "income_statement", freq)
    return prefetched or route_to_vendor("get_income_statement", ticker, freq, curr_date)


def _prefetched_statement(
    state: dict[str, Any] | None, statement: str, frequency: str
) -> str | None:
    if not isinstance(state, dict):
        return None
    return statement_from_prefetch_bundle(
        state.get("fundamentals_prefetch_bundle"),
        statement=statement,
        frequency=frequency,
    )
