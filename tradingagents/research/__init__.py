"""Deterministic research-domain primitives.

The package deliberately has no LangGraph, LLM, or data-provider dependency so
that a strategy conclusion can be inspected and replayed independently from
the model that described the underlying evidence.
"""

from .convergence import (
    ConfluenceLevel,
    ConvergenceAssessment,
    CrowdDivergenceWarning,
    ThesisConfluence,
    WarningSeverity,
    assess_convergence,
    render_convergence_assessment,
)
from .dossier import ResearchDossier, build_research_dossier, render_research_dossier
from .holding_review import build_holding_review_summary, holding_review_quote_from_bundle
from .logic_loop import evaluate_logic_edge
from .metric_catalog import METRIC_CATALOG, all_metric_definitions, metric_definition
from .metric_engine import calculate_metric, calculate_roe, calculate_yoy
from .metric_models import (
    FormulaEvaluationV1,
    LogicEdgeV1,
    MetricComparisonV1,
    MetricDefinitionV1,
    MetricObservationV1,
    PeerSetV1,
)
from .metric_provider_adapter import observations_from_fundamentals_bundle
from .peer_set import PeerCandidateV1, build_peer_set, compare_metric
from .price_coverage import (
    AdjustedPriceCapability,
    adjusted_price_capability_dict,
    assess_adjusted_price_capability,
    bundle_for_analyst,
)
from .public_hash import canonical_json_bytes, package_sha256
from .research_package import ResearchEvidenceRefV1, ResearchPackageV1, research_package_from_case
from .strategy import (
    StrategyConsensus,
    StrategySignal,
    aggregate_strategy_signals,
)

__all__ = [
    "canonical_json_bytes",
    "package_sha256",
    "ResearchDossier",
    "build_research_dossier",
    "render_research_dossier",
    "ResearchEvidenceRefV1",
    "ResearchPackageV1",
    "research_package_from_case",
    "MetricDefinitionV1",
    "MetricObservationV1",
    "MetricComparisonV1",
    "FormulaEvaluationV1",
    "LogicEdgeV1",
    "PeerSetV1",
    "PeerCandidateV1",
    "METRIC_CATALOG",
    "metric_definition",
    "all_metric_definitions",
    "calculate_metric",
    "calculate_yoy",
    "calculate_roe",
    "build_peer_set",
    "compare_metric",
    "observations_from_fundamentals_bundle",
    "evaluate_logic_edge",
    "build_holding_review_summary",
    "holding_review_quote_from_bundle",
    "AdjustedPriceCapability",
    "assess_adjusted_price_capability",
    "adjusted_price_capability_dict",
    "bundle_for_analyst",
    "StrategyConsensus",
    "StrategySignal",
    "aggregate_strategy_signals",
    "ConfluenceLevel",
    "ConvergenceAssessment",
    "CrowdDivergenceWarning",
    "ThesisConfluence",
    "WarningSeverity",
    "assess_convergence",
    "render_convergence_assessment",
]
