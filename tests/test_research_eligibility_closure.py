from __future__ import annotations

from datetime import datetime, timezone

from tradingagents.agents.schemas import (
    AnalystCard,
    CoverageRefV1,
    EvidenceRefV2,
    LearningResearchCaseDraft,
    PublicClaim,
)
from tradingagents.dataflows.capability_result import CapabilityResultV1
from tradingagents.dataflows.coverage import BundleCoverageV1, SourceCoverageV1
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
from tradingagents.research.case_assembly import assemble_research_case
from tradingagents.research.eligibility import assess_decision_eligibility
from tradingagents.research.evidence_registry import EvidenceRegistry
from tradingagents.research.horizon_policy import build_data_window_plan
from tradingagents.research.official_disclosures import (
    build_official_disclosure_result,
)
from tradingagents.runtime.run_models import RunSnapshot

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _coverage(capability: str, *, complete: bool = True) -> CoverageRefV1:
    source = f"test.{capability}"
    record = SourceCoverageV1(
        capability=capability,
        source_id=source,
        requested_start="2026-01-01",
        requested_end="2026-08-13",
        actual_start="2026-01-01" if complete else None,
        actual_end="2026-08-13" if complete else None,
        item_count=1 if complete else 0,
        completeness="complete" if complete else "unavailable",
        sources=(source,),
        degradations=() if complete else ("test_unavailable",),
        as_of="2026-08-13",
    )
    envelope = BundleCoverageV1.build(
        capability=capability,
        records=(record,),
        required_source_ids=(source,),
        optional_source_ids=(),
    )
    return CoverageRefV1(
        coverage_ref_id=f"coverage_{capability}",
        capability=capability,
        envelope=envelope,
    )


def _facts_and_cards(lenses: tuple[str, ...]):
    claims = tuple(
        PublicClaim(
            claim_key=f"{lens}.growth_quality.company.stable",
            claim_type="fact",
            text=f"Verified {lens} fact",
            evidence_ref_ids=(f"evidence_{lens}",),
            source_dates=(NOW,),
            coverage_ref_ids=(f"coverage_{lens}",),
            confidence=0.7,
            action_impact="neutral",
        )
        for lens in lenses
    )
    cards = tuple(
        AnalystCard(
            lens=lens,
            availability="ready",
            summary=f"{lens} ready",
            confidence=0.7,
            finding_claim_keys=(f"{lens}.growth_quality.company.stable",),
        )
        for lens in lenses
    )
    return claims, cards


def _global_official(horizon: str) -> CapabilityResultV1:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )
    wrapped = build_official_disclosure_result(
        "AAPL",
        "2026-08-13",
        horizon=horizon,
        cutoff=cutoff,
        recorded_at=NOW,
    )
    return CapabilityResultV1.model_validate(wrapped["capability_result"])


def test_required_global_sec_gap_forces_insufficient_evidence() -> None:
    plan = build_data_window_plan("medium", "2026-08-13", market="global")
    claims, cards = _facts_and_cards(("market", "fundamentals", "news"))
    coverage = tuple(
        _coverage(capability.capability_id, complete=capability.capability_id != "official_disclosures")
        for capability in plan.capabilities
        if capability.requirement == "required"
    )

    assessment = assess_decision_eligibility(
        plan=plan,
        evidence_verdict="PASS",
        claims=claims,
        analyst_cards=cards,
        coverage_refs=coverage,
        capability_results=(_global_official("medium"),),
    )

    assert assessment.decision_eligibility == "limited"
    assert assessment.forced_research_rating == "insufficient_evidence"
    assert assessment.missing_capability_actions[0].capability == (
        "official_disclosures"
    )


def test_optional_short_official_gap_does_not_force_rating() -> None:
    plan = build_data_window_plan("short", "2026-08-13", market="global")
    claims, cards = _facts_and_cards(("market", "news"))
    coverage = tuple(
        _coverage(capability.capability_id)
        for capability in plan.capabilities
        if capability.requirement == "required"
    )

    assessment = assess_decision_eligibility(
        plan=plan,
        evidence_verdict="PASS",
        claims=claims,
        analyst_cards=cards,
        coverage_refs=coverage,
        capability_results=(_global_official("short"),),
    )

    assert assessment.decision_eligibility == "full"
    assert assessment.forced_research_rating is None
    assert assessment.missing_capability_actions == ()


def test_case_assembly_overrides_model_rating_and_adds_review_action() -> None:
    plan = build_data_window_plan("medium", "2026-08-13", market="global")
    coverage = tuple(
        _coverage(
            capability.capability_id,
            complete=capability.capability_id != "official_disclosures",
        )
        for capability in plan.capabilities
        if capability.requirement == "required"
    )
    evidence = {
        lens: EvidenceRefV2(
            ref_id=(str(index) * 64),
            run_id="run_20260813T080000000000Z_1234abcd",
            artifact_id=f"evidence-bundle:{str(index) * 64}",
            media_type="application/json",
            locator=f"evidence/{lens}.json",
            source_observed_at=NOW,
            captured_at=NOW,
            resolution_status="available",
        )
        for index, lens in enumerate(("market", "fundamentals", "news"), start=1)
    }
    coverage_by_capability = {item.capability: (item,) for item in coverage}
    official = _global_official("medium")
    registry = EvidenceRegistry(
        evidence_refs=tuple(evidence.values()),
        coverage_refs=coverage,
        by_ref_id={item.ref_id: item for item in evidence.values()},
        by_artifact_id={item.artifact_id: (item,) for item in evidence.values()},
        coverage_by_capability=coverage_by_capability,
        capability_results_by_capability={"official_disclosures": (official,)},
        evidence_by_state_key={
            "adjusted_price_bundle": evidence["market"],
            "fundamentals_prefetch_bundle": evidence["fundamentals"],
            "news_window_bundle": evidence["news"],
        },
    )
    facts = [
        {
            "claim_key": f"{lens}.growth_quality.company.stable",
            "claim_type": "fact",
            "text": f"Verified {lens} fact",
            "evidence_keys": (f"evidence:{evidence_key}",),
            "coverage_keys": (f"coverage:{capability}",),
            "confidence": 0.7,
            "action_impact": "neutral",
        }
        for lens, evidence_key, capability in (
            ("market", "price_bundle", "adjusted_price_history"),
            ("fundamentals", "fundamentals_bundle", "fundamentals_quarterly"),
            ("news", "news_bundle", "company_event_window"),
        )
    ]
    keys = tuple(item["claim_key"] for item in facts)
    draft = LearningResearchCaseDraft.model_validate(
        {
            "research_tilt": "favorable",
            "confidence": 0.9,
            "facts": facts,
            "upside": {
                "scenario_id": "upside",
                "title": "Upside",
                "research_implication": "Upside implication",
                "condition_claim_keys": keys,
                "trigger_claim_keys": (keys[0],),
                "confidence": 0.6,
            },
            "base": {
                "scenario_id": "base",
                "title": "Base",
                "research_implication": "Base implication",
                "condition_claim_keys": keys,
                "confidence": 0.7,
            },
            "downside": {
                "scenario_id": "downside",
                "title": "Downside",
                "research_implication": "Downside implication",
                "condition_claim_keys": keys,
                "invalidation_claim_keys": (keys[1],),
                "confidence": 0.5,
            },
            "next_review": "Review when official filing data becomes available.",
        }
    )
    snapshot = RunSnapshot.create(
        run_id="run_20260813T080000000000Z_1234abcd",
        ticker="AAPL",
        analysis_date="2026-08-13",
        horizon="medium",
    )

    case = assemble_research_case(
        snapshot,
        draft=draft,
        registry=registry,
        plan=plan,
        source_sequence=10,
        evidence_verdict="PASS",
    )

    assert case.decision_eligibility == "limited"
    assert case.research_rating == "insufficient_evidence"
    assert any(
        claim.claim_key == "news.governance_risk.official_disclosures.uncertain"
        for claim in case.claims
    )
    assert any(item.item_id == "verify_official_disclosures" for item in case.catalysts)
