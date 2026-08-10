"""Deterministic research-domain primitives.

The package deliberately has no LangGraph, LLM, or data-provider dependency so
that a strategy conclusion can be inspected and replayed independently from
the model that described the underlying evidence.
"""

from .dossier import ResearchDossier, build_research_dossier, render_research_dossier
from .holding_review import build_holding_review_summary, holding_review_quote_from_bundle
from .price_coverage import (
    AdjustedPriceCapability,
    adjusted_price_capability_dict,
    assess_adjusted_price_capability,
    bundle_for_analyst,
)
from .strategy import (
    StrategyConsensus,
    StrategySignal,
    aggregate_strategy_signals,
)

__all__ = [
    "ResearchDossier",
    "build_research_dossier",
    "render_research_dossier",
    "build_holding_review_summary",
    "holding_review_quote_from_bundle",
    "AdjustedPriceCapability",
    "assess_adjusted_price_capability",
    "adjusted_price_capability_dict",
    "bundle_for_analyst",
    "StrategyConsensus",
    "StrategySignal",
    "aggregate_strategy_signals",
]
