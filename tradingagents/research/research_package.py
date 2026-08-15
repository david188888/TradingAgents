"""Versioned public artifact for temporal, peer, and logic-loop research."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timezone
from math import isclose
from statistics import median
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from tradingagents.agents.schemas._research_case import EvidenceRefV2

from .metric_catalog import all_metric_definitions
from .metric_engine import calculate_metric, calculate_yoy
from .metric_models import (
    FormulaEvaluationV1,
    LogicEdgeV1,
    MetricComparisonV1,
    MetricDefinitionV1,
    MetricObservationV1,
    PeerSetV1,
)
from .metric_provider_adapter import observations_from_fundamentals_bundle


class ResearchEvidenceRefV1(BaseModel):
    """Small package-local evidence index without raw storage locators."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    ref_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=128)
    source_label: str = Field(min_length=1, max_length=160)
    resolution_status: Literal["available", "unavailable"] = "available"


class ResearchPackageV1(BaseModel):
    """Machine-readable fact layer derived from one durable research run."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["research-package-v1"] = "research-package-v1"
    package_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    target_entity_id: str | None = Field(default=None, min_length=1, max_length=120)
    analysis_cutoff: date
    created_at: datetime
    evidence_refs: tuple[ResearchEvidenceRefV1, ...] = ()
    metric_definitions: tuple[MetricDefinitionV1, ...] = ()
    observations: tuple[MetricObservationV1, ...] = ()
    formula_evaluations: tuple[FormulaEvaluationV1, ...] = ()
    peer_sets: tuple[PeerSetV1, ...] = ()
    comparisons: tuple[MetricComparisonV1, ...] = ()
    logic_edges: tuple[LogicEdgeV1, ...] = ()
    unknowns: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> ResearchPackageV1:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        evidence_index = {item.ref_id: item for item in self.evidence_refs}
        if len(evidence_index) != len(self.evidence_refs):
            raise ValueError("evidence refs must be unique")
        if any(item.run_id != self.run_id for item in self.evidence_refs):
            raise ValueError("evidence refs must belong to the current run")
        definitions = {item.metric_id: item for item in self.metric_definitions}
        if len(definitions) != len(self.metric_definitions):
            raise ValueError("metric definitions must be unique")
        observations = {item.observation_id: item for item in self.observations}
        all_observations = dict(observations)
        evaluations = {item.evaluation_id: item for item in self.formula_evaluations}
        peer_sets = {item.peer_set_id: item for item in self.peer_sets}
        allowed_entities = {self.target_entity_id or self.ticker}
        for peer_set in self.peer_sets:
            allowed_entities.update(peer_set.member_entity_ids)
        comparisons = {item.comparison_id: item for item in self.comparisons}
        edges = {item.edge_id: item for item in self.logic_edges}
        for collection, name in (
            (observations, "observation IDs"),
            (evaluations, "evaluation IDs"),
            (peer_sets, "peer set IDs"),
            (comparisons, "comparison IDs"),
            (edges, "logic edge IDs"),
        ):
            original = {
                "observation IDs": self.observations,
                "evaluation IDs": self.formula_evaluations,
                "peer set IDs": self.peer_sets,
                "comparison IDs": self.comparisons,
                "logic edge IDs": self.logic_edges,
            }[name]
            if len(collection) != len(original):
                raise ValueError(f"{name} must be unique")
        for observation in self.observations:
            if observation.run_id != self.run_id:
                raise ValueError("observations must belong to the current run")
            if observation.as_of > self.analysis_cutoff:
                raise ValueError("observations cannot be later than analysis cutoff")
            if observation.metric_id not in definitions:
                raise ValueError("observation references unknown metric definition")
            if not set(observation.source_evidence_ref_ids).issubset(evidence_index):
                raise ValueError("observation references unknown evidence")
            if observation.entity_id not in allowed_entities:
                raise ValueError("observations must belong to the target or a declared peer set")
            if observation.value is not None and not math.isfinite(float(observation.value)):
                raise ValueError("observations must contain finite values")
            if (
                observation.observation_kind == "derived"
                and observation.unit != definitions[observation.metric_id].unit
            ):
                raise ValueError("derived observation unit does not match its metric definition")
        for evaluation in self.formula_evaluations:
            if evaluation.run_id != self.run_id:
                raise ValueError("formula evaluations must belong to the current run")
            if evaluation.metric_id not in definitions:
                raise ValueError("formula references unknown metric definition")
            input_observations = [
                all_observations.get(item) for item in evaluation.input_observation_ids
            ]
            if any(item is None for item in input_observations):
                raise ValueError("formula references unknown input observation")
            definition = definitions[evaluation.metric_id]
            expected_metrics = Counter(
                key.removesuffix("_current").removesuffix("_prior")
                for key in definition.required_inputs
            )
            actual_metrics = Counter(item.metric_id for item in input_observations if item is not None)
            if actual_metrics != expected_metrics:
                raise ValueError("formula input metrics do not match the definition")
            if len({item.entity_id for item in input_observations if item is not None}) != 1:
                raise ValueError("formula inputs must belong to one entity")
            input_frequencies = {item.frequency for item in input_observations if item is not None}
            input_as_ofs = {item.as_of for item in input_observations if item is not None}
            if len(input_frequencies) != 1:
                raise ValueError("formula inputs must share frequency")
            if not evaluation.metric_id.endswith("_yoy") and len(input_as_ofs) != 1:
                raise ValueError("formula inputs must share as_of")
            output = evaluation.output_observation
            existing = all_observations.get(output.observation_id)
            if existing is not None and existing != output:
                raise ValueError("formula output conflicts with an observation")
            if output.run_id != self.run_id:
                raise ValueError("derived observations must belong to the current run")
            if output.as_of > self.analysis_cutoff:
                raise ValueError("derived observations cannot be later than analysis cutoff")
            if output.entity_id not in allowed_entities:
                raise ValueError("derived observations must belong to the target or a declared peer set")
            if not set(output.source_evidence_ref_ids).issubset(evidence_index):
                raise ValueError("derived observations reference unknown evidence")
            if not all(all_observations[item].run_id == self.run_id for item in evaluation.input_observation_ids):
                raise ValueError("formula inputs must belong to the current run")
            all_observations[output.observation_id] = output
        for peer_set in self.peer_sets:
            if peer_set.run_id != self.run_id:
                raise ValueError("peer sets must belong to the current run")
            if peer_set.as_of > self.analysis_cutoff:
                raise ValueError("peer set cannot be later than analysis cutoff")
            if not set(peer_set.source_evidence_ref_ids).issubset(evidence_index):
                raise ValueError("peer set references unknown evidence")
        for comparison in self.comparisons:
            if comparison.run_id != self.run_id:
                raise ValueError("comparisons must belong to the current run")
            peer_set = peer_sets.get(comparison.peer_set_id)
            if peer_set is None:
                raise ValueError("comparison references unknown peer set")
            target = all_observations.get(comparison.target_observation_id)
            if target is None:
                raise ValueError("comparison references unknown target observation")
            peers = [all_observations.get(item) for item in comparison.peer_observation_ids]
            if any(item is None for item in peers):
                raise ValueError("comparison references unknown peer observation")
            peer_values = [item for item in peers if item is not None]
            if target.metric_id != comparison.metric_id or target.entity_id != peer_set.target_entity_id:
                raise ValueError("comparison target does not match metric or peer set")
            if any(
                item.metric_id != comparison.metric_id
                or item.entity_id not in peer_set.member_entity_ids
                or item.period != comparison.period
                or item.as_of != comparison.as_of
                or item.frequency != target.frequency
                or item.unit != comparison.unit
                for item in peer_values
            ):
                raise ValueError("comparison observations are not semantically comparable")
            if comparison.as_of > self.analysis_cutoff:
                raise ValueError("comparisons cannot be later than analysis cutoff")
            if comparison.sample_size != len(peer_values):
                raise ValueError("comparison sample_size does not match peer observations")
            if comparison.availability == "available":
                if target.availability != "available" or any(item.availability != "available" for item in peer_values):
                    raise ValueError("available comparison requires available observations")
                values = [float(item.value) for item in peer_values]
                if not isclose(float(comparison.target_value), float(target.value), rel_tol=1e-9):
                    raise ValueError("comparison target_value does not match target observation")
                if not isclose(float(comparison.peer_median), float(median(values)), rel_tol=1e-9):
                    raise ValueError("comparison peer_median does not match peer observations")
            elif comparison.unavailable_reason is None:
                raise ValueError("unavailable comparison requires a reason")
        for edge in self.logic_edges:
            if edge.run_id != self.run_id:
                raise ValueError("logic edges must belong to the current run")
            if not set(edge.input_observation_ids).issubset(all_observations):
                raise ValueError("logic edge references unknown observation")
            if not set(edge.evidence_ref_ids).issubset(evidence_index):
                raise ValueError("logic edge references unknown evidence")
            if edge.status == "blocked" and not edge.missing_evidence:
                raise ValueError("blocked logic edges require missing_evidence")
        return self

    def content_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()


def _bundle_ref_id(bundle: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _derived_evaluations(
    observations: tuple[MetricObservationV1, ...],
) -> tuple[FormulaEvaluationV1, ...]:
    index = {(item.metric_id, item.period, item.frequency): item for item in observations}
    evaluations: list[FormulaEvaluationV1] = []
    for metric_id, required in (
        ("gross_margin", ("gross_profit", "revenue")),
        ("net_margin", ("net_income", "revenue")),
        ("cash_conversion", ("operating_cash_flow", "net_income")),
        ("debt_ratio", ("total_liabilities", "total_assets")),
    ):
        contexts = sorted(
            {(item.period, item.frequency) for item in observations if item.metric_id in required}
        )
        for period, frequency in contexts:
            inputs = {
                key: index[(key, period, frequency)]
                for key in required
                if (key, period, frequency) in index
            }
            if len(inputs) != len(required):
                continue
            evaluation = calculate_metric(metric_id, inputs, period=period)
            refs = tuple(
                dict.fromkeys(
                    ref
                    for item in inputs.values()
                    for ref in item.source_evidence_ref_ids
                )
            )
            output = evaluation.output_observation.model_copy(
                update={"source_evidence_ref_ids": refs}
            )
            evaluations.append(evaluation.model_copy(update={"output_observation": output}))

    for base_metric, yoy_metric in (
        ("revenue", "revenue_yoy"),
        ("net_income", "net_income_yoy"),
        ("operating_cash_flow", "operating_cash_flow_yoy"),
    ):
        by_frequency: dict[str, list[MetricObservationV1]] = {}
        for item in observations:
            if item.metric_id == base_metric:
                by_frequency.setdefault(item.frequency, []).append(item)
        for _frequency, values in by_frequency.items():
            ordered = sorted(values, key=lambda item: item.period)
            if len(ordered) < 2:
                continue
            current, prior = ordered[-1], ordered[-2]
            evaluation = calculate_yoy(yoy_metric, current, prior)
            refs = tuple(dict.fromkeys(current.source_evidence_ref_ids + prior.source_evidence_ref_ids))
            output = evaluation.output_observation.model_copy(
                update={"source_evidence_ref_ids": refs}
            )
            evaluations.append(evaluation.model_copy(update={"output_observation": output}))
    return tuple(evaluations)


def research_package_from_case(
    case: object,
    *,
    analysis_cutoff: date,
    created_at: datetime | None = None,
    fundamentals_bundle: Mapping[str, object] | None = None,
) -> ResearchPackageV1:
    """Create the first public package shell from a validated research case.

    The package always contains definitions and evidence anchors. When a
    committed fundamentals bundle has explicit filing dates and matching
    evidence, the same builder also publishes structured observations and
    deterministic formula evaluations. Missing or unproven observations stay
    explicit so later providers can fill the same versioned package without
    changing the conversation or Reader contract.
    """
    run_id = str(case.run_id)
    ticker = str(case.ticker)
    raw_refs = tuple(getattr(case, "evidence_refs", ()))
    evidence_refs = tuple(
        ResearchEvidenceRefV1(
            ref_id=str(ref.ref_id),
            run_id=str(ref.run_id),
            source_label=str(ref.artifact_id).split(":", 1)[0],
            resolution_status=str(ref.resolution_status),
        )
        for ref in raw_refs
    )
    observations: tuple[MetricObservationV1, ...] = ()
    formula_evaluations: tuple[FormulaEvaluationV1, ...] = ()
    if fundamentals_bundle is not None:
        bundle_ref_id = _bundle_ref_id(fundamentals_bundle)
        if any(ref.ref_id == bundle_ref_id and ref.resolution_status == "available" for ref in evidence_refs):
            observations = observations_from_fundamentals_bundle(
                fundamentals_bundle,
                run_id=run_id,
                entity_id=ticker,
                analysis_cutoff=analysis_cutoff,
                evidence_ref_id=bundle_ref_id,
            )
            formula_evaluations = _derived_evaluations(observations)
            observations = (*observations, *(item.output_observation for item in formula_evaluations))
    unknowns = (
        (() if observations else ("metrics.structured_observations_unavailable",))
        + ("peers.verified_peer_set_unavailable", "logic_loop.structured_inputs_unavailable")
    )
    return ResearchPackageV1(
        package_id=f"research-package:{run_id.casefold()}",
        run_id=run_id,
        ticker=ticker,
        target_entity_id=ticker,
        analysis_cutoff=analysis_cutoff,
        created_at=created_at or getattr(case, "as_of", datetime.now(timezone.utc)),
        evidence_refs=evidence_refs,
        metric_definitions=all_metric_definitions(),
        observations=observations,
        formula_evaluations=formula_evaluations,
        unknowns=unknowns,
    )


def evidence_refs_from_case(refs: tuple[EvidenceRefV2, ...]) -> tuple[ResearchEvidenceRefV1, ...]:
    """Adapt existing evidence refs without importing ResearchCaseV2 into callers."""
    return tuple(
        ResearchEvidenceRefV1(
            ref_id=ref.ref_id,
            run_id=ref.run_id,
            source_label=ref.artifact_id.split(":", 1)[0],
            resolution_status=ref.resolution_status,
        )
        for ref in refs
    )
