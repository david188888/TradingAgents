"""Read-only projection of committed shared research records. No backfill."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from tradingagents.agents.schemas._catalyst_research import CatalystResearchCase
from tradingagents.agents.schemas._research_case import ResearchCaseV2
from tradingagents.agents.schemas._research_record import RESEARCH_RECORD_CONTRACT
from tradingagents.research.record_assembly import case_content_sha256
from tradingagents.research.record_codec import ResearchRecord, parse_research_record


class ResearchRecordReadyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["ready"] = "ready"
    schema_version: Literal[1] = 1
    run_id: str
    record: ResearchRecord


class ResearchRecordUnavailableV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["unavailable"] = "unavailable"
    schema_version: Literal[1] = 1
    run_id: str
    reason_code: Literal["not_published", "publication_failed", "corrupt", "source_case_mismatch"]


def _latest(events, contract):
    candidates = [event for event in events if event.type == "artifact.written"
        and event.status == "committed" and event.payload.get("public_contract") == contract
        and isinstance(event.payload.get("committed_sequence"), int)
        and isinstance(event.payload.get("artifact_id"), str)]
    return max(candidates, key=lambda event: (event.payload["committed_sequence"], event.sequence), default=None)


def _read_checked(store, run_id, event):
    raw = store.read_artifact(run_id, event.payload["artifact_id"])
    if hashlib.sha256(raw).hexdigest() != event.payload.get("content_sha256"):
        raise ValueError("committed artifact integrity mismatch")
    return raw


def _validate_numeric_publication(store, run_id, event, events, record, snapshot):
    """Bind new numeric records to their exact publication checkpoint.

    Legacy records keep their original read contract. A numeric policy cannot
    be inferred from a later checkpoint, nor may a detached attribution table
    turn an old publication into a numerically verified one.
    """
    from tradingagents.agents.schemas._verification_plan import canonical_sha256
    from tradingagents.research.numeric_integration import validate_record_numeric
    from tradingagents.runtime.catalyst_checkpoint import CHECKPOINT_KIND, load_checkpoint

    marker = (snapshot.metadata or {}).get("numeric_narrative_policy")
    attribution = getattr(record, "numeric_attribution", None)
    try:
        checkpoint = load_checkpoint(store, run_id, through=event.sequence)
    except Exception:
        if marker is None and attribution is None and record.schema_version == 'research-record-v1':
            # Old public Reader records did not require a catalyst checkpoint.
            return
        raise
    identity = checkpoint["identity"] if checkpoint is not None else {}
    if marker is None and "numeric_narrative_policy" not in identity and record.schema_version == "research-record-v1":
        validate_record_numeric(record, identity)
        return
    if marker is not None and marker != identity.get("numeric_narrative_policy"):
        raise ValueError("numeric publication policy mismatch")
    barrier = next((item for item in events if item.event_id == event.parent_event_id), None)
    if (barrier is None or barrier.type != "artifact.written" or barrier.status != "committed"
            or barrier.payload.get("kind") != CHECKPOINT_KIND
            or barrier.sequence != event.payload.get("committed_sequence")
            or barrier.sequence >= event.sequence
            or event.payload.get("graph_task_id") != "native.final"):
        raise ValueError("numeric publication barrier missing")
    saved = json.loads(_read_checked(store, run_id, barrier))
    if (not isinstance(saved, dict) or saved.get("version") != 1
            or saved.get("run_id") != run_id or saved.get("identity") != identity):
        raise ValueError("numeric publication barrier identity mismatch")
    candidate = record.model_dump(mode="json")
    if (saved.get("native_publication_candidate") != candidate
            or saved.get("native_publication_authorized_candidate_sha256") != canonical_sha256(candidate)
            or saved.get("publication_authorized") is not True):
        raise ValueError("numeric publication authorization mismatch")
    validate_record_numeric(record, saved["identity"])
    if record.numeric_attribution is not None and record.numeric_attribution.input_identity != saved.get("native_input"):
        raise ValueError("numeric publication input binding mismatch")


def project_research_record(store: Any, run_id: str, *, through: int | None = None) -> dict[str, Any]:
    snapshot = store.read_snapshot(run_id)  # Existing global 404 for missing run.
    events = (store.read_events(run_id) if through is None else store.read_events(run_id, through=through))
    if through is not None:
        events = [event for event in events if not isinstance(event.payload.get("committed_sequence"), int)
                  or event.payload["committed_sequence"] <= through]
    insight_event = _latest(events, 'insight-research-v1')
    if insight_event is not None:
        from tradingagents.web.insight_projection import project_insight_record
        return project_insight_record(store, snapshot, events, insight_event)
    events_by_contract = [_latest(events, version) for version in ('research-record-v1', 'research-record-v2')]
    event = max((e for e in events_by_contract if e is not None), key=lambda e: (e.payload['committed_sequence'], e.sequence), default=None)
    reason = "not_published"
    if event is None and any(item.type == "artifact.projection_unavailable"
                            and item.payload.get("public_contract") == RESEARCH_RECORD_CONTRACT for item in events):
        reason = "publication_failed"
    if event is not None:
        try:
            record = parse_research_record(json.loads(_read_checked(store, run_id, event)))
            if event.payload.get('public_contract') != record.schema_version:
                raise ValueError('research artifact schema mismatch')
            mode = "catalyst_research" if (snapshot.metadata or {}).get("research_profile") == "catalyst_v1" else snapshot.mode
            if record.run_id != run_id or record.ticker != snapshot.ticker or record.mode != mode or record.analysis_date != date.fromisoformat(snapshot.analysis_date):
                raise ValueError("research record identity mismatch")
            if (snapshot.metadata or {}).get("research_profile") == "evidence_v1" and (
                    record.construction != "native" or record.assessment is None):
                raise ValueError("native profile requires its assessed native record")
            if record.construction == "native":
                from tradingagents.research.native_versions import validate_assessment_version
                validate_assessment_version(record, (snapshot.metadata or {}).get("native_workflow_version"))
                _validate_numeric_publication(store, run_id, event, events, record, snapshot)
        except Exception:
            reason = "corrupt"
        else:
            if record.construction == "adapted_case":
                source = _latest(events, record.source_case_contract)
                try:
                    if source is None:
                        raise ValueError("source case not committed")
                    cls = CatalystResearchCase if record.source_case_contract == "catalyst-research-case-v1" else ResearchCaseV2
                    case = cls.model_validate_json(_read_checked(store, run_id, source))
                    if case.run_id != run_id or case.ticker != snapshot.ticker or case_content_sha256(case) != record.source_case_sha256:
                        raise ValueError("research record source case mismatch")
                except Exception:
                    reason = "source_case_mismatch"
                else:
                    return ResearchRecordReadyV1(run_id=run_id, record=record).model_dump(mode="json")
            else:
                return ResearchRecordReadyV1(run_id=run_id, record=record).model_dump(mode="json")
    return ResearchRecordUnavailableV1(run_id=run_id, reason_code=reason).model_dump(mode="json")
