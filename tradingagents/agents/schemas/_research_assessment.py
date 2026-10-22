"""Evidence-bound native synthesis, independent of transport/profile selection."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from ._evidence_checks import ChallengeAssessmentV2
from ._research_dialogue import (
    ChallengeAdjudicationV1,
    InvestmentArgumentV1,
    JudgementConditionV1,
)
from ._synthesis_sections import SynthesisSectionsV1

DIMENSIONS_BY_MODE = {
    "company_research": ("operating_quality", "valuation", "market_context"),
    "catalyst_research": ("operating_quality", "catalyst_delivery", "market_context"),
    "holding_review": ("holding_thesis", "operating_quality", "valuation", "market_context"),
}
Dimension = Literal["operating_quality", "valuation", "market_context", "catalyst_delivery", "holding_thesis"]


class _AssessmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DimensionAssessmentV1(_AssessmentModel):
    dimension: Dimension
    status: Literal["supported", "conditional", "unresolved"]
    judgement: str = Field(min_length=1, max_length=400)
    claim_ids: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class SynthesisDimensionV1(_AssessmentModel):
    dimensions: tuple[DimensionAssessmentV1, ...] = Field(min_length=1, max_length=1)


class ChallengeAssessmentV1(_AssessmentModel):
    challenge_id: str = Field(min_length=1, max_length=512)
    # C1 only checks predicates. Native C2 cannot close an economic challenge.
    outcome: Literal["unresolved"] = "unresolved"
    rationale: str = Field(min_length=1, max_length=400)


class ResearchAssessmentV1(_AssessmentModel):
    schema_version: Literal["research-assessment-v1"] = "research-assessment-v1"
    input_snapshot_id: str = Field(min_length=1, max_length=160)
    research_question: str = Field(min_length=1, max_length=400)
    judgement: str = Field(min_length=1, max_length=240)
    dimensions: tuple[DimensionAssessmentV1, ...] = Field(min_length=1, max_length=4)
    key_claim_ids: tuple[str, ...] = Field(default=(), max_length=3)
    primary_challenge_id: str | None = None
    next_check: str = Field(min_length=1, max_length=240)
    challenge_assessments: tuple[ChallengeAssessmentV1, ...] = ()
    completeness: Literal["complete", "partial"]
    quality: Literal["PASS", "LOW_CONFIDENCE"]
    forward_window_calendar_days: Literal[84] | None = None
    limitations: tuple[str, ...] = ()


class ResearchAssessmentV2(ResearchAssessmentV1):
    schema_version: Literal["research-assessment-v2"] = "research-assessment-v2"
    challenge_assessments: tuple[ChallengeAssessmentV2, ...] = ()


class ResearchAssessmentV3(ResearchAssessmentV2):
    schema_version: Literal["research-assessment-v3"] = "research-assessment-v3"
    investment_stance: Literal["favorable", "neutral", "unfavorable", "insufficient_evidence"] | None
    report_status: Literal["synthesized", "analysis_unrated", "specialist_summary", "basic_report"] | None = None
    supporting_arguments: tuple["InvestmentArgumentV1", ...] = Field(default=(), max_length=3)
    opposing_arguments: tuple["InvestmentArgumentV1", ...] = Field(default=(), max_length=3)
    change_conditions: tuple["JudgementConditionV1", ...] = Field(default=(), max_length=3)
    adjudications: tuple["ChallengeAdjudicationV1", ...] = Field(default=(), max_length=3)
    synthesis_sections: SynthesisSectionsV1 | None = None

    @model_serializer(mode="wrap")
    def compatible_delivery_status(self, handler):
        value = handler(self)
        if self.report_status is None:
            value.pop("report_status", None)
        if self.synthesis_sections is None:
            value.pop("synthesis_sections", None)
        return value




ResearchAssessmentV3.model_rebuild()
