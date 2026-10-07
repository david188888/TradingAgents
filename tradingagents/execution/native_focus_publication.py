"""Optional artifact promotion after the mandatory baseline is committed."""

from tradingagents.agents.schemas._research_focus import (
    FOCUS_RESPONSE_CONTRACT,
    validate_focus_response,
)
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.native_focus import bind_focus
from tradingagents.execution.native_publication import NativePublicationError, _existing_artifact
from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.runtime.focus_artifacts import FOCUS_PUBLIC_TASK, read_focus_artifact


def publish_focus_response(observer, *, record, response, ledger, base_artifact_id):
    journal = ledger.journal
    validate_focus_response(record, response)
    if journal.failed or journal.state.get("publication_authorized") is not True:
        raise NativePublicationError("focus publication requires lifecycle authorization")
    if _existing_artifact(observer, record) != base_artifact_id:
        raise NativePublicationError("focus publication requires committed baseline")
    bind_focus(journal, "native_focus_candidate", response.model_dump(mode="json"))
    bind_focus(journal, "native_focus_authorized_candidate_sha256", canonical_sha256(response))
    bind_focus(journal, "native_focus_base_artifact_id", base_artifact_id)
    binding = {"base_record_sha256": canonical_sha256(record), "candidate_sha256": canonical_sha256(response)}
    prior = journal.state.get("native_focus_publication")
    if prior and any(prior.get(k) != v for k, v in binding.items()):
        raise NativePublicationError("focus publication disposition conflict")
    events = observer.store.read_events(observer.run_id)
    existing = read_focus_artifact(observer.store, observer.run_id, record, journal.state, events)
    if existing is None and prior and prior["state"] == "committed":
        raise NativePublicationError("focus committed artifact missing")
    if existing is None and prior and prior["state"] == "unavailable":
        return None
    if existing is None:
        if prior is None:
            journal.put("native_focus_publication", {**binding, "state": "pending"})
        try:
            barrier = journal.last_event
            promote_derived_public_artifact(observer, contract=FOCUS_RESPONSE_CONTRACT, value=response,
                graph_task_id=FOCUS_PUBLIC_TASK, checkpoint_event_id=barrier.event_id,
                committed_sequence=barrier.sequence, promoted=set())
        except Exception:
            if journal.failed:
                raise
            # A crash after commit must be recovered, never labelled failed.
            existing = read_focus_artifact(observer.store, observer.run_id, record, journal.state,
                                           observer.store.read_events(observer.run_id))
            if existing is None:
                journal.put("native_focus_publication", {**binding, "state": "unavailable",
                                                        "reason_code": "publication_failed"})
                return None
        else:
            existing = read_focus_artifact(observer.store, observer.run_id, record, journal.state,
                                           observer.store.read_events(observer.run_id))
    if existing is None:
        raise NativePublicationError("focus promotion did not commit")
    _, event = existing
    disposition = {**binding, "state": "committed", "artifact_id": event.payload["artifact_id"],
                   "event_id": event.event_id}
    if prior != disposition:
        journal.put("native_focus_publication", disposition)
    return event.payload["artifact_id"]
