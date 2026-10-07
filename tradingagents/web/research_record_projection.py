"""Read-only projection of committed shared research records. No backfill."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from tradingagents.agents.schemas._catalyst_research import CatalystResearchCase
from tradingagents.agents.schemas._research_case import ResearchCaseV2
from tradingagents.agents.schemas._research_record import RESEARCH_RECORD_CONTRACT, ResearchRecordV1
from tradingagents.research.record_assembly import case_content_sha256


class ResearchRecordReadyV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["ready"] = "ready"
    schema_version: Literal[1] = 1
    run_id: str
    record: ResearchRecordV1


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


def project_research_record(store: Any, run_id: str, *, through: int | None = None) -> dict[str, Any]:
    snapshot = store.read_snapshot(run_id)  # Existing global 404 for missing run.
    events = (store.read_events(run_id) if through is None else store.read_events(run_id, through=through))
    if through is not None:
        events = [event for event in events if not isinstance(event.payload.get("committed_sequence"), int)
                  or event.payload["committed_sequence"] <= through]
    event = _latest(events, RESEARCH_RECORD_CONTRACT)
    reason = "not_published"
    if event is None and any(item.type == "artifact.projection_unavailable"
                            and item.payload.get("public_contract") == RESEARCH_RECORD_CONTRACT for item in events):
        reason = "publication_failed"
    if event is not None:
        try:
            record = ResearchRecordV1.model_validate_json(_read_checked(store, run_id, event))
            mode = "catalyst_research" if (snapshot.metadata or {}).get("research_profile") == "catalyst_v1" else snapshot.mode
            if record.run_id != run_id or record.ticker != snapshot.ticker or record.mode != mode or record.analysis_date != date.fromisoformat(snapshot.analysis_date):
                raise ValueError("research record identity mismatch")
            if (snapshot.metadata or {}).get("research_profile") == "evidence_v1" and (
                    record.construction != "native" or record.assessment is None):
                raise ValueError("native profile requires its assessed native record")
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
