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


def assemble_fail_stop_research_case(
    snapshot: RunSnapshot,
    *,
    source_sequence: int,
    reason_code: str,
) -> ResearchCaseV2:
    """Publish a safe shell when attribution or temporal integrity is unsafe."""

    result = assemble_partial_research_case(
        snapshot,
        source_sequence=source_sequence,
        evidence_verdict="FAIL_STOP",
    )
    return result.model_copy(
        update={
            "omissions": tuple(
                sorted(set(result.omissions) | {f"research_integrity.{reason_code}"})
            )
        }
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
from tradingagents.research.claim_capability_policy import (  # noqa: E402
    LENS_CAPABILITIES,
    capabilities_for_lens,
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
def _sentiment_capabilities(registry: EvidenceRegistry) -> tuple[str, ...]:
    """Return supplement coverage capabilities attributed to the sentiment lens.

    Deterministic first-version approximation: every coverage capability the
    registry carries that is not one of the fixed price/event capabilities is
    treated as sentiment-relevant (A-share supplement output such as capital
    flow or northbound flow).
    """
    return tuple(
        sorted(
            capabilities_for_lens(
                "sentiment", registry.coverage_by_capability
            )
        )
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

        lens = draft.claim_key.split(".", 1)[0]
        allowed_capabilities = capabilities_for_lens(
            lens, registry.coverage_by_capability
        )
        coverage_matches_lens = bool(coverage_refs) and all(
            ref.capability in allowed_capabilities for ref in coverage_refs
        )
        if not coverage_matches_lens:
            omissions.add("research_case.claim_omitted_capability_lens_mismatch")

        source_dates = _evidence_source_dates(evidence_refs)
        evidence_ref_ids = tuple(ref.ref_id for ref in evidence_refs)
        coverage_ref_ids = tuple(ref.coverage_ref_id for ref in coverage_refs)
        if (
            not evidence_ref_ids
            or not source_dates
            or not coverage_ref_ids
            or not coverage_matches_lens
        ):
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
        "market": tuple(sorted(LENS_CAPABILITIES["market"])),
        "news": tuple(sorted(LENS_CAPABILITIES["news"])),
        "sentiment": sentiment_caps,
        "fundamentals": tuple(sorted(LENS_CAPABILITIES["fundamentals"])),
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
    for capability in plan.capabilities:
        for ref in registry.get_coverage(capability.capability_id):
            coverage_by_id.setdefault(ref.coverage_ref_id, ref)

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
        capability_results=tuple(
            result
            for capability in plan.capabilities
            for result in registry.get_capability_results(capability.capability_id)
        ),
        conflicts=(),
        used_optional_capabilities=used_optional_capabilities,
    )
    decision_eligibility = assessment.decision_eligibility
    data_quality = assessment.data_quality

    generated_unknowns = tuple(
        _missing_capability_unknown(action)
        for action in assessment.missing_capability_actions
        if _missing_capability_claim_key(action.capability) not in claim_keys
    )
    public_claims += generated_unknowns
    claim_keys.update(claim.claim_key for claim in generated_unknowns)
    existing_review_ids = {item.item_id for item in review_items}
    generated_reviews = tuple(
        _missing_capability_review(action)
        for action in assessment.missing_capability_actions
        if f"verify_{action.capability}" not in existing_review_ids
    )
    review_items += generated_reviews
    catalysts += generated_reviews
    if generated_reviews:
        review_plan = ReviewPlan(
            next_review_at=None,
            item_ids=tuple(item.item_id for item in review_items),
            reason=draft.next_review,
        )

    if decision_eligibility == "none":
        research_rating = None
        rating_confidence = None
    else:
        research_rating = assessment.forced_research_rating or draft.research_tilt
        rating_confidence = draft.confidence

    availability = (
        "partial"
        if (
            omissions
            or scenarios is None
            or dropped_facts
            or assessment.missing_capability_actions
        )
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


def _missing_capability_claim_key(capability: str) -> str:
    lens = (
        "news"
        if capability == "official_disclosures"
        else "fundamentals"
        if capability.startswith("fundamentals_")
        else "market"
    )
    topic = (
        "governance_risk"
        if capability == "official_disclosures"
        else "growth_quality"
        if capability.startswith("fundamentals_")
        else "market_trend"
    )
    return f"{lens}.{topic}.{capability}.uncertain"


def _missing_capability_unknown(action) -> PublicClaim:
    return PublicClaim(
        claim_key=_missing_capability_claim_key(action.capability),
        claim_type="unknown",
        text=(
            f"Required capability {action.capability} is unavailable "
            f"({action.reason_code}); no substantive conclusion is inferred from it."
        ),
        action_impact="limits",
        required_evidence=(action.required_evidence,),
        review_trigger=action.review_trigger,
    )


def _missing_capability_review(action) -> ReviewItem:
    return ReviewItem(
        item_id=f"verify_{action.capability}",
        text=f"Recheck {action.capability} after resolving {action.reason_code}.",
        claim_keys=(_missing_capability_claim_key(action.capability),),
        trigger_kind="filing",
        trigger_value=action.review_trigger,
    )


# ---------------------------------------------------------------------------
# Catalyst profile assembly
# ---------------------------------------------------------------------------
#
# ``catalyst-research-case-v1`` is a separate contract from ``ResearchCaseV2``
# and is assembled here rather than by loosening the older model's lens and
# scenario requirements. The functions below are the deterministic half of
# design section 9.1: they compute the research priority ceiling from
# committed facts, so a synthesis model's proposal is bounded by code and
# never by a prompt.

from tradingagents.agents.schemas import (  # noqa: E402
    PRIORITY_BLOCKING_REASONS,
    SAFETY_OVERFLOW_PRIORITY,
    SAFETY_OVERFLOW_REASON,
    BriefLine,
    BudgetUsage,
    CatalystBrief,
    CatalystResearchCase,
    Challenge,
    ChallengeDisposition,
    ResearchPriority,
    ResearchPriorityDecision,
    SpecialistFinding,
    brief_character_count,
)

CATALYST_EVIDENCE_POLICY = "catalyst-evidence-policy-v1"

# Conditions design section 9.1 caps at information-insufficient regardless of
# which matrix row they appear in. Ordered most severe first: the caller
# collects all that apply and the ceiling takes the strictest outcome.
_CATALYST_INSUFFICIENT_REASONS = (
    "hard_error",
    "identity_conflict",
    "required_source_unqualified",
    "observation_window_unqualified",
    "required_capability_unavailable",
    "required_coverage_insufficient",
    "pit_unverified",
    "required_specialist_failed",
    "refutation_stage_missing",
    "synthesis_failed",
    "key_challenge_unresolved",
    SAFETY_OVERFLOW_REASON,
)

# Integrity conditions that force information-insufficient outright, even when
# the case is otherwise complete: the run's facts about the security itself
# cannot be trusted.
_CATALYST_INTEGRITY_REASONS = frozenset(
    {"hard_error", "identity_conflict", "required_source_unqualified"}
)


def collect_catalyst_blocking_reasons(
    *,
    findings: tuple[SpecialistFinding, ...],
    challenges: tuple[Challenge, ...],
    dispositions: tuple[ChallengeDisposition, ...],
    completeness: str,
    run_reason_codes: tuple[str, ...] = (),
    brief: CatalystBrief | None = None,
) -> tuple[str, ...]:
    """Return every code-visible condition that caps the research priority.

    Deliberately conservative: a condition that might apply is reported and
    the ceiling moves down. An over-restrictive ceiling costs the reader a
    stronger category on a run that might have earned it; an
    under-restrictive one publishes "verify first" on a run that cannot
    support it, which the design treats as unpublishable.
    """
    reasons: list[str] = list(run_reason_codes)
    surviving = {finding.finding_id for finding in findings if finding.survives}
    by_challenge = {challenge.challenge_id: challenge for challenge in challenges}
    for disposition in dispositions:
        challenge = by_challenge.get(disposition.challenge_id)
        if challenge is None:
            continue
        # A challenge whose targets were all removed no longer constrains
        # anything, so it must not cap the priority forever.
        if not set(challenge.target_finding_ids) & surviving:
            continue
        if challenge.is_key and disposition.outcome == "unresolved":
            reasons.append("key_challenge_unresolved")
    if completeness != "complete" and not reasons:
        # A non-complete case with no recorded cause still may not claim the
        # top category: something reduced the result and the cause is missing.
        reasons.append("required_coverage_insufficient")
    if brief is not None and brief.kind == "safety_overflow":
        reasons.append(SAFETY_OVERFLOW_REASON)
    wanted = set(reasons)
    ordered = [code for code in _CATALYST_INSUFFICIENT_REASONS if code in wanted]
    return tuple(ordered + sorted(wanted - set(ordered)))


def decide_catalyst_priority(
    *,
    candidate: ResearchPriority,
    rationale: str,
    blocking_reasons: tuple[str, ...],
) -> ResearchPriorityDecision:
    """Apply the deterministic ceiling to a synthesis model's candidate.

    Both values are retained so a reader can tell a capped result from a
    genuinely lower one: that is the difference between "the evidence did not
    support it" and "the process could not verify it".
    """
    caps_top = any(code in PRIORITY_BLOCKING_REASONS for code in blocking_reasons)
    if caps_top or (candidate == "verify_first" and blocking_reasons):
        published: ResearchPriority = SAFETY_OVERFLOW_PRIORITY
    else:
        published = candidate
    return ResearchPriorityDecision(
        priority=published,
        candidate_priority=candidate,
        proposed_by="synthesis" if published == candidate else "code",
        blocking_reasons=blocking_reasons,
        rationale=rationale,
    )


def build_catalyst_brief(
    *,
    judgement: str,
    priority: ResearchPriority,
    primary_catalyst_event_id: str | None,
    primary_catalyst_text: str | None,
    key_evidence: tuple[BriefLine, ...],
    key_question: BriefLine,
    next_check: BriefLine,
    critical_limitations: tuple[BriefLine, ...],
) -> CatalystBrief:
    """Build the first-screen brief, degrading to the overflow template.

    Overflow is not a repair loop. If the ordinary brief does not fit, the
    answer is the safety template plus the full limitation list -- never a
    truncated brief, and never a shorter list of risks. The limitation list is
    exempt from the template's own budget for exactly this reason: it is the
    payload the reader needs.

    ``CatalystBrief`` raises when the ordinary shape overflows, so this
    catches that one failure and re-publishes. Any other construction error
    propagates: silently swapping a malformed brief for the template would
    hide a real defect behind a valid-looking response.
    """
    try:
        return CatalystBrief(
            kind="ordinary",
            judgement=judgement,
            priority=priority,
            primary_catalyst_event_id=primary_catalyst_event_id,
            primary_catalyst=(
                BriefLine(
                    text=primary_catalyst_text,
                    event_ids=(primary_catalyst_event_id,),
                )
                if primary_catalyst_event_id is not None and primary_catalyst_text
                else None
            ),
            key_evidence=key_evidence,
            key_question=key_question,
            next_check=next_check,
            critical_limitations=critical_limitations,
        )
    except ValueError as exc:
        if "character budget" not in str(exc):
            raise
        return build_safety_overflow_brief(limitations=critical_limitations)


# The code template. Fixed text, not a model output: this result exists
# precisely because the budget could not be met, so asking a model for
# shorter words would be both unbounded and unreliable.
SAFETY_OVERFLOW_JUDGEMENT = "本次信息限制较多，暂不能形成可靠的简短判断。"
SAFETY_OVERFLOW_QUESTION = "本次覆盖窗口内存在未解决的重大反证或关键资料缺口。"
SAFETY_OVERFLOW_NEXT_CHECK = "请以新的 run 补做缺失来源后重新判断。"


def build_safety_overflow_brief(*, limitations: tuple[BriefLine, ...]) -> CatalystBrief:
    """Emit the design section 4.3 overflow result.

    The limitation list must be non-empty. A caller with nothing to show is
    not in the situation the rule describes, and an empty list would let a
    real overflow pass as a legitimate short result.
    """
    if not limitations:
        raise ValueError("the safety-overflow brief requires a limitation list")
    return CatalystBrief(
        kind="safety_overflow",
        judgement=SAFETY_OVERFLOW_JUDGEMENT,
        priority=SAFETY_OVERFLOW_PRIORITY,
        key_question=BriefLine(text=SAFETY_OVERFLOW_QUESTION),
        next_check=BriefLine(text=SAFETY_OVERFLOW_NEXT_CHECK),
        overflow_reason=SAFETY_OVERFLOW_REASON,
        critical_limitations=limitations,
    )


def assemble_blocked_catalyst_case(
    *,
    run_id: str,
    ticker: str,
    as_of: datetime,
    source_sequence: int,
    reason_codes: tuple[str, ...],
    findings: tuple[SpecialistFinding, ...] = (),
    challenges: tuple[Challenge, ...] = (),
    dispositions: tuple[ChallengeDisposition, ...] = (),
    budget_usage: BudgetUsage | None = None,
    research_question: str | None = None,
) -> CatalystResearchCase:
    """Publish the safe shell for a run that must not form a research view.

    Same rule as ``assemble_fail_stop_research_case`` on the classic path: a
    run that cannot be trusted still gets a truthful, publishable artifact,
    so the reader sees "insufficient information" with its cause rather than
    an empty page or a stale earlier result.
    """
    limitations = tuple(BriefLine(text=code) for code in reason_codes) or (
        BriefLine(text=SAFETY_OVERFLOW_QUESTION),
    )
    decision = decide_catalyst_priority(
        candidate="verify_first",
        rationale="A blocking integrity condition forbids any directional research view.",
        blocking_reasons=tuple(
            code for code in reason_codes if code in _CATALYST_INTEGRITY_REASONS
        ),
    )
    return CatalystResearchCase(
        run_id=run_id,
        ticker=ticker,
        evidence_policy=CATALYST_EVIDENCE_POLICY,
        as_of=as_of,
        source_sequence=source_sequence,
        completeness="blocked",
        quality="FAIL_STOP",
        reason_codes=tuple(reason_codes),
        research_question=research_question,
        findings=findings,
        challenges=challenges,
        dispositions=dispositions,
        priority_decision=decision,
        brief=build_safety_overflow_brief(limitations=limitations),
        budget_usage=budget_usage
        or BudgetUsage(
            model_attempts=0,
            structured_output_repairs=0,
            network_retries=0,
            data_capability_calls=0,
            http_attempts=0,
            semantic_preprocess_calls=0,
            model_usage_available=False,
        ),
    )


def build_markdown_from_case(case: CatalystResearchCase) -> str:
    """Render the report from the same case, never from a second model call.

    First screen, detail, and Markdown all read this one object, so a claim
    cannot read differently in the report than in the brief the reader
    judged. Design section 5.2: synthesis writes one structured brief and the
    report is a projection of it.
    """
    brief = case.brief
    lines: list[str] = [f"# {case.ticker} 催化研究简报", ""]
    lines.append(f"研究优先级：{case.priority_decision.priority}")
    lines.append(f"完成程度：{case.completeness} / 质量：{case.quality}")
    lines.append("")
    lines.append(f"## 研究判断\n\n{brief.judgement}")
    if brief.primary_catalyst is not None:
        lines.append(f"\n## 关键催化\n\n{brief.primary_catalyst.text}")
    if brief.key_evidence:
        lines.append("\n## 关键依据")
        lines.extend(f"- {line.text}" for line in brief.key_evidence)
    lines.append(f"\n## 最大疑点\n\n{brief.key_question.text}")
    lines.append(f"\n## 下一步验证\n\n{brief.next_check.text}")
    if brief.critical_limitations:
        lines.append("\n## 影响判断的限制")
        lines.extend(f"- {line.text}" for line in brief.critical_limitations)
    if case.challenges:
        lines.append("\n## 反证处理")
        by_id = {item.challenge_id: item for item in case.dispositions}
        for challenge in case.challenges:
            disposition = by_id[challenge.challenge_id]
            lines.append(
                f"- [{disposition.outcome}] {challenge.statement} "
                f"（严重性 {challenge.severity}，验证方式：{challenge.test_method}）"
            )
    lines.append("")
    lines.append(
        f"<!-- {case.schema_version} brief_characters={brief_character_count(brief)} -->"
    )
    return "\n".join(lines)
