"""Graph prefetch node for frozen fundamentals evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tradingagents.research.analysis_cutoff import parse_analysis_cutoff
from tradingagents.research.fundamentals_prefetch import (
    build_fundamentals_prefetch_bundle,
    canonical_fundamentals_bundle,
)
from tradingagents.research.horizon_policy import InvestmentHorizon


def run_fundamentals_prefetch(
    symbol: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    analysis_cutoff: Mapping[str, Any] | None,
) -> str:
    cutoff = parse_analysis_cutoff(analysis_cutoff)
    if cutoff is None or cutoff.status != "resolved":
        return canonical_fundamentals_bundle(
            {
                "schema_version": 1,
                "ticker": symbol,
                "horizon": horizon,
                "as_of": analysis_date,
                "status": "invalid",
                "reason_code": "analysis_cutoff_resolution_failed",
                "analysis_cutoff": dict(analysis_cutoff or {}),
                "results": [],
            }
        )
    bundle = build_fundamentals_prefetch_bundle(
        symbol,
        analysis_date,
        horizon=horizon,
        cutoff=cutoff,
    )
    return canonical_fundamentals_bundle(bundle)


def create_fundamentals_prefetch_node():
    def prefetch(state: Mapping[str, Any]) -> dict[str, str]:
        raw_horizon = state.get("horizon")
        horizon: InvestmentHorizon = (
            raw_horizon if raw_horizon in {"short", "medium", "long"} else "medium"
        )
        return {
            "fundamentals_prefetch_bundle": run_fundamentals_prefetch(
                str(state["company_of_interest"]),
                str(state["trade_date"]),
                horizon=horizon,
                analysis_cutoff=state.get("analysis_cutoff"),
            )
        }

    return prefetch
