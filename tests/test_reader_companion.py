"""Public Companion selection and recursive Reader privacy contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tradingagents.agents.schemas._research_case import (
    AnalystCard,
    CapabilityStatus,
    CoverageRefV1,
    DataQuality,
    EvidenceRefV2,
    PublicClaim,
    ResearchCaseV2,
    ReviewItem,
)
from tradingagents.dataflows.coverage import BundleCoverageV1, SourceCoverageV1
from tradingagents.observability.events import RunEventDraft
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.reader_models import CompanionSelection

AS_OF = datetime(2026, 8, 10, tzinfo=timezone.utc)
FACT_KEY = "market.price.trend.primary"
INFERENCE_KEY = "fundamentals.margin.outlook.primary"
UNKNOWN_KEY = "news.demand.outlook.primary"
RISK_ID = "margin_break"


def _coverage() -> CoverageRefV1:
    capability = "market.price"
    source = SourceCoverageV1(
        capability=capability,
        source_id="public_market_source",
        requested_start="2026-07-10",
        requested_end="2026-08-10",
        actual_start="2026-07-10",
        actual_end="2026-08-10",
        item_count=22,
        completeness="complete",
        sources=("public_market_source",),
        as_of="2026-08-10",
    )
    return CoverageRefV1(
        coverage_ref_id="coverage.market_price",
        capability=capability,
        envelope=BundleCoverageV1.build(
            capability=capability,
            records=(source,),
            required_source_ids=(source.source_id,),
            optional_source_ids=(),
        ),
    )


def _case(
    run_id: str,
    *,
    evidence_artifact_id: str,
    evidence_locator: str,
    available_ref_id: str,
    unavailable_artifact_id: str,
    unavailable_locator: str,
    unavailable_ref_id: str,
) -> ResearchCaseV2:
    coverage = _coverage()
    evidence = EvidenceRefV2(
        ref_id=available_ref_id,
        run_id=run_id,
        artifact_id=evidence_artifact_id,
        media_type="application/json",
        locator=evidence_locator,
        source_observed_at=AS_OF,
        captured_at=AS_OF,
        resolution_status="available",
    )
    unavailable = EvidenceRefV2(
        ref_id=unavailable_ref_id,
        run_id=run_id,
        artifact_id=unavailable_artifact_id,
        media_type="application/json",
        locator=unavailable_locator,
        captured_at=AS_OF,
        resolution_status="unavailable",
    )
    fact = PublicClaim(
        claim_key=FACT_KEY,
        claim_type="fact",
        text="价格趋势在实际覆盖窗口内改善。",
        evidence_ref_ids=(available_ref_id,),
        source_dates=(AS_OF,),
        coverage_ref_ids=(coverage.coverage_ref_id,),
        confidence=0.78,
        action_impact="supports",
    )
    inference = PublicClaim(
        claim_key=INFERENCE_KEY,
        claim_type="inference",
        text="利润率改善仍受需求验证约束。",
        evidence_ref_ids=(available_ref_id,),
        source_dates=(AS_OF,),
        supporting_claim_keys=(FACT_KEY,),
        confidence=0.64,
        action_impact="limits",
    )
    unknown = PublicClaim(
        claim_key=UNKNOWN_KEY,
        claim_type="unknown",
        text="需求恢复节奏仍未知。",
        action_impact="neutral",
        required_evidence=("下一期经营数据",),
        review_trigger="下一期财报",
    )
    risk = ReviewItem(
        item_id=RISK_ID,
        text="若利润率再次跌破基线，则当前改善论点失效。",
        claim_keys=(INFERENCE_KEY,),
        trigger_kind="filing",
        trigger_value="下一期财报",
        status="pending",
        evidence_ref_ids=(available_ref_id,),
    )
    return ResearchCaseV2(
        run_id=run_id,
        ticker="000338.SZ",
        horizon="medium",
        source_sequence=7,
        as_of=AS_OF,
        availability="full",
        decision_eligibility="none",
        evidence_verdict="PASS",
        claims=(fact, inference, unknown),
        invalidation_conditions=(risk,),
        analyst_cards=(
            AnalystCard(
                lens="market",
                availability="ready",
                summary="市场视角覆盖了价格趋势和实际数据窗口。",
                confidence=0.78,
                finding_claim_keys=(FACT_KEY,),
                capability_statuses=(
                    CapabilityStatus(
                        capability=coverage.capability,
                        status="ok",
                        coverage_ref_ids=(coverage.coverage_ref_id,),
                    ),
                ),
            ),
        ),
        data_quality=DataQuality(
            level="limited",
            coverage_ref_ids=(coverage.coverage_ref_id,),
        ),
        evidence_refs=(evidence, unavailable),
        coverage_refs=(coverage,),
    )


def _seed_run(
    store: RunStore,
    *,
    run_id: str,
    available_ref_id: str,
    unavailable_ref_id: str,
) -> dict[str, str]:
    snapshot = RunSnapshot.create(
        run_id=run_id,
        ticker="000338.SZ",
        analysis_date="2026-08-10",
        horizon="medium",
        mode="company_research",
    )
    store.create_run(snapshot)
    evidence_artifact = store.store_artifact(
        run_id,
        kind="private-evidence",
        value={"raw_secret": "must-never-reach-reader"},
    )
    unavailable_artifact = store.store_artifact(
        run_id,
        kind="private-unavailable",
        value={"raw_secret": "also-private"},
    )
    case = _case(
        run_id,
        evidence_artifact_id=evidence_artifact.artifact_id,
        evidence_locator=evidence_artifact.locator,
        available_ref_id=available_ref_id,
        unavailable_artifact_id=unavailable_artifact.artifact_id,
        unavailable_locator=unavailable_artifact.locator,
        unavailable_ref_id=unavailable_ref_id,
    )
    case_artifact = store.store_artifact(
        run_id,
        kind="research-case-v2",
        value=case.model_dump(mode="json"),
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "artifact.written",
            {
                "artifact_id": case_artifact.artifact_id,
                "kind": case_artifact.kind,
                "media_type": case_artifact.media_type,
                "content_sha256": case_artifact.content_sha256,
                "byte_size": case_artifact.byte_size,
                "locator": case_artifact.locator,
                "public_contract": "research-case-v2",
                "committed_sequence": 7,
            },
            status="committed",
        )
    )
    diff_artifact = store.store_artifact(
        run_id,
        kind="thesis-diff-v1",
        value={
            "schema_version": 1,
            "run_id": run_id,
            "ticker": case.ticker,
            "horizon": case.horizon,
            "current_research_case_artifact_id": case_artifact.artifact_id,
            "previous_research_case_artifact_id": "research-case-v2:" + "f" * 64,
            "previous_run_id": "run_previous",
            "baseline_completed_at": "2026-07-10T00:00:00Z",
            "entries": [
                {
                    "claim_key": FACT_KEY,
                    "diff_kind": "maintained",
                    "previous_claim_type": "fact",
                    "current_claim_type": "fact",
                    "previous_text": "价格趋势稳定。",
                    "current_text": case.claims[0].text,
                    "previous_confidence": 0.7,
                    "current_confidence": 0.78,
                    "previous_lifecycle_status": "active",
                    "current_lifecycle_status": "active",
                    "change_flags": ["text_changed", "confidence_changed"],
                    "counter_evidence_ref_ids": [],
                },
            ],
        },
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "artifact.written",
            {
                "artifact_id": diff_artifact.artifact_id,
                "kind": diff_artifact.kind,
                "media_type": diff_artifact.media_type,
                "content_sha256": diff_artifact.content_sha256,
                "byte_size": diff_artifact.byte_size,
                "locator": diff_artifact.locator,
                "public_contract": "thesis-diff-v1",
                "committed_sequence": 8,
            },
            status="committed",
        )
    )
    return {
        "case_artifact_id": case_artifact.artifact_id,
        "evidence_artifact_id": evidence_artifact.artifact_id,
        "evidence_locator": evidence_artifact.locator,
        "diff_artifact_id": diff_artifact.artifact_id,
    }


def _assert_reader_private_values_absent(payload: object, private_values: set[str]) -> None:
    forbidden_keys = {
        "artifact_id",
        "audit_refs",
        "content_sha256",
        "current_research_case_artifact_id",
        "locator",
        "previous_research_case_artifact_id",
        "raw",
        "raw_secret",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
        elif isinstance(value, str):
            assert value not in private_values

    walk(payload)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "must-never-reach-reader" not in serialized
    assert "also-private" not in serialized


def test_reader_recursively_omits_content_addressed_and_raw_fields(tmp_path) -> None:
    store = RunStore(tmp_path)
    run_id = "run_20260810T010000000000Z_aaaaaaaa"
    private = _seed_run(
        store,
        run_id=run_id,
        available_ref_id="a" * 64,
        unavailable_ref_id="c" * 64,
    )

    response = TestClient(create_app(store=store)).get(f"/api/runs/{run_id}/reader")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "typed"
    assert payload["thesis_diff"] is not None
    assert "c" * 64 not in json.dumps(payload)
    _assert_reader_private_values_absent(payload, set(private.values()))


def test_companion_resolves_only_four_current_run_public_selection_kinds(tmp_path) -> None:
    store = RunStore(tmp_path)
    run_id = "run_20260810T020000000000Z_bbbbbbbb"
    available_ref_id = "b" * 64
    private = _seed_run(
        store,
        run_id=run_id,
        available_ref_id=available_ref_id,
        unavailable_ref_id="d" * 64,
    )
    client = TestClient(create_app(store=store))
    selections = {
        "role": "market",
        "claim": FACT_KEY,
        "evidence": available_ref_id,
        "risk": RISK_ID,
    }

    for kind, selection_id in selections.items():
        response = client.get(
            f"/api/runs/{run_id}/reader/companion",
            params={"kind": kind, "id": selection_id},
        )
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {
            "schema_version",
            "run_id",
            "selection",
            "summary",
            "actual_coverage",
            "conclusion_impact",
            "next_validation",
        }
        assert payload["selection"] == {"kind": kind, "id": selection_id}
        assert payload["summary"]
        assert payload["actual_coverage"]
        assert payload["conclusion_impact"]
        assert payload["next_validation"]
        _assert_reader_private_values_absent(payload, set(private.values()))


def test_companion_returns_typed_404_for_cross_run_unknown_and_unpublic_ids(
    tmp_path,
) -> None:
    store = RunStore(tmp_path)
    run_id = "run_20260810T030000000000Z_cccccccc"
    other_run_id = "run_20260810T040000000000Z_dddddddd"
    unavailable_ref_id = "e" * 64
    _seed_run(
        store,
        run_id=run_id,
        available_ref_id="c" * 64,
        unavailable_ref_id=unavailable_ref_id,
    )
    _seed_run(
        store,
        run_id=other_run_id,
        available_ref_id="d" * 64,
        unavailable_ref_id="f" * 64,
    )
    client = TestClient(create_app(store=store))

    for kind, selection_id in (
        ("evidence", "d" * 64),
        ("claim", "market.unknown.claim.primary"),
        ("evidence", unavailable_ref_id),
    ):
        response = client.get(
            f"/api/runs/{run_id}/reader/companion",
            params={"kind": kind, "id": selection_id},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "companion_not_found"
        assert "artifact" not in json.dumps(response.json()).lower()

    invalid_kind = client.get(
        f"/api/runs/{run_id}/reader/companion",
        params={"kind": "artifact", "id": "anything"},
    )
    assert invalid_kind.status_code == 422

    legacy_run = RunSnapshot.create(
        run_id="run_20260810T050000000000Z_eeeeeeee",
        ticker="000338.SZ",
        analysis_date="2026-08-10",
    ).evolve(mode=None)
    store.create_run(legacy_run)
    legacy_response = client.get(
        f"/api/runs/{legacy_run.run_id}/reader/companion",
        params={"kind": "claim", "id": FACT_KEY},
    )
    assert legacy_response.status_code == 404
    assert legacy_response.json()["detail"]["code"] == "companion_not_found"


def test_companion_selection_model_is_closed() -> None:
    with pytest.raises(ValidationError):
        CompanionSelection.model_validate({"kind": "artifact", "id": "x"})
    with pytest.raises(ValidationError):
        CompanionSelection.model_validate(
            {"kind": "claim", "id": FACT_KEY, "artifact_id": "private"}
        )
