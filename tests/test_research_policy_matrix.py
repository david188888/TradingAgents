from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.agents.schemas import AnalystCard, CoverageRefV1, PublicClaim
from tradingagents.agents.utils import market_data_validation_tools, news_data_tools
from tradingagents.dataflows.capability_result import CapabilityResultV1
from tradingagents.dataflows.coverage import BundleCoverageV1, CoveredText, SourceCoverageV1
from tradingagents.dataflows.routing_trace import RouteAttemptTrace, RoutedVendorCall
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
from tradingagents.research.claim_registry import available_candidate_keys
from tradingagents.research.eligibility import assess_decision_eligibility
from tradingagents.research.horizon_policy import build_data_window_plan
from tradingagents.research.official_disclosures import build_official_disclosure_result
from tradingagents.research.policy_closure import CAPABILITY_PIPELINES

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _source_coverage(capability: str, source: str, start: str, end: str):
    return SourceCoverageV1(
        capability=capability,
        source_id=source,
        requested_start=start,
        requested_end=end,
        actual_start=start,
        actual_end=end,
        item_count=3,
        page_count=1,
        pagination_exhausted=True,
        completeness="complete",
        sources=(source,),
        as_of=end,
    )


def test_price_prefetch_produces_identity_snapshot_and_adjusted_results(monkeypatch):
    coverage = _source_coverage(
        "adjusted_price_history",
        "yfinance.adjusted_ohlcv",
        "2025-08-13",
        "2026-08-13",
    )
    attempt = RouteAttemptTrace(
        vendor="yfinance",
        outcome="observed",
        reason_code="provider_payload_observed",
        recorded_at=NOW,
        started_at=NOW,
        ended_at=NOW,
    )
    monkeypatch.setattr(
        market_data_validation_tools,
        "route_to_vendor_with_trace",
        lambda *_args, **_kwargs: RoutedVendorCall(
            CoveredText("adjusted rows", coverage), None, (attempt,)
        ),
    )
    monkeypatch.setattr(
        market_data_validation_tools,
        "route_to_vendor",
        lambda *_args, **_kwargs: "raw audit rows",
    )
    monkeypatch.setattr(
        market_data_validation_tools,
        "get_verified_current_quote",
        lambda *_args, **_kwargs: SimpleNamespace(
            close=210.0,
            observed_on="2026-08-13",
            source_id="yfinance.ohlcv",
        ),
    )
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )

    bundle = __import__("json").loads(
        market_data_validation_tools.run_adjusted_price_prefetch(
            "AAPL",
            "2026-08-13",
            horizon="short",
            analysis_cutoff=cutoff,
        )
    )

    results = {item["capability"]: item["capability_result"] for item in bundle["results"]}
    assert set(results) == {
        "verified_identity",
        "verified_market_snapshot",
        "adjusted_price_history",
    }
    assert all(item["availability"] == "available" for item in results.values())


def test_news_prefetch_produces_company_event_and_official_results(monkeypatch):
    def route(method, *args, **_kwargs):
        if method == "get_news":
            coverage = _source_coverage(
                "company_news", "yfinance.company_news", args[1], args[2]
            )
            return CoveredText("company event", coverage)
        return "unused"

    monkeypatch.setattr(news_data_tools, "route_to_vendor", route)
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )

    bundle = __import__("json").loads(
        news_data_tools.run_news_windows(
            "AAPL",
            "2026-08-13",
            horizon="short",
            analysis_cutoff=cutoff,
        )
    )

    results = {item["capability"]: item["capability_result"] for item in bundle["results"]}
    assert results["company_event_window"]["availability"] == "available"
    assert results["official_disclosures"]["availability"] == "not_supported"


@pytest.mark.parametrize("market", ["a_share", "global"])
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_six_cell_required_policy_has_closed_typed_pipeline(market, horizon):
    plan = build_data_window_plan(horizon, "2026-08-13", market=market)
    required = {
        capability.capability_id
        for capability in plan.capabilities
        if capability.requirement == "required"
    }

    assert required <= set(CAPABILITY_PIPELINES)
    assert all(CAPABILITY_PIPELINES[item].typed_result for item in required)


def test_complete_coverage_without_typed_result_cannot_reach_full():
    plan = build_data_window_plan("short", "2026-08-13", market="global")
    claims, cards = _claims_and_cards(("market", "news"))
    coverage = tuple(
        _complete_coverage(item.capability_id)
        for item in plan.capabilities
        if item.requirement == "required"
    )

    assessment = assess_decision_eligibility(
        plan=plan,
        evidence_verdict="PASS",
        claims=claims,
        analyst_cards=cards,
        coverage_refs=coverage,
    )

    assert assessment.decision_eligibility == "limited"
    assert "required_capability_result_missing" in assessment.reason_codes


def test_candidate_keys_expose_only_available_typed_capabilities():
    quarterly = _typed_available(_complete_coverage("fundamentals_quarterly"))
    events = _typed_available(_complete_coverage("company_event_window"))
    state = {
        "fundamentals_prefetch_bundle": {
            "results": [
                {
                    "capability": quarterly.capability,
                    "capability_result_id": quarterly.capability_result_id,
                    "capability_result": quarterly.semantic_payload(),
                },
                {
                    "capability_result": {
                        "capability": "fundamentals_annual",
                        "availability": "provider_unavailable",
                    }
                },
            ]
        },
        "news_window_bundle": {
            "results": [
                {
                    "capability": events.capability,
                    "capability_result_id": events.capability_result_id,
                    "capability_result": events.semantic_payload(),
                },
                {
                    "capability_result": {
                        "capability": "official_disclosures",
                        "availability": "not_supported",
                    }
                },
            ]
        },
    }

    candidates = available_candidate_keys(state)

    assert "coverage:fundamentals_quarterly" in candidates["coverage"]
    assert "coverage:fundamentals_annual" not in candidates["coverage"]
    assert "coverage:company_event_window" in candidates["coverage"]
    assert "coverage:official_disclosures" not in candidates["coverage"]
    assert "evidence:fundamentals_bundle" in candidates["evidence"]


def test_candidate_keys_do_not_revive_unavailable_typed_legacy_bundle():
    state = {
        "adjusted_price_bundle": {
            "results": [
                {
                    "capability_result": {
                        "capability": "adjusted_price_history",
                        "availability": "invalid",
                    }
                }
            ]
        },
        "news_window_bundle": {
            "results": [
                {
                    "capability_result": {
                        "capability": "company_event_window",
                        "availability": "provider_unavailable",
                    }
                }
            ]
        },
    }

    assert available_candidate_keys(state) == {"coverage": [], "evidence": []}


def _complete_coverage(capability: str) -> CoverageRefV1:
    source = f"fixture.{capability}"
    record = _source_coverage(capability, source, "2026-01-01", "2026-08-13")
    return CoverageRefV1(
        coverage_ref_id=f"coverage_{capability}",
        capability=capability,
        envelope=BundleCoverageV1.build(
            capability=capability,
            records=(record,),
            required_source_ids=(source,),
            optional_source_ids=(),
        ),
    )


def _claims_and_cards(
    lenses, *, fundamentals_capability="fundamentals_quarterly"
):
    capability_by_lens = {
        "market": "adjusted_price_history",
        "fundamentals": fundamentals_capability,
        "news": "company_event_window",
        "sentiment": "capital_flow",
    }
    claims = tuple(
        PublicClaim(
            claim_key=f"{lens}.growth_quality.company.stable",
            claim_type="fact",
            text=f"{lens} fact",
            evidence_ref_ids=(f"evidence_{lens}",),
            source_dates=(NOW,),
            coverage_ref_ids=(f"coverage_{capability_by_lens[lens]}",),
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


@pytest.mark.parametrize("market", ["a_share", "global"])
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_six_cell_eligibility_expectation(market, horizon):
    plan = build_data_window_plan(horizon, "2026-08-13", market=market)
    lenses = ("market", "news") if horizon == "short" else ("market", "fundamentals", "news")
    claims, cards = _claims_and_cards(
        lenses,
        fundamentals_capability=(
            "fundamentals_annual" if horizon == "long" else "fundamentals_quarterly"
        ),
    )
    coverage = tuple(
        _complete_coverage(capability.capability_id)
        for capability in plan.capabilities
        if capability.requirement == "required"
    )
    typed = tuple(_typed_available(item, market=market) for item in coverage)
    if market == "global" and horizon in {"medium", "long"}:
        cutoff = resolve_analysis_cutoff(
            "AAPL", "2026-08-13", identity={"exchange": "NMS"}
        )
        wrapped = build_official_disclosure_result(
            "AAPL", "2026-08-13", horizon=horizon, cutoff=cutoff, recorded_at=NOW
        )
        official = CapabilityResultV1.model_validate(wrapped["capability_result"])
        coverage = tuple(
            item
            for item in coverage
            if item.capability != "official_disclosures"
        ) + (
            CoverageRefV1(
                coverage_ref_id="coverage_official_unavailable",
                capability="official_disclosures",
                envelope=official.coverage,
            ),
        )
        typed = tuple(
            item
            for item in typed
            if item.capability != "official_disclosures"
        ) + (official,)

    assessment = assess_decision_eligibility(
        plan=plan,
        evidence_verdict="PASS",
        claims=claims,
        analyst_cards=cards,
        coverage_refs=coverage,
        capability_results=typed,
    )

    if market == "global" and horizon in {"medium", "long"}:
        assert assessment.decision_eligibility == "limited"
        assert assessment.forced_research_rating == "insufficient_evidence"
    else:
        assert assessment.decision_eligibility == "full"
        assert assessment.forced_research_rating is None


def _typed_available(
    ref: CoverageRefV1, *, market: str = "a_share"
) -> CapabilityResultV1:
    attempts = tuple(
        {
            "source_id": record.source_id,
            "provider": record.source_id.split(".", 1)[0],
            "outcome": "observed",
            "reason_code": "provider_payload_observed",
            "recorded_at": NOW,
            "started_at": NOW,
            "ended_at": NOW,
        }
        for record in ref.envelope.records
    )
    return CapabilityResultV1(
        capability=ref.capability,
        symbol="fixture",
        market=market,
        analysis_date="2026-08-13",
        analysis_cutoff_at=NOW,
        availability="available",
        freshness="current",
        coverage=ref.envelope,
        source_ids=tuple(record.source_id for record in ref.envelope.records),
        attempts=attempts,
        fetched_at=NOW,
    )
