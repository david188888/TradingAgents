"""Consumer-neutral inputs and successful outputs for shared graph execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from threading import Event
from typing import Any, Literal

from tradingagents.analysts import ANALYST_WIRE_KEYS
from tradingagents.portfolio import FeatureContributionArtifact, PortfolioContext

ResearchMode = Literal["company_research", "holding_review"]
HoldingSource = Literal["user_provided", "legacy_portfolio"]


@dataclass(frozen=True)
class HoldingContext:
    """Normalized, non-secret facts for a learning-oriented holding review.

    This intentionally is not a portfolio or execution context.  It captures
    only the target holding facts a reader may discuss and never contains
    tradable quantities, limits, or inferred account facts.
    """

    ticker: str
    quantity: float
    average_cost: float
    cash: float | None
    total_account_value: float | None
    currency: str | None
    facts_as_of: str
    original_thesis: str | None
    source: HoldingSource

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("holding ticker is required")
        if not isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("holding quantity must be positive")
        if not isfinite(self.average_cost) or self.average_cost <= 0:
            raise ValueError("holding average_cost must be positive")
        if self.cash is not None and (not isfinite(self.cash) or self.cash < 0):
            raise ValueError("holding cash must be non-negative")
        if self.total_account_value is not None and (
            not isfinite(self.total_account_value) or self.total_account_value <= 0
        ):
            raise ValueError("holding total_account_value must be positive")
        if self.currency is not None and (
            len(self.currency) != 3 or not self.currency.isalpha()
        ):
            raise ValueError("holding currency must be a three-letter code")
        try:
            date.fromisoformat(self.facts_as_of)
        except ValueError as exc:
            raise ValueError("holding facts_as_of must use YYYY-MM-DD") from exc
        if self.source not in {"user_provided", "legacy_portfolio"}:
            raise ValueError("unsupported holding source")


def holding_context_from_dict(value: Mapping[str, Any]) -> HoldingContext:
    """Rehydrate the explicit snapshot contract without accepting omissions."""
    return HoldingContext(
        ticker=str(value["ticker"]),
        quantity=float(value["quantity"]),
        average_cost=float(value["average_cost"]),
        cash=float(value["cash"]) if value.get("cash") is not None else None,
        total_account_value=(
            float(value["total_account_value"])
            if value.get("total_account_value") is not None
            else None
        ),
        currency=str(value["currency"]) if value.get("currency") is not None else None,
        facts_as_of=str(value["facts_as_of"]),
        original_thesis=(
            str(value["original_thesis"])
            if value.get("original_thesis") is not None
            else None
        ),
        source=str(value["source"]),
    )


@dataclass(frozen=True)
class AnalysisRequest:
    ticker: str
    analysis_date: str
    asset_type: Literal["stock", "crypto"] = "stock"
    selected_analysts: tuple[str, ...] = ANALYST_WIRE_KEYS
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1
    portfolio: PortfolioContext | None = None
    feature_contribution_artifact: FeatureContributionArtifact | None = None
    effective_config: Mapping[str, Any] = field(default_factory=dict)
    horizon: Literal["short", "medium", "long"] = "medium"
    mode: ResearchMode = "company_research"
    holding_context: HoldingContext | None = None

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("ticker is required")
        try:
            date.fromisoformat(self.analysis_date)
        except ValueError as exc:
            raise ValueError("analysis_date must use YYYY-MM-DD") from exc
        if not self.selected_analysts:
            raise ValueError("at least one analyst is required")
        unknown = set(self.selected_analysts) - set(ANALYST_WIRE_KEYS)
        if unknown:
            raise ValueError(f"unknown analyst keys: {', '.join(sorted(unknown))}")
        if len(set(self.selected_analysts)) != len(self.selected_analysts):
            raise ValueError("selected_analysts must not contain duplicates")
        if self.max_debate_rounds < 1 or self.max_risk_discuss_rounds < 1:
            raise ValueError("debate and risk rounds must be positive")
        if self.horizon not in {"short", "medium", "long"}:
            raise ValueError(f"unsupported investment horizon: {self.horizon}")
        if self.mode not in {"company_research", "holding_review"}:
            raise ValueError(f"unsupported research mode: {self.mode}")
        if self.mode == "company_research" and self.holding_context is not None:
            raise ValueError("company_research cannot include holding_context")
        if self.mode == "holding_review" and self.holding_context is None:
            raise ValueError("holding_review requires holding_context")


@dataclass(frozen=True)
class AnalysisResult:
    final_state: Mapping[str, Any]
    final_signal: str

    def __post_init__(self) -> None:
        if not self.final_signal.strip():
            raise ValueError("successful AnalysisResult requires final_signal")


class AnalysisCancelled(Exception):
    def __init__(self, partial_state: Mapping[str, Any] | None = None):
        self.partial_state = partial_state
        super().__init__("analysis cancelled")


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(
        self,
        partial_state: Mapping[str, Any] | None = None,
    ) -> None:
        if self.is_cancelled:
            raise AnalysisCancelled(partial_state)
