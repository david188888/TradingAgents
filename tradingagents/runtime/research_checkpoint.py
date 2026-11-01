"""Durable, run-scoped frontier for the bounded research executor."""

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

CHECKPOINT_KIND = "research-checkpoint"


class ResearchCheckpointConflict(ValueError):
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
        raise ResearchCheckpointConflict("research checkpoint unreadable or corrupt") from exc
    if hashlib.sha256(raw).hexdigest() != event.payload["content_sha256"]:
        raise ResearchCheckpointConflict("research checkpoint hash mismatch")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ResearchCheckpointConflict("research checkpoint invalid JSON") from exc
    if not isinstance(value, dict):
        raise ResearchCheckpointConflict("research checkpoint must be an object")
    if value.get("version") != 1 or value.get("run_id") != run_id:
        raise ResearchCheckpointConflict("research checkpoint identity mismatch")
    if not isinstance(value.get("identity"), dict) or not isinstance(value.get("results"), dict) or not isinstance(value.get("stages"), dict) or not isinstance(value.get("records"), list):
        raise ResearchCheckpointConflict("research checkpoint shape mismatch")
    # Constructing the ledger validates duplicate/conflicting attempt identities.
    BudgetLedger(run_id, records=(_record_from_json(r) for r in value["records"]))
    if any(not isinstance(v, dict) for v in value["results"].values()):
        raise ResearchCheckpointConflict("research result cache shape mismatch")
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


class ResearchJournal:
    def __init__(self, observer: Any, identity: dict[str, Any], *, require_existing=False):
        self.observer = observer
        self.lock = threading.RLock()
        self.failed = False
        state = load_checkpoint(observer.store, observer.run_id)
        if require_existing and state is None:
            raise ResearchCheckpointConflict("no research checkpoint exists")
        if state is not None and state.get("identity") != identity:
            raise ResearchCheckpointConflict("research checkpoint incompatible")
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
                raise ResearchCheckpointConflict("research persistence failed")
            try:
                self.state["records"] = [_record_json(r) for r in self.ledger.records()]
                artifact = self.observer.store.store_artifact(
                    self.observer.run_id, kind=CHECKPOINT_KIND, value=self.state,
                )
                self.last_event = self.observer.emit(RunEventDraft(
                    self.observer.run_id, "artifact.written", {
                        **asdict(artifact), "research_stages": dict(self.state["stages"]),
                    }, status="committed",
                ))
            except BaseException:
                self.failed = True
                raise

    def put(self, key: str, value: Any) -> None:
        with self.lock:
            if key in {"candidate", "draft", "evidence_context", "as_of"} and key in self.state and self.state[key] != value:
                raise ResearchCheckpointConflict("same research frontier has different content")
            self.state[key] = value
            self.persist()



class DurableBudgetLedger(BudgetLedger):
    """Every transition reaches disk before its caller can dispatch work."""

    def __init__(self, journal: ResearchJournal):
        self.journal = journal
        from tradingagents.execution.search_budget import SEARCH_BUDGET_POLICY
        from tradingagents.research.native_versions import INSIGHT_WORKFLOW_VERSION
        identity = journal.state["identity"]
        if identity.get("workflow_version") != INSIGHT_WORKFLOW_VERSION:
            raise ResearchCheckpointConflict("unsupported research checkpoint version")
        if identity.get("search_budget_policy") != SEARCH_BUDGET_POLICY:
            raise ResearchCheckpointConflict("search budget policy mismatch")
        limits = {BudgetBucket(key): value for key, value in SEARCH_BUDGET_POLICY["limits"].items()}
        policy = {"structured_repair": 8, "basic_model_attempts": 20, "model_attempts": 29}
        if identity.get("insight_budget_policy") != policy:
            raise ResearchCheckpointConflict("insight budget policy mismatch")
        limits.update({BudgetBucket(key): value for key, value in policy.items()})
        super().__init__(journal.observer.run_id, limits=limits, records=(
            _record_from_json(value) for value in journal.state["records"]
        ))

    def _transition(self, method: str, *args, **kwargs):
        with self.journal.lock:
            if self.journal.failed:
                raise ResearchCheckpointConflict("research persistence failed")
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
                raise ResearchCheckpointConflict("same logical task has different content")
            self.journal.state["results"][logical_call_id] = value
            self.journal.persist()
