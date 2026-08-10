import json
from collections.abc import Mapping
from typing import Annotated, Any

from langchain_core.tools import tool

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.coverage import CoveredText
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.market_data_validator import (
    build_verified_current_market_snapshot,
    build_verified_market_snapshot,
    get_verified_current_quote,
)
from tradingagents.dataflows.ticker_utils import is_a_share_ticker
from tradingagents.research.horizon_policy import InvestmentHorizon
from tradingagents.research.price_prefetch import build_price_prefetch_plan

MAX_PRICE_BUNDLE_CHARS = 24_000


@tool
@guard_target_ticker("symbol")
def get_verified_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[
        int, "number of recent trading rows to include for sanity-checking"
    ] = 30,
) -> str:
    """Deterministic verification snapshot for exact market-data claims.

    Returns the latest OHLCV row on or before curr_date, common technical
    indicators, and recent closes. Call this before making exact claims about
    price levels, Bollinger bands, RSI, MACD, moving averages, support /
    resistance, or historical comparisons, and treat it as the source of truth.
    """
    return build_verified_market_snapshot(symbol, curr_date, look_back_days)


@tool
@guard_target_ticker("symbol")
def get_verified_current_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
) -> str:
    """Return only the latest verified OHLCV row for current-price facts.

    Historical rows and technical indicators are excluded by contract. Use
    the deterministic adjusted-price bundle for every historical or technical
    claim.
    """
    return build_verified_current_market_snapshot(symbol, curr_date)


def _state_horizon(state: Mapping[str, Any]) -> InvestmentHorizon:
    value = state.get("horizon")
    return value if value in {"short", "medium", "long"} else "medium"


def _price_result(raw: object, *, adjusted: bool) -> dict[str, object]:
    rendered = str(raw)
    truncated = len(rendered) > MAX_PRICE_BUNDLE_CHARS
    public_data = rendered
    if truncated:
        head_chars = MAX_PRICE_BUNDLE_CHARS // 6
        public_data = (
            rendered[:head_chars]
            + "\n... middle rows omitted by deterministic bundle limit ...\n"
            + rendered[-(MAX_PRICE_BUNDLE_CHARS - head_chars) :]
        )
    result: dict[str, object] = {
        "status": "ok" if isinstance(raw, CoveredText) or not adjusted else "degraded",
        "data": public_data,
        "truncated": truncated,
    }
    if isinstance(raw, CoveredText):
        result["coverage"] = raw.coverage.model_dump(mode="json")
    elif adjusted:
        result["degradations"] = ["adjusted_price_coverage_not_reported"]
    return result


def run_adjusted_price_prefetch(
    symbol: str,
    curr_date: str,
    *,
    horizon: InvestmentHorizon,
) -> str:
    """Fetch required adjusted history and a separately labelled raw audit."""
    market = "a_share" if is_a_share_ticker(symbol) else "global"
    plan = build_price_prefetch_plan(horizon, curr_date, market=market)
    try:
        adjusted = _price_result(
            route_to_vendor(
                "get_adjusted_price_history",
                symbol,
                plan.start_date,
                curr_date,
            ),
            adjusted=True,
        )
    except Exception as exc:
        adjusted = {
            "status": "unavailable",
            "degradations": ["adjusted_price_source_unavailable"],
            "error_type": type(exc).__name__,
        }
    try:
        current_quote = get_verified_current_quote(symbol, curr_date)
        quote_snapshot: dict[str, object] = {
            "status": "available",
            "market_price": current_quote.close,
            "price_as_of": current_quote.observed_on,
            # Instrument identity establishes the A-share quote currency, but
            # never the user's cost/NAV currency. Global quote currency remains
            # deliberately unverified until a vendor declares it.
            "quote_currency": "CNY" if market == "a_share" else None,
        }
    except Exception as exc:
        quote_snapshot = {
            "status": "unavailable",
            "reason_code": "verified_market_price_unavailable",
            "error_type": type(exc).__name__,
        }
    try:
        raw_audit = _price_result(
            route_to_vendor("get_stock_data", symbol, plan.start_date, curr_date),
            adjusted=False,
        )
    except Exception as exc:
        raw_audit = {
            "status": "unavailable",
            "degradations": ["raw_price_audit_unavailable"],
            "error_type": type(exc).__name__,
        }
    return json.dumps(
        {
            "schema_version": 1,
            "policy_version": plan.policy_version,
            "ticker": symbol,
            "market": market,
            "horizon": horizon,
            "as_of": curr_date,
            "start_date": plan.start_date,
            "requested_windows": plan.requested_windows,
            "granularities": plan.granularities,
            "required_trading_days": plan.required_trading_days,
            "adjusted": adjusted,
            "current_quote": quote_snapshot,
            "raw_audit": raw_audit,
        },
        ensure_ascii=False,
    )


def create_adjusted_price_prefetch_node():
    """Create the deterministic graph task that precedes Market Analyst."""

    def prefetch(state: Mapping[str, Any]) -> dict[str, str]:
        return {
            "adjusted_price_bundle": run_adjusted_price_prefetch(
                str(state["company_of_interest"]),
                str(state["trade_date"]),
                horizon=_state_horizon(state),
            )
        }

    return prefetch
