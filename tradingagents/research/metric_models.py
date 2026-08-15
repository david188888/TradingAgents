"""Closed, provider-neutral contracts for comparable research metrics.

These models are intentionally independent from LangGraph and vendor payloads.
They describe public facts and deterministic calculations only; prose and
private model context do not belong in a research package.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MetricAvailability = Literal["available", "partial", "unavailable", "not_applicable"]
ObservationKind = Literal["observed", "derived"]
InterpretationMode = Literal["higher_is_better", "lower_is_better", "descriptive"]
FormulaStatus = Literal["available", "unavailable"]
EdgeStatus = Literal["supported", "conditional", "blocked", "contradicted"]


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class MetricDefinitionV1(_PublicModel):
    metric_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label_zh: str = Field(min_length=1, max_length=80)
    label_en: str = Field(min_length=1, max_length=120)
    plain_explanation: str = Field(min_length=1, max_length=600)
    formula_text: str = Field(min_length=1, max_length=240)
    unit: str = Field(min_length=1, max_length=40)
    interpretation_mode: InterpretationMode
    higher_is_better: bool | None = None
    required_inputs: tuple[str, ...] = ()
    validity_conditions: tuple[str, ...] = ()
    pitfalls: tuple[str, ...] = ()
    source_capabilities: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_interpretation(self) -> MetricDefinitionV1:
        if self.interpretation_mode == "descriptive" and self.higher_is_better is not None:
            raise ValueError("descriptive metrics cannot declare higher_is_better")
        if self.interpretation_mode != "descriptive" and self.higher_is_better is None:
            raise ValueError("directional metrics must declare higher_is_better")
        if len(set(self.required_inputs)) != len(self.required_inputs):
            raise ValueError("required_inputs must be unique")
        return self


class MetricObservationV1(_PublicModel):
    observation_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128)
    metric_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    entity_id: str = Field(min_length=1, max_length=120)
    period: str = Field(min_length=1, max_length=80)
    as_of: date
    frequency: Literal[
        "daily", "weekly", "monthly", "quarterly", "annual", "ttm", "snapshot"
    ]
    value: float | None = None
    unit: str = Field(min_length=1, max_length=40)
    availability: MetricAvailability = "available"
    unavailable_reason: str | None = Field(default=None, max_length=160)
    source_evidence_ref_ids: tuple[str, ...] = ()
    point_in_time: bool = True
    observation_kind: ObservationKind = "observed"

    @model_validator(mode="after")
    def validate_availability(self) -> MetricObservationV1:
        if self.availability == "available" and self.value is None:
            raise ValueError("available observations require value")
        if self.availability != "available" and self.value is not None:
            raise ValueError("unavailable observations cannot contain value")
        if self.availability == "available" and not self.point_in_time:
            raise ValueError("available observations must be point-in-time validated")
        if self.availability == "available" and self.unavailable_reason is not None:
            raise ValueError("available observations cannot contain unavailable_reason")
        if self.availability != "available" and not self.unavailable_reason:
            raise ValueError("unavailable observations require unavailable_reason")
        if (
            self.observation_kind == "observed"
            and self.availability == "available"
            and not self.source_evidence_ref_ids
        ):
            raise ValueError("available observed metrics require evidence refs")
        if len(set(self.source_evidence_ref_ids)) != len(self.source_evidence_ref_ids):
            raise ValueError("source evidence refs must be unique")
        return self


class FormulaEvaluationV1(_PublicModel):
    evaluation_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128)
    metric_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    formula: str = Field(min_length=1, max_length=240)
    input_observation_ids: tuple[str, ...] = Field(min_length=1)
    output_observation: MetricObservationV1
    status: FormulaStatus
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_output(self) -> FormulaEvaluationV1:
        if self.output_observation.run_id != self.run_id:
            raise ValueError("formula output must belong to the evaluation run")
        if self.output_observation.metric_id != self.metric_id:
            raise ValueError("formula output metric must match evaluation metric")
        if self.output_observation.observation_kind != "derived":
            raise ValueError("formula output must be marked derived")
        if self.status == "available" and self.output_observation.availability != "available":
            raise ValueError("available evaluation requires available output")
        if self.status == "unavailable" and self.output_observation.availability == "available":
            raise ValueError("unavailable evaluation cannot have available output")
        if len(set(self.input_observation_ids)) != len(self.input_observation_ids):
            raise ValueError("formula inputs must be unique")
        return self


class PeerExclusionV1(_PublicModel):
    entity_id: str = Field(min_length=1, max_length=120)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class PeerSetV1(_PublicModel):
    peer_set_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128)
    target_entity_id: str = Field(min_length=1, max_length=120)
    selection_method: Literal["user_specified", "deterministic_rule", "unavailable"]
    criteria: tuple[str, ...] = ()
    as_of: date
    member_entity_ids: tuple[str, ...] = ()
    source_evidence_ref_ids: tuple[str, ...] = ()
    excluded_candidates: tuple[PeerExclusionV1, ...] = ()
    unavailable_reason: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_members(self) -> PeerSetV1:
        if len(set(self.member_entity_ids)) != len(self.member_entity_ids):
            raise ValueError("peer members must be unique")
        if self.target_entity_id in self.member_entity_ids:
            raise ValueError("target must not be included in peer members")
        if self.selection_method == "unavailable":
            if self.member_entity_ids or not self.unavailable_reason:
                raise ValueError("unavailable peer sets require a reason and no members")
        elif not self.member_entity_ids:
            raise ValueError("usable peer sets require at least one member")
        return self


class MetricComparisonV1(_PublicModel):
    comparison_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128)
    metric_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    peer_set_id: str
    target_observation_id: str
    peer_observation_ids: tuple[str, ...] = ()
    period: str = Field(min_length=1, max_length=80)
    as_of: date
    unit: str = Field(min_length=1, max_length=40)
    target_value: float | None = None
    peer_median: float | None = None
    target_percentile: float | None = Field(default=None, ge=0, le=100)
    target_rank: int | None = Field(default=None, ge=1)
    sample_size: int = Field(ge=0)
    availability: MetricAvailability = "available"
    unavailable_reason: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_comparison(self) -> MetricComparisonV1:
        summary = (self.target_value, self.peer_median, self.target_percentile, self.target_rank)
        if self.availability == "available":
            if any(value is None for value in summary) or self.sample_size < 1:
                raise ValueError("available comparisons require complete statistics")
            if self.unavailable_reason is not None:
                raise ValueError("available comparisons cannot carry unavailable_reason")
        else:
            if any(value is not None for value in summary):
                raise ValueError("unavailable comparisons cannot carry statistics")
            if not self.unavailable_reason:
                raise ValueError("unavailable comparisons require unavailable_reason")
        return self


class LogicEdgeV1(_PublicModel):
    edge_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128)
    from_node: str = Field(min_length=1, max_length=120)
    to_node: str = Field(min_length=1, max_length=120)
    status: EdgeStatus
    input_observation_ids: tuple[str, ...] = ()
    supporting_claim_keys: tuple[str, ...] = ()
    evidence_ref_ids: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    next_validation: str = Field(min_length=1, max_length=400)
    invalidation: str = Field(min_length=1, max_length=400)
