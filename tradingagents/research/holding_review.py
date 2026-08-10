"""Deterministic, learning-only holding-review calculations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from math import isfinite
from typing import Any

from tradingagents.execution.models import HoldingContext, holding_context_from_dict


def build_holding_review_summary(
    holding: HoldingContext | Mapping[str, Any],
    *,
    analysis_date: str,
    market_price: float | None = None,
    quote_currency: str | None = None,
    price_as_of: str | None = None,
) -> dict[str, Any]:
    """Return only reproducible review facts, never a transaction instruction.

    A price is usable only when it is finite, positive, aligned to the
    analysis date, and its quote currency matches the user's explicit holding
    currency.  This deliberately does not infer a currency from the ticker.
    """
    context = (
        holding if isinstance(holding, HoldingContext) else holding_context_from_dict(holding)
    )
    price_reason = _price_reason(
        context,
        analysis_date=analysis_date,
        market_price=market_price,
        quote_currency=quote_currency,
        price_as_of=price_as_of,
    )
    original_thesis = (
        {"status": "provided", "text": context.original_thesis}
        if context.original_thesis
        else {"status": "unavailable", "reason_code": "original_thesis_not_provided"}
    )
    concentration = _concentration(context, market_price, price_reason)
    pnl = _pnl(context, market_price, price_reason)
    return {
        "schema_version": 1,
        "mode": "holding_review",
        "ticker": context.ticker,
        "facts_as_of": context.facts_as_of,
        "original_thesis": original_thesis,
        "concentration": concentration,
        "unrealized_pnl": pnl,
        "scenario_sensitivity": _scenario_sensitivity(context, market_price, price_reason),
        "review_boundary": "learning_only_no_transaction_instruction",
    }


def holding_review_quote_from_bundle(value: object) -> dict[str, object]:
    """Extract only the committed, code-owned quote fields from prefetch JSON."""
    if not isinstance(value, str):
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    quote = payload.get("current_quote")
    if not isinstance(quote, Mapping) or quote.get("status") != "available":
        return {}
    price = quote.get("market_price")
    price_as_of = quote.get("price_as_of")
    currency = quote.get("quote_currency")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return {}
    return {
        "market_price": float(price),
        "price_as_of": price_as_of if isinstance(price_as_of, str) else None,
        "quote_currency": currency if isinstance(currency, str) else None,
    }


def _price_reason(
    holding: HoldingContext,
    *,
    analysis_date: str,
    market_price: float | None,
    quote_currency: str | None,
    price_as_of: str | None,
) -> str | None:
    if (
        market_price is None
        or not isinstance(market_price, (int, float))
        or not isfinite(market_price)
        or market_price <= 0
        or price_as_of != analysis_date
    ):
        return "verified_market_price_unavailable"
    if holding.currency is None or quote_currency is None:
        return "currency_unverified"
    if holding.currency.upper() != quote_currency.upper():
        return "currency_mismatch"
    return None


def _unavailable(reason_code: str) -> dict[str, str]:
    return {"status": "unavailable", "reason_code": reason_code}


def _concentration(
    holding: HoldingContext,
    market_price: float | None,
    price_reason: str | None,
) -> dict[str, Any]:
    if holding.total_account_value is None:
        return _unavailable("total_account_value_not_provided")
    if price_reason is not None:
        return _unavailable(price_reason)
    assert market_price is not None
    position_value = holding.quantity * market_price
    return {
        "status": "available",
        "position_market_value": position_value,
        "total_account_value": holding.total_account_value,
        "weight": position_value / holding.total_account_value,
    }


def _pnl(
    holding: HoldingContext,
    market_price: float | None,
    price_reason: str | None,
) -> dict[str, Any]:
    if price_reason is not None:
        return _unavailable(price_reason)
    assert market_price is not None
    cost_basis = holding.quantity * holding.average_cost
    market_value = holding.quantity * market_price
    return {
        "status": "available",
        "cost_basis": cost_basis,
        "market_value": market_value,
        "amount": market_value - cost_basis,
        "return_ratio": market_value / cost_basis - 1,
    }


def _scenario_sensitivity(
    holding: HoldingContext,
    market_price: float | None,
    price_reason: str | None,
) -> dict[str, Any]:
    if price_reason is not None:
        return _unavailable(price_reason)
    assert market_price is not None
    return {
        "status": "available",
        "market_price": market_price,
        "value_change_per_price_unit": holding.quantity,
        "cost_gap_per_unit": market_price - holding.average_cost,
    }
