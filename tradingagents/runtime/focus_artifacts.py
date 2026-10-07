"""Read and qualify committed focus artifacts without any work or mutation."""

import hashlib
import json

from tradingagents.agents.schemas._research_focus import (
    FOCUS_RESPONSE_CONTRACT,
    ResearchFocusResponseV1,
    validate_focus_response,
)
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.observability.canonical import canonical_sha256 as config_sha256
from tradingagents.research.focus_context import focus_context, focus_identity
from tradingagents.research.native_versions import FOCUS_WORKFLOW_VERSION
from tradingagents.runtime.catalyst_checkpoint import CHECKPOINT_KIND

FOCUS_PUBLIC_TASK = "native.focus.final"


def read_focus_publication_failure(store, run_id, record, checkpoint, events):
    """Validate a durable local promotion failure; never reveal its candidate."""
    disposition = checkpoint.get("native_focus_publication")
    if not disposition or disposition.get("state") != "unavailable":
        return None
    if read_focus_artifact(store, run_id, record, checkpoint, events) is not None:
        raise ValueError("failed focus has a committed artifact")
    candidate = ResearchFocusResponseV1.model_validate(checkpoint["native_focus_candidate"])
    validate_focus_response(record, candidate)
    identity = checkpoint["identity"]
    expected = focus_identity(focus_context(record, candidate.focus, str(identity["config"].get("output_language", "Chinese"))),
                              config_sha256(identity["config"]))
    if (identity.get("workflow_version") != FOCUS_WORKFLOW_VERSION
            or identity.get("research_question") != candidate.focus
            or store.read_snapshot(run_id).metadata.get("research_question") != candidate.focus
            or checkpoint.get("native_focus_input") != expected
            or checkpoint.get("native_base_record_sha256") != canonical_sha256(record)
            or checkpoint["results"]["native.focus_response"] != {"identity": expected, "response": candidate.model_dump(mode="json")}
            or checkpoint.get("publication_authorized") is not True
            or disposition.get("candidate_sha256") != canonical_sha256(candidate)
            or disposition.get("base_record_sha256") != candidate.base_record_sha256
            or disposition.get("reason_code") != "publication_failed"):
        raise ValueError("focus failure binding mismatch")
    return "publication_failed"


def read_focus_artifact(store, run_id, record, checkpoint, events):
    """Return (response, event) or None. Invalid bindings fail closed."""
    candidates = [e for e in events if e.type == "artifact.written" and e.status == "committed"
                  and e.payload.get("public_contract") == FOCUS_RESPONSE_CONTRACT]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("duplicate committed focus")
    event = candidates[0]
    def checked(e):
        raw = store.read_artifact(run_id, e.payload["artifact_id"])
        if hashlib.sha256(raw).hexdigest() != e.payload.get("content_sha256"):
            raise ValueError("focus artifact digest mismatch")
        return raw
    response = ResearchFocusResponseV1.model_validate_json(checked(event))
    validate_focus_response(record, response)
    identity = checkpoint["identity"]
    if identity.get("workflow_version") != FOCUS_WORKFLOW_VERSION or identity.get("research_question") != response.focus:
        raise ValueError("focus request binding mismatch")
    snapshot = store.read_snapshot(run_id)
    if snapshot.metadata.get("research_question") != response.focus:
        raise ValueError("focus snapshot binding mismatch")
    language = str(identity["config"].get("output_language", "Chinese"))
    expected = focus_identity(focus_context(record, response.focus, language), config_sha256(identity["config"]))
    result = checkpoint["results"]["native.focus_response"]
    if (checkpoint.get("native_base_record_sha256") != canonical_sha256(record)
            or checkpoint.get("native_focus_input") != expected or result.get("identity") != expected
            or result.get("response") != response.model_dump(mode="json")):
        raise ValueError("focus input/output mismatch")
    barrier = next((e for e in events if e.event_id == event.parent_event_id), None)
    if (barrier is None or barrier.status != "committed" or barrier.payload.get("kind") != CHECKPOINT_KIND
            or event.payload.get("committed_sequence") != barrier.sequence
            or event.payload.get("graph_task_id") != FOCUS_PUBLIC_TASK):
        raise ValueError("focus barrier mismatch")
    saved = json.loads(checked(barrier))
    if (saved.get("publication_authorized") is not True
            or saved.get("native_focus_candidate") != response.model_dump(mode="json")
            or saved.get("native_focus_authorized_candidate_sha256") != canonical_sha256(response)
            or saved.get("native_publication_candidate") != record.model_dump(mode="json")
            or saved.get("native_focus_input") != expected):
        raise ValueError("focus authorization mismatch")
    base_events = [e for e in events if e.type == "artifact.written" and e.status == "committed"
                   and e.payload.get("public_contract") == "research-record-v1" and e.sequence < event.sequence
                   and e.payload.get("artifact_id") == saved.get("native_focus_base_artifact_id")]
    if len(base_events) != 1 or canonical_sha256(ResearchRecordV1.model_validate_json(checked(base_events[0]))) != canonical_sha256(record):
        raise ValueError("focus published baseline mismatch")
    disposition = checkpoint.get("native_focus_publication")
    if disposition and (disposition.get("base_record_sha256") != canonical_sha256(record)
                        or disposition.get("candidate_sha256") != canonical_sha256(response)
                        or disposition.get("state") == "unavailable"):
        raise ValueError("focus publication disposition mismatch")
    if disposition and disposition.get("state") == "committed" and (
        disposition.get("artifact_id") != event.payload["artifact_id"] or disposition.get("event_id") != event.event_id
    ):
        raise ValueError("focus publication event mismatch")
    return response, event
