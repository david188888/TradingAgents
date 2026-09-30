"""Budget ledger behaviour for the bounded research flow (plan T20).

The tests here are mostly negative on purpose.  A budget that is only ever
exercised on the happy path proves nothing, because the failure mode -- a
ceiling that quietly overspends, or a resume that quietly refunds a run's
spend -- looks exactly like success from the outside.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from tradingagents.execution.budget import (
    DEFAULT_LIMITS,
    AttemptOutcome,
    AttemptPhase,
    BudgetBucket,
    BudgetConflictError,
    BudgetExhausted,
    BudgetLedger,
    BudgetLimitHit,
    clear_ledgers,
    ledger_for_run,
    register_ledger,
)


def _ledger(run_id: str = "run_1", **limits: int) -> BudgetLedger:
    merged = dict(DEFAULT_LIMITS)
    merged.update(limits)
    return BudgetLedger(run_id, limits=merged)


def _spend(ledger: BudgetLedger, stage: str, count: int, **kwargs) -> None:
    for index in range(count):
        reservation = ledger.reserve(
            kwargs.pop("bucket", BudgetBucket.MAIN_ANALYSIS),
            stage=stage,
            logical_call_id=f"{stage}-{index}-{id(ledger)}",
        )
        assert not isinstance(reservation, BudgetLimitHit)
        ledger.mark_dispatched(reservation)
        ledger.settle(reservation, ok=True, **kwargs)


# -- ceilings ---------------------------------------------------------------


def test_reserve_refuses_once_the_ceiling_is_reached() -> None:
    ledger = _ledger(main_analysis=1)
    first = ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="specialist")
    assert not isinstance(first, BudgetLimitHit)
    ledger.mark_dispatched(first)
    ledger.settle(first, ok=True)

    second = ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="specialist")
    assert isinstance(second, BudgetLimitHit)
    assert second.limit == 1
    assert second.consumed == 1
    assert second.reason == "run_limit_reached"


def test_released_reservation_does_not_consume_quota() -> None:
    """A held unit that never became a call must be spendable again.

    Without this, one cancelled specialist would permanently shrink the
    remaining budget and a later legitimate call would be refused for a call
    that never happened.
    """
    ledger = _ledger(main_analysis=1)
    held = ledger.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="specialist")
    ledger.release(held, reason="cancelled before dispatch")
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0

    again = ledger.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="specialist")
    ledger.mark_dispatched(again)
    ledger.settle(again, ok=True)
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1


def test_failed_call_still_consumes_quota() -> None:
    """A network failure is a spent attempt.

    Design SS5.5 counts failed calls; refunding them would let a run retry
    indefinitely against a ceiling that only ever charges for successes.
    """
    ledger = _ledger(main_analysis=1)
    reservation = ledger.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="specialist")
    ledger.mark_dispatched(reservation)
    ledger.settle(reservation, ok=False, detail="connection reset")

    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert isinstance(
        ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="specialist"),
        BudgetLimitHit,
    )


def test_structured_repair_is_capped_per_stage_and_per_run() -> None:
    """Design SS5.5: two repairs per run, one per stage.

    Without the per-stage cap, one stage could burn both repairs and the other
    stage would have none -- while still looking compliant with the run total.
    """
    ledger = _ledger()
    for stage in ("specialist:catalyst_events", "specialist:market_reaction"):
        grant = ledger.reserve(BudgetBucket.STRUCTURED_REPAIR, stage=stage)
        assert not isinstance(grant, BudgetLimitHit)
        ledger.mark_dispatched(grant)
        ledger.settle(grant, ok=True)

    third = ledger.reserve(
        BudgetBucket.STRUCTURED_REPAIR, stage="specialist:catalyst_events"
    )
    assert isinstance(third, BudgetLimitHit)
    assert third.reason == "per_stage_limit_reached"
    assert third.limit == 1


def test_repair_also_consumes_the_run_wide_model_attempt_total() -> None:
    """A repair is a real model call, not a free side channel.

    If repairs did not roll up, a run could take 5 main analyses plus 2
    repairs and still describe itself as within the "12 total attempts" cap
    while actually having made 7 model calls through two separate budgets.
    """
    ledger = _ledger(model_attempts=1)
    grant = ledger.reserve_or_raise(BudgetBucket.STRUCTURED_REPAIR, stage="synthesis")
    ledger.mark_dispatched(grant)
    ledger.settle(grant, ok=True)

    assert ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 1
    assert isinstance(
        ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="synthesis"),
        BudgetLimitHit,
    )


def test_model_bucket_rollup_uses_the_strongest_ceiling() -> None:
    """A run-wide total must be able to refuse a per-bucket-legal call."""
    ledger = _ledger(model_attempts=2, main_analysis=5)
    _spend(ledger, "a", 1)
    _spend(ledger, "b", 1)
    hit = ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="c")
    assert isinstance(hit, BudgetLimitHit)
    assert hit.reason == "total_model_attempts_reached"
    assert ledger.remaining(BudgetBucket.MAIN_ANALYSIS) == 0


def test_exhausted_raises_with_a_structured_reason() -> None:
    """The design forbids spending a second model call to explain a timeout."""
    ledger = _ledger(main_analysis=0)
    with pytest.raises(BudgetExhausted) as error:
        ledger.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="specialist")
    assert error.value.hit.bucket is BudgetBucket.MAIN_ANALYSIS
    assert error.value.hit.as_dict()["reason"] == "run_limit_reached"


# -- concurrency ------------------------------------------------------------


def test_concurrent_reservations_never_overspend() -> None:
    """Atomic decrement under the specialist fan-out (design SS5.4).

    Twenty threads race for five units. A check-then-act implementation lets
    every thread observe "4 used" before any of them writes, so the run makes
    far more than five calls. The assertion is on the *number of grants*, not
    on the absence of an exception.
    """
    ledger = _ledger(main_analysis=5, model_attempts=100)
    grants: list[object] = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def worker() -> None:
        barrier.wait()
        result = ledger.reserve(
            BudgetBucket.MAIN_ANALYSIS,
            stage="specialist",
            logical_call_id=f"call-{threading.get_ident()}",
        )
        with lock:
            grants.append(result)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    granted = [item for item in grants if not isinstance(item, BudgetLimitHit)]
    assert len(granted) == 5
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 5
    assert len(grants) - len(granted) == 15


def test_reservation_idempotent_for_a_repeated_logical_call() -> None:
    """Replaying a logical task must not buy a second unit.

    Design SS5.4 requires that resubmitting the same content be a no-op; the
    same rule applied to spend is what keeps a retry loop from draining a run.
    """
    ledger = _ledger(main_analysis=1)
    first = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    second = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    assert first.attempt_id == second.attempt_id
    assert len(ledger.records()) == 1


# -- resume -----------------------------------------------------------------


def test_resume_inherits_consumed_quota() -> None:
    """Design SS5.5: a restored run must not reset to zero.

    The failure this catches is the expensive one: a resumed run that starts
    with a full budget can make 5 main analyses, fail, resume, and make 5 more,
    for a total the user never authorised.
    """
    ledger = _ledger(main_analysis=5)
    _spend(ledger, "specialist", 3)
    records = ledger.records()

    resumed = BudgetLedger("run_1", records=records)
    assert resumed.consumed(BudgetBucket.MAIN_ANALYSIS) == 3
    assert resumed.remaining(BudgetBucket.MAIN_ANALYSIS) == 2
    assert isinstance(
        resumed.reserve(BudgetBucket.MAIN_ANALYSIS, stage="specialist"),
        BudgetLimitHit,
    ) is False


def test_resume_bills_an_unresolved_dispatch_as_consumed() -> None:
    """A request that was sent and never resolved may still have been billed.

    Design SS5.5 is explicit: unknown state counts as consumed. Treating it as
    free would let a run resume into an unbounded number of real charges.
    """
    ledger = _ledger(main_analysis=5)
    reservation = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    ledger.mark_dispatched(reservation)
    # Simulate a process that died here: the record stays DISPATCHED.
    interrupted = ledger.records()

    resumed = BudgetLedger("run_1", records=interrupted)
    settled = resumed.reconcile_uncertain()
    assert len(settled) == 1
    assert settled[0].outcome is AttemptOutcome.UNKNOWN
    assert settled[0].counts_against_budget() is True
    assert resumed.consumed(BudgetBucket.MAIN_ANALYSIS) == 1


def test_resume_releases_a_reservation_that_never_dispatched() -> None:
    """A unit held but never sent provably cost nothing and is refundable."""
    ledger = _ledger(main_analysis=1)
    ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    resumed = BudgetLedger("run_1", records=ledger.records())
    resumed.reconcile_uncertain()
    assert resumed.consumed(BudgetBucket.MAIN_ANALYSIS) == 0
    resumed.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-2"
    )


def test_retry_after_an_uncertain_attempt_uses_a_new_attempt_id() -> None:
    """Design SS5.5: a retry is a new attempt bounded by remaining quota.

    Reusing the unresolved attempt's id would let one indeterminate call be
    retried under cover of a key the ledger already considers spent.
    """
    ledger = _ledger(main_analysis=5)
    first = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    ledger.mark_dispatched(first)
    resumed = BudgetLedger("run_1", records=ledger.records())
    resumed.reconcile_uncertain()

    retry = resumed.reserve_or_raise(
        BudgetBucket.NETWORK_RETRY, stage="specialist", logical_call_id="task-1"
    )
    assert retry.attempt_id != first.attempt_id
    assert resumed.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert resumed.consumed(BudgetBucket.NETWORK_RETRY) == 1


def test_resume_rejects_a_conflicting_record_for_the_same_key() -> None:
    """Same id, different content is a conflict, not a merge (design SS5.4)."""
    ledger = _ledger()
    reservation = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    ledger.mark_dispatched(reservation)
    ledger.settle(reservation, ok=True)
    original = ledger.records()[0]
    tampered = replace(original, outcome=AttemptOutcome.FAILED)
    assert tampered.attempt_key() == original.attempt_key()
    with pytest.raises(BudgetConflictError):
        BudgetLedger("run_1", records=[original, tampered])


def test_resume_rejects_a_record_from_another_run() -> None:
    """Cross-run contamination is the failure design A11 exists to catch."""
    ledger = _ledger()
    reservation = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist", logical_call_id="task-1"
    )
    ledger.mark_dispatched(reservation)
    ledger.settle(reservation, ok=True)
    with pytest.raises(ValueError):
        BudgetLedger("other_run", records=ledger.records())


# -- usage accounting -------------------------------------------------------


def test_missing_token_usage_is_recorded_unknown_never_zero() -> None:
    """A provider that reports nothing must not look free (design SS5.5)."""
    ledger = _ledger()
    reservation = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="specialist"
    )
    ledger.mark_dispatched(reservation)
    ledger.settle(
        reservation,
        ok=True,
        input_tokens=None,
        output_tokens=None,
        usage_available=False,
    )
    usage = ledger.usage_snapshot()
    assert usage.model_usage_available is False
    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_aggregate_usage_is_unavailable_when_any_attempt_is_unknown() -> None:
    """A partial token sum presented as a total hides cost regressions."""
    ledger = _ledger()
    first = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="a", logical_call_id="a"
    )
    ledger.mark_dispatched(first)
    ledger.settle(first, ok=True, input_tokens=10, output_tokens=5)
    second = ledger.reserve_or_raise(
        BudgetBucket.MAIN_ANALYSIS, stage="b", logical_call_id="b"
    )
    ledger.mark_dispatched(second)
    ledger.settle(second, ok=True, usage_available=False)

    usage = ledger.usage_snapshot()
    assert usage.model_usage_available is False
    assert usage.input_tokens is None


def test_usage_snapshot_reports_ledger_counters() -> None:
    ledger = _ledger()
    _spend(ledger, "specialist", 2, input_tokens=10, output_tokens=4, duration_ms=25)
    usage = ledger.usage_snapshot(termination_reason="completed")
    assert usage.model_attempts == 2
    assert usage.semantic_preprocess_calls == 0
    assert usage.stage_durations_ms == (("specialist", 50),)
    assert usage.termination_reason == "completed"


def test_model_attempts_total_counts_every_model_bucket() -> None:
    ledger = _ledger()
    for bucket, stage in (
        (BudgetBucket.MAIN_ANALYSIS, "a"),
        (BudgetBucket.SEMANTIC_PREPROCESS, "b"),
        (BudgetBucket.STRUCTURED_REPAIR, "c"),
        (BudgetBucket.NETWORK_RETRY, "d"),
    ):
        grant = ledger.reserve_or_raise(bucket, stage=stage, logical_call_id=stage)
        ledger.mark_dispatched(grant)
        ledger.settle(grant, ok=True)
    assert ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 4


# -- registry ---------------------------------------------------------------


def test_registry_refuses_two_owners_for_one_run() -> None:
    clear_ledgers()
    try:
        first = register_ledger(_ledger("run_x"))
        assert ledger_for_run("run_x") is first
        register_ledger(first)  # idempotent
        with pytest.raises(BudgetConflictError):
            register_ledger(_ledger("run_x"))
    finally:
        clear_ledgers()


def test_ledger_is_not_shared_between_runs() -> None:
    a, b = _ledger("run_a", main_analysis=1), _ledger("run_b", main_analysis=1)
    a.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="s")
    assert b.consumed(BudgetBucket.MAIN_ANALYSIS) == 0
    assert isinstance(
        b.reserve(BudgetBucket.MAIN_ANALYSIS, stage="s"), BudgetLimitHit
    ) is False


def test_record_phase_transitions_are_monotonic() -> None:
    """A settle after a re-dispatch must not rewrite a settled outcome."""
    ledger = _ledger()
    reservation = ledger.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="s")
    assert reservation.record.phase is AttemptPhase.RESERVED
    ledger.mark_dispatched(reservation)
    settled = ledger.settle(reservation, ok=True)
    assert settled.phase is AttemptPhase.SETTLED
    assert settled.outcome is AttemptOutcome.OK
    # Re-settling is a no-op rather than a second write.
    assert ledger.settle(reservation, ok=False).outcome is AttemptOutcome.OK
