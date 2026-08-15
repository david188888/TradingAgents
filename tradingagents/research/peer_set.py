"""Deterministic peer-set selection and point-in-time metric comparison."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from .metric_models import MetricComparisonV1, MetricObservationV1, PeerExclusionV1, PeerSetV1


class PeerCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_id: str = Field(min_length=1, max_length=120)
    industry_code: str | None = Field(default=None, max_length=80)
    market_cap: float | None = None
    business_similarity: float | None = Field(default=None, ge=0, le=1)
    as_of: date
    source_evidence_ref_ids: tuple[str, ...] = ()


def build_peer_set(
    target_entity_id: str,
    candidates: Iterable[PeerCandidateV1],
    *,
    run_id: str,
    as_of: date,
    requested_peer_ids: Sequence[str] = (),
    target_industry: str | None = None,
    min_size_multiple: float = 0.2,
    max_size_multiple: float = 5.0,
    min_peers: int = 1,
) -> PeerSetV1:
    """Build a reproducible peer set without accepting model-generated names."""
    if min_size_multiple <= 0 or max_size_multiple < min_size_multiple:
        raise ValueError("size multiples must be positive and ordered")
    if min_peers < 1:
        raise ValueError("min_peers must be positive")
    candidate_map: dict[str, PeerCandidateV1] = {}
    exclusions: list[PeerExclusionV1] = []
    for candidate in candidates:
        if candidate.entity_id in candidate_map:
            raise ValueError("duplicate peer candidate")
        candidate_map[candidate.entity_id] = candidate

    target = candidate_map.get(target_entity_id)
    effective_industry = target_industry or (target.industry_code if target else None)
    target_cap = target.market_cap if target else None
    requested = tuple(dict.fromkeys(requested_peer_ids))
    selected: list[PeerCandidateV1] = []
    source_ids: set[str] = set()
    for entity_id in sorted(requested or candidate_map):
        candidate = candidate_map.get(entity_id)
        reason: str | None = None
        if entity_id == target_entity_id:
            reason = "target_excluded"
        elif candidate is None:
            reason = "candidate_not_observed"
        elif candidate.as_of > as_of:
            reason = "future_dated"
        elif effective_industry is not None and candidate.industry_code != effective_industry:
            reason = "industry_mismatch"
        elif target_cap is not None and candidate.market_cap is None:
            reason = "missing_market_cap"
        elif target_cap is not None and (
            candidate.market_cap < target_cap * min_size_multiple
            or candidate.market_cap > target_cap * max_size_multiple
        ):
            reason = "size_out_of_range"
        elif not candidate.source_evidence_ref_ids:
            reason = "missing_evidence"
        if reason:
            exclusions.append(PeerExclusionV1(entity_id=entity_id, reason_code=reason))
            continue
        selected.append(candidate)
        source_ids.update(candidate.source_evidence_ref_ids)

    selected.sort(
        key=lambda item: (
            -(item.business_similarity if item.business_similarity is not None else -1),
            abs((item.market_cap or 0) - (target_cap or 0)),
            item.entity_id,
        )
    )
    members = tuple(item.entity_id for item in selected)
    method = "user_specified" if requested else "deterministic_rule"
    unavailable_reason = None
    if len(members) < min_peers:
        unavailable_reason = "insufficient_verified_peers"
        method = "unavailable"
        members = ()
    return PeerSetV1(
        peer_set_id=f"{run_id}:peer-set:{target_entity_id}:{as_of.isoformat()}",
        run_id=run_id,
        target_entity_id=target_entity_id,
        selection_method=method,
        criteria=(
            "same_industry" if effective_industry is not None else "industry_unavailable",
            f"market_cap_multiple:{min_size_multiple:g}-{max_size_multiple:g}",
            "stable_entity_id_sort",
        ),
        as_of=as_of,
        member_entity_ids=members,
        source_evidence_ref_ids=tuple(sorted(source_ids)),
        excluded_candidates=tuple(exclusions),
        unavailable_reason=unavailable_reason,
    )


def compare_metric(
    peer_set: PeerSetV1,
    target: MetricObservationV1,
    peers: Iterable[MetricObservationV1],
    *,
    comparison_id: str | None = None,
    min_sample_size: int = 2,
) -> MetricComparisonV1:
    """Compare same-period, same-unit observations; mismatches become unavailable."""
    if target.entity_id != peer_set.target_entity_id:
        raise ValueError("target observation does not match peer set")
    if target.run_id != peer_set.run_id:
        raise ValueError("target observation must belong to peer-set run")
    peer_map: dict[str, MetricObservationV1] = {}
    for item in peers:
        if item.entity_id in peer_map:
            raise ValueError("duplicate peer observation")
        peer_map[item.entity_id] = item
    selected = [peer_map[entity_id] for entity_id in peer_set.member_entity_ids if entity_id in peer_map]
    available = [
        item
        for item in selected
        if item.availability == "available"
        and item.metric_id == target.metric_id
        and item.period == target.period
        and item.as_of == target.as_of
        and item.frequency == target.frequency
        and item.unit == target.unit
    ]
    reason: str | None = None
    if target.availability != "available":
        reason = "target_metric_unavailable"
    elif peer_set.selection_method == "unavailable":
        reason = peer_set.unavailable_reason or "peer_set_unavailable"
    elif len(available) < min_sample_size:
        reason = "insufficient_comparable_observations"
    values = [float(item.value) for item in available]
    target_value = float(target.value) if target.availability == "available" else None
    if reason:
        return MetricComparisonV1(
            comparison_id=comparison_id or f"{peer_set.peer_set_id}:{target.metric_id}",
            run_id=peer_set.run_id,
            metric_id=target.metric_id,
            peer_set_id=peer_set.peer_set_id,
            target_observation_id=target.observation_id,
            peer_observation_ids=tuple(item.observation_id for item in available),
            period=target.period,
            as_of=target.as_of,
            unit=target.unit,
            sample_size=len(values),
            availability="unavailable",
            unavailable_reason=reason,
        )
    combined = sorted(values + [target_value])
    rank = combined.index(target_value) + 1
    percentile = 100 * sum(value <= target_value for value in values) / len(values)
    return MetricComparisonV1(
        comparison_id=comparison_id or f"{peer_set.peer_set_id}:{target.metric_id}",
        run_id=peer_set.run_id,
        metric_id=target.metric_id,
        peer_set_id=peer_set.peer_set_id,
        target_observation_id=target.observation_id,
        peer_observation_ids=tuple(item.observation_id for item in available),
        period=target.period,
        as_of=target.as_of,
        unit=target.unit,
        target_value=target_value,
        peer_median=median(values),
        target_percentile=percentile,
        target_rank=rank,
        sample_size=len(values),
        availability="available",
    )
