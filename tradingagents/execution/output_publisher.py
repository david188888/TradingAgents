"""Stateless public-output promotion for durable graph runs.

These helpers turn committed observation candidates into typed public
artifacts (reader outputs, report revisions, role completions). They operate
only on the ``observer`` and are imported back into ``runner.py``; they hold
no runner/checkpoint state.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

DERIVED_PUBLIC_CONTRACTS = frozenset({"insight-research-v1"})

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
