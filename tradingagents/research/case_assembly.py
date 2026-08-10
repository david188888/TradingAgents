"""Deterministic, commit-safe assembly of a minimum public Research Case."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from tradingagents.agents.schemas import DataQuality, ResearchCaseV2
from tradingagents.runtime.run_models import RunSnapshot


def assemble_partial_research_case(
    snapshot: RunSnapshot,
    *,
    source_sequence: int,
    evidence_verdict: str,
) -> ResearchCaseV2:
    """Create the honest fallback when no evidence-bound claim set exists.

    This function intentionally does not read analyst Markdown, prompts, or
    tool traces. A later assembler can replace this partial result only by
    validating public claims and their current-run evidence references.
    """
    verdict: Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"] = (
        evidence_verdict
        if evidence_verdict in {"PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"}
        else "GATE_ERROR"
    )
    as_of = datetime.fromisoformat(snapshot.analysis_date).replace(tzinfo=timezone.utc)
    return ResearchCaseV2(
        run_id=snapshot.run_id,
        ticker=snapshot.ticker,
        horizon=snapshot.horizon or "medium",
        source_sequence=source_sequence,
        as_of=as_of,
        availability="partial",
        decision_eligibility="none",
        evidence_verdict=verdict,
        data_quality=DataQuality(
            level="blocked",
            unavailable_capabilities=("evidence_bound_claims",),
        ),
        omissions=(
            "research_case.evidence_bound_claims_unavailable",
            "research_case.rating_withheld",
        ),
    )


# ---------------------------------------------------------------------------
# Full evidence-bound assembler
# ---------------------------------------------------------------------------

from tradingagents.agents.schemas import (  # noqa: E402
    AnalystCard,
    CapabilityStatus,
    CoverageRefV1,
    EvidenceRefV2,
    PublicClaim,
    ResearchScenario,
    ReviewItem,
    ReviewPlan,
    ScenarioSet,
)
from tradingagents.agents.schemas._research_case_draft import (  # noqa: E402
    ClaimDraft,
    LearningResearchCaseDraft,
)
from tradingagents.research.eligibility import assess_decision_eligibility  # noqa: E402
from tradingagents.research.evidence_registry import EvidenceRegistry  # noqa: E402
from tradingagents.research.horizon_policy import DataWindowPlanV1  # noqa: E402

# Fixed first-version lens -> capability mapping for AnalystCard statuses.
# ``market`` tracks the deterministic adjusted price series; ``news`` tracks the
# deterministic company event window.  ``sentiment`` is fed by A-share
# supplement capabilities, which we approximate deterministically as every
# registered coverage capability that is not the fixed price/event ones.  This
# is an explicit approximation so the eligibility policy never lets model prose
# decide capability status; ``fundamentals`` has no coverage in this first
# version and stays empty.
_LENS_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "market": ("adjusted_price_history",),
    "news": ("company_event_window",),
    "sentiment": (),  # filled dynamically from registry in _sentiment_capabilities
    "fundamentals": (),
}

# Fixed, non-supplement coverage capabilities that belong to price/event lenses.
_FIXED_COVERAGE_CAPABILITIES = frozenset(
    {"adjusted_price_history", "company_event_window"}
)


def _sentiment_capabilities(registry: EvidenceRegistry) -> tuple[str, ...]:
    """Return supplement coverage capabilities attributed to the sentiment lens.

    Deterministic first-version approximation: every coverage capability the
    registry carries that is not one of the fixed price/event capabilities is
    treated as sentiment-relevant (A-share supplement output such as capital
    flow or northbound flow).
    """
    return tuple(
        capability
        for capability in sorted(registry.coverage_by_capability)
        if capability not in _FIXED_COVERAGE_CAPABILITIES
    )


def _normalize_verdict(evidence_verdict: str) -> Literal[
    "PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"
]:
    return (
        evidence_verdict
        if evidence_verdict in {"PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"}
        else "GATE_ERROR"
    )


def _resolved_evidence_refs(
    registry: EvidenceRegistry,
    evidence_keys: tuple[str, ...],
) -> tuple[EvidenceRefV2, ...]:
    refs: list[EvidenceRefV2] = []
    for key in evidence_keys:
        ref = registry.resolve_evidence_key(key)
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def _resolved_coverage_refs(
    registry: EvidenceRegistry,
    coverage_keys: tuple[str, ...],
) -> tuple[CoverageRefV1, ...]:
    refs: list[CoverageRefV1] = []
    for key in coverage_keys:
        ref = registry.resolve_coverage_key(key)
        if ref is not None:
            refs.append(ref)
    return tuple(refs)


def _evidence_source_dates(refs: tuple[EvidenceRefV2, ...]) -> tuple[datetime, ...]:
    """Unique, ascending source dates taken from evidence refs (drop None)."""
    seen: set[datetime] = set()
    ordered: list[datetime] = []
    for ref in refs:
        if ref.source_observed_at is not None and ref.source_observed_at not in seen:
            seen.add(ref.source_observed_at)
            ordered.append(ref.source_observed_at)
    return tuple(sorted(ordered))


def _build_facts(
    registry: EvidenceRegistry,
    facts: tuple[ClaimDraft, ...],
    omissions: set[str],
) -> tuple[tuple[PublicClaim, ...], set[str]]:
    """Resolve fact drafts into public claims, dropping any that lack evidence.

    Returns ``(claims, dropped_keys)``.  A fact is dropped when it has no
    resolvable evidence, no source date, or no resolvable coverage ref.
    """
    claims: list[PublicClaim] = []
    dropped: set[str] = set()
    for draft in facts:
        evidence_refs = _resolved_evidence_refs(registry, draft.evidence_keys)
        if len(evidence_refs) != len(draft.evidence_keys):
            omissions.add("research_case.evidence_key_unresolved")
        coverage_refs = _resolved_coverage_refs(registry, draft.coverage_keys)
        if len(coverage_refs) != len(draft.coverage_keys):
            omissions.add("research_case.coverage_key_unresolved")

        source_dates = _evidence_source_dates(evidence_refs)
        evidence_ref_ids = tuple(ref.ref_id for ref in evidence_refs)
        coverage_ref_ids = tuple(ref.coverage_ref_id for ref in coverage_refs)
        if not evidence_ref_ids or not source_dates or not coverage_ref_ids:
            omissions.add("research_case.claim_omitted_missing_evidence")
            dropped.add(draft.claim_key)
            continue
        claims.append(
            PublicClaim(
                claim_key=draft.claim_key,
                claim_type="fact",
                text=draft.text,
                evidence_ref_ids=evidence_ref_ids,
                source_dates=source_dates,
                supporting_claim_keys=(),
                coverage_ref_ids=coverage_ref_ids,
                confidence=draft.confidence,
                action_impact=draft.action_impact,
                lifecycle_status=draft.lifecycle_status,
                required_evidence=(),
                review_trigger=None,
            )
        )
    return tuple(claims), dropped


def _build_inferences(
    registry: EvidenceRegistry,
    inferences: tuple[ClaimDraft, ...],
    fact_claims: tuple[PublicClaim, ...],
    omissions: set[str],
) -> tuple[PublicClaim, ...]:
    """Resolve inference drafts, requiring all supporting facts to survive."""
    fact_by_key = {claim.claim_key: claim for claim in fact_claims}
    claims: list[PublicClaim] = []
    for draft in inferences:
        if not set(draft.supporting_claim_keys).issubset(fact_by_key):
            omissions.add("research_case.claim_omitted_missing_supporting")
            continue
        supporting = [fact_by_key[key] for key in draft.supporting_claim_keys]
        allowed_evidence = {
            ref_id for fact in supporting for ref_id in fact.evidence_ref_ids
        }
        inherited_dates = sorted(
            {date for fact in supporting for date in fact.source_dates}
        )
        # An inference's evidence must be a subset of its supporting facts'
        # evidence.  Only keep evidence the draft actually cited that is also
        # carried by a surviving supporting fact; if they do not intersect,
        # drop the inference rather than silently attaching evidence the model
        # did not cite.
        draft_evidence_ids = {
            ref.ref_id
            for ref in _resolved_evidence_refs(registry, draft.evidence_keys)
        }
        evidence_ids = tuple(
            ref_id for ref_id in allowed_evidence if ref_id in draft_evidence_ids
        )
        if not evidence_ids:
            omissions.add("research_case.claim_omitted_unsupported_evidence")
            continue
        claims.append(
            PublicClaim(
                claim_key=draft.claim_key,
                claim_type="inference",
                text=draft.text,
                evidence_ref_ids=evidence_ids,
                source_dates=tuple(inherited_dates),
                supporting_claim_keys=draft.supporting_claim_keys,
                coverage_ref_ids=(),
                confidence=draft.confidence,
                action_impact=draft.action_impact,
                lifecycle_status=draft.lifecycle_status,
                required_evidence=(),
                review_trigger=None,
            )
        )
    return tuple(claims)


def _build_unknowns(unknowns: tuple[ClaimDraft, ...]) -> tuple[PublicClaim, ...]:
    return tuple(
        PublicClaim(
            claim_key=draft.claim_key,
            claim_type="unknown",
            text=draft.text,
            evidence_ref_ids=(),
            source_dates=(),
            supporting_claim_keys=(),
            coverage_ref_ids=(),
            confidence=None,
            action_impact=draft.action_impact,
            lifecycle_status=draft.lifecycle_status,
            required_evidence=draft.required_evidence,
            review_trigger=draft.review_trigger,
        )
        for draft in unknowns
    )


def _build_scenario_set(
    draft: LearningResearchCaseDraft,
    claim_keys: set[str],
    omissions: set[str],
) -> ScenarioSet | None:
    scenarios = (draft.upside, draft.base, draft.downside)
    for scenario in scenarios:
        referenced = (
            scenario.condition_claim_keys
            + scenario.trigger_claim_keys
            + scenario.invalidation_claim_keys
        )
        if not set(referenced).issubset(claim_keys):
            omissions.add("research_case.scenarios_invalid_or_incomplete")
            return None
    return ScenarioSet(
        upside=_scenario(draft.upside),
        base=_scenario(draft.base),
        downside=_scenario(draft.downside),
    )


def _scenario(scenario) -> ResearchScenario:
    return ResearchScenario(
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        research_implication=scenario.research_implication,
        condition_claim_keys=scenario.condition_claim_keys,
        trigger_claim_keys=scenario.trigger_claim_keys,
        invalidation_claim_keys=scenario.invalidation_claim_keys,
        confidence=scenario.confidence,
    )


def _build_review_items(
    registry: EvidenceRegistry,
    items: tuple,
    claim_keys: set[str],
    omissions: set[str],
) -> tuple[ReviewItem, ...]:
    review_items: list[ReviewItem] = []
    for draft in items:
        if not set(draft.claim_keys).issubset(claim_keys):
            omissions.add("research_case.review_item_omitted")
            continue
        evidence_ref_ids = tuple(
            ref.ref_id for ref in _resolved_evidence_refs(registry, draft.evidence_keys)
        )
        review_items.append(
            ReviewItem(
                item_id=draft.item_id,
                text=draft.text,
                claim_keys=draft.claim_keys,
                trigger_kind=draft.trigger_kind,
                trigger_value=draft.trigger_value,
                evidence_ref_ids=evidence_ref_ids,
            )
        )
    return tuple(review_items)


def _capability_status(
    registry: EvidenceRegistry, capability: str
) -> CapabilityStatus | None:
    refs = registry.get_coverage(capability)
    if not refs:
        return None
    ref = refs[0]
    completeness = ref.envelope.bundle_completeness
    if completeness == "complete":
        status = "ok"
    elif completeness == "unavailable":
        status = "unavailable"
    else:
        status = "degraded"
    return CapabilityStatus(
        capability=capability,
        status=status,
        coverage_ref_ids=(ref.coverage_ref_id,),
    )


def _build_analyst_cards(
    registry: EvidenceRegistry,
    fact_claims: tuple[PublicClaim, ...],
) -> tuple[AnalystCard, ...]:
    cards: list[AnalystCard] = []
    sentiment_caps = _sentiment_capabilities(registry)
    capability_by_lens = {
        "market": _LENS_CAPABILITIES["market"],
        "news": _LENS_CAPABILITIES["news"],
        "sentiment": sentiment_caps,
        "fundamentals": _LENS_CAPABILITIES["fundamentals"],
    }
    for lens in ("market", "fundamentals", "news", "sentiment"):
        lens_facts = [
            claim for claim in fact_claims if claim.claim_key.split(".", 1)[0] == lens
        ]
        finding_claim_keys = tuple(claim.claim_key for claim in lens_facts)
        availability = "ready" if finding_claim_keys else "unavailable"
        summary = (
            lens_facts[0].text if lens_facts else "该视角暂无已验证事实。"
        )
        confidence = (
            round(sum(claim.confidence for claim in lens_facts) / len(lens_facts), 4)
            if lens_facts
            else None
        )
        capability_statuses = tuple(
            status
            for capability in capability_by_lens[lens]
            if (status := _capability_status(registry, capability)) is not None
        )
        cards.append(
            AnalystCard(
                lens=lens,
                availability=availability,
                summary=summary,
                confidence=confidence,
                finding_claim_keys=finding_claim_keys,
                capability_statuses=capability_statuses,
            )
        )
    return tuple(cards)


def assemble_research_case(
    snapshot: RunSnapshot,
    *,
    draft: LearningResearchCaseDraft,
    registry: EvidenceRegistry,
    plan: DataWindowPlanV1,
    source_sequence: int,
    evidence_verdict: str,
) -> ResearchCaseV2:
    """Assemble a full/partial ResearchCaseV2 from an evidence-bound draft.

    Short ``evidence:`` / ``coverage:`` keys in the draft are resolved against
    the registry into real ``EvidenceRefV2`` / ``CoverageRefV1`` objects and
    ``source_dates`` are computed.  Claims that cannot be resolved, and
    scenarios/review items that reference dropped claims, are removed with a
    matching omission code; the assembler always returns a schema-valid case
    (or raises a ``ValidationError`` that the caller may fall back on).
    """
    verdict = _normalize_verdict(evidence_verdict)
    as_of = datetime.fromisoformat(snapshot.analysis_date).replace(tzinfo=timezone.utc)
    horizon = snapshot.horizon or "medium"

    omissions: set[str] = set()

    fact_claims, dropped_facts = _build_facts(registry, draft.facts, omissions)
    inference_claims = _build_inferences(
        registry, draft.inferences, fact_claims, omissions
    )
    unknown_claims = _build_unknowns(draft.unknowns)
    public_claims = fact_claims + inference_claims + unknown_claims
    claim_keys = {claim.claim_key for claim in public_claims}

    scenarios = _build_scenario_set(draft, claim_keys, omissions)

    catalysts = _build_review_items(
        registry, draft.catalysts, claim_keys, omissions
    )
    invalidation_conditions = _build_review_items(
        registry, draft.invalidation_conditions, claim_keys, omissions
    )
    review_items = catalysts + invalidation_conditions
    review_plan = ReviewPlan(
        next_review_at=None,
        item_ids=tuple(item.item_id for item in review_items),
        reason=draft.next_review,
    )

    analyst_cards = _build_analyst_cards(registry, fact_claims)

    # Collect all referenced evidence and coverage refs (dedup by id).
    evidence_by_id: dict[str, EvidenceRefV2] = {}
    coverage_by_id: dict[str, CoverageRefV1] = {}
    for claim in public_claims:
        for ref_id in claim.evidence_ref_ids:
            ref = registry.get_evidence(ref_id)
            if ref is not None:
                evidence_by_id.setdefault(ref_id, ref)
        for ref_id in claim.coverage_ref_ids:
            ref = next(
                (c for c in registry.coverage_refs if c.coverage_ref_id == ref_id),
                None,
            )
            if ref is not None:
                coverage_by_id.setdefault(ref_id, ref)
    for item in review_items:
        for ref_id in item.evidence_ref_ids:
            ref = registry.get_evidence(ref_id)
            if ref is not None:
                evidence_by_id.setdefault(ref_id, ref)
    for card in analyst_cards:
        for status in card.capability_statuses:
            for ref_id in status.coverage_ref_ids:
                ref = next(
                    (c for c in registry.coverage_refs if c.coverage_ref_id == ref_id),
                    None,
                )
                if ref is not None:
                    coverage_by_id.setdefault(ref_id, ref)

    evidence_refs = tuple(evidence_by_id.values())
    coverage_refs = tuple(coverage_by_id.values())

    used_optional_capabilities = tuple(
        capability.capability_id
        for capability in plan.capabilities
        if capability.requirement == "optional"
        and registry.get_coverage(capability.capability_id)
    )

    assessment = assess_decision_eligibility(
        plan=plan,
        evidence_verdict=verdict,
        claims=public_claims,
        analyst_cards=analyst_cards,
        coverage_refs=coverage_refs,
        conflicts=(),
        used_optional_capabilities=used_optional_capabilities,
    )
    decision_eligibility = assessment.decision_eligibility
    data_quality = assessment.data_quality

    if decision_eligibility == "none":
        research_rating = None
        rating_confidence = None
    else:
        research_rating = draft.research_tilt
        rating_confidence = draft.confidence

    availability = (
        "partial"
        if (omissions or scenarios is None or dropped_facts)
        else "full"
    )

    return ResearchCaseV2(
        run_id=snapshot.run_id,
        ticker=snapshot.ticker,
        horizon=horizon,
        source_sequence=source_sequence,
        as_of=as_of,
        availability=availability,
        decision_eligibility=decision_eligibility,
        evidence_verdict=verdict,
        research_rating=research_rating,
        rating_confidence=rating_confidence,
        claims=public_claims,
        scenarios=scenarios,
        catalysts=catalysts,
        invalidation_conditions=invalidation_conditions,
        review_plan=review_plan,
        analyst_cards=analyst_cards,
        debate_digest=None,
        data_quality=data_quality,
        evidence_refs=evidence_refs,
        coverage_refs=coverage_refs,
        audit_refs=(),
        omissions=tuple(sorted(omissions)),
    )
