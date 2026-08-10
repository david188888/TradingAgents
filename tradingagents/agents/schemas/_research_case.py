"""Closed public contracts for the version-two learning research case.

The models in this module intentionally describe only public evidence and
research conclusions.  They are not prompts, tool traces, portfolio inputs,
or execution instructions.  Assembly and durable publication are separate
steps so a malformed public case cannot change the outcome of an analysis run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.dataflows.coverage import BundleCoverageV1

CLAIM_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){3}$"
OMISSION_CODE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"

ClaimType = Literal["fact", "inference", "unknown"]
ClaimLifecycle = Literal["active", "resolved", "invalidated"]
ResearchTilt = Literal["favorable", "neutral", "cautious", "insufficient_evidence"]
ActionImpact = Literal["supports", "opposes", "limits", "neutral"]
DecisionEligibility = Literal["full", "limited", "none"]
EvidenceVerdict = Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"]

_CLAIM_LENSES = frozenset({"market", "fundamentals", "news", "sentiment"})
_CLAIM_TOPICS = frozenset(
    {
        "market_trend",
        "market_volatility",
        "growth_quality",
        "cash_conversion",
        "balance_sheet",
        "valuation",
        "company_event",
        "industry_transmission",
        "sentiment_fast",
        "sentiment_slow",
        "governance_risk",
    }
)
_CLAIM_PREDICATES = frozenset(
    {
        "accelerating",
        "decelerating",
        "expanding",
        "contracting",
        "improving",
        "deteriorating",
        "supportive",
        "adverse",
        "stable",
        "elevated",
        "resolved",
        "invalidated",
        "uncertain",
    }
)


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EvidenceRefV2(_PublicModel):
    ref_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=128)
    locator: str = Field(min_length=1, max_length=2048)
    source_observed_at: datetime | None = None
    captured_at: datetime
    resolution_status: Literal["available", "unavailable"]


class CoverageRefV1(_PublicModel):
    coverage_ref_id: str = Field(min_length=1, max_length=160)
    capability: str = Field(min_length=1, max_length=120)
    envelope: BundleCoverageV1

    @model_validator(mode="after")
    def _match_capability(self) -> CoverageRefV1:
        if self.envelope.capability != self.capability:
            raise ValueError("coverage ref capability must match its envelope")
        return self


class PublicClaim(_PublicModel):
    claim_key: str = Field(pattern=CLAIM_KEY_PATTERN)
    claim_type: ClaimType
    text: str = Field(min_length=1, max_length=1200)
    evidence_ref_ids: tuple[str, ...] = ()
    source_dates: tuple[datetime, ...] = ()
    supporting_claim_keys: tuple[str, ...] = ()
    coverage_ref_ids: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)
    action_impact: ActionImpact
    lifecycle_status: ClaimLifecycle = "active"
    required_evidence: tuple[str, ...] = ()
    review_trigger: str | None = Field(default=None, max_length=500)

    @field_validator("claim_key")
    @classmethod
    def _registered_claim_key(cls, value: str) -> str:
        # Only the lens segment is code-controlled; topic/subject/predicate
        # are shape-checked by the field pattern so the model does not have
        # to hit a fixed ontology on the first try.
        parts = value.split(".")
        if len(parts) != 4:
            raise ValueError("claim key must have four segments")
        lens, _topic, subject, _predicate = parts
        if lens not in _CLAIM_LENSES:
            raise ValueError("claim key lens is not registered")
        if not subject:
            raise ValueError("claim key subject is required")
        return value

    @model_validator(mode="after")
    def _claim_shape(self) -> PublicClaim:
        if len(set(self.evidence_ref_ids)) != len(self.evidence_ref_ids):
            raise ValueError("claim evidence refs must be unique")
        if len(set(self.coverage_ref_ids)) != len(self.coverage_ref_ids):
            raise ValueError("claim coverage refs must be unique")
        if len(set(self.supporting_claim_keys)) != len(self.supporting_claim_keys):
            raise ValueError("supporting claim keys must be unique")
        if self.claim_type == "unknown":
            if self.evidence_ref_ids or self.source_dates or self.supporting_claim_keys:
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
            if not self.evidence_ref_ids:
                raise ValueError("fact and inference claims require evidence refs")
        if self.claim_type == "fact":
            if not self.coverage_ref_ids or not self.source_dates:
                raise ValueError("facts require coverage refs and source dates")
            if self.supporting_claim_keys:
                raise ValueError("facts cannot depend on other claims")
        if self.claim_type == "inference" and not self.supporting_claim_keys:
            raise ValueError("inferences require supporting fact claims")
        return self


class ResearchScenario(_PublicModel):
    scenario_id: Literal["upside", "base", "downside"]
    title: str = Field(min_length=1, max_length=160)
    condition_claim_keys: tuple[str, ...] = Field(min_length=1)
    research_implication: str = Field(min_length=1, max_length=1200)
    trigger_claim_keys: tuple[str, ...] = ()
    invalidation_claim_keys: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class ScenarioSet(_PublicModel):
    upside: ResearchScenario
    base: ResearchScenario
    downside: ResearchScenario

    @model_validator(mode="after")
    def _keys_match_scenario_ids(self) -> ScenarioSet:
        if (
            self.upside.scenario_id != "upside"
            or self.base.scenario_id != "base"
            or self.downside.scenario_id != "downside"
        ):
            raise ValueError("scenario IDs must match their fixed keys")
        for scenario in (self.upside, self.downside):
            if not (scenario.trigger_claim_keys or scenario.invalidation_claim_keys):
                raise ValueError("upside and downside scenarios require a trigger or invalidation")
        return self


class ReviewItem(_PublicModel):
    item_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str = Field(min_length=1, max_length=600)
    claim_keys: tuple[str, ...] = Field(min_length=1)
    trigger_kind: Literal["date", "event", "price", "filing"]
    trigger_value: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    status: Literal["pending", "met", "invalidated"] = "pending"
    evidence_ref_ids: tuple[str, ...] = ()


class ReviewPlan(_PublicModel):
    next_review_at: datetime | None = None
    item_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=600)


class CapabilityStatus(_PublicModel):
    capability: str = Field(min_length=1, max_length=120)
    status: Literal["ok", "degraded", "unavailable"]
    coverage_ref_ids: tuple[str, ...] = ()


class AnalystCard(_PublicModel):
    lens: Literal["market", "fundamentals", "news", "sentiment"]
    availability: Literal["ready", "limited", "unavailable"]
    summary: str = Field(min_length=1, max_length=1200)
    confidence: float | None = Field(default=None, ge=0, le=1)
    finding_claim_keys: tuple[str, ...] = ()
    capability_statuses: tuple[CapabilityStatus, ...] = ()


class DebateDigest(_PublicModel):
    agreed_claim_keys: tuple[str, ...] = ()
    disagreement_claim_keys: tuple[str, ...] = ()
    changed_claim_keys: tuple[str, ...] = ()
    uncertainty_claim_keys: tuple[str, ...] = ()


class ConflictRecord(_PublicModel):
    conflict_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: Literal["minor", "material", "critical"]
    capability: str = Field(min_length=1, max_length=120)
    evidence_ref_ids: tuple[str, ...] = ()
    reason_code: str = Field(pattern=OMISSION_CODE_PATTERN)


class DataQuality(_PublicModel):
    level: Literal["healthy", "limited", "conflicted", "blocked"]
    degraded_capabilities: tuple[str, ...] = ()
    unavailable_capabilities: tuple[str, ...] = ()
    conflicts: tuple[ConflictRecord, ...] = ()
    coverage_ref_ids: tuple[str, ...] = ()


class ResearchCaseV2(_PublicModel):
    """A single current-run research record with closed public references."""

    schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    horizon: Literal["short", "medium", "long"]
    source_sequence: int = Field(ge=0)
    as_of: datetime
    availability: Literal["full", "partial"]
    decision_eligibility: DecisionEligibility
    evidence_verdict: EvidenceVerdict
    research_rating: ResearchTilt | None = None
    rating_confidence: float | None = Field(default=None, ge=0, le=1)
    claims: tuple[PublicClaim, ...] = ()
    scenarios: ScenarioSet | None = None
    catalysts: tuple[ReviewItem, ...] = ()
    invalidation_conditions: tuple[ReviewItem, ...] = ()
    review_plan: ReviewPlan | None = None
    analyst_cards: tuple[AnalystCard, ...] = ()
    debate_digest: DebateDigest | None = None
    data_quality: DataQuality
    evidence_refs: tuple[EvidenceRefV2, ...] = ()
    coverage_refs: tuple[CoverageRefV1, ...] = ()
    audit_refs: tuple[str, ...] = ()
    omissions: tuple[str, ...] = ()

    @field_validator("omissions")
    @classmethod
    def _valid_omissions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if len(set(values)) != len(values) or any(
            re.fullmatch(OMISSION_CODE_PATTERN, value) is None for value in values
        ):
            raise ValueError("omissions must be unique registered-style codes")
        return values

    @model_validator(mode="after")
    def _validate_public_graph(self) -> ResearchCaseV2:
        if self.decision_eligibility == "none":
            if self.research_rating is not None or self.rating_confidence is not None:
                raise ValueError("ineligible research cases cannot include a research rating")
        elif self.research_rating is None or self.rating_confidence is None:
            raise ValueError("eligible research cases require a research rating and confidence")

        claim_index = _unique_index(self.claims, "claim_key", "claim keys")
        evidence_index = _unique_index(self.evidence_refs, "ref_id", "evidence refs")
        coverage_index = _unique_index(self.coverage_refs, "coverage_ref_id", "coverage refs")
        if any(reference.run_id != self.run_id for reference in self.evidence_refs):
            raise ValueError("evidence refs must belong to the current run")

        for claim in self.claims:
            _validate_claim_references(claim, claim_index, evidence_index, coverage_index)
        _validate_scenarios(self.scenarios, claim_index)
        review_items = self.catalysts + self.invalidation_conditions
        if len({item.item_id for item in review_items}) != len(review_items):
            raise ValueError("review item IDs must be unique")
        for item in review_items:
            _validate_claim_ids(item.claim_keys, claim_index, "review item claim")
            _validate_evidence_ids(item.evidence_ref_ids, evidence_index, "review item evidence")
        if self.review_plan is not None:
            item_ids = {item.item_id for item in review_items}
            if not set(self.review_plan.item_ids).issubset(item_ids):
                raise ValueError("review plan references unknown review items")
        for card in self.analyst_cards:
            _validate_claim_ids(card.finding_claim_keys, claim_index, "analyst card claim")
            for capability in card.capability_statuses:
                _validate_coverage_ids(
                    capability.coverage_ref_ids, coverage_index, "capability coverage"
                )
        if self.debate_digest is not None:
            _validate_claim_ids(
                _digest_claim_ids(self.debate_digest), claim_index, "debate digest claim"
            )
        _validate_coverage_ids(self.data_quality.coverage_ref_ids, coverage_index, "quality")
        for conflict in self.data_quality.conflicts:
            _validate_evidence_ids(conflict.evidence_ref_ids, evidence_index, "conflict")
        return self


def _unique_index(
    values: tuple[object, ...], field: str, label: str
) -> dict[str, object]:
    index = {str(getattr(value, field)): value for value in values}
    if len(index) != len(values):
        raise ValueError(f"{label} must be unique")
    return index


def _validate_claim_references(
    claim: PublicClaim,
    claim_index: dict[str, object],
    evidence_index: dict[str, object],
    coverage_index: dict[str, object],
) -> None:
    _validate_evidence_ids(claim.evidence_ref_ids, evidence_index, "claim")
    _validate_coverage_ids(claim.coverage_ref_ids, coverage_index, "claim")
    if claim.claim_type == "fact":
        evidence = [
            cast(EvidenceRefV2, evidence_index[ref_id]) for ref_id in claim.evidence_ref_ids
        ]
        if any(reference.resolution_status != "available" for reference in evidence):
            raise ValueError("facts require available evidence refs")
        observed_dates = {
            reference.source_observed_at
            for reference in evidence
            if reference.source_observed_at is not None
        }
        if not observed_dates or set(claim.source_dates) != observed_dates:
            raise ValueError("fact source dates must come from available evidence")
    elif claim.claim_type == "inference":
        _validate_claim_ids(claim.supporting_claim_keys, claim_index, "supporting")
        supporting = [
            cast(PublicClaim, claim_index[key]) for key in claim.supporting_claim_keys
        ]
        if any(item.claim_type != "fact" for item in supporting):
            raise ValueError("inferences can only depend on fact claims")
        allowed_evidence = {
            ref_id for item in supporting for ref_id in item.evidence_ref_ids
        }
        if not set(claim.evidence_ref_ids).issubset(allowed_evidence):
            raise ValueError("inference evidence must be inherited from facts")
        inherited_dates = {
            source_date for item in supporting for source_date in item.source_dates
        }
        if set(claim.source_dates) != inherited_dates:
            raise ValueError("inference source dates must be inherited from facts")


def _validate_scenarios(
    scenarios: ScenarioSet | None, claim_index: dict[str, object]
) -> None:
    if scenarios is None:
        return
    for scenario in (scenarios.upside, scenarios.base, scenarios.downside):
        _validate_claim_ids(scenario.condition_claim_keys, claim_index, "scenario condition")
        _validate_claim_ids(scenario.trigger_claim_keys, claim_index, "scenario trigger")
        _validate_claim_ids(
            scenario.invalidation_claim_keys, claim_index, "scenario invalidation"
        )


def _validate_claim_ids(
    values: tuple[str, ...], index: dict[str, object], label: str
) -> None:
    if not set(values).issubset(index):
        raise ValueError(f"{label} references an unknown current-run claim")


def _validate_evidence_ids(
    values: tuple[str, ...], index: dict[str, object], label: str
) -> None:
    if not set(values).issubset(index):
        raise ValueError(f"{label} references unknown evidence")


def _validate_coverage_ids(
    values: tuple[str, ...], index: dict[str, object], label: str
) -> None:
    if not set(values).issubset(index):
        raise ValueError(f"{label} references unknown coverage")


def _digest_claim_ids(digest: DebateDigest) -> tuple[str, ...]:
    return (
        digest.agreed_claim_keys
        + digest.disagreement_claim_keys
        + digest.changed_claim_keys
        + digest.uncertainty_claim_keys
    )
