"""Deterministic decision-eligibility and public data-quality policy."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from tradingagents.agents.schemas._research_case import (
    AnalystCard,
    ConflictRecord,
    CoverageRefV1,
    DataQuality,
    EvidenceVerdict,
    PublicClaim,
)
from tradingagents.research.horizon_policy import DataWindowPlanV1, LensGroupV1

Eligibility = Literal["full", "limited", "none"]


@dataclass(frozen=True)
class EligibilityAssessment:
    decision_eligibility: Eligibility
    data_quality: DataQuality
    reason_codes: tuple[str, ...]


def assess_decision_eligibility(
    *,
    plan: DataWindowPlanV1,
    evidence_verdict: EvidenceVerdict,
    claims: Iterable[PublicClaim],
    analyst_cards: Iterable[AnalystCard],
    coverage_refs: Iterable[CoverageRefV1],
    conflicts: Iterable[ConflictRecord] = (),
    used_optional_capabilities: Iterable[str] = (),
) -> EligibilityAssessment:
    """Apply the approved policy without allowing model prose to upgrade it."""
    claim_items = tuple(claims)
    cards = tuple(analyst_cards)
    coverage = {item.capability: item for item in coverage_refs}
    conflict_items = tuple(conflicts)
    required = tuple(item.capability_id for item in plan.capabilities if item.requirement == "required")
    required_statuses = {
        capability: coverage.get(capability).envelope.bundle_completeness
        if coverage.get(capability) is not None
        else "unavailable"
        for capability in required
    }
    fact_lenses = _usable_lenses(claim_items, cards)
    required_lenses_ok = set(plan.required_lenses).issubset(fact_lenses) and all(
        _lens_group_usable(group, fact_lenses) for group in plan.required_lens_groups
    )
    codes: list[str] = []
    critical = any(conflict.severity == "critical" for conflict in conflict_items)
    material = any(conflict.severity == "material" for conflict in conflict_items)
    if evidence_verdict in {"FAIL_STOP", "GATE_ERROR"}:
        codes.append("evidence_gate_blocked")
    if critical:
        codes.append("critical_conflict")
    if len(fact_lenses) < 2:
        codes.append("insufficient_independent_lenses")
    if codes:
        eligibility: Eligibility = "none"
    else:
        incomplete_required = [
            capability for capability, status in required_statuses.items() if status != "complete"
        ]
        if evidence_verdict == "LOW_CONFIDENCE":
            codes.append("evidence_low_confidence")
        if incomplete_required:
            codes.append("required_capability_incomplete")
        if not required_lenses_ok:
            codes.append("required_lens_unavailable")
        if material:
            codes.append("material_conflict")
        eligibility = "limited" if codes else "full"

    data_quality = _data_quality(
        eligibility=eligibility,
        evidence_verdict=evidence_verdict,
        required_statuses=required_statuses,
        conflicts=conflict_items,
        coverage=coverage,
        used_optional_capabilities=tuple(used_optional_capabilities),
    )
    return EligibilityAssessment(eligibility, data_quality, tuple(codes))


def _usable_lenses(
    claims: tuple[PublicClaim, ...], cards: tuple[AnalystCard, ...]
) -> set[str]:
    fact_keys = {claim.claim_key for claim in claims if claim.claim_type == "fact"}
    usable: set[str] = set()
    for card in cards:
        if card.availability != "ready":
            continue
        if any(
            key in fact_keys and key.split(".", 1)[0] == card.lens
            for key in card.finding_claim_keys
        ):
            usable.add(card.lens)
    return usable


def _lens_group_usable(group: LensGroupV1, usable_lenses: set[str]) -> bool:
    return sum(lens in usable_lenses for lens in group.lens_ids) >= group.minimum_usable


def _data_quality(
    *,
    eligibility: Eligibility,
    evidence_verdict: EvidenceVerdict,
    required_statuses: dict[str, str],
    conflicts: tuple[ConflictRecord, ...],
    coverage: dict[str, CoverageRefV1],
    used_optional_capabilities: tuple[str, ...],
) -> DataQuality:
    critical = any(conflict.severity == "critical" for conflict in conflicts)
    material = any(conflict.severity == "material" for conflict in conflicts)
    optional_degraded = tuple(
        capability
        for capability in used_optional_capabilities
        if coverage.get(capability) is None
        or coverage[capability].envelope.bundle_completeness != "complete"
    )
    unavailable = tuple(
        capability
        for capability, status in required_statuses.items()
        if status == "unavailable"
    )
    degraded = tuple(
        capability
        for capability, status in required_statuses.items()
        if status in {"partial", "unknown"}
    ) + optional_degraded
    if eligibility == "none" or evidence_verdict in {"FAIL_STOP", "GATE_ERROR"} or critical:
        level = "blocked"
    elif material:
        level = "conflicted"
    elif eligibility == "limited" or degraded or unavailable:
        level = "limited"
    else:
        level = "healthy"
    return DataQuality(
        level=level,
        degraded_capabilities=degraded,
        unavailable_capabilities=unavailable,
        conflicts=conflicts,
        coverage_ref_ids=tuple(
            reference.coverage_ref_id for reference in coverage.values()
        ),
    )
