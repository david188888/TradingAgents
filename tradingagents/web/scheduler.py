"""FIFO admission queue and bounded-concurrency execution slots for runs.

Extracted from SingleRunManager so the lifecycle flows (start / retry /
resume / cancel / recover) stay readable while the scheduling machinery --
the pending deque, resume options, the active registry, the concurrency cap,
and the drain loop that turns queued ids into worker threads -- lives in one
place.

The scheduler never publishes domain events itself: admission side effects
(``run.started`` publication, batch-manifest sync) are injected hooks owned
by SingleRunManager. All state is guarded by the manager's RLock, which is
passed in at construction so external ``with manager._guard:`` blocks stay
reentrant rather than deadlocking.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tradingagents.execution.models import AnalysisRequest, CancellationToken

from .run_models import RunSnapshot
from .store import RunNotFound, RunStore

# Statuses for which a queued id may still be launched during a drain. A run
# resumed from "interrupted" is already persisted as "running" by the time it
# is enqueued, hence its presence alongside the fresh statuses.
DRAINABLE_RUN_STATUSES = frozenset({"created", "queued", "running"})

# Options attached to a queued id. Plain starts carry the default tuple;
# resumes override all three fields.
_PendingOptions = tuple[bool, Any | None, int | None]

_NO_OPTIONS: _PendingOptions = (False, None, None)

WorkerTarget = Callable[
    [str, AnalysisRequest, CancellationToken, bool, Any | None, int | None],
    None,
]
RequestResolverHook = Callable[[RunSnapshot], AnalysisRequest]
AdmittedHook = Callable[[str, AnalysisRequest], None]
LaunchFailureHook = Callable[[str, BaseException], None]


@dataclass
class _ActiveRun:
    run_id: str
    token: CancellationToken
    thread: threading.Thread
    phase: str = "running"


class RunScheduler:
    """Owns the FIFO admission queue and the bounded execution slots."""

    def __init__(
        self,
        *,
        store: RunStore,
        lock: threading.RLock,
        resolve_request: RequestResolverHook,
        thread_target: WorkerTarget,
        on_admitted: AdmittedHook,
        on_launch_failure: LaunchFailureHook,
    ) -> None:
        self.store = store
        self._lock = lock
        self._resolve_request = resolve_request
        self._thread_target = thread_target
        self._on_admitted = on_admitted
        self._on_launch_failure = on_launch_failure
        self._active: dict[str, _ActiveRun] = {}
        self._pending: deque[str] = deque()
        self._pending_options: dict[str, _PendingOptions] = {}
        self._max_concurrency = 3

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return next(iter(self._active), None)

    @property
    def active_run_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active)

    @property
    def pending(self) -> deque[str]:
        """The live FIFO deque. Mutating it requires holding the owner lock."""
        return self._pending

    @property
    def max_concurrency(self) -> int:
        with self._lock:
            return self._max_concurrency

    def set_concurrency(self, value: int) -> int:
        if value not in (1, 2, 3):
            raise ValueError("concurrency must be between 1 and 3")
        with self._lock:
            self._max_concurrency = value
            self.drain()
            return value

    def active_entry(self, run_id: str) -> _ActiveRun | None:
        with self._lock:
            return self._active.get(run_id)

    def queued_by_occupancy(self) -> bool:
        """Fresh single runs queue whenever anything is ahead of them."""
        with self._lock:
            return bool(self._active) or bool(self._pending)

    def queued_by_capacity(self) -> bool:
        """Batch items queue once admitted slots reach the concurrency cap."""
        with self._lock:
            return len(self._active) + len(self._pending) >= self._max_concurrency

    def is_queued(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._pending

    def queue_run(
        self,
        run_id: str,
        *,
        resume: bool = False,
        checkpoint_guard: Any | None = None,
        resumed_from: int | None = None,
    ) -> None:
        """Append an id to the FIFO, optionally carrying resume overrides."""
        with self._lock:
            self._pending.append(run_id)
            if resume:
                self._pending_options[run_id] = (resume, checkpoint_guard, resumed_from)

    def discard_queued(self, run_id: str) -> None:
        """Drop a not-yet-launched id (cancellation before execution)."""
        with self._lock:
            self._pending = deque(item for item in self._pending if item != run_id)
            self._pending_options.pop(run_id, None)

    def drain(self) -> None:
        """Launch queued runs while free slots remain. Caller may hold the lock."""
        with self._lock:
            while len(self._active) < self._max_concurrency and self._pending:
                run_id = self._pending.popleft()
                try:
                    snapshot = self.store.read_snapshot(run_id)
                except RunNotFound:
                    # Deleted between enqueue and drain (e.g. bulk clear): drop
                    # it instead of crashing the scheduling path for later runs.
                    continue
                if snapshot.status not in DRAINABLE_RUN_STATUSES:
                    continue
                request = self._resolve_request(snapshot)
                resume, guard, resumed_from = self._pending_options.pop(
                    run_id, _NO_OPTIONS
                )
                self.launch(
                    run_id,
                    request,
                    resume=resume,
                    checkpoint_guard_override=guard,
                    resumed_from_sequence=resumed_from,
                )

    def launch(
        self,
        run_id: str,
        request: AnalysisRequest,
        *,
        resume: bool,
        checkpoint_guard_override: Any | None = None,
        resumed_from_sequence: int | None = None,
    ) -> None:
        token = CancellationToken()
        thread = threading.Thread(
            target=self._thread_target,
            args=(
                run_id,
                request,
                token,
                resume,
                checkpoint_guard_override,
                resumed_from_sequence,
            ),
            name=f"tradingagents-{run_id}",
            daemon=True,
        )
        active = _ActiveRun(run_id, token, thread)
        self._active[run_id] = active
        self._on_admitted(run_id, request)
        self.sync_batch_for_run(run_id)
        try:
            thread.start()
        except BaseException as exc:
            self._active.pop(run_id, None)
            self._on_launch_failure(run_id, exc)
            self.drain()
            raise

    def release(self, run_id: str) -> None:
        """Free the slot taken by a finished worker and pull the next run."""
        with self._lock:
            self._active.pop(run_id, None)
            self.sync_batch_for_run(run_id)
            self.drain()

    def mark_terminalizing(self, run_id: str) -> None:
        """Flag the run so further cancellations are refused as too late."""
        with self._lock:
            active = self._active.get(run_id)
            if active is not None:
                active.phase = "terminalizing"

    def sync_batch_for_run(self, run_id: str) -> None:
        """Best-effort batch-manifest sync after a run changed state."""
        try:
            snapshot = self.store.read_snapshot(run_id)
            batch_id = snapshot.metadata.get("batch_id")
            if not isinstance(batch_id, str):
                return
            batch = self.store.read_batch(batch_id)
            next(item for item in batch.items if item.run_id == run_id)
        except (RunNotFound, StopIteration):
            # The run or its batch manifest vanished concurrently (bulk
            # clear); batch sync is best-effort, so degrade to a no-op.
            return
        error_message = snapshot.error_message if snapshot.status == "failed" else None
        updated = batch.with_item_status(
            run_id,
            snapshot.status if snapshot.status in {"queued", "running", "completed", "failed", "cancelled", "interrupted"} else "queued",
            error_message=error_message,
        )
        if updated != batch:
            self.store.write_batch_atomic(updated)
