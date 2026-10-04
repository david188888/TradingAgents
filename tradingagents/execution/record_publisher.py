"""Additive committed-record publication for existing case workflows."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Any

from tradingagents.agents.schemas._research_record import RESEARCH_RECORD_CONTRACT, ResearchRecordV1
from tradingagents.execution.output_publisher import promote_derived_public_artifact

logger = logging.getLogger(__name__)


def promote_research_record(observer: Any, *, build: Callable[[], ResearchRecordV1],
                            graph_task_id: str, checkpoint_event_id: str,
                            committed_sequence: int, promoted: set[tuple[str, str]]) -> str | None:
    """Compatibility record is additive; preserve readable source cases.

    Validate existing records for the same task before publishing. A conflict
    never overwrites one. Read paths do not invoke this producer or backfill.
    """
    from tradingagents.observability.events import RunEventDraft

    if (graph_task_id, RESEARCH_RECORD_CONTRACT) in promoted:
        return None
    try:
        record = ResearchRecordV1.model_validate(build().model_dump(mode="json"))
        if record.run_id != observer.run_id:
            raise ValueError("research record belongs to another run")
        for event in observer.store.read_events(observer.run_id):
            if event.type != "artifact.written" or event.status != "committed" or event.payload.get("public_contract") != RESEARCH_RECORD_CONTRACT or event.payload.get("graph_task_id") != graph_task_id:
                continue
            raw = observer.store.read_artifact(observer.run_id, event.payload["artifact_id"])
            if hashlib.sha256(raw).hexdigest() != event.payload.get("content_sha256"):
                raise ValueError("prior committed research record integrity mismatch")
            prior = ResearchRecordV1.model_validate_json(raw)
            if prior != record:
                raise ValueError("same source task has conflicting research record")
            promoted.add((graph_task_id, RESEARCH_RECORD_CONTRACT))
            return event.payload["artifact_id"]
        return promote_derived_public_artifact(observer, contract=RESEARCH_RECORD_CONTRACT,
            value=record, graph_task_id=graph_task_id, checkpoint_event_id=checkpoint_event_id,
            committed_sequence=committed_sequence, promoted=promoted)
    except Exception as exc:
        # Stable reason/type only. Provider content and model validation text
        # can carry private payloads and must not be logged.
        logger.warning("research record unavailable for run %s (%s)", observer.run_id, type(exc).__name__)
        observer.emit(RunEventDraft(observer.run_id, "artifact.projection_unavailable", {
            "public_contract": RESEARCH_RECORD_CONTRACT,
            "graph_task_id": graph_task_id, "reason_code": "research_record_publication_failed",
        }, parent_event_id=checkpoint_event_id, status="failed"))
        return None
