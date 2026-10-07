"""Budget enforcement for the bounded ``catalyst_v1`` research flow.

Design SS5.5 fixes hard ceilings and the rules for reaching them.  Three of
those rules are accounting problems rather than modelling problems, and this
module is where they are solved:

* **Reserve before the call, decrement atomically.**  A ceiling that is only
  checked after the fact has already spent the call it was meant to prevent.
  Under the specialist fan-out of design SS5.4 two roles hold their own locks,
  so a check-then-act sequence would let both observe the last remaining unit
  and both spend it.
* **Resume inherits consumption.**  A run that is restored from a checkpoint
  must not re-acquire the budget it already spent.  The ledger therefore
  persists every attempt and reconstructs consumed and uncertain quota on
  load; it never resets a bucket to zero.
* **Unknown state counts as consumed.**  A network call that was dispatched
  and never resolved may or may not have been billed.  Counting it as free
  makes the ceiling an estimate, and a missing token measurement counted as
  zero makes a cost regression invisible.  Both are recorded as unknown.

Every attempt is keyed by ``run_id + logical_call_id + attempt_id`` and the
result visibility is recorded separately from the reservation, so a resumed
run can distinguish "reserved but never started" from "started, outcome
unknown".  Only the first counts as consumed; a reservation that never became
an attempt is released on load.

The ledger is a plain object with no graph, LLM, or provider dependency: it
decides whether a call may happen, and records what happened.  It deliberately
does not know what a call *is*.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------


class BudgetBucket(str, Enum):
    """The buckets design SS5.5 enumerates.

    The split matters more than the names.  ``structured_repair`` and
    ``network_retry`` are sub-budgets that are *also* members of
    ``model_attempts``: a repair is a real model call, and a retry is a real
    attempt.  Modelling them as siblings would let a run take four main
    analyses plus three repairs and call that within "5 main analyses".
    """

    MAIN_ANALYSIS = "main_analysis"
    FOCUS_RESPONSE = "focus_response"
    SEMANTIC_PREPROCESS = "semantic_preprocess"
    STRUCTURED_REPAIR = "structured_repair"
    NETWORK_RETRY = "network_retry"
    MODEL_ATTEMPTS = "model_attempts"
    DATA_CAPABILITY_CALLS = "data_capability_calls"
    DATA_HTTP_ATTEMPTS = "data_http_attempts"
    SPECIALIST_CONCURRENCY = "specialist_concurrency"
    SUPPLEMENT_ROUNDS = "supplement_rounds"
    SUPPLEMENT_CAPABILITIES = "supplement_capabilities"


# A repair attempt or a network retry is a model attempt, so those buckets
# roll up into the run-wide total rather than sitting beside it.
_MODEL_BUCKETS = frozenset(
    {
        BudgetBucket.MAIN_ANALYSIS,
        BudgetBucket.FOCUS_RESPONSE,
        BudgetBucket.SEMANTIC_PREPROCESS,
        BudgetBucket.STRUCTURED_REPAIR,
        BudgetBucket.NETWORK_RETRY,
    }
)


# Per-bucket and run-wide ceilings from design SS5.5.  These are the numbers
# the table in the design specifies; they are defaults, not measurements, and
# the design explicitly allows a documented adjustment but forbids removing a
# ceiling.  ``None`` would mean "no ceiling" and is not accepted.
DEFAULT_LIMITS: Mapping[BudgetBucket, int] = {
    BudgetBucket.MAIN_ANALYSIS: 5,
    BudgetBucket.FOCUS_RESPONSE: 0,
    BudgetBucket.SEMANTIC_PREPROCESS: 2,
    BudgetBucket.STRUCTURED_REPAIR: 2,
    BudgetBucket.NETWORK_RETRY: 3,
    BudgetBucket.MODEL_ATTEMPTS: 12,
    BudgetBucket.DATA_CAPABILITY_CALLS: 24,
    BudgetBucket.DATA_HTTP_ATTEMPTS: 64,
    BudgetBucket.SPECIALIST_CONCURRENCY: 2,
    BudgetBucket.SUPPLEMENT_ROUNDS: 1,
    BudgetBucket.SUPPLEMENT_CAPABILITIES: 3,
}

# Design SS5.5: at most one structured repair per stage, and at most two across
# the whole run.  A per-stage cap is what stops a single stage from burning the
# entire repair budget twice over.
DEFAULT_STAGE_LIMITS: Mapping[BudgetBucket, int] = {
    BudgetBucket.STRUCTURED_REPAIR: 1,
}


# ---------------------------------------------------------------------------
# Attempt records
# ---------------------------------------------------------------------------


class AttemptPhase(str, Enum):
    """The three lifecycle points design SS5.5 requires be recorded apart.

    Keeping reservation, dispatch, and outcome in separate fields is what
    makes a resumed run honest: a reservation with no dispatch never spent
    anything, while a dispatch with no outcome is an unknown that must be
    billed conservatively.
    """

    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    SETTLED = "settled"


class AttemptOutcome(str, Enum):
    OK = "ok"
    FAILED = "failed"
    # Dispatched, never settled. Conservatively treated as consumed.
    UNKNOWN = "unknown"
    # Reserved and released without ever being dispatched.
    RELEASED = "released"


@dataclass(frozen=True)
class AttemptRecord:
    """One reserved unit of budget, identified the way the design requires."""

    run_id: str
    logical_call_id: str
    attempt_id: str
    bucket: BudgetBucket
    stage: str
    reserved_at: datetime
    phase: AttemptPhase
    outcome: AttemptOutcome = AttemptOutcome.RELEASED
    dispatched_at: datetime | None = None
    settled_at: datetime | None = None
    # ``None`` means the provider did not report usage. It is never coerced to
    # zero: an unmeasured call is not a free call.
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_available: bool = True
    duration_ms: int | None = None
    detail: str = ""

    def attempt_key(self) -> tuple[str, str, str]:
        return (self.run_id, self.logical_call_id, self.attempt_id)

    def counts_against_budget(self) -> bool:
        """Whether this attempt holds or spends quota.

        A *held* reservation counts, and this is the point of reserving at
        all: design SS5.5 requires the check to happen before the call, so the
        unit must be unavailable to a concurrent caller for the whole window
        between the check and the dispatch. A reservation that was explicitly
        released is the one state that gives the unit back.
        """
        return not (
            self.phase is AttemptPhase.SETTLED
            and self.outcome is AttemptOutcome.RELEASED
        )


@dataclass(frozen=True)
class BudgetLimitHit:
    """Why a call was refused, in a form an event stream can carry."""

    bucket: BudgetBucket
    stage: str
    limit: int
    consumed: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket.value,
            "stage": self.stage,
            "limit": self.limit,
            "consumed": self.consumed,
            "reason": self.reason,
        }


class BudgetExhausted(RuntimeError):
    """Raised by strict callers when a call may not proceed.

    The design requires a written reason when a ceiling is hit, never a second
    model call to explain the timeout, so the reason travels on the exception
    as structured data rather than prose a model produced.
    """

    def __init__(self, hit: BudgetLimitHit):
        self.hit = hit
        super().__init__(
            f"budget exhausted for {hit.bucket.value} at stage {hit.stage!r}: "
            f"{hit.consumed}/{hit.limit} ({hit.reason})"
        )


@dataclass(frozen=True)
class Reservation:
    """A granted unit of budget, before anything was dispatched."""

    run_id: str
    logical_call_id: str
    attempt_id: str
    bucket: BudgetBucket
    stage: str
    reserved_at: datetime
    record: AttemptRecord

    def key(self) -> tuple[str, str, str]:
        return self.record.attempt_key()


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def new_attempt_id(logical_call_id: str, sequence: int) -> str:
    """A stable, restart-safe attempt identifier.

    The sequence number is part of the identifier so that a resumed run cannot
    reuse a key it already spent: the ledger treats an incoming record whose
    key already exists as a replay rather than as new quota.
    """
    digest = hashlib.sha256(
        f"{logical_call_id}#{sequence}".encode()
    ).hexdigest()[:16]
    return f"attempt_{sequence}_{digest}"


class BudgetLedger:
    """Thread-safe, resumable budget accounting for one run.

    One instance belongs to one run.  The instance is safe to share between
    the specialist threads of design SS5.4 because every mutation happens under
    one lock: reservation, dispatch, and settlement each take the lock, so two
    concurrent callers cannot both observe the last remaining unit.
    """

    def __init__(
        self,
        run_id: str,
        *,
        limits: Mapping[BudgetBucket, int] | None = None,
        stage_limits: Mapping[BudgetBucket, int] | None = None,
        records: Iterable[AttemptRecord] = (),
        clock: Any = datetime.utcnow,
    ) -> None:
        self.run_id = run_id
        # Overrides merge onto the defaults rather than replacing them. A
        # caller that tightens one bucket and forgets another should get the
        # standard ceiling for the one it forgot, not an unbounded bucket and
        # a KeyError.
        self._limits = dict(DEFAULT_LIMITS)
        self._limits.update(limits or {})
        self._stage_limits = dict(DEFAULT_STAGE_LIMITS)
        self._stage_limits.update(stage_limits or {})
        for bucket, limit in self._limits.items():
            if limit < 0:
                raise ValueError(f"budget limit for {bucket.value} cannot be negative")
        self._clock = clock
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str, str], AttemptRecord] = {}
        self._next_sequence: dict[str, int] = {}
        self._stage_durations_ms: dict[str, int] = {}
        self._termination_reason: str | None = None
        # Restore first.  A resumed run must inherit every attempt it already
        # made, not re-derive its own quota from the ceilings.
        for record in records:
            self._adopt(record)

    # -- reconstruction ---------------------------------------------------

    def _adopt(self, record: AttemptRecord) -> None:
        """Take ownership of a persisted attempt.

        A key seen twice with different content is a conflict, not a merge.
        Silently letting the later copy win would let a replayed task claim
        quota it already spent, or a divergent one erase a spend.
        """
        if record.run_id != self.run_id:
            raise ValueError(
                f"budget record belongs to run {record.run_id!r}, not {self.run_id!r}"
            )
        key = record.attempt_key()
        existing = self._records.get(key)
        if existing is not None and existing != record:
            raise BudgetConflictError(
                f"conflicting budget record for attempt {key}: "
                f"{existing.phase.value}/{existing.outcome.value} vs "
                f"{record.phase.value}/{record.outcome.value}"
            )
        self._records[key] = record
        self._track_sequence(record)
        # A stage that genuinely took under a millisecond records 0, and 0 is
        # not "unmeasured": gating on it would drop most synthetic calls and
        # make the published duration map depend on how fast the host was.
        if record.stage and record.duration_ms is not None:
            self._stage_durations_ms[record.stage] = (
                self._stage_durations_ms.get(record.stage, 0) + record.duration_ms
            )

    def _track_sequence(self, record: AttemptRecord) -> None:
        # The stored attempt id embeds the sequence that produced it, so a
        # resumed run continues numbering instead of restarting at 1 and
        # colliding with a key it has already spent.
        _, _, attempt_id = record.attempt_key()
        if attempt_id.startswith("attempt_"):
            tail = attempt_id.split("_", 2)
            if len(tail) == 3 and tail[1].isdigit():
                sequence = int(tail[1])
                logical = record.logical_call_id
                self._next_sequence[logical] = max(
                    self._next_sequence.get(logical, 0), sequence
                )

    # -- introspection ----------------------------------------------------

    def consumed(self, bucket: BudgetBucket, stage: str | None = None) -> int:
        """Units already spent in a bucket, optionally within one stage.

        ``MODEL_ATTEMPTS`` is derived rather than stored: every record in a
        model bucket is also one run-wide attempt.  Storing a second counter
        would be a second thing to keep in step, and the run-wide total is
        exactly the number a reader needs to audit.
        """
        with self._lock:
            if bucket is BudgetBucket.MODEL_ATTEMPTS:
                targets = _MODEL_BUCKETS
            else:
                targets = frozenset({bucket})
            return sum(
                1
                for record in self._records.values()
                if record.bucket in targets
                and record.counts_against_budget()
                and (stage is None or record.stage == stage)
            )

    def limit(self, bucket: BudgetBucket) -> int:
        return self._limits[bucket]

    def remaining(self, bucket: BudgetBucket, stage: str | None = None) -> int:
        if bucket in _MODEL_BUCKETS:
            # A model bucket is doubly bounded: by its own ceiling and by the
            # run-wide attempt total.  Reporting only the larger of the two
            # would hide a run that has exhausted the total while the
            # per-bucket counter still reads zero.
            return min(
                self._limits[bucket] - self.consumed(bucket, stage),
                self._limits[BudgetBucket.MODEL_ATTEMPTS]
                - self.consumed(BudgetBucket.MODEL_ATTEMPTS),
            )
        return self._limits[bucket] - self.consumed(bucket, stage)

    def records(self) -> tuple[AttemptRecord, ...]:
        """Every attempt, in reservation order, for persistence.

        Ordering is by the embedded sequence within a logical call so a
        reloaded ledger replays a call's attempts in the order they happened.
        """
        with self._lock:
            return tuple(
                sorted(
                    self._records.values(),
                    key=lambda item: (item.reserved_at, item.logical_call_id, item.attempt_id),
                )
            )

    def has_record(self, logical_call_id: str, attempt_id: str) -> bool:
        with self._lock:
            return (self.run_id, logical_call_id, attempt_id) in self._records

    # -- reservation ------------------------------------------------------

    def reserve(
        self,
        bucket: BudgetBucket,
        *,
        stage: str,
        logical_call_id: str | None = None,
    ) -> Reservation | BudgetLimitHit:
        """Reserve one unit, or explain why it is refused.

        Returns the grant rather than raising, because several callers must be
        able to degrade rather than abort: a specialist that cannot run has to
        report that, not crash the run.  Callers that genuinely cannot degrade
        use :meth:`reserve_or_raise`.
        """
        now = self._clock()
        with self._lock:
            logical = logical_call_id or f"{stage}:{bucket.value}"
            # Idempotent replay: a re-executed logical task that already holds
            # a reservation reuses it instead of paying twice. Design SS5.4
            # requires repeated submission of the same content to be a no-op.
            for key, record in self._records.items():
                if (
                    key[0] == self.run_id
                    and key[1] == logical
                    and record.bucket is bucket
                    and record.phase is AttemptPhase.RESERVED
                ):
                    return Reservation(
                        run_id=self.run_id,
                        logical_call_id=logical,
                        attempt_id=record.attempt_id,
                        bucket=bucket,
                        stage=stage,
                        reserved_at=record.reserved_at,
                        record=record,
                    )
            hit = self._limit_check(bucket, stage)
            if hit is not None:
                return hit
            sequence = self._next_sequence.get(logical, 0) + 1
            self._next_sequence[logical] = sequence
            attempt_id = new_attempt_id(logical, sequence)
            record = AttemptRecord(
                run_id=self.run_id,
                logical_call_id=logical,
                attempt_id=attempt_id,
                bucket=bucket,
                stage=stage,
                phase=AttemptPhase.RESERVED,
                reserved_at=now,
            )
            self._records[record.attempt_key()] = record
            return Reservation(
                run_id=self.run_id,
                logical_call_id=logical,
                attempt_id=attempt_id,
                bucket=bucket,
                stage=stage,
                reserved_at=now,
                record=record,
            )

    def reserve_or_raise(self, bucket: BudgetBucket, *, stage: str, logical_call_id: str | None = None) -> Reservation:
        granted = self.reserve(bucket, stage=stage, logical_call_id=logical_call_id)
        if isinstance(granted, BudgetLimitHit):
            raise BudgetExhausted(granted)
        return granted

    def _limit_check(self, bucket: BudgetBucket, stage: str) -> BudgetLimitHit | None:
        stage_cap = self._stage_limits.get(bucket)
        if stage_cap is not None:
            used = self.consumed(bucket, stage)
            if used >= stage_cap:
                return BudgetLimitHit(
                    bucket=bucket,
                    stage=stage,
                    limit=stage_cap,
                    consumed=used,
                    reason="per_stage_limit_reached",
                )
        used = self.consumed(bucket)
        if used >= self._limits[bucket]:
            return BudgetLimitHit(
                bucket=bucket,
                stage=stage,
                limit=self._limits[bucket],
                consumed=used,
                reason="run_limit_reached",
            )
        if bucket in _MODEL_BUCKETS:
            total = self.consumed(BudgetBucket.MODEL_ATTEMPTS)
            if total >= self._limits[BudgetBucket.MODEL_ATTEMPTS]:
                return BudgetLimitHit(
                    bucket=bucket,
                    stage=stage,
                    limit=self._limits[BudgetBucket.MODEL_ATTEMPTS],
                    consumed=total,
                    reason="total_model_attempts_reached",
                )
        return None

    # -- lifecycle --------------------------------------------------------

    def mark_dispatched(
        self, reservation: Reservation, *, dispatched_at: datetime | None = None
    ) -> AttemptRecord:
        """Record that the call actually left the process."""
        with self._lock:
            record = self._require(reservation)
            if record.phase in (AttemptPhase.DISPATCHED, AttemptPhase.SETTLED):
                return record
            record = replace(
                record,
                phase=AttemptPhase.DISPATCHED,
                dispatched_at=dispatched_at or self._clock(),
            )
            self._records[record.attempt_key()] = record
            return record

    def settle(
        self,
        reservation: Reservation,
        *,
        ok: bool,
        settled_at: datetime | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        usage_available: bool | None = None,
        duration_ms: int | None = None,
        detail: str = "",
    ) -> AttemptRecord:
        """Close an attempt with its measured (or explicitly unknown) usage."""
        with self._lock:
            record = self._require(reservation)
            if record.phase is AttemptPhase.SETTLED:
                return record
            available = (
                record.usage_available
                if usage_available is None
                else bool(usage_available)
            )
            if not available:
                # A provider that did not report usage must not be recorded as
                # a call that used nothing. Coercing here is precisely the
                # accounting error the schema forbids.
                input_tokens = None
                output_tokens = None
            record = replace(
                record,
                phase=AttemptPhase.SETTLED,
                outcome=AttemptOutcome.OK if ok else AttemptOutcome.FAILED,
                settled_at=settled_at or self._clock(),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usage_available=available,
                duration_ms=duration_ms,
                detail=detail,
            )
            self._records[record.attempt_key()] = record
            if record.stage and duration_ms is not None:
                self._stage_durations_ms[record.stage] = (
                    self._stage_durations_ms.get(record.stage, 0) + duration_ms
                )
            return record

    def release(self, reservation: Reservation, *, reason: str = "") -> AttemptRecord:
        """Give a reservation back because the call was never attempted.

        This is the one transition that does not consume quota: the unit was
        held but the call did not happen, so a later reservation may take it.
        """
        with self._lock:
            record = self._require(reservation)
            if record.phase is AttemptPhase.SETTLED:
                return record
            record = replace(
                record,
                phase=AttemptPhase.SETTLED,
                outcome=AttemptOutcome.RELEASED,
                settled_at=self._clock(),
                detail=reason,
            )
            self._records[record.attempt_key()] = record
            return record

    def mark_uncertain(self, reservation: Reservation, *, reason: str = "") -> AttemptRecord:
        """Close an attempt whose outcome will never be known.

        Used on resume: a record left mid-dispatch has to be billed, and the
        retry that follows needs a fresh attempt id so it is bounded by the
        remaining quota rather than inheriting the unresolved one.
        """
        with self._lock:
            record = self._require(reservation)
            if record.phase is AttemptPhase.SETTLED:
                return record
            record = replace(
                record,
                phase=AttemptPhase.SETTLED,
                outcome=AttemptOutcome.UNKNOWN,
                settled_at=self._clock(),
                usage_available=False,
                detail=reason or "outcome_unknown",
            )
            self._records[record.attempt_key()] = record
            return record

    def _require(self, reservation: Reservation) -> AttemptRecord:
        record = self._records.get(reservation.key())
        if record is None:
            raise BudgetConflictError(
                f"no budget record for reservation {reservation.key()}"
            )
        return record

    # -- reporting --------------------------------------------------------

    def stage_durations_ms(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(sorted(self._stage_durations_ms.items()))

    def termination_reason(self) -> str | None:
        return self._termination_reason

    def set_termination_reason(self, reason: str) -> None:
        with self._lock:
            self._termination_reason = reason

    def uncertain_attempts(self) -> tuple[AttemptRecord, ...]:
        """Attempts whose consumption must be assumed on a later resume."""
        with self._lock:
            return tuple(
                record
                for record in self._records.values()
                if record.outcome is AttemptOutcome.UNKNOWN
                or (
                    record.phase is AttemptPhase.DISPATCHED
                    and record.outcome is AttemptOutcome.RELEASED
                )
            )

    def reconcile_uncertain(self) -> tuple[AttemptRecord, ...]:
        """Bill every attempt left unresolved by an interruption.

        A process that died mid-call leaves a record in ``DISPATCHED``.  On the
        next run that record describes a request the provider may have
        served, so it is settled as unknown -- and therefore consumed -- before
        anything new is scheduled.  Reservations that never dispatched are
        released instead, since those provably spent nothing.
        """
        settled: list[AttemptRecord] = []
        with self._lock:
            for key, record in list(self._records.items()):
                if record.phase is AttemptPhase.RESERVED:
                    updated = replace(
                        record,
                        phase=AttemptPhase.SETTLED,
                        outcome=AttemptOutcome.RELEASED,
                        settled_at=self._clock(),
                        detail="reservation_not_dispatched_before_interruption",
                    )
                    self._records[key] = updated
                    settled.append(updated)
                elif record.phase is AttemptPhase.DISPATCHED:
                    updated = replace(
                        record,
                        phase=AttemptPhase.SETTLED,
                        outcome=AttemptOutcome.UNKNOWN,
                        settled_at=self._clock(),
                        usage_available=False,
                        detail="dispatched_without_settlement_before_interruption",
                    )
                    self._records[key] = updated
                    settled.append(updated)
        return tuple(settled)

    def usage_snapshot(
        self,
        *,
        model_usage_available: bool = True,
        termination_reason: str | None = None,
    ) -> Any:
        """Project the ledger onto the canonical ``BudgetUsage`` model.

        Token totals are summed only from attempts that actually reported them.
        If any attempt's usage is unknown the aggregate is reported as
        unavailable, because a partial sum presented as a total is how a cost
        regression stays hidden.
        """
        from tradingagents.agents.schemas._catalyst_research import BudgetUsage

        with self._lock:
            records = tuple(self._records.values())
            consumed = [item for item in records if item.counts_against_budget()]
            tokens_known = all(
                item.usage_available
                and item.input_tokens is not None
                and item.output_tokens is not None
                for item in consumed
            )
            input_tokens = (
                sum(int(item.input_tokens or 0) for item in consumed)
                if tokens_known and consumed
                else None
            )
            output_tokens = (
                sum(int(item.output_tokens or 0) for item in consumed)
                if tokens_known and consumed
                else None
            )
            return BudgetUsage(
                model_attempts=self.consumed(BudgetBucket.MODEL_ATTEMPTS),
                structured_output_repairs=self.consumed(BudgetBucket.STRUCTURED_REPAIR),
                network_retries=self.consumed(BudgetBucket.NETWORK_RETRY),
                data_capability_calls=self.consumed(BudgetBucket.DATA_CAPABILITY_CALLS),
                http_attempts=self.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS),
                semantic_preprocess_calls=self.consumed(BudgetBucket.SEMANTIC_PREPROCESS),
                model_usage_available=bool(tokens_known and model_usage_available),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                stage_durations_ms=self.stage_durations_ms(),
                termination_reason=(
                    termination_reason
                    if termination_reason is not None
                    else self._termination_reason
                ),
            )


class BudgetConflictError(RuntimeError):
    """The same key arrived twice with different content.

    Design SS5.4 requires that the same id with different content is an
    explicit conflict rather than a silent overwrite; the same rule applies to
    a spend that is already recorded.
    """


# ---------------------------------------------------------------------------
# Per-run ledger registry
# ---------------------------------------------------------------------------

_LEDGER_LOCK = threading.Lock()
_LEDGERS: dict[str, BudgetLedger] = {}


def register_ledger(ledger: BudgetLedger) -> BudgetLedger:
    """Publish a ledger so role code can find the one belonging to its run.

    The design requires run configuration and provenance to cross executor and
    thread boundaries explicitly rather than through ambient state, so the
    registry is keyed by ``run_id`` and is only ever written by the runner that
    owns the run.  A second registration for the same run is a conflict: two
    owners for one ledger would each believe they own the whole budget.
    """
    with _LEDGER_LOCK:
        existing = _LEDGERS.get(ledger.run_id)
        if existing is not None and existing is not ledger:
            raise BudgetConflictError(
                f"run {ledger.run_id!r} already has a different budget ledger"
            )
        _LEDGERS[ledger.run_id] = ledger
        return ledger


def ledger_for_run(run_id: str) -> BudgetLedger | None:
    with _LEDGER_LOCK:
        return _LEDGERS.get(run_id)


def release_ledger(run_id: str) -> None:
    with _LEDGER_LOCK:
        _LEDGERS.pop(run_id, None)


def clear_ledgers() -> None:
    """Drop every registered ledger. Test-only; a live run never needs it."""
    with _LEDGER_LOCK:
        _LEDGERS.clear()
