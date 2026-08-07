"""Research Manager structured-output schemas and renderers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from tradingagents.research import StrategySignal, aggregate_strategy_signals
from tradingagents.research.delegation import (
    ResearchDelegationRequest,
    ResearchDelegationResult,
    render_delegation_results,
)

from ._common import ModelClaimInput, PortfolioRating


class ResearchDelegationTask(BaseModel):
    """A bounded, public subquestion the manager may delegate once.

    The executor, rather than the model, decides which named tools actually
    exist.  This schema deliberately has no prompt, trace, or hidden-reasoning
    field, so saved plans cannot become a private chain-of-thought store.
    """

    request_id: str = Field(min_length=1, max_length=80)
    subquestion: str = Field(min_length=1, max_length=600)
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, object] = Field(default_factory=dict)

    def to_domain(self) -> ResearchDelegationRequest:
        return ResearchDelegationRequest(
            request_id=self.request_id,
            subquestion=self.subquestion,
            tool_name=self.tool_name,
            arguments=self.arguments,
        )


class ResearchPublicDigest(BaseModel):
    agreed_facts: list[ModelClaimInput] = Field(default_factory=list, max_length=5)
    key_disagreements: list[ModelClaimInput] = Field(default_factory=list, max_length=5)
    changed_views: list[ModelClaimInput] = Field(default_factory=list, max_length=5)
    remaining_uncertainties: list[ModelClaimInput] = Field(default_factory=list, max_length=5)


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )
    strategy_signals: list[ResearchStrategySignal] = Field(
        default_factory=list,
        description=(
            "One independent signal for each applicable lens among market, "
            "fundamentals, news, and sentiment. conviction is in [-1, +1]; "
            "set abstain=true when that lens lacks sufficient evidence. Do not "
            "use zero to mean no opinion."
        ),
    )
    delegation_tasks: list[ResearchDelegationTask] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "At most three independent, read-only evidence lookups. Each uses only a "
            "tool name supplied in the prompt. Do not ask a delegated task to delegate. "
            "Write only the concrete subquestion and JSON-safe lookup arguments; do not "
            "include hidden reasoning, prompts, or tool traces."
        ),
    )
    public_digest: ResearchPublicDigest | None = Field(
        default=None,
        description="Optional public reader digest with evidence-ref IDs supplied by the system prompt.",
    )


class ResearchStrategySignal(BaseModel):
    """A model-described input to the deterministic StrategyEngine."""

    strategy_id: Literal["market", "fundamentals", "news", "sentiment"]
    conviction: float | None = Field(default=None, ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    abstain: bool = False
    rationale: str = Field(
        default="",
        description="A short public evidence summary; never private model reasoning.",
    )
    key_findings: list[ModelClaimInput] | None = Field(
        default=None,
        max_length=3,
        description="Optional reader findings with only supplied evidence-ref IDs.",
    )

    @model_validator(mode="after")
    def _require_explicit_abstain_semantics(self):
        if self.abstain and self.conviction is not None:
            raise ValueError("an abstaining strategy must not supply conviction")
        if not self.abstain and self.conviction is None:
            raise ValueError("a non-abstaining strategy must supply conviction")
        return self

    def to_domain(self) -> StrategySignal:
        return StrategySignal(
            strategy_id=self.strategy_id,
            conviction=None if self.abstain else self.conviction,
            confidence=self.confidence,
            rationale=self.rationale,
        )


def render_research_plan(
    plan: ResearchPlan,
    delegated_results: tuple[ResearchDelegationResult, ...] = (),
) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    parts = [
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ]
    if plan.strategy_signals:
        consensus = aggregate_strategy_signals(
            [signal.to_domain() for signal in plan.strategy_signals]
        )
        conviction = "abstain" if consensus.conviction is None else f"{consensus.conviction:+.2f}"
        parts.extend([
            "",
            "**Strategy Consensus**: "
            f"{consensus.consensus_level}; conviction {conviction}; "
            f"{consensus.disagreement}; conflicts={consensus.conflict_count}",
        ])
    delegated = render_delegation_results(delegated_results)
    if delegated:
        parts.extend(["", delegated])
    return "\n".join(parts)

