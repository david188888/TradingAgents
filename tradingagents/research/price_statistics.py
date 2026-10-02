"""Code-owned descriptive statistics inside a qualifying price payload.

This payload is frozen and checkpointed with its source evidence, then read
by the market specialist. Saved results can be projected into research-record-v1;
this computation is not a valuation.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from tradingagents.dataflows.risk_metrics import (
    RiskMetricsUnavailableError,
    calculate_return_risk_metrics,
    calculate_wilder_atr,
)


def build_price_statistics(bars: list[dict[str, Any]], provenance: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input_sha256": provenance["input_sha256"], "source": provenance["source"],
        "price_basis": provenance["price_basis"], "adjustment_anchor": provenance["adjustment_anchor"],
        "return_method": "simple daily returns; no missing-session fill",
        "annualization_sessions": 252, "var_method": "signed daily q(0.05), linear interpolation",
        "es_method": "mean signed returns <= VaR threshold",
        "atr_method": "Wilder 14; seed first 14 true ranges with previous closes",
        "limitations": ["descriptive historical statistics; not future loss bounds or intrinsic value"],
        "benchmark_statistics": {"status": "unavailable", "reason": "qualified_benchmark_not_supplied"},
    }
    if not provenance.get("window_covered") or provenance.get("pit_status") != "verified":
        for key in ("return_statistics", "atr"):
            result[key] = {"status": "unavailable", "reason": "price_window_or_vintage_unqualified"}
        return result
    dates = pd.to_datetime([row["Date"] for row in bars])
    calendar = pd.to_datetime(provenance["expected_sessions"])
    close = pd.Series([row["Close"] for row in bars], index=dates)
    try:
        returns = calculate_return_risk_metrics(close, expected_sessions=calendar)
        result["return_statistics"] = {"status": "available", "units": "signed return fractions", **asdict(returns)}
        if returns.tail_observation_count < 5:
            result["limitations"].append("fewer_than_five_tail_observations")
    except RiskMetricsUnavailableError as exc:
        result["return_statistics"] = {"status": "unavailable", "reason": str(exc)}
    try:
        atr = calculate_wilder_atr(
            pd.Series([row["High"] for row in bars], index=dates),
            pd.Series([row["Low"] for row in bars], index=dates), close, expected_sessions=calendar,
        )
        result["atr"] = {"status": "available", "unit": provenance["price_unit"], **asdict(atr)}
    except (RiskMetricsUnavailableError, KeyError) as exc:
        result["atr"] = {"status": "unavailable", "reason": "ohlc_not_supplied" if isinstance(exc, KeyError) else str(exc)}
    return result
