"""Portfolio Manager structured-output schema and renderer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from tradingagents.portfolio import aggregate_risk_convictions

from ._common import ModelClaimInput, PortfolioRating, TraderAction, _coerce_optional_float
from ._risk import RiskDebateSignal


class PortfolioReaderFields(BaseModel):
    executive_summary: ModelClaimInput
    catalysts: list[ModelClaimInput] = Field(default_factory=list, max_length=3)
    invalidation_conditions: list[ModelClaimInput] = Field(default_factory=list, max_length=3)


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    price_target: float | None = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: str | None = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )
    execution_action: TraderAction | None = Field(
        default=None,
        description=(
            "When deterministic portfolio constraints are supplied, request one "
            "of Buy / Hold / Sell. It will be clamped after the model call."
        ),
    )
    requested_quantity: int | None = Field(
        default=None,
        ge=0,
        description=(
            "When deterministic portfolio constraints are supplied, request a "
            "non-negative whole-unit quantity. It will be clamped after the model call."
        ),
    )
    risk_signals: list[RiskDebateSignal] = Field(
        default_factory=list,
        description=(
            "Deprecated compatibility field. In the graph execution path the Portfolio "
            "Manager ignores this value and consumes only independently emitted risk "
            "signals from risk_debate_state; callers outside the graph may still render it."
        ),
    )
    top_drivers: list[DecisionDriver] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "At most five evidence-backed drivers. Importance must be a measured or "
            "explicitly supplied score, not a fabricated causal claim."
        ),
    )
    reader_fields: PortfolioReaderFields | None = Field(
        default=None,
        description="Optional reader summary, catalysts, and invalidation conditions with supplied evidence refs.",
    )

    @field_validator("price_target", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)


class DecisionDriver(BaseModel):
    """A citation-backed input driver; not an inferred causal attribution."""

    label: str = Field(min_length=1, max_length=160)
    importance: float = Field(ge=0.0, le=1.0)
    evidence_ref: str = Field(
        min_length=1,
        max_length=320,
        description="Source URI, artifact ID, or report section supporting this driver.",
    )
    evidence_ref_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=8,
        description="Optional validated reader evidence references; the legacy text citation is preserved above.",
    )
    direction: Literal["positive", "negative", "risk"]


def render_pm_decision(
    decision: PortfolioDecision,
    *,
    risk_signals: list[RiskDebateSignal] | None = None,
    execution_outcome: dict[str, object] | None = None,
) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    if execution_outcome is not None:
        requested_action = execution_outcome.get("requested_action")
        requested_quantity = execution_outcome.get("requested_quantity")
        if requested_action is not None:
            label = "Requested Execution"
            if execution_outcome.get("availability") != "executable":
                label += " (not executable)"
            parts.extend([
                "",
                f"**{label}**: {requested_action} {requested_quantity or 0}",
            ])
        parts.extend([
            "",
            "**Effective Execution**: "
            f"{execution_outcome.get('effective_action') or 'none'} "
            f"{execution_outcome.get('effective_quantity') or 0} "
            f"({execution_outcome.get('reason_code') or 'unknown'})",
        ])
    elif decision.execution_action is not None:
        quantity = decision.requested_quantity or 0
        parts.extend(["", f"**Requested Execution**: {decision.execution_action.value} {quantity}"])
    effective_risk_signals = decision.risk_signals if risk_signals is None else risk_signals
    if effective_risk_signals:
        aggregate = aggregate_risk_convictions(
            [signal.to_domain() for signal in effective_risk_signals]
        )
        conviction = "abstain" if aggregate.conviction is None else f"{aggregate.conviction:+.2f}"
        parts.extend([
            "",
            "**Risk Conviction Aggregate**: "
            f"{conviction}; disagreement={aggregate.disagreement}; "
            f"abstained={','.join(aggregate.abstained_roles) or 'none'}",
        ])
    if decision.top_drivers:
        parts.extend(["", "**Top Evidence-backed Drivers**:"])
        parts.extend(
            f"- {driver.direction}: {driver.label} "
            f"(importance={driver.importance:.2f}; evidence={driver.evidence_ref})"
            for driver in decision.top_drivers
        )
    return "\n".join(parts)

