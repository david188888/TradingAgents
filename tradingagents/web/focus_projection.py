"""Closed, read-only qualification of the optional focus response."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.schemas._research_focus import ResearchFocusResponseV1
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.research.native_versions import FOCUS_WORKFLOW_VERSION
from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
from tradingagents.runtime.focus_artifacts import (
    read_focus_artifact,
    read_focus_publication_failure,
)
from tradingagents.web.research_record_projection import project_research_record


class ReaderFocusDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    workflow_version: str | None = None
    state: Literal["ready", "pending", "unavailable", "not_applicable"]
    focus: str | None = None
    response: ResearchFocusResponseV1 | None = None
    reason_code: Literal[
        "focus_not_requested", "legacy_question_semantics", "unsupported_profile",
        "workflow_unsupported", "publication_pending", "not_published", "publication_failed",
        "corrupt", "base_unavailable",
    ] | None = None


def project_reader_focus(store, run_id, *, through=None):
    snapshot = store.read_snapshot(run_id)
    sequence = snapshot.latest_sequence if through is None else through
    if sequence < 0 or sequence > snapshot.latest_sequence:
        raise ValueError("reader_sequence_unavailable")
    base = {"run_id": run_id, "source_sequence": sequence}
    def result(state, reason=None, **fields):
        return ReaderFocusDTO(**base, state=state, reason_code=reason, **fields).model_dump(mode="json")
    if snapshot.metadata.get("research_profile") != "evidence_v1":
        return result("not_applicable", "unsupported_profile")
    try:
        cp = load_checkpoint(store, run_id, through=sequence)
        events = store.read_events(run_id, through=sequence)
        version = cp["identity"].get("workflow_version") if cp else snapshot.metadata.get("native_workflow_version")
        base["workflow_version"] = version
        if version != FOCUS_WORKFLOW_VERSION:
            if version is not None and version not in {f"evidence-production-v{i}" for i in range(1, 6)}:
                return result("unavailable", "workflow_unsupported")
            return result("not_applicable", "legacy_question_semantics")
        focus = snapshot.metadata.get("research_question")
        if not focus:
            return result("not_applicable", "focus_not_requested")
        base["focus"] = focus
        ended = any(e.type in {"run.completed", "run.failed", "run.cancelled", "run.interrupted"} for e in events)
        record = project_research_record(store, run_id, through=sequence)
        if record["state"] != "ready":
            return result("unavailable" if ended else "pending", "base_unavailable" if ended else "publication_pending")
        if cp is None:
            return result("unavailable", "corrupt")
        saved = read_focus_artifact(store, run_id, ResearchRecordV1.model_validate(record["record"]), cp, events)
        failure = read_focus_publication_failure(store, run_id, ResearchRecordV1.model_validate(record["record"]), cp, events)
        if failure:
            return result("unavailable", failure)
        if saved is None:
            return result("unavailable" if ended else "pending", "not_published" if ended else "publication_pending")
        response, _ = saved
        return result("ready", response=response)
    except Exception:
        return result("unavailable", "corrupt")
