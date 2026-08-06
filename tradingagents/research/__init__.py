"""Deterministic research-domain primitives.

The package deliberately has no LangGraph, LLM, or data-provider dependency so
that a strategy conclusion can be inspected and replayed independently from
the model that described the underlying evidence.
"""

from .dossier import ResearchDossier, build_research_dossier, render_research_dossier
from .strategy import (
    StrategyConsensus,
    StrategySignal,
    aggregate_strategy_signals,
)

__all__ = [
    "ResearchDossier",
    "build_research_dossier",
    "render_research_dossier",
    "StrategyConsensus",
    "StrategySignal",
    "aggregate_strategy_signals",
]
