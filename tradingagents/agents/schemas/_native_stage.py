"""Closed model proposals; facts, IDs, execution and publication remain code-owned."""

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.agents.schemas._evidence_checks import CheckId, ObservedRisk
from tradingagents.agents.schemas._research_assessment import (
    ChallengeAssessmentV1,
    DimensionAssessmentV1,
)
from tradingagents.agents.schemas._verification_plan import VerificationConditionV1

from ._research_dialogue import (
    ChallengeAdjudicationV1,
    InvestmentArgumentV1,
    JudgementConditionV1,
)


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HypothesisConditionProposalV1(_Proposal):
    condition_role: Literal["necessary", "invalidation"]
    text: str = Field(min_length=1, max_length=300)
    check: VerificationConditionV1 | None = None


class HypothesisProposalV1(_Proposal):
    statement: str = Field(min_length=1, max_length=400)
    supporting_fact_ids: tuple[str, ...] = Field(min_length=1, max_length=6)
    conditions: tuple[HypothesisConditionProposalV1, ...] = Field(min_length=1, max_length=4)
    alternative_explanation: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def falsifiable_and_unique(self):
        if not any(item.condition_role == "invalidation" for item in self.conditions):
            raise ValueError("native hypothesis requires an invalidation condition")
        if len(set(self.supporting_fact_ids)) != len(self.supporting_fact_ids):
            raise ValueError("duplicate hypothesis fact reference")
        if len({(item.condition_role, item.text) for item in self.conditions}) != len(self.conditions):
            raise ValueError("duplicate hypothesis condition")
        return self


class SpecialistProposalV1(_Proposal):
    hypotheses: tuple[HypothesisProposalV1, ...] = Field(default=(), max_length=3)
    unknowns: tuple[Annotated[str, Field(min_length=1, max_length=300)], ...] = Field(default=(), max_length=3)


class NativeEvidenceBindingError(ValueError):
    """A proposal's references violate the frozen evidence boundary."""

    def __init__(self, message: str, *, code: str = "condition_evidence_reference"):
        super().__init__(message)
        self.code = code


ReferenceCode = Literal[
    "specialist_fact_reference", "condition_evidence_reference", "condition_metric_reference",
    "numeric_literal_unbound", "numeric_anchor_unknown", "numeric_anchor_scope",
    "numeric_basis_mismatch", "numeric_plan_mismatch", "numeric_render_limit",
    "numeric_manifest_binding", "numeric_catalog_limit",
]


class HypothesisRejectionV1(_Proposal):
    index: int = Field(ge=0, le=2, strict=True)
    code: ReferenceCode


class SpecialistCandidateV1(_Proposal):
    """Internal checkpoint envelope; rejected model content is never retained."""

    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    proposal: SpecialistProposalV1
    indices: tuple[Annotated[int, Field(strict=True, ge=0, le=2)], ...] = Field(max_length=3)
    rejections: tuple[HypothesisRejectionV1, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def closed_indices(self):
        indices = (*self.indices, *(r.index for r in self.rejections))
        if (len(self.indices) != len(self.proposal.hypotheses)
                or any(type(i) is not int for i in self.indices)
                or list(self.indices) != sorted(self.indices)
                or sorted(indices) != list(range(len(indices))) or len(indices) > 3):
            raise ValueError("specialist candidate indices invalid")
        return self


def validate_hypothesis_references(hypothesis, facts, metric_evidence, *, conditions=True):
    """One owning scope for adapter admission and kernel publication."""
    if not set(hypothesis.supporting_fact_ids) <= facts.keys():
        raise NativeEvidenceBindingError("specialist reference outside supplied facts", code="specialist_fact_reference")
    evidence_ids = {eid for fid in hypothesis.supporting_fact_ids for eid in facts[fid]}
    if conditions:
        validate_condition_evidence(hypothesis, evidence_ids, metric_evidence)


def saved_specialist_acceptance(checkpoint, role, proposal):
    """Read exact accepted indices/reasons across adapter, kernel and Reader."""
    from tradingagents.research.native_versions import SPECIALIST_REFERENCE_POLICY

    policy = checkpoint.get("identity", {}).get("specialist_reference_policy")
    if policy is None:
        return None
    if policy != SPECIALIST_REFERENCE_POLICY:
        raise ValueError("specialist reference policy mismatch")
    results = checkpoint["results"]
    saved = results.get("native.specialist_accepted." + role)
    if saved is None:
        repaired = results.get("native." + role + ".repair")
        if repaired is not None and repaired.get("proposal") == proposal.model_dump(mode="json"):
            return None
        saved = results.get("native.specialist_candidate." + role)
        if saved is None:
            return None
    candidate = SpecialistCandidateV1.model_validate(saved)
    if (candidate.proposal != proposal
            or candidate.prompt_sha256 != checkpoint.get("native.prompt." + role)):
        raise ValueError("specialist acceptance binding invalid")
    return candidate


def validate_condition_evidence(
    hypothesis: HypothesisProposalV1,
    evidence_ids: Iterable[str],
    metric_evidence: Mapping[str, Iterable[str]],
) -> None:
    """Conditions may use only sources supporting their own hypothesis."""
    allowed = set(evidence_ids)
    for condition in hypothesis.conditions:
        check = condition.check
        if check is None:
            continue
        if check.kind == "financial":
            operands = (check.current,) if check.base is None else (check.current, check.base)
            if any(operand.evidence_id not in allowed for operand in operands):
                raise NativeEvidenceBindingError("condition references evidence outside its hypothesis")
        else:
            sources = metric_evidence.get(check.metric_id)
            if sources is None or not set(sources) <= allowed:
                raise NativeEvidenceBindingError("condition references a metric outside its hypothesis", code="condition_metric_reference")


class ChallengeProposalV1(_Proposal):
    hypothesis_id: str = Field(min_length=1, max_length=512)
    statement: str = Field(min_length=1, max_length=400)
    severity: Literal["minor", "material", "critical"]
    risk_type: Literal["evidence_quality", "operations", "governance", "market", "valuation", "unclassified"]
    proposed_test: str = Field(min_length=1, max_length=300)
    condition_id: str | None = None


class ChallengesProposalV1(_Proposal):
    challenges: tuple[ChallengeProposalV1, ...] = Field(default=(), max_length=3)


class SynthesisProposalV1(_Proposal):
    judgement: str = Field(min_length=1, max_length=240)
    dimensions: tuple[DimensionAssessmentV1, ...] = Field(min_length=1, max_length=4)
    key_claim_ids: tuple[str, ...] = Field(default=(), max_length=3)
    primary_challenge_id: str | None = None
    next_check: str = Field(min_length=1, max_length=240)
    challenge_assessments: tuple[ChallengeAssessmentV1, ...] = ()


class ChallengeProposalV2(ChallengeProposalV1):
    check_id: CheckId | None = None
    observed_risk: ObservedRisk | None = None
    observation_date: date | None = None

    @model_validator(mode="after")
    def risk_scope(self):
        if self.observed_risk and self.check_id not in {None, "cash_conversion"}:
            raise ValueError("CFO risk cannot answer another check's question")
        return self


class ChallengesProposalV2(_Proposal):
    challenges: tuple[ChallengeProposalV2, ...] = Field(default=(), max_length=3)


class SynthesisProposalV2(SynthesisProposalV1):
    # Narrative rationales remain proposals. The host generates v2 outcomes.
    pass





class SynthesisProposalV3(SynthesisProposalV2):
    investment_stance: Literal["favorable", "neutral", "unfavorable", "insufficient_evidence"]
    supporting_arguments: tuple[InvestmentArgumentV1, ...] = Field(default=(), max_length=3)
    opposing_arguments: tuple[InvestmentArgumentV1, ...] = Field(default=(), max_length=3)
    change_conditions: tuple[JudgementConditionV1, ...] = Field(default=(), max_length=3)
    adjudications: tuple[ChallengeAdjudicationV1, ...] = Field(default=(), max_length=3)
