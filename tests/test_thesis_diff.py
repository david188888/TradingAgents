"""Reproducible contracts for ThesisDiff computation, publication, and Reader."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tradingagents.agents.schemas._research_case import (
    DataQuality,
    PublicClaim,
    ResearchCaseV2,
)
from tradingagents.observability.events import RunEventDraft
from tradingagents.research.thesis_diff import (
    ThesisDiffEntry,
    ThesisDiffV1,
    compute_thesis_diff,
    select_baseline,
)
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.manager import SingleRunManager

CURRENT_RUN_ID = "run_20260810T000000000000Z_bbbbbbbb"
TICKER = "000338.SZ"
AS_OF = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _claim(
    key: str,
    *,
    claim_type: str = "fact",
    text: str = "claim",
    confidence: float | None = 0.6,
    lifecycle: str = "active",
    evidence: tuple[str, ...] = (),
) -> PublicClaim:
    """Construct a diff-only claim without invoking ResearchCase graph checks."""
    return PublicClaim.model_construct(
        claim_key=key,
        claim_type=claim_type,
        text=text,
        evidence_ref_ids=evidence,
        supporting_claim_keys=(),
        source_dates=(AS_OF,) if evidence else (),
        confidence=confidence,
        lifecycle_status=lifecycle,
        action_impact="neutral",
    )


def _diff_case(
    *claims: PublicClaim,
    run_id: str = CURRENT_RUN_ID,
    horizon: str = "medium",
) -> ResearchCaseV2:
    return ResearchCaseV2.model_construct(
        run_id=run_id,
        ticker=TICKER,
        horizon=horizon,
        source_sequence=1,
        as_of=AS_OF,
        availability="partial",
        decision_eligibility="none",
        evidence_verdict="PASS",
        claims=claims,
        data_quality=DataQuality(level="limited"),
    )


def _unknown(key: str) -> PublicClaim:
    return PublicClaim(
        claim_key=key,
        claim_type="unknown",
        text=f"unknown state for {key}",
        action_impact="neutral",
        required_evidence=("additional evidence",),
        review_trigger="next filing",
    )


def _valid_case(
    run_id: str,
    *,
    claim_keys: tuple[str, ...] = ("market.price.trend.primary",),
    horizon: str = "medium",
) -> ResearchCaseV2:
    return ResearchCaseV2(
        run_id=run_id,
        ticker=TICKER,
        horizon=horizon,
        source_sequence=1,
        as_of=AS_OF,
        availability="partial",
        decision_eligibility="none",
        evidence_verdict="PASS",
        claims=tuple(_unknown(key) for key in claim_keys),
        data_quality=DataQuality(level="limited"),
    )


def _seed_completed_run(
    store: RunStore,
    *,
    run_id: str,
    completed_at: str,
    case: ResearchCaseV2,
) -> tuple[str, str]:
    snapshot = RunSnapshot.create(
        run_id=run_id,
        ticker=TICKER,
        analysis_date="2026-08-10",
        horizon=case.horizon,
        mode="company_research",
    )
    store.create_run(snapshot)

    reports_dir = store.root / run_id / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "complete_report.md"
    report_path.write_text("# complete report\n", encoding="utf-8")
    final_report_artifact_id = (
        "report-final:" + hashlib.sha256(report_path.read_bytes()).hexdigest()
    )

    completed_ts = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    normalized_completed_at = completed_ts.isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
    store.write_snapshot_atomic(
        snapshot.evolve(status="completed", completed_at=normalized_completed_at)
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
                "graph_task_id": "task_research_case",
                "public_contract": "research-case-v2",
                "committed_sequence": 7,
            },
            parent_event_id="checkpoint:research-case",
            status="committed",
        )
    )

    completed_event = store.append_event(
        RunEventDraft(
            run_id,
            "run.completed",
            {
                "run_status": "completed",
                "completed_at": normalized_completed_at,
                "summary": "completed",
                "final_report_artifact_id": final_report_artifact_id,
                "degraded_data_sources": [],
            },
            status="completed",
            timestamp=completed_ts,
        )
    )
    return case_artifact.artifact_id, completed_event.event_id


def test_diff_five_states_and_invalidation_guard() -> None:
    evidence = "a" * 64
    maintained_key = "market.price.trend.maintained"
    invalidated_key = "market.price.trend.invalidated"
    missing_key = "market.price.trend.not_reassessed"
    previous = _diff_case(
        _claim(maintained_key, evidence=(evidence,)),
        _claim(invalidated_key, evidence=(evidence,)),
        _claim(missing_key, evidence=(evidence,)),
    )
    current = _diff_case(
        _claim(maintained_key, evidence=(evidence,)),
        _claim(
            invalidated_key,
            text="counter evidence",
            lifecycle="invalidated",
            evidence=(evidence,),
        ),
        _claim("market.price.trend.unresolved", claim_type="unknown"),
        _claim("market.price.trend.new", evidence=(evidence,)),
    )

    diff = compute_thesis_diff(
        run_id=CURRENT_RUN_ID,
        current_case=current,
        current_case_artifact_id="case:current",
        previous_case=previous,
        previous_case_artifact_id="case:previous",
    )
    kinds = {entry.claim_key: entry.diff_kind for entry in diff.entries}
    assert kinds == {
        maintained_key: "maintained",
        invalidated_key: "invalidated",
        "market.price.trend.unresolved": "unresolved",
        "market.price.trend.new": "new",
        missing_key: "not_reassessed",
    }
    assert diff.entries[1].counter_evidence_ref_ids == (evidence,)

    with pytest.raises(ValidationError):
        ThesisDiffV1(
            run_id=CURRENT_RUN_ID,
            ticker=TICKER,
            horizon="medium",
            current_research_case_artifact_id="case:current",
            entries=(
                ThesisDiffEntry(
                    claim_key=invalidated_key,
                    diff_kind="invalidated",
                ),
            ),
        )


def test_baseline_uses_strict_completed_at_run_id_tuple(tmp_path) -> None:
    store = RunStore(tmp_path)
    completed_at = "2026-08-10T00:00:00Z"
    smaller = "run_20260810T000000000000Z_aaaaaaaa"
    larger = "run_20260810T000000000000Z_cccccccc"
    _seed_completed_run(
        store,
        run_id=smaller,
        completed_at=completed_at,
        case=_valid_case(smaller),
    )
    _seed_completed_run(
        store,
        run_id=larger,
        completed_at=completed_at,
        case=_valid_case(larger),
    )

    baseline = select_baseline(
        store,
        current_run_id=CURRENT_RUN_ID,
        current_case=_valid_case(CURRENT_RUN_ID),
        current_completed_at="2026-08-10T00:00:00.000Z",
    )

    assert baseline is not None
    assert baseline.run_id == smaller


def test_post_completion_publication_is_idempotent_and_reader_visible(tmp_path) -> None:
    store = RunStore(tmp_path)
    case = _valid_case(CURRENT_RUN_ID)
    source_artifact_id, completed_event_id = _seed_completed_run(
        store,
        run_id=CURRENT_RUN_ID,
        completed_at="2026-08-10T00:00:00Z",
        case=case,
    )
    manager = SingleRunManager(store)

    first_artifact_id = manager._publish_thesis_diff(
        CURRENT_RUN_ID, "2026-08-10T00:00:00.000Z"
    )
    replay_artifact_id = manager._publish_thesis_diff(
        CURRENT_RUN_ID, "2026-08-10T00:00:00.000Z"
    )
    assert replay_artifact_id == first_artifact_id

    diff_events = [
        event
        for event in store.read_events(CURRENT_RUN_ID)
        if event.type == "artifact.written"
        and event.payload.get("public_contract") == "thesis-diff-v1"
    ]
    assert len(diff_events) == 1
    event = diff_events[0]
    assert event.parent_event_id == completed_event_id
    assert event.payload["source_artifact_id"] == source_artifact_id
    assert event.payload["source_event_id"] == completed_event_id
    assert event.payload["publication_phase"] == "post_completion"
    assert event.payload["committed_sequence"] == 7

    response = TestClient(create_app(store=store)).get(
        f"/api/runs/{CURRENT_RUN_ID}/reader"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "typed"
    assert payload["thesis_diff"]["run_id"] == CURRENT_RUN_ID


def test_thesis_diff_integration_preserves_cancel_terminalizer(tmp_path) -> None:
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(
        ticker=TICKER,
        analysis_date="2026-08-10",
        mode="company_research",
    )
    store.create_run(snapshot)

    SingleRunManager(store)._finish_cancelled(snapshot.run_id)

    assert store.read_events(snapshot.run_id)[-1].type == "run.cancelled"
