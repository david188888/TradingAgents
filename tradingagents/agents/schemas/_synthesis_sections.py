"""Section delivery and numeric fragments, without invented model analysis."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._research_dialogue import ChallengeAdjudicationV1, InvestmentArgumentV1, JudgementConditionV1

SYNTHESIS_SECTIONS_POLICY = "synthesis-sections-v1"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SynthesisSectionV1(_Frozen):
    section_id: str = Field(min_length=1, max_length=160)
    status: Literal["accepted", "unavailable"]
    phase: Literal["main", "repair"] | None = None
    reason_code: Literal["missing_section", "schema_validation", "reference_validation",
        "numeric_literal_unbound", "numeric_anchor_unknown", "numeric_anchor_scope",
        "numeric_basis_mismatch", "numeric_plan_mismatch", "numeric_render_limit",
        "premise_binding_invalid", "premise_binding_missing", "premise_observation_unknown",
        "premise_observation_scope", "premise_support_missing", "numeric_manifest_binding", "numeric_catalog_limit"] | None = None

    @model_validator(mode="after")
    def delivery_state(self):
        if (self.status == "accepted") != (self.phase is not None and self.reason_code is None):
            raise ValueError("invalid synthesis section delivery")
        if self.status == "unavailable" and (self.phase is not None or self.reason_code is None):
            raise ValueError("unavailable synthesis section requires closed reason")
        return self


class SynthesisSectionsV1(_Frozen):
    policy: Literal["synthesis-sections-v1"] = SYNTHESIS_SECTIONS_POLICY
    sections: tuple[SynthesisSectionV1, ...] = Field(min_length=6, max_length=9)

    @model_validator(mode="after")
    def unique_sections(self):
        if len({s.section_id for s in self.sections}) != len(self.sections):
            raise ValueError("duplicate synthesis section")
        return self


class SynthesisOverallV1(_Frozen):
    judgement: str = Field(min_length=1, max_length=240)
    investment_stance: Literal["favorable", "neutral", "unfavorable", "insufficient_evidence"]
    key_claim_ids: tuple[str, ...] = Field(default=(), max_length=3)
    primary_challenge_id: str | None = None
    next_check: str = Field(min_length=1, max_length=240)
    supporting_arguments: tuple[InvestmentArgumentV1, ...] = Field(default=(), max_length=3)
    opposing_arguments: tuple[InvestmentArgumentV1, ...] = Field(default=(), max_length=3)


class SynthesisConditionsV1(_Frozen):
    change_conditions: tuple[JudgementConditionV1, ...] = Field(max_length=3)


class SynthesisAdjudicationV1(_Frozen):
    adjudications: tuple[ChallengeAdjudicationV1, ...] = Field(min_length=1, max_length=1)


class SynthesisSectionReceiptV1(_Frozen):
    section_id: str = Field(min_length=1, max_length=160)
    phase: Literal["main", "repair"]
    proposal: dict
    proof: dict


class SectionedSynthesisProofV1(_Frozen):
    kind: Literal["synthesis-sections-v1"] = SYNTHESIS_SECTIONS_POLICY
    stage: Literal["synthesis"] = "synthesis"
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    receipts: tuple[SynthesisSectionReceiptV1, ...] = Field(max_length=9)
    delivery: SynthesisSectionsV1
    fields: tuple[dict, ...]
