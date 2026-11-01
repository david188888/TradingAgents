"""Closed, read-only qualification of the optional focus response."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from tradingagents.agents.schemas._insight import SavedInsight
from tradingagents.runtime.research_checkpoint import load_checkpoint
from tradingagents.web.research_record_projection import project_research_record


class ReaderFocusDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    run_id: str
    source_sequence: int = Field(ge=0)
    workflow_version: str | None = None
    state: Literal["ready", "pending", "unavailable", "not_applicable"]
    focus: str | None = None
    response: None = None
    insight_response: tuple[SavedInsight, ...] | None = None
    reason_code: Literal[
        "focus_not_requested", "legacy_question_semantics", "unsupported_profile",
        "workflow_unsupported", "publication_pending", "not_published", "publication_failed",
        "corrupt", "base_unavailable",
    ] | None = None

    @model_serializer(mode='wrap')
    def compatible_shape(self, handler):
        value = handler(self)
        if self.insight_response is None:
            value.pop('insight_response', None)
        return value


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
        if version == 'evidence-production-v9':
            focus = snapshot.metadata.get('research_question')
            if not focus:
                return result('not_applicable', 'focus_not_requested')
            base['focus'] = focus
            projected = project_research_record(store, run_id, through=sequence)
            if projected['state'] != 'insight_ready':
                ended = any(e.type in {'run.completed', 'run.failed', 'run.cancelled', 'run.interrupted'} for e in events)
                return result('unavailable' if ended else 'pending', 'base_unavailable' if ended else 'publication_pending')
            items = projected['record']['focus_insights']
            return result('ready' if items else 'unavailable', None if items else 'not_published', insight_response=items)
        return result("unavailable", "workflow_unsupported")
    except Exception:
        return result("unavailable", "corrupt")
