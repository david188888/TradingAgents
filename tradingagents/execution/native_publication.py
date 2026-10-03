"""Mandatory, committed publication for native evidence-driven research.

Unlike compatibility projections, failure here is a failed publication. The
consumer must not complete a run after this function raises.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from tradingagents.agents.schemas._research_record import RESEARCH_RECORD_CONTRACT, ResearchRecordV1
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.runtime.catalyst_checkpoint import (
    CHECKPOINT_KIND,
    CatalystJournal,
    DurableBudgetLedger,
)

NATIVE_PUBLIC_TASK = "native.final"
_CANDIDATE = "native_publication_candidate"
_AUTHORIZED = "native_publication_authorized_candidate_sha256"


class NativePublicationError(RuntimeError):
    """Stable publication error that does not expose model/source payloads."""


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _existing_artifact(observer: Any, record: ResearchRecordV1) -> str | None:
    artifact_id = None
    events = observer.store.read_events(observer.run_id)
    event_index = {event.event_id: event for event in events}
    for event in events:
        if event.type != "artifact.written" or event.status != "committed" or event.payload.get("public_contract") != RESEARCH_RECORD_CONTRACT:
            continue
        try:
            raw = observer.store.read_artifact(observer.run_id, event.payload["artifact_id"])
        except Exception:
            raise NativePublicationError("native publication integrity mismatch") from None
        if hashlib.sha256(raw).hexdigest() != event.payload.get("content_sha256"):
            raise NativePublicationError("native publication integrity mismatch")
        prior = ResearchRecordV1.model_validate_json(raw)
        if prior != record or event.payload.get("graph_task_id") != NATIVE_PUBLIC_TASK:
            raise NativePublicationError("native publication content conflict")
        barrier = event_index.get(event.parent_event_id)
        if barrier is None or barrier.status != "committed" or barrier.payload.get("kind") != CHECKPOINT_KIND or barrier.sequence != event.payload.get("committed_sequence"):
            raise NativePublicationError("native publication barrier missing")
        barrier_raw = observer.store.read_artifact(observer.run_id, barrier.payload["artifact_id"])
        if hashlib.sha256(barrier_raw).hexdigest() != barrier.payload.get("content_sha256"):
            raise NativePublicationError("native publication barrier integrity mismatch")
        saved_barrier = json.loads(barrier_raw)
        candidate = record.model_dump(mode="json")
        if saved_barrier.get(_CANDIDATE) != candidate or saved_barrier.get(_AUTHORIZED) != _digest(candidate) or saved_barrier.get("publication_authorized") is not True:
            raise NativePublicationError("native publication barrier authorization mismatch")
        artifact_id = event.payload["artifact_id"]
    return artifact_id


def publish_native_record(
    observer: Any,
    *,
    record: ResearchRecordV1,
    ledger: DurableBudgetLedger,
    publication_authorizer: Callable[[CatalystJournal], None],
) -> str:
    """Save the candidate, arbitrate cancellation, then publish the exact record.

    The authorizer must durably write ``publication_authorized=True`` under the
    consumer's lifecycle lock. It is invoked without journal/store locks, so
    cancellation and publication retain the existing lock ordering. Replay
    verifies persisted public bytes and performs no model or provider work.
    """
    try:
        record = ResearchRecordV1.model_validate(record.model_dump(mode="json"))
        journal = ledger.journal
        if journal.observer.store is not observer.store or journal.observer.run_id != observer.run_id or record.run_id != observer.run_id or ledger.run_id != observer.run_id:
            raise NativePublicationError("native publication identity mismatch")
        if record.construction != "native" or record.assessment is None:
            raise NativePublicationError("native publication requires a native assessment")
        if not callable(publication_authorizer):
            raise NativePublicationError("native publication requires a lifecycle authorizer")
        candidate = record.model_dump(mode="json")
        digest = _digest(candidate)
        with journal.lock:
            prior = journal.state.get(_CANDIDATE)
            if prior is not None and prior != candidate:
                raise NativePublicationError("native publication candidate conflict")
            if prior is None:
                journal.put(_CANDIDATE, candidate)
            existing = _existing_artifact(observer, record)
            if existing is not None:
                if journal.state.get(_AUTHORIZED) != digest or journal.state.get("publication_authorized") is not True:
                    raise NativePublicationError("native publication authorization missing")
                return existing

        # Do not hold the journal/store lock while entering the lifecycle lock.
        publication_authorizer(journal)
        with journal.lock, observer.store.lock_for(observer.run_id):
            if journal.failed or journal.state.get("publication_authorized") is not True:
                raise NativePublicationError("native publication authorization missing")
            if journal.state.get(_CANDIDATE) != candidate:
                raise NativePublicationError("native publication candidate conflict")
            prior_digest = journal.state.get(_AUTHORIZED)
            if prior_digest is not None and prior_digest != digest:
                raise NativePublicationError("native publication authorization conflict")
            if prior_digest is None:
                journal.put(_AUTHORIZED, digest)
            existing = _existing_artifact(observer, record)
            if existing is not None:
                return existing
            barrier = journal.last_event
            artifact_id = promote_derived_public_artifact(observer,
                contract=RESEARCH_RECORD_CONTRACT, value=record,
                graph_task_id=NATIVE_PUBLIC_TASK, checkpoint_event_id=barrier.event_id,
                committed_sequence=barrier.sequence, promoted=set())
            if artifact_id is None:
                raise NativePublicationError("native publication did not commit an artifact")
            return artifact_id
    except (NativePublicationError, AnalysisCancelled):
        raise
    except Exception:
        # Validation and I/O exception messages can contain private payloads.
        raise NativePublicationError("native publication failed") from None
