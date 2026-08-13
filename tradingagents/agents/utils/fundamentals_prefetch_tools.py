"""Graph prefetch node for frozen fundamentals evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tradingagents.research.analysis_cutoff import parse_analysis_cutoff
from tradingagents.research.fundamentals_prefetch import (
    build_fundamentals_cutoff_failure_bundle,
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
    include_optional: bool = True,
) -> str:
    cutoff = parse_analysis_cutoff(analysis_cutoff)
    if cutoff is None or cutoff.status != "resolved":
        return canonical_fundamentals_bundle(
            build_fundamentals_cutoff_failure_bundle(
                symbol,
                analysis_date,
                horizon=horizon,
                cutoff=cutoff,
                include_optional=include_optional,
            )
        )
    bundle = build_fundamentals_prefetch_bundle(
        symbol,
        analysis_date,
        horizon=horizon,
        cutoff=cutoff,
        include_optional=include_optional,
    )
    return canonical_fundamentals_bundle(bundle)


def create_fundamentals_prefetch_node(*, include_optional: bool = True):
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
                include_optional=include_optional,
            )
        }

    return prefetch
