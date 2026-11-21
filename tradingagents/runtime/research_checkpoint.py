"""Durable, run-scoped frontier for the bounded research executor."""

from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from types import MappingProxyType
from typing import Any

import rfc8785

from tradingagents.execution.budget import (
    AttemptOutcome,
    AttemptPhase,
    AttemptRecord,
    BudgetBucket,
    BudgetLedger,
)
from tradingagents.observability.canonical import canonical_business_value
from tradingagents.observability.events import RunEventDraft
from tradingagents.runtime.store import SHA256_PATTERN

CHECKPOINT_KIND = "research-checkpoint"
CHECKPOINT_BLOB_KIND = "checkpoint-blob"
BLOB_MIN_BYTES = 4096
BLOB_FIELDS = frozenset({"native_seed", "insight.review_catalog", "insight.report", "native_publication_candidate"})
BLOB_MAPS = frozenset({"results", "insight.catalogs", "insight.catalog_history"})
CheckpointRefs = dict[str, str | dict[str, str]]


class ResearchCheckpointConflict(ValueError):
    pass


def _immutable(*_args: Any, **_kwargs: Any) -> None:
    raise TypeError("replace saved research data through the journal")


class _SavedDict(dict):
    __setitem__ = __delitem__ = __ior__ = clear = pop = popitem = setdefault = update = _immutable


class _SavedList(list):
    __setitem__ = __delitem__ = __iadd__ = __imul__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable


def _saved_value(value: Any) -> Any:
    # Remain compatible with dict/list consumers while preventing stale blob
    # references from in-place writes. Ordinary decoded checkpoints stay mutable.
    if isinstance(value, dict):
        return _SavedDict((key, _saved_value(item)) for key, item in value.items())
    if isinstance(value, list):
        return _SavedList(_saved_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_saved_value(item) for item in value)
    return value


def read_checkpoint_artifact(store: Any, run_id: str, event: Any) -> tuple[dict[str, Any], CheckpointRefs | None]:
    """Read the exact committed artifact, returning the original logical state and its physical layout."""
    try:
        raw = store.read_artifact(run_id, event.payload["artifact_id"])
        if hashlib.sha256(raw).hexdigest() != event.payload["content_sha256"]:
            raise ResearchCheckpointConflict("research checkpoint hash mismatch")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ResearchCheckpointConflict("research checkpoint must be an object")
        refs = None
        if value.get("version") == 2:
            refs, value = value.get("blobs"), value.get("state")
            if not isinstance(refs, dict) or not isinstance(value, dict):
                raise ResearchCheckpointConflict("research checkpoint index shape mismatch")
        if value.get("version") != 1 or value.get("run_id") != run_id:
            raise ResearchCheckpointConflict("research checkpoint identity mismatch")
        if refs is not None:
            decoded: dict[str, Any] = {}

            def hydrate(parent: dict, key: str, digest: Any) -> None:
                if key not in parent or parent[key] is not None or not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
                    raise ResearchCheckpointConflict("research checkpoint reference invalid")
                if digest in decoded:
                    parent[key] = deepcopy(decoded[digest])
                else:
                    decoded[digest] = parent[key] = json.loads(store.read_artifact(run_id, f"{CHECKPOINT_BLOB_KIND}:{digest}"))

            for field, ref in refs.items():
                if field in BLOB_FIELDS:
                    hydrate(value, field, ref)
                elif field in BLOB_MAPS and isinstance(ref, dict) and isinstance(value.get(field), dict):
                    for key, digest in ref.items():
                        hydrate(value[field], key, digest)
                else:
                    raise ResearchCheckpointConflict("research checkpoint blob field invalid")
        return value, refs
    except ResearchCheckpointConflict:
        raise
    except Exception as exc:
        raise ResearchCheckpointConflict("research checkpoint unreadable or corrupt") from exc


def load_checkpoint(store: Any, run_id: str, *, through: int | None = None) -> dict[str, Any] | None:
    saved = _load_checkpoint(store, run_id, through=through)
    return saved[0] if saved else None


def _load_checkpoint(store: Any, run_id: str, *, through: int | None = None) -> tuple[dict[str, Any], CheckpointRefs | None] | None:
    events = [
        event for event in (store.read_events(run_id) if through is None else store.read_events(run_id, through=through))
        if event.type == "artifact.written"
        and event.status == "committed"
        and event.payload.get("kind") == CHECKPOINT_KIND
    ]
    if not events:
        return None
    value, refs = read_checkpoint_artifact(store, run_id, events[-1])
    if not isinstance(value.get("identity"), dict) or not isinstance(value.get("results"), dict) or not isinstance(value.get("stages"), dict) or not isinstance(value.get("records"), list):
        raise ResearchCheckpointConflict("research checkpoint shape mismatch")
    # Constructing the ledger validates duplicate/conflicting attempt identities.
    BudgetLedger(run_id, records=(_record_from_json(r) for r in value["records"]))
    if any(not isinstance(v, dict) for v in value["results"].values()):
        raise ResearchCheckpointConflict("research result cache shape mismatch")
    return value, refs


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
        saved = _load_checkpoint(observer.store, observer.run_id)
        # Keep a resumed v1 run in its original layout. Only new runs start v2.
        state, self._blob_refs = saved if saved is not None else (None, {})
        if require_existing and state is None:
            raise ResearchCheckpointConflict("no research checkpoint exists")
        if state is not None and state.get("identity") != identity:
            raise ResearchCheckpointConflict("research checkpoint incompatible")
        self._state = state or {
            "version": 1, "run_id": observer.run_id, "identity": identity,
            "records": [], "results": {}, "stages": {},
        }
        if self._blob_refs is not None:
            for key in (BLOB_FIELDS | BLOB_MAPS) & self._state.keys():
                self._state[key] = _saved_value(self._state[key])
        self.state = MappingProxyType(self._state)
        self.ledger = DurableBudgetLedger(self)
        if state is not None:
            self.ledger.reconcile_uncertain()
        self.persist()

    def _store_blob(self, key: str, value: Any) -> str | None:
        # Canonicalize under the original key so a sensitive field is redacted
        # just as it would be inside the inline snapshot.
        raw = rfc8785.dumps(canonical_business_value({key: value}).value[key])
        if len(raw) < BLOB_MIN_BYTES:
            return None
        ref = self.observer.store.store_artifact(self.observer.run_id, kind=CHECKPOINT_BLOB_KIND, value=raw)
        return ref.content_sha256

    def _indexed_state(self, field: str | None, result_key: str | None, previous: Any) -> dict[str, Any]:
        refs = self._blob_refs
        if refs is None:
            return self._state
        if result_key is not None:
            results = refs.setdefault("results", {})
            digest = self._store_blob(result_key, self.state["results"][result_key])
            if digest is not None:
                results[result_key] = digest
            else:
                results.pop(result_key, None)
        elif field in BLOB_FIELDS or field in BLOB_MAPS:
            value = self.state[field]
            prior_refs = refs.pop(field, None)
            if field in BLOB_MAPS and isinstance(value, dict):
                next_refs = {}
                for key, item in value.items():
                    if isinstance(previous, dict) and key in previous and item is previous[key]:
                        digest = prior_refs.get(key) if isinstance(prior_refs, dict) else None
                    else:
                        digest = self._store_blob(key, item)
                    if digest is not None:
                        next_refs[key] = digest
                refs[field] = next_refs
            elif field in BLOB_FIELDS and (digest := self._store_blob(field, value)) is not None:
                refs[field] = digest

        inline = dict(self.state)
        for key, ref in refs.items():
            if isinstance(ref, dict):
                inline[key] = {**inline[key], **dict.fromkeys(ref)}
            else:
                inline[key] = None
        return {"version": 2, "state": inline, "blobs": refs}

    def persist(self, *, field: str | None = None, result_key: str | None = None, previous: Any = None) -> None:
        with self.lock:
            if self.failed:
                raise ResearchCheckpointConflict("research persistence failed")
            try:
                self._state["records"] = [_record_json(r) for r in self.ledger.records()]
                artifact = self.observer.store.store_artifact(
                    self.observer.run_id, kind=CHECKPOINT_KIND, value=self._indexed_state(field, result_key, previous),
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
            previous = self.state.get(key)
            if self._blob_refs is not None:
                if key in BLOB_MAPS and isinstance(value, dict) and isinstance(previous, dict):
                    value = _SavedDict(
                        (name, previous[name] if name in previous and previous[name] == item else _saved_value(item))
                        for name, item in value.items()
                    )
                elif key in BLOB_FIELDS or key in BLOB_MAPS:
                    value = _saved_value(value)
            self._state[key] = value
            self.persist(field=key, previous=previous)

    def setdefault_inline(self, key: str, value: Any) -> Any:
        """Initialize mutable inline state without creating a commit."""
        if key in BLOB_FIELDS or key in BLOB_MAPS:
            raise ValueError("saved research data requires a journal write")
        with self.lock:
            return self._state.setdefault(key, value)


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
            if old is None:
                if self.journal._blob_refs is not None:
                    self.journal._state["results"] = _SavedDict({**self.journal.state["results"], logical_call_id: _saved_value(value)})
                else:
                    self.journal.state["results"][logical_call_id] = value
                self.journal.persist(result_key=logical_call_id)
            else:
                self.journal.persist()
