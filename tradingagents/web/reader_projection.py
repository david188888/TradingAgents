"""Pure-function projection of a run into the read-only learning reader.

``project_reader`` is deterministic and side-effect free: it reads persisted run
facts from the store, chooses a reader family (typed / legacy / unavailable),
and returns a plain dict (``model_dump(mode="json")``).  It never calls an LLM,
never touches the network, and never writes files.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import cast

from tradingagents.agents.schemas._research_case import ResearchCaseV2
from tradingagents.runtime.store import RunStore

from .reader_models import (
    AuditEntryDTO,
    LearningReaderV2,
    LegacyDataQualityDTO,
    LegacyReaderV1,
    ReaderEvidenceRef,
    ReaderUnavailableV1,
    ResearchMode,
    ThesisDiffDTO,
)

logger = logging.getLogger(__name__)

_TYPED_MODES = frozenset({"company_research", "holding_review"})
_RESEARCH_CASE_CONTRACT = "research-case-v2"


def project_reader(store: RunStore, run_id: str) -> dict:
    """Project a run into a reader dict (one of the three reader kinds)."""
    # RunNotFound propagates to the API layer, which maps it to 404.
    snapshot = store.read_snapshot(run_id)
    events = store.read_events(run_id)
    audit = _audit_entry(events, run_id)

    if snapshot.mode in _TYPED_MODES:
        case_ref = _latest_research_case(events)
        if case_ref is None:
            model = ReaderUnavailableV1(
                run_id=run_id,
                ticker=snapshot.ticker,
                reason_code="research_case_unavailable",
                audit_entry=audit,
            )
            return model.model_dump(mode="json")
        try:
            raw = store.read_artifact(run_id, case_ref)
            payload = json.loads(raw)
            case = ResearchCaseV2.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - projection must not raise
            logger.warning("reader projection failed for run %s: %s", run_id, exc)
            model = ReaderUnavailableV1(
                run_id=run_id,
                ticker=snapshot.ticker,
                reason_code="reader_projection_failed",
                audit_entry=audit,
            )
            return model.model_dump(mode="json")
        model = _project_typed(
            snapshot.mode,
            case,
            audit,
            _load_thesis_diff(store, run_id, events),
        )
        return model.model_dump(mode="json")

    model = _project_legacy(snapshot.run_id, snapshot.ticker, snapshot.analysis_date, snapshot.final_signal, audit)
    return model.model_dump(mode="json")


def _latest_research_case(events) -> str | None:
    """Return the artifact_id of the highest committed_sequence research-case-v2."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != _RESEARCH_CASE_CONTRACT:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if not isinstance(sequence, int) or not isinstance(artifact_id, str):
            continue
        if best is None or sequence > best[0]:
            best = (sequence, artifact_id)
    return best[1] if best is not None else None


def _audit_entry(events, run_id: str) -> AuditEntryDTO:
    artifact_count = 0
    tool_call_count = 0
    degradation_count = 0
    audit_refs: list[str] = []
    for event in events:
        if event.type == "artifact.written":
            artifact_count += 1
            artifact_id = event.payload.get("artifact_id")
            if isinstance(artifact_id, str):
                audit_refs.append(artifact_id)
        elif event.type == "tool.committed":
            tool_call_count += 1
        elif event.type.startswith("degradation"):
            degradation_count += 1
    return AuditEntryDTO(
        route="reader",
        artifact_count=artifact_count,
        tool_call_count=tool_call_count,
        degradation_count=degradation_count,
        audit_refs=tuple(audit_refs),
    )


def _load_thesis_diff(store, run_id: str, events) -> dict | None:
    """Return the highest-sequence thesis-diff-v1 artifact, if any."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != "thesis-diff-v1":
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if (
            isinstance(sequence, int)
            and isinstance(artifact_id, str)
            and (best is None or sequence > best[0])
        ):
            best = (sequence, artifact_id)
    if best is None:
        return None
    try:
        raw = store.read_artifact(run_id, best[1])
        value = json.loads(raw)
        return ThesisDiffDTO.model_validate(value)
    except Exception as exc:  # noqa: BLE001 - reader stays available without diff
        logger.warning("failed to read thesis diff %s: %s", best[1], exc)
        return None


def _project_typed(
    mode: str,
    case: ResearchCaseV2,
    audit: AuditEntryDTO,
    thesis_diff: ThesisDiffDTO | None,
) -> LearningReaderV2:
    evidence_refs = tuple(
        ReaderEvidenceRef(
            ref_id=ref.ref_id,
            source_label=_source_label(ref.artifact_id),
            resolution_status="available",
        )
        for ref in case.evidence_refs
    )
    return LearningReaderV2(
        run_id=case.run_id,
        mode=cast(ResearchMode, mode),
        ticker=case.ticker,
        horizon=case.horizon,
        as_of=case.as_of,
        availability=case.availability,
        decision_eligibility=case.decision_eligibility,
        evidence_verdict=case.evidence_verdict,
        research_tilt=case.research_rating,
        rating_confidence=case.rating_confidence,
        claims=case.claims,
        scenarios=case.scenarios,
        catalysts=case.catalysts,
        invalidation_conditions=case.invalidation_conditions,
        review_plan=case.review_plan,
        analyst_cards=case.analyst_cards,
        data_quality=case.data_quality,
        evidence_refs=evidence_refs,
        coverage_refs=case.coverage_refs,
        omissions=case.omissions,
        thesis_diff=thesis_diff,
        audit_entry=audit,
    )


def _project_legacy(
    run_id: str,
    ticker: str,
    analysis_date: str,
    final_signal: str | None,
    audit: AuditEntryDTO,
) -> LegacyReaderV1:
    return LegacyReaderV1(
        run_id=run_id,
        ticker=ticker,
        as_of=_legacy_as_of(analysis_date),
        final_signal=final_signal,
        portfolio_report_markdown=None,
        data_quality=LegacyDataQualityDTO(
            level="unknown",
            summary="Legacy run without typed data quality.",
            degradation_count=0,
        ),
        stage_refs=(),
        audit_entry=audit,
        reason_codes=("legacy_run", "legacy_markdown_not_projected"),
    )


def _source_label(artifact_id: str) -> str:
    """Derive a human-friendly source label without leaking locator/hashes."""
    if ":" in artifact_id:
        return artifact_id.split(":", 1)[0]
    return artifact_id


def _legacy_as_of(analysis_date: str) -> datetime:
    """Best-effort research date for a legacy run; never crashes."""
    try:
        return datetime.fromisoformat(analysis_date).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
