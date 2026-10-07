"""Durable, run-scoped frontier for the bounded catalyst executor."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from datetime import datetime
from typing import Any

from tradingagents.execution.budget import (
    AttemptOutcome,
    AttemptPhase,
    AttemptRecord,
    BudgetBucket,
    BudgetLedger,
)
from tradingagents.observability.events import RunEventDraft

CHECKPOINT_KIND = "catalyst-checkpoint"


class CatalystCheckpointConflict(ValueError):
    pass


def load_checkpoint(store: Any, run_id: str, *, through: int | None = None) -> dict[str, Any] | None:
    events = [
        event for event in (store.read_events(run_id) if through is None else store.read_events(run_id, through=through))
        if event.type == "artifact.written"
        and event.status == "committed"
        and event.payload.get("kind") == CHECKPOINT_KIND
    ]
    if not events:
        return None
    event = events[-1]
    try:
        raw = store.read_artifact(run_id, event.payload["artifact_id"])
    except Exception as exc:
        raise CatalystCheckpointConflict("catalyst checkpoint unreadable or corrupt") from exc
    if hashlib.sha256(raw).hexdigest() != event.payload["content_sha256"]:
        raise CatalystCheckpointConflict("catalyst checkpoint hash mismatch")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise CatalystCheckpointConflict("catalyst checkpoint invalid JSON") from exc
    if not isinstance(value, dict):
        raise CatalystCheckpointConflict("catalyst checkpoint must be an object")
    if value.get("version") != 1 or value.get("run_id") != run_id:
        raise CatalystCheckpointConflict("catalyst checkpoint identity mismatch")
    if not isinstance(value.get("identity"), dict) or not isinstance(value.get("results"), dict) or not isinstance(value.get("stages"), dict) or not isinstance(value.get("records"), list):
        raise CatalystCheckpointConflict("catalyst checkpoint shape mismatch")
    # Constructing the ledger validates duplicate/conflicting attempt identities.
    BudgetLedger(run_id, records=(_record_from_json(r) for r in value["records"]))
    if any(not isinstance(v, dict) for v in value["results"].values()):
        raise CatalystCheckpointConflict("catalyst result cache shape mismatch")
    return value


def _record_json(record: AttemptRecord) -> dict[str, Any]:
    value = asdict(record)
    for key in ("reserved_at", "dispatched_at", "settled_at"):
        if value[key] is not None:
            value[key] = value[key].isoformat()
    for key in ("bucket", "phase", "outcome"):
        value[key] = value[key].value
    return value


def _record_from_json(value: dict[str, Any]) -> AttemptRecord:
    value = dict(value)
    for key in ("reserved_at", "dispatched_at", "settled_at"):
        if value[key] is not None:
            value[key] = datetime.fromisoformat(value[key])
    value["bucket"] = BudgetBucket(value["bucket"])
    value["phase"] = AttemptPhase(value["phase"])
    value["outcome"] = AttemptOutcome(value["outcome"])
    return AttemptRecord(**value)


class CatalystJournal:
    def __init__(self, observer: Any, identity: dict[str, Any], *, require_existing=False):
        self.observer = observer
        self.lock = threading.RLock()
        self.failed = False
        state = load_checkpoint(observer.store, observer.run_id)
        if require_existing and state is None:
            raise CatalystCheckpointConflict("no catalyst checkpoint exists")
        if state is not None and state.get("identity") != identity:
            raise CatalystCheckpointConflict("catalyst checkpoint incompatible")
        self.state = state or {
            "version": 1, "run_id": observer.run_id, "identity": identity,
            "records": [], "results": {}, "stages": {},
        }
        self.ledger = DurableBudgetLedger(self)
        if state is not None:
            self.ledger.reconcile_uncertain()
        self.persist()

    def persist(self) -> None:
        with self.lock:
            if self.failed:
                raise CatalystCheckpointConflict("catalyst persistence failed")
            try:
                self.state["records"] = [_record_json(r) for r in self.ledger.records()]
                artifact = self.observer.store.store_artifact(
                    self.observer.run_id, kind=CHECKPOINT_KIND, value=self.state,
                )
                self.last_event = self.observer.emit(RunEventDraft(
                    self.observer.run_id, "artifact.written", {
                        **asdict(artifact), "catalyst_stages": dict(self.state["stages"]),
                    }, status="committed",
                ))
            except BaseException:
                self.failed = True
                raise

    def put(self, key: str, value: Any) -> None:
        with self.lock:
            if key in {"candidate", "draft", "evidence_context", "as_of"} and key in self.state and self.state[key] != value:
                raise CatalystCheckpointConflict("same catalyst frontier has different content")
            self.state[key] = value
            self.persist()

    def stage(self, name: str, status: str, *, role_statuses=None) -> None:
        with self.lock:
            self.state["stages"][name] = status
            self.persist()
            from tradingagents.observability.roles import CATALYST_ROLE_REGISTRY, role_instance_id
            keys = ("catalyst_events", "operating_delivery", "market_reaction") if name == "specialists" else (name,)
            events = self.observer.store.read_events(self.observer.run_id)
            for key in keys:
                role = next(r for r in CATALYST_ROLE_REGISTRY if r.actor_id == "catalyst." + key)
                previous = next((e.payload["new_status"] for e in reversed(events)
                    if e.type == "role.status_changed" and e.actor_id == role.actor_id), "pending")
                new = (role_statuses or {}).get(key, status)
                if new == previous:
                    continue
                self.observer.emit(RunEventDraft(self.observer.run_id, "role.status_changed", {
                    "role_instance_id": role_instance_id(self.observer.run_id, role.actor_id),
                    "previous_status": previous, "new_status": new, "reason": "catalyst_durable_frontier",
                }, actor_id=role.actor_id, node_id=role.node_id, team_id=role.team_id,
                    status=new, parent_event_id=self.last_event.event_id))


class DurableBudgetLedger(BudgetLedger):
    """Every transition reaches disk before its caller can dispatch work."""

    def __init__(self, journal: CatalystJournal):
        self.journal = journal
        super().__init__(journal.observer.run_id, records=(
            _record_from_json(value) for value in journal.state["records"]
        ))

    def _transition(self, method: str, *args, **kwargs):
        with self.journal.lock:
            if self.journal.failed:
                raise CatalystCheckpointConflict("catalyst persistence failed")
            result = getattr(super(), method)(*args, **kwargs)
            self.journal.persist()
            return result

    def reserve(self, *args, **kwargs):
        return self._transition("reserve", *args, **kwargs)

    def mark_dispatched(self, *args, **kwargs):
        return self._transition("mark_dispatched", *args, **kwargs)

    def settle(self, *args, **kwargs):
        return self._transition("settle", *args, **kwargs)

    def release(self, *args, **kwargs):
        return self._transition("release", *args, **kwargs)

    def reconcile_uncertain(self):
        return self._transition("reconcile_uncertain")

    def cached_result(self, logical_call_id: str):
        with self.journal.lock:
            value = self.journal.state["results"].get(logical_call_id)
            return None if value is None else json.loads(json.dumps(value))

    def record_result(self, logical_call_id: str, value: Any) -> None:
        with self.journal.lock:
            old = self.journal.state["results"].get(logical_call_id)
            if old is not None and old != value:
                raise CatalystCheckpointConflict("same logical task has different content")
            self.journal.state["results"][logical_call_id] = value
            self.journal.persist()
