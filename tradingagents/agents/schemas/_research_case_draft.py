"""LLM-facing draft models for the evidence-bound learning research case.

These models are the structured output contract for the learning-mode Research
Manager.  Unlike the closed public ``ResearchCaseV2``, a draft references
evidence and coverage by short, stable keys (see
``tradingagents.research.claim_registry``) that a later assembler resolves into
real ``EvidenceRefV2`` / ``CoverageRefV1`` objects and computes ``source_dates``.

A draft deliberately has no ``source_dates`` and no resolved ref ids: those are
assembler concerns.  The draft's shape rules mirror ``PublicClaim`` /
``ResearchScenario`` / ``ReviewItem`` where that shape does not depend on
resolved evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.agents.schemas._learning_research import HoldingThesisAssessment
from tradingagents.research.claim_registry import validate_claim_key

ClaimType = Literal["fact", "inference", "unknown"]
ResearchTilt = Literal["favorable", "neutral", "cautious", "insufficient_evidence"]
ActionImpact = Literal["supports", "opposes", "limits", "neutral"]
LifecycleStatus = Literal["active", "resolved", "invalidated"]
ScenarioId = Literal["upside", "base", "downside"]
TriggerKind = Literal["date", "event", "price", "filing"]


class _DraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ClaimDraft(_DraftModel):
    claim_key: str
    claim_type: ClaimType
    text: str = Field(min_length=1, max_length=1200)
    evidence_keys: tuple[str, ...] = ()
    supporting_claim_keys: tuple[str, ...] = ()
    coverage_keys: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)
    action_impact: ActionImpact
    lifecycle_status: LifecycleStatus = "active"
    required_evidence: tuple[str, ...] = ()
    review_trigger: str | None = Field(default=None, max_length=500)

    @field_validator("claim_key")
    @classmethod
    def _registered_claim_key(cls, value: str) -> str:
        validate_claim_key(value)
        return value

    @model_validator(mode="after")
    def _claim_shape(self) -> ClaimDraft:
        if len(set(self.evidence_keys)) != len(self.evidence_keys):
            raise ValueError("claim evidence keys must be unique")
        if len(set(self.coverage_keys)) != len(self.coverage_keys):
            raise ValueError("claim coverage keys must be unique")
        if len(set(self.supporting_claim_keys)) != len(self.supporting_claim_keys):
            raise ValueError("supporting claim keys must be unique")
        if self.claim_type == "unknown":
            if self.evidence_keys or self.supporting_claim_keys:
                raise ValueError("unknown claims cannot include evidence or supporting claims")
            if self.confidence is not None:
                raise ValueError("unknown claims must not include confidence")
            if not self.required_evidence or self.review_trigger is None:
                raise ValueError("unknown claims require evidence needed and a review trigger")
            if self.lifecycle_status != "active":
                raise ValueError("unknown claims must be active")
        else:
            if self.confidence is None:
                raise ValueError("fact and inference claims require confidence")
            if not self.evidence_keys:
                raise ValueError("fact and inference claims require evidence keys")
        if self.claim_type == "fact" and self.supporting_claim_keys:
            raise ValueError("facts cannot depend on other claims")
        if self.claim_type == "inference" and not self.supporting_claim_keys:
            raise ValueError("inferences require supporting fact claims")
        return self


class ScenarioDraft(_DraftModel):
    scenario_id: ScenarioId
    title: str = Field(min_length=1, max_length=160)
    research_implication: str = Field(min_length=1, max_length=1200)
    condition_claim_keys: tuple[str, ...] = Field(min_length=1)
    trigger_claim_keys: tuple[str, ...] = ()
    invalidation_claim_keys: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class ReviewItemDraft(_DraftModel):
    item_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str = Field(min_length=1, max_length=600)
    claim_keys: tuple[str, ...] = Field(min_length=1)
    trigger_kind: TriggerKind
    trigger_value: str = Field(min_length=1, max_length=200)
    evidence_keys: tuple[str, ...] = ()


class LearningResearchCaseDraft(_DraftModel):
    research_tilt: ResearchTilt
    confidence: float = Field(ge=0, le=1)
    facts: tuple[ClaimDraft, ...] = Field(default=(), max_length=5)
    inferences: tuple[ClaimDraft, ...] = Field(default=(), max_length=4)
    unknowns: tuple[ClaimDraft, ...] = Field(default=(), max_length=4)
    upside: ScenarioDraft
    base: ScenarioDraft
    downside: ScenarioDraft
    catalysts: tuple[ReviewItemDraft, ...] = Field(default=(), max_length=4)
    invalidation_conditions: tuple[ReviewItemDraft, ...] = Field(default=(), max_length=4)
    next_review: str = Field(min_length=1, max_length=500)
    holding_thesis_assessment: HoldingThesisAssessment | None = None

    @model_validator(mode="after")
    def _validate_draft_graph(self) -> LearningResearchCaseDraft:
        all_claims = self.facts + self.inferences + self.unknowns
        claim_keys = [claim.claim_key for claim in all_claims]
        if len(set(claim_keys)) != len(claim_keys):
            raise ValueError("claim keys must be unique within the draft")
        claim_index = set(claim_keys)

        for scenario in (self.upside, self.base, self.downside):
            referenced = (
                scenario.condition_claim_keys
                + scenario.trigger_claim_keys
                + scenario.invalidation_claim_keys
            )
            if not set(referenced).issubset(claim_index):
                raise ValueError("scenario references an unknown claim key")
        if not (self.upside.trigger_claim_keys or self.upside.invalidation_claim_keys):
            raise ValueError("upside scenario requires a trigger or invalidation")
        if not (self.downside.trigger_claim_keys or self.downside.invalidation_claim_keys):
            raise ValueError("downside scenario requires a trigger or invalidation")

        review_items = self.catalysts + self.invalidation_conditions
        if len({item.item_id for item in review_items}) != len(review_items):
            raise ValueError("review item IDs must be unique")
        for item in review_items:
            if not set(item.claim_keys).issubset(claim_index):
                raise ValueError("review item references an unknown claim key")
        return self

    def to_learning_summary_dict(self) -> dict:
        """Project the draft onto the legacy ``LearningResearchSummary`` shape.

        The projection is intentionally lossy: only the claim/summary text
        surfaces, exactly as the existing public reader expects, so the
        ``reader_public_output`` shape stays unchanged.
        """
        claim_by_key = {claim.claim_key: claim for claim in self.facts + self.inferences + self.unknowns}

        def scenario_dict(scenario: ScenarioDraft) -> dict:
            condition = "；".join(
                claim_by_key[key].text for key in scenario.condition_claim_keys
            )
            return {
                "title": scenario.title,
                # Bridge only: the real Reader uses claim references directly.
                "condition": condition[:500],
                "implication": scenario.research_implication[:600],
            }

        result: dict = {
            "research_tilt": self.research_tilt,
            "confidence": self.confidence,
            "facts": tuple(claim.text for claim in self.facts),
            "inferences": tuple(claim.text for claim in self.inferences),
            "unknowns": tuple(claim.text for claim in self.unknowns),
            "upside": scenario_dict(self.upside),
            "base": scenario_dict(self.base),
            "downside": scenario_dict(self.downside),
            "catalysts": tuple(item.text for item in self.catalysts),
            "invalidation_conditions": tuple(item.text for item in self.invalidation_conditions),
            "next_review": self.next_review,
        }
        if self.holding_thesis_assessment is not None:
            result["holding_thesis_assessment"] = self.holding_thesis_assessment.model_dump(mode="json")
        return result


def render_learning_case_draft(draft: LearningResearchCaseDraft) -> str:
    """Render the draft as a readable research report, never a trade plan.

    The section structure matches ``render_learning_research_summary`` so the
    markdown handed to downstream nodes and saved reports stays stable.
    """
    claim_by_key = {claim.claim_key: claim for claim in draft.facts + draft.inferences + draft.unknowns}
    lines = [
        "## 研究倾向",
        "",
        f"- 倾向：{draft.research_tilt}",
        f"- 置信度：{draft.confidence:.0%}",
        "- 本报告用于学习与复盘，不构成交易指令；不包含仓位、数量、订单或执行时间。",
        "",
        "## 事实",
        *(_bullets(tuple(claim.text for claim in draft.facts)) or ["- 当前没有足够的可验证事实。"]),
        "",
        "## 推论",
        *(_bullets(tuple(claim.text for claim in draft.inferences)) or ["- 当前不作额外推论。"]),
        "",
        "## 未知与待验证",
        *(_bullets(tuple(claim.text for claim in draft.unknowns)) or ["- 没有额外未知项被记录。"]),
        "",
        "## 三种情景",
        *_scenario_lines("上行", draft.upside, claim_by_key),
        *_scenario_lines("基准", draft.base, claim_by_key),
        *_scenario_lines("下行", draft.downside, claim_by_key),
        "",
        "## 催化剂与失效条件",
        "### 催化剂",
        *(_bullets(tuple(item.text for item in draft.catalysts)) or ["- 暂无已验证催化剂。"]),
        "### 失效条件",
        *(_bullets(tuple(item.text for item in draft.invalidation_conditions)) or ["- 暂无额外失效条件。"]),
        "",
        "## 下次复核",
        draft.next_review,
    ]
    if draft.holding_thesis_assessment is not None:
        assessment = draft.holding_thesis_assessment
        lines += [
            "",
            "## 持仓理由复核",
            f"- 当前证据评估：{assessment.status}",
            f"- 依据：{assessment.rationale}",
            f"- 当前可观察研究假设：{assessment.current_research_hypothesis}",
        ]
    return "\n".join(lines)


def _bullets(items: tuple[str, ...]) -> list[str]:
    return [f"- {item}" for item in items]


def _scenario_lines(
    label: str,
    scenario: ScenarioDraft,
    claim_by_key: dict[str, ClaimDraft],
) -> list[str]:
    condition = "；".join(claim_by_key[key].text for key in scenario.condition_claim_keys)
    return [
        f"### {label}：{scenario.title}",
        f"- 条件：{condition}",
        f"- 研究含义：{scenario.research_implication}",
    ]
