"""Read-only current Insight publications; retired runs are not upgraded."""

from tradingagents.web.insight_projection import project_insight_record


def _latest(events, contract):
    candidates = [event for event in events if event.type == "artifact.written"
        and event.status == "committed" and event.payload.get("public_contract") == contract
        and isinstance(event.payload.get("committed_sequence"), int)
        and isinstance(event.payload.get("artifact_id"), str)]
    return max(candidates, key=lambda event: (event.payload["committed_sequence"], event.sequence), default=None)


def project_research_record(store, run_id, *, through=None):
    snapshot = store.read_snapshot(run_id)
    if (snapshot.metadata.get("research_profile") != "evidence_v1"
            or snapshot.metadata.get("native_workflow_version") != "evidence-production-v9"):
        return {"state": "unavailable", "schema_version": 1, "run_id": run_id, "reason_code": "unsupported_version"}
    events = store.read_events(run_id) if through is None else store.read_events(run_id, through=through)
    if through is not None:
        events = [event for event in events if not isinstance(event.payload.get("committed_sequence"), int)
            or event.payload["committed_sequence"] <= through]
    event = _latest(events, "insight-research-v1")
    if event is not None:
        return project_insight_record(store, snapshot, events, event)
    return {"state": "unavailable", "schema_version": 1, "run_id": run_id, "reason_code": "not_published"}
