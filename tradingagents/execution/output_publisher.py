"""Stateless public-output promotion for durable graph runs.

These helpers turn committed observation candidates into typed public
artifacts (reader outputs, report revisions, role completions). They operate
only on the ``observer`` and are imported back into ``runner.py``; they hold
no runner/checkpoint state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

DERIVED_PUBLIC_CONTRACTS = frozenset(
    {
        "research-case-v2",
        "position-draft-v1",
        "position-overlay-v1",
        "thesis-diff-v1",
    }
)


def promote_derived_public_artifact(
    observer: Any,
    *,
    contract: str,
    value: BaseModel,
    graph_task_id: str,
    checkpoint_event_id: str,
    committed_sequence: int,
    promoted: set[tuple[str, str]],
) -> str | None:
    """Write one public derived artifact after its source graph task commits.

    The caller must supply the task identity and the durable barrier identity;
    this function deliberately cannot promote an arbitrary pre-commit model
    response.  Replays are idempotent by `(graph_task_id, contract)`.
    """
    if contract not in DERIVED_PUBLIC_CONTRACTS:
        raise ValueError("unsupported derived public contract")
    if not graph_task_id or not checkpoint_event_id or committed_sequence < 0:
        raise ValueError("derived public artifact requires a committed graph task")
    identity = (graph_task_id, contract)
    if identity in promoted:
        return None
    public_value = value.model_dump(mode="json")
    if public_value.get("run_id") != observer.run_id:
        raise ValueError("derived public artifact must belong to the observer run")
    artifact = observer.store.store_artifact(
        observer.run_id,
        kind=contract,
        value=public_value,
    )
    from tradingagents.observability.events import RunEventDraft

    observer.emit(
        RunEventDraft(
            observer.run_id,
            "artifact.written",
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "content_sha256": artifact.content_sha256,
                "byte_size": artifact.byte_size,
                "locator": artifact.locator,
                "graph_task_id": graph_task_id,
                "public_contract": contract,
                "committed_sequence": committed_sequence,
            },
            parent_event_id=checkpoint_event_id,
            status="committed",
        )
    )
    promoted.add(identity)
    return artifact.artifact_id


def _step_applied_draft(
    run_id: str,
    graph_step: int,
    applied_task_ids: tuple[str, ...],
    state_sha256: str,
):
    from tradingagents.observability.events import RunEventDraft

    return RunEventDraft(
        run_id,
        "graph.step_applied",
        {
            "graph_step": graph_step,
            "applied_task_ids": list(applied_task_ids),
            "state_sha256": state_sha256,
            "next_nodes": [],
        },
        status="committed",
    )


def _read_candidate_delta(observer: Any, artifact_id: str) -> dict[str, Any]:
    try:
        value = json.loads(observer.store.read_artifact(observer.run_id, artifact_id))
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("committed candidate artifact is unreadable") from exc
    if not isinstance(value, dict):
        raise RuntimeError("committed candidate artifact must contain an object")
    return value


def _state_updated_draft(
    run_id: str,
    commit: Any,
    changed_keys: tuple[str, ...],
    checkpoint_event_id: str,
):
    from tradingagents.observability.events import RunEventDraft

    return RunEventDraft(
        run_id,
        "state.updated",
        {
            "turn_id": commit.turn_id,
            "graph_task_id": commit.graph_task_id,
            "changed_keys": list(changed_keys),
            "checkpoint_event_id": checkpoint_event_id,
        },
        node_id=commit.node_id,
        parent_event_id=checkpoint_event_id,
        status="committed",
    )

def _promote_public_output(
    observer: Any,
    commit: Any,
    delta: Mapping[str, Any],
    checkpoint_event_id: str,
    committed_sequence: int,
    promoted_tasks: set[str],
) -> None:
    """Publish a typed public output only after its graph delta is committed."""
    if not commit.turn_id or commit.graph_task_id in promoted_tasks:
        return
    raw = delta.get("reader_public_output")
    if not isinstance(raw, Mapping):
        return
    kind = raw.get("kind")
    value = raw.get("value")
    if kind not in {"research", "trader", "portfolio", "risk"} or not isinstance(value, Mapping):
        return
    public_value = {
        "schema_version": 1,
        "run_id": observer.run_id,
        "turn_id": commit.turn_id,
        "committed_sequence": committed_sequence,
        **dict(value),
    }
    artifact = observer.store.store_artifact(
        observer.run_id,
        kind=f"public-{kind}",
        value=public_value,
    )
    from tradingagents.observability.events import RunEventDraft

    observer.emit(
        RunEventDraft(
            observer.run_id,
            "artifact.written",
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "content_sha256": artifact.content_sha256,
                "byte_size": artifact.byte_size,
                "locator": artifact.locator,
                "turn_id": commit.turn_id,
                "graph_task_id": commit.graph_task_id,
                "public_output_kind": kind,
                "committed_sequence": committed_sequence,
            },
            node_id=commit.node_id,
            parent_event_id=checkpoint_event_id,
            status="committed",
        )
    )
    promoted_tasks.add(commit.graph_task_id)


_REPORT_FIELDS = {
    "market_report": "market",
    "sentiment_report": "sentiment",
    "news_report": "news",
    "fundamentals_report": "fundamentals",
    "trader_investment_plan": "trader",
    "final_trade_decision": "portfolio",
}


def _promote_report_revisions(
    observer: Any,
    commit: Any,
    delta: Mapping[str, Any],
    checkpoint_event_id: str,
    promoted_reports: set[tuple[str, str]],
) -> None:
    if not commit.turn_id:
        return
    from tradingagents.observability.events import RunEventDraft
    from tradingagents.runtime.reports import ReportArtifactWriter

    writer = ReportArtifactWriter(observer.store)
    for state_field, report_kind in _REPORT_FIELDS.items():
        content = delta.get(state_field)
        identity = (commit.graph_task_id, report_kind)
        if not isinstance(content, str) or not content or identity in promoted_reports:
            continue
        revision = writer.write_revision_once(observer.run_id, report_kind, content)
        events = observer.store.read_events(observer.run_id)
        if not any(
            event.type == "artifact.written"
            and event.payload.get("artifact_id") == revision.artifact.artifact_id
            for event in events
        ):
            observer.emit(
                RunEventDraft(
                    observer.run_id,
                    "artifact.written",
                    {
                        "artifact_id": revision.artifact.artifact_id,
                        "kind": revision.artifact.kind,
                        "media_type": revision.artifact.media_type,
                        "content_sha256": revision.artifact.content_sha256,
                        "byte_size": revision.artifact.byte_size,
                        "locator": revision.artifact.locator,
                    },
                    parent_event_id=checkpoint_event_id,
                )
            )
        observer.emit(
            RunEventDraft(
                observer.run_id,
                "report.updated",
                {
                    "turn_id": commit.turn_id,
                    "graph_task_id": commit.graph_task_id,
                    "report_kind": report_kind,
                    "revision": revision.revision,
                    "artifact_id": revision.artifact.artifact_id,
                    "checkpoint_event_id": checkpoint_event_id,
                },
                node_id=commit.node_id,
                parent_event_id=checkpoint_event_id,
                status="committed",
            )
        )
        promoted_reports.add(identity)


def _ensure_role_completion(
    observer: Any,
    turn_id: str,
    checkpoint_event_id: str,
) -> None:
    from tradingagents.observability.events import RunEventDraft

    events = observer.store.read_events(observer.run_id)
    if any(
        event.type == "role.status_changed"
        and event.payload.get("turn_id") == turn_id
        and event.payload.get("new_status") == "completed"
        for event in events
    ):
        return
    turn_event = next(
        (
            event
            for event in events
            if event.type.startswith("turn.")
            and event.payload.get("turn_id") == turn_id
        ),
        None,
    )
    if turn_event is None or turn_event.actor_id is None:
        raise RuntimeError("committed turn has no durable role identity")
    previous = next(
        (
            event.payload.get("new_status")
            for event in reversed(events)
            if event.type == "role.status_changed"
            and event.actor_id == turn_event.actor_id
        ),
        "running",
    )
    observer.emit(
        RunEventDraft(
            observer.run_id,
            "role.status_changed",
            {
                "role_instance_id": turn_event.payload["role_instance_id"],
                "previous_status": previous,
                "new_status": "completed",
                "reason": "checkpoint_committed",
                "turn_id": turn_id,
            },
            team_id=turn_event.team_id,
            actor_id=turn_event.actor_id,
            node_id=turn_event.node_id,
            parent_event_id=checkpoint_event_id,
            status="completed",
        )
    )
