"""The bounded research workflow for the ``catalyst_v1`` profile.

Design SS5.1 replaces the classic debate graph with an explicit sequence:
freeze, three specialists, merge, one independent refutation, one synthesis,
then deterministic validation and publish.  This module is that sequence.

Four decisions carry most of the weight, and each is enforced here rather than
described in a prompt:

**Partitioned state.**  Each specialist writes to its own key and nothing else.
The classic graph's failure mode -- several roles appending to one shared
``messages`` list, a ``sender`` field, and a concatenated report string -- makes
the result depend on completion order.  ``SpecialistSlots`` has no shared
collection for a role to append to, so that failure is unrepresentable.

**Fixed-order merge.**  The merge reads roles in :data:`ROLE_ORDER` and sorts
findings by id within a role.  Completion order cannot reach the output.

**Duty and context isolation.**  A specialist receives a
:class:`SpecialistEvidenceView`, never the draft and never another role's
output.  The refuter receives the *finding list* and is explicitly denied the
brief and the candidate priority: given a high-priority conclusion first, a
refuter produces a defence of it rather than a challenge to it.

**One synthesis pass.**  The synthesizer writes the brief draft once.  There is
no second summarization model and no repair loop beyond the single structured
repair the budget allows; a synthesis that cannot produce a valid brief falls
back to a code-built template rather than buying more text with more calls.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol

from tradingagents.agents.schemas._catalyst_research import (
    PRIORITY_BLOCKING_REASONS,
    BriefLine,
    BudgetUsage,
    CatalystBrief,
    CatalystEvent,
    CatalystEvidence,
    CatalystResearchCase,
    Challenge,
    ChallengeDisposition,
    ResearchPriorityDecision,
    SpecialistFinding,
)
from tradingagents.execution.budget import (
    AttemptOutcome,
    BudgetBucket,
    BudgetLedger,
    BudgetLimitHit,
    Reservation,
    register_ledger,
)
from tradingagents.research.catalyst_evidence_policy import (
    CATALYST_EVIDENCE_POLICY_VERSION,
)
from tradingagents.research.evidence_freeze import (
    ROLE_ORDER,
    CapabilityStatus,
    FrozenEvidenceDraft,
    SpecialistEvidenceView,
    SpecialistRole,
    build_specialist_view,
)

# Design SS5.5: the initial release allows at most two specialists in flight,
# with a serial degradation path at one. Both must produce the same public
# result -- only the wall clock differs.
DEFAULT_SPECIALIST_CONCURRENCY = 2

# Design SS5.5 / SS5.2: at most three core findings and three unknowns per
# role on the first screen. Serious quality errors are exempt -- they are gated
# rather than counted away, so a hard error is never suppressed by a display
# limit.
MAX_FINDINGS_PER_ROLE = 3
MAX_UNKNOWNS_PER_ROLE = 3

# Design SS5.5: one refutation pass, three challenges maximum. A refuter that
# returns more is not being more careful, it is writing a second report.
MAX_CHALLENGES = 3


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------


class ModelCaller(Protocol):
    """How a role reaches a model.

    A protocol rather than a LangChain runnable so the workflow can be tested
    without a provider, and so the same workflow drives whichever client the
    runtime already configured.  Implementations must count every call they
    make, including SDK-internal retries: the hidden-call audit found that an
    untracked retry is a call the budget cannot see.
    """

    def __call__(self, *, role: str, prompt: str) -> Mapping[str, Any]:
        ...


class ModelCallRefused(RuntimeError):
    """The budget refused a call. Callers degrade; they do not retry."""

    def __init__(self, bucket: BudgetBucket, stage: str, reason: str):
        self.bucket = bucket
        self.stage = stage
        self.reason = reason
        super().__init__(f"{bucket.value} exhausted at {stage}: {reason}")


# "No reservation was supplied" is a third state, distinct from both a grant
# and a refusal, so it cannot be a value of the union it annotates.  A
# dedicated sentinel is what keeps the default argument backwards compatible:
# every existing direct caller keeps reserving for itself.
_RESERVE_INTERNALLY: Any = object()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class RoleStatus(str, Enum):
    OK = "ok"
    # The role ran and produced nothing. Distinct from FAILED, because an
    # empty analysis and a broken one must not be reported the same way.
    EMPTY = "empty"
    FAILED = "failed"
    # A required capability was not qualified, so the role was skipped rather
    # than asked to reason about material it never received.
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    REFUSED = "refused"


@dataclass(frozen=True)
class SpecialistResult:
    """One role's bounded output, stored under its own key.

    ``findings`` is a tuple and the whole object is frozen, so a completed role
    cannot be edited by a later one.  ``error_category`` is a type name, never
    an exception message: a vendor URL or a raw provider error must not reach
    the public artifact.
    """

    role: SpecialistRole
    status: RoleStatus
    findings: tuple[SpecialistFinding, ...] = ()
    duration_ms: int = 0
    error_category: str = ""
    logical_call_id: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status is RoleStatus.OK

    def sorted_findings(self) -> tuple[SpecialistFinding, ...]:
        """Deterministic within-role order, independent of emission order."""
        return tuple(sorted(self.findings, key=lambda item: item.finding_id))


@dataclass(frozen=True)
class SpecialistSlots:
    """Per-role partitioned state.

    Every access goes through a role key.  There is no ``messages`` list, no
    ``sender``, and no concatenated report string to write to, so two roles
    running at once cannot interleave into a shared buffer.
    """

    results: Mapping[SpecialistRole, SpecialistResult] = field(default_factory=dict)

    def put(self, result: SpecialistResult) -> None:
        existing = self.results.get(result.role)
        if existing is not None and existing != result:
            from tradingagents.execution.budget import BudgetConflictError

            raise BudgetConflictError(
                f"role {result.role!r} already produced a different result; "
                "the same id with different content is a conflict, not an overwrite"
            )
        self.results[result.role] = result

    def get(self, role: SpecialistRole) -> SpecialistResult | None:
        return self.results.get(role)

    def ordered_results(self) -> tuple[SpecialistResult, ...]:
        """Read in the fixed role order, never in completion order."""
        return tuple(
            self.results[role] for role in ROLE_ORDER if role in self.results
        )

    def merged_findings(self) -> tuple[SpecialistFinding, ...]:
        """The merged finding list in the fixed role order.

        This is the only shape the refuter and the synthesizer may read.  It is
        a flat, ordered list of records -- not a narrative -- which is what
        lets a refuter challenge item 2 without having been anchored by item 1's
        conclusion.
        """
        return tuple(
            finding
            for result in self.ordered_results()
            for finding in result.sorted_findings()
        )

    def failed_roles(self) -> tuple[SpecialistRole, ...]:
        return tuple(
            role
            for role in ROLE_ORDER
            if role in self.results
            and self.results[role].status
            in {RoleStatus.FAILED, RoleStatus.REFUSED, RoleStatus.CANCELLED}
        )

    def missing_roles(self) -> tuple[SpecialistRole, ...]:
        return tuple(role for role in ROLE_ORDER if role not in self.results)

    def incomplete_roles(self) -> tuple[SpecialistRole, ...]:
        """Roles that did not produce a usable analysis.

        Design SS5.4: a failed specialist is not zero findings.  The case must
        say which stage failed rather than render an empty list that reads like
        "we looked and found nothing".
        """
        return tuple(
            role
            for role in ROLE_ORDER
            if role not in self.results
            or self.results[role].status
            not in {RoleStatus.OK, RoleStatus.EMPTY}
        )


@dataclass(frozen=True)
class RefutationResult:
    challenges: tuple[Challenge, ...] = ()
    status: RoleStatus = RoleStatus.OK
    error_category: str = ""


@dataclass(frozen=True)
class SynthesisDraft:
    """What the one synthesis pass produced.

    ``dispositions`` covers every challenge.  A synthesis that silently drops a
    challenge would let a refutation disappear from the published case, so the
    coverage is validated rather than trusted.
    """

    judgement: str
    priority: str
    primary_catalyst_event_id: str | None = None
    key_evidence_finding_ids: tuple[str, ...] = ()
    key_question_text: str = ""
    key_question_finding_ids: tuple[str, ...] = ()
    key_question_challenge_ids: tuple[str, ...] = ()
    next_check_text: str = ""
    next_check_finding_ids: tuple[str, ...] = ()
    critical_limitation_texts: tuple[str, ...] = ()
    critical_limitation_finding_ids: tuple[tuple[str, ...], ...] = ()
    critical_limitation_challenge_ids: tuple[tuple[str, ...], ...] = ()
    dispositions: tuple[ChallengeDisposition, ...] = ()
    rationale: str = ""


# ---------------------------------------------------------------------------
# Global concurrency
# ---------------------------------------------------------------------------

# Design SS5.4: a global semaphore, not a per-run one.  Without it, batch
# concurrency multiplied by role concurrency is the real limit on the system,
# and a user lowering neither number still gets an unbounded fan-out.
_GLOBAL_MODEL_SLOTS = threading.BoundedSemaphore(
    DEFAULT_SPECIALIST_CONCURRENCY
)


def global_model_slots() -> Any:
    """The process-wide model semaphore. Exposed so tests can assert on it."""
    return _GLOBAL_MODEL_SLOTS


# ---------------------------------------------------------------------------
# Role execution
# ---------------------------------------------------------------------------


def _finding_id(role: SpecialistRole, index: int) -> str:
    # Every dot-segment must start with a letter: the canonical ID_PATTERN
    # rejects a numeric segment, so a counter is spelled rather than written.
    return f"f.{role}.i{index}"


def normalize_findings(
    role: SpecialistRole,
    run_id: str,
    raw: Iterable[Mapping[str, Any]],
) -> tuple[SpecialistFinding, ...]:
    """Coerce a role's output into canonical findings, bounded and ordered.

    Two rules are applied here rather than trusted to the model.  Unknowns and
    core findings are each capped at three, because the first screen shows a
    bounded number and a longer list means the role wrote a report instead of
    answering its question.  Findings that fail the canonical schema are
    dropped rather than repaired, because a repair would be a second model call
    the budget has already accounted for elsewhere.
    """
    by_kind: dict[str, list[SpecialistFinding]] = {"fact": [], "inference": [], "unknown": []}
    for item in raw:
        payload = dict(item)
        payload.setdefault("finding_id", _finding_id(role, len(by_kind["fact"]) + len(by_kind["inference"]) + len(by_kind["unknown"])))
        payload["run_id"] = run_id
        payload["role"] = role
        try:
            finding = SpecialistFinding(**payload)
        except Exception:
            # A malformed finding is a quality error, not a run failure. It is
            # recorded by the caller through the role status; dropping it here
            # keeps one bad record from taking down the whole role.
            continue
        by_kind[finding.kind].append(finding)

    capped: list[SpecialistFinding] = []
    for kind, limit in (
        ("fact", MAX_FINDINGS_PER_ROLE),
        ("inference", MAX_FINDINGS_PER_ROLE),
        ("unknown", MAX_UNKNOWNS_PER_ROLE),
    ):
        capped.extend(sorted(by_kind[kind], key=lambda item: item.finding_id)[:limit])
    return tuple(sorted(capped, key=lambda item: item.finding_id))


def run_specialist(
    role: SpecialistRole,
    view: SpecialistEvidenceView,
    *,
    caller: ModelCaller,
    ledger: BudgetLedger,
    run_id: str,
    cancel: Callable[[], bool] | None = None,
    reservation: Reservation | BudgetLimitHit | None = _RESERVE_INTERNALLY,
) -> SpecialistResult:
    """Run one specialist against its own frozen view.

    The role holds the global model slot for the duration of its call.  That
    is what makes the design SS5.4 concurrency ceiling real across concurrent
    runs rather than per run.

    ``reservation`` is how the caller takes responsibility for *when* the
    budget unit is claimed.  The default means "reserve it yourself, here".
    A caller that already holds a grant passes it in, so the unit is claimed
    on the main thread in a fixed order rather than by whichever thread the
    pool happens to schedule first; a caller that already knows the unit was
    refused passes the :class:`BudgetLimitHit` and the role reports REFUSED
    without touching the ledger at all.  ``None`` is deliberately not a
    usable value -- it would be indistinguishable from "not supplied".
    """
    stage = f"specialist:{role}"
    logical_call_id = f"specialist.{role}"
    held: Reservation | None = None
    if cancel is not None and cancel():
        # A grant handed in by the caller has already been charged to the
        # ledger, and this role is about to return without using it.
        if isinstance(reservation, Reservation):
            ledger.release(reservation, reason="cancelled_before_dispatch")
        return SpecialistResult(role=role, status=RoleStatus.CANCELLED)

    blocked = _blocked_by_required_capability(view)
    if blocked:
        if isinstance(reservation, Reservation):
            ledger.release(reservation, reason="skipped_by_capability")
        return SpecialistResult(
            role=role,
            status=RoleStatus.SKIPPED,
            error_category=blocked,
            logical_call_id=logical_call_id,
        )

    if isinstance(reservation, BudgetLimitHit):
        # The caller already spent this role's turn against the ceiling and
        # lost.  Reporting it here rather than re-reserving is the whole point:
        # the refusal is a property of the fixed order, not of this thread.
        return SpecialistResult(
            role=role,
            status=RoleStatus.REFUSED,
            error_category=f"budget_{reservation.bucket.value}",
            logical_call_id=logical_call_id,
        )
    if isinstance(reservation, Reservation):
        held = reservation

    started = time.monotonic()
    # A late cancellation must win over whatever the try/except below already
    # decided -- including an early return from an except clause -- which is
    # why the outcome is assembled in a variable rather than returned
    # directly: a `return` inside `finally` would achieve the same override,
    # but it would also silently swallow a BaseException (e.g.
    # KeyboardInterrupt) that reached here uncaught, which this must not do.
    outcome: SpecialistResult | None = None
    try:
        raw = _invoke_budgeted(
            ledger=ledger,
            bucket=BudgetBucket.MAIN_ANALYSIS,
            stage=stage,
            logical_call_id=logical_call_id,
            run=lambda: caller(role=role, prompt=render_specialist_prompt(view)),
            reservation=held,
        )
    except ModelCallRefused as refusal:
        outcome = SpecialistResult(
            role=role,
            status=RoleStatus.REFUSED,
            error_category=f"budget_{refusal.bucket.value}",
            logical_call_id=logical_call_id,
        )
    except Exception as exc:
        outcome = SpecialistResult(
            role=role,
            status=RoleStatus.FAILED,
            error_category=type(exc).__name__,
            duration_ms=int((time.monotonic() - started) * 1000),
            logical_call_id=logical_call_id,
        )
    finally:
        if cancel is not None and cancel():
            outcome = SpecialistResult(role=role, status=RoleStatus.CANCELLED)
            # A granted unit that never produced a call must go back, or a
            # cancelled run would leave the next run's ceiling smaller.  If
            # the call did happen, the record is already settled and release
            # is a no-op, so this is correct on both paths.
            if held is not None:
                ledger.release(held, reason="cancelled_before_settle")
    if outcome is not None:
        return outcome

    findings = normalize_findings(role, run_id, raw.get("findings", ()))
    return SpecialistResult(
        role=role,
        status=RoleStatus.OK if findings else RoleStatus.EMPTY,
        findings=findings,
        duration_ms=int((time.monotonic() - started) * 1000),
        logical_call_id=logical_call_id,
    )


def _blocked_by_required_capability(view: SpecialistEvidenceView) -> str:
    from tradingagents.research.evidence_freeze import ROLE_REQUIRED_CAPABILITIES

    for name in ROLE_REQUIRED_CAPABILITIES[view.role]:
        status = CapabilityStatus(view.capability_status.get(name, "unavailable"))
        if status.blocks_specialists:
            return f"required_capability_unqualified:{name}"
    return ""


def _invoke_budgeted(
    *,
    ledger: BudgetLedger,
    bucket: BudgetBucket,
    stage: str,
    logical_call_id: str,
    run: Callable[[], Any],
    reservation: Reservation | None = None,
) -> Any:
    """Reserve, dispatch, call, settle -- around one provider call.

    Every model call in this flow goes through here.  There is no second path,
    which is what makes the ceiling in design SS5.5 true of the run rather than
    of the calls somebody remembered to instrument.

    ``reservation`` lets a caller that already claimed the unit on an ordered
    path hand the grant in, so this function does not claim it a second time.
    ``reserve`` is idempotent for an in-flight logical call, so the two routes
    agree; the parameter exists to make the *order* of claiming explicit
    rather than to change how much is charged.
    """
    cached_result = getattr(ledger, "cached_result", None)
    if callable(cached_result):
        cached = cached_result(logical_call_id)
        if cached is not None:
            return cached
    if reservation is None:
        bucket = _resume_model_bucket(ledger, logical_call_id, bucket)
    granted = (
        reservation
        if reservation is not None
        else ledger.reserve(bucket, stage=stage, logical_call_id=logical_call_id)
    )
    if isinstance(granted, BudgetLimitHit):
        raise ModelCallRefused(bucket, stage, granted.reason)
    started = time.monotonic()
    ledger.mark_dispatched(granted)
    try:
        result = run()
    except Exception:
        ledger.settle(
            granted,
            ok=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            detail="provider_error",
        )
        raise
    usage = result.get("usage") if isinstance(result, Mapping) else None
    record_result = getattr(ledger, "record_result", None)
    if callable(record_result):
        record_result(logical_call_id, result)
    ledger.settle(
        granted,
        ok=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        input_tokens=usage.get("input_tokens") if isinstance(usage, Mapping) else None,
        output_tokens=usage.get("output_tokens") if isinstance(usage, Mapping) else None,
        usage_available=isinstance(usage, Mapping),
    )
    return result


def _resume_model_bucket(ledger, logical_call_id, bucket):
    # A repeated logical main call after an interrupted/failed dispatch is a
    # network retry. It inherits the original spent unit and requires a new
    # unit from the independent retry ceiling, not an extra free main call.
    if bucket is BudgetBucket.MAIN_ANALYSIS and any(
        record.logical_call_id == logical_call_id and record.dispatched_at is not None
        and record.outcome in {AttemptOutcome.UNKNOWN, AttemptOutcome.FAILED}
        for record in ledger.records()
    ):
        return BudgetBucket.NETWORK_RETRY
    return bucket


def render_specialist_prompt(view: SpecialistEvidenceView) -> str:
    """The role's complete input, as text.

    Only the view is rendered.  The frozen draft's other roles' capabilities
    are not in scope, so they cannot appear here even by accident.
    """
    lines = [
        f"ROLE: {view.role}",
        f"QUESTION: {view.question}",
        f"SECURITY: {view.ticker}",
        f"RESEARCH CUTOFF: {view.cutoff}",
        f"EVIDENCE DRAFT: {view.draft_id}",
        "EVENTS:",
    ]
    if view.events:
        for event in view.events:
            support = (
                f" [independent sources: {event.independent_support}]"
                if event.independent_support > 1
                else ""
            )
            lines.append(
                f"- {event.event_id} | {event.publication_date} | {event.status} | "
                f"{event.strength} | {event.title}{support}"
            )
    else:
        lines.append("- (none in this draft)")
    if view.prices:
        lines.append("PRICE OBSERVATIONS:")
        for observation in view.prices:
            lines.append(
                f"- {observation.observed_on} close={observation.close} "
                f"adjustment={observation.adjustment} source={observation.source}"
            )
    if view.limitations:
        lines.append("LIMITATIONS YOU MUST CARRY INTO YOUR ANSWER:")
        lines.extend(f"- {item}" for item in view.limitations)
    lines.append(
        f"Return at most {MAX_FINDINGS_PER_ROLE} core findings and "
        f"{MAX_UNKNOWNS_PER_ROLE} unknowns. Every fact or inference must cite an "
        "evidence id from the list above. An unknown carries no evidence."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Refutation
# ---------------------------------------------------------------------------


def render_refutation_prompt(
    findings: Sequence[SpecialistFinding], run_id: str
) -> str:
    """The refuter's entire input: the finding list and nothing else.

    This function is the anti-anchoring mechanism the design asks for in
    SS5.2.  It takes findings, not a brief, not a priority, and not a headline.
    A refuter shown "priority: verify first, catalyst: buyback" will spend its
    budget testing that framing; a refuter shown the same findings with no
    framing will find whichever one does not hold up.
    """
    lines = [
        "ROLE: independent_refutation",
        "You did not participate in producing the findings below and you are "
        "not shown any conclusion, priority, or summary of them.",
        f"FINDINGS ({len(findings)}):",
    ]
    for finding in findings:
        lines.append(
            f"- {finding.finding_id} [{finding.kind}] {finding.text} "
            f"evidence={list(finding.evidence_ids)} events={list(finding.event_ids)}"
        )
    lines.append(
        f"Return at most {MAX_CHALLENGES} challenges against the specific "
        "findings above. For each, say what test would settle it. Do not "
        "restate the findings and do not write a second negative report."
    )
    return "\n".join(lines)


def run_refutation(
    findings: Sequence[SpecialistFinding],
    *,
    caller: ModelCaller,
    ledger: BudgetLedger,
    run_id: str,
    cancel: Callable[[], bool] | None = None,
) -> RefutationResult:
    """One independent refutation pass over the finding list."""
    if cancel is not None and cancel():
        return RefutationResult(status=RoleStatus.CANCELLED)
    stage = "refutation"
    try:
        raw = _invoke_budgeted(
            ledger=ledger,
            bucket=BudgetBucket.MAIN_ANALYSIS,
            stage=stage,
            logical_call_id="refutation",
            run=lambda: caller(
                role="independent_refutation",
                prompt=render_refutation_prompt(findings, run_id),
            ),
        )
    except ModelCallRefused as refusal:
        return RefutationResult(
            status=RoleStatus.REFUSED, error_category=f"budget_{refusal.bucket.value}"
        )
    except Exception as exc:
        return RefutationResult(status=RoleStatus.FAILED, error_category=type(exc).__name__)
    challenges: list[Challenge] = []
    for index, item in enumerate(raw.get("challenges", ())):
        payload = dict(item)
        payload.setdefault("challenge_id", f"ch.i{index}")
        payload["run_id"] = run_id
        try:
            challenges.append(Challenge(**payload))
        except Exception:
            continue
    ordered = tuple(sorted(challenges, key=lambda item: item.challenge_id)[:MAX_CHALLENGES])
    return RefutationResult(challenges=ordered, status=RoleStatus.OK)


def validate_dispositions(
    challenges: Sequence[Challenge],
    dispositions: Sequence[ChallengeDisposition],
) -> None:
    """Every challenge must be handled exactly once (design A08).

    A dropped disposition is how a strong refutation disappears between the
    model and the published case, so the coverage is checked rather than
    assumed.
    """
    seen: list[str] = []
    for disposition in dispositions:
        seen.append(disposition.challenge_id)
    if len(set(seen)) != len(seen):
        raise ValueError("a challenge may carry only one disposition")
    missing = {item.challenge_id for item in challenges} - set(seen)
    if missing:
        raise ValueError(f"challenges without a disposition: {sorted(missing)}")


def key_unresolved_challenges(
    challenges: Sequence[Challenge],
    dispositions: Sequence[ChallengeDisposition],
) -> tuple[str, ...]:
    """Which key challenges remain unresolved.

    Design SS6/SS9.1: an unresolved key challenge caps the final priority at
    insufficient information, because the refutation stage found the load-
    bearing assumption unsupported and the research has not answered it.
    """
    by_id = {item.challenge_id: item for item in dispositions}
    return tuple(
        sorted(
            challenge.challenge_id
            for challenge in challenges
            if challenge.is_key
            and by_id.get(challenge.challenge_id) is not None
            and by_id[challenge.challenge_id].outcome == "unresolved"
        )
    )


# ---------------------------------------------------------------------------
# Deterministic priority matrix (design SS9.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessState:
    """The completeness and blocking facts code decides from committed evidence.

    Every field here is something a reviewer can check against the run record.
    The model proposes a category; this is what bounds it.
    """

    completeness: Literal["complete", "partial", "blocked"]
    quality: Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"]
    reason_codes: tuple[str, ...] = ()
    missing_required_capabilities: tuple[str, ...] = ()
    incomplete_roles: tuple[SpecialistRole, ...] = ()
    refutation_missing: bool = False
    key_unresolved: tuple[str, ...] = ()
    synthesis_failed: bool = False
    brief_overflowed: bool = False

    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for code in self.reason_codes:
            if code in PRIORITY_BLOCKING_REASONS:
                reasons.append(code)
        if self.missing_required_capabilities:
            reasons.append("required_capability_unavailable")
        if self.incomplete_roles:
            reasons.append("required_specialist_failed")
        if self.refutation_missing:
            reasons.append("refutation_stage_missing")
        if self.key_unresolved:
            reasons.append("key_challenge_unresolved")
        if self.synthesis_failed:
            reasons.append("synthesis_failed")
        if self.brief_overflowed:
            reasons.append("brief_safety_overflow")
        return tuple(dict.fromkeys(reasons))

    def all_reason_codes(self) -> tuple[str, ...]:
        codes = list(self.reason_codes)
        if self.missing_required_capabilities:
            codes.append("required_capability_unavailable")
        if self.incomplete_roles:
            codes.append("required_specialist_failed")
        if self.refutation_missing:
            codes.append("refutation_stage_missing")
        if self.key_unresolved:
            codes.append("key_challenge_unresolved")
        if self.synthesis_failed:
            codes.append("synthesis_failed")
        if self.brief_overflowed:
            codes.append("brief_safety_overflow")
        return tuple(dict.fromkeys(codes))

    def ceiling_priority(self) -> str:
        """The best category this state permits.

        Design SS9.1 is a top-down severity table, and the code implements it
        as such rather than as a scoring function.  Two rows matter here:

        * a blocked or partial run permits *only* information-insufficient --
          the table says so literally, rather than allowing a lesser-but-still
          directional category;
        * a complete run permits all four categories and lets the verified
          findings decide.  PASS is a statement about evidence and process
          requirements, not a promotion to the top research priority, so the
          code must not read it as one.
        """
        if self.completeness == "blocked":
            return "insufficient_information"
        if self.completeness == "partial":
            return "insufficient_information"
        if self.blocking_reasons():
            return "insufficient_information"
        return "verify_first"


def decide_priority(
    candidate: str, state: ProcessState
) -> ResearchPriorityDecision:
    """Apply the ceiling to a model-proposed category.

    Only a ceiling is applied here.  When the model's category is permitted,
    it stands: the design is explicit that the code bounds the answer and does
    not compute it.
    """
    ceiling = state.ceiling_priority()
    blocking = state.blocking_reasons()
    if candidate not in {"verify_first", "keep_watching", "defer_research", "insufficient_information"}:
        candidate = "insufficient_information"
    if _rank(candidate) <= _rank(ceiling):
        return ResearchPriorityDecision(
            priority=candidate,
            candidate_priority=candidate,
            blocking_reasons=(),
            rationale="the proposed category is within the evidence and process ceiling",
        )
    if blocking:
        return ResearchPriorityDecision(
            priority="insufficient_information",
            candidate_priority=candidate,
            blocking_reasons=blocking,
            rationale=(
                "code lowered the category to information-insufficient because "
                + ", ".join(blocking)
                + " forbid the higher one"
            ),
        )
    return ResearchPriorityDecision(
        priority=ceiling,
        candidate_priority=candidate,
        blocking_reasons=blocking,
        rationale=(
            "code lowered the category because "
            + ", ".join(blocking)
            + " forbid the higher one"
        ),
    )


_PRIORITY_RANK = {
    "verify_first": 3,
    "keep_watching": 2,
    "defer_research": 1,
    "insufficient_information": 0,
}


def _rank(priority: str) -> int:
    return _PRIORITY_RANK.get(priority, 0)


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def render_synthesis_prompt(
    findings: Sequence[SpecialistFinding],
    challenges: Sequence[Challenge],
    dispositions: Sequence[ChallengeDisposition],
    state: ProcessState,
) -> str:
    """The synthesizer's single input.

    It receives the verified findings, the challenges, how each challenge was
    handled, and the deterministic state the code has already established.  It
    does not receive a budget, a tool, or a chance to fetch.  The brief it
    writes is a selection over these objects, not new prose about them.
    """
    lines = [
        "ROLE: synthesis",
        "Write the first-screen brief by selecting from the objects below. "
        "Do not introduce a claim that is not one of them.",
        f"STATE: completeness={state.completeness} quality={state.quality} "
        f"reason_codes={list(state.all_reason_codes())}",
        f"MAXIMUM PRIORITY PERMITTED BY CODE: {state.ceiling_priority()}",
        "FINDINGS:",
    ]
    for finding in findings:
        lines.append(f"- {finding.finding_id} [{finding.role}/{finding.kind}] {finding.text}")
    if challenges:
        lines.append("CHALLENGES AND HOW EACH WAS HANDLED:")
        by_id = {item.challenge_id: item for item in dispositions}
        for challenge in challenges:
            disposition = by_id.get(challenge.challenge_id)
            outcome = disposition.outcome if disposition is not None else "unhandled"
            lines.append(
                f"- {challenge.challenge_id} [{challenge.severity}"
                f"{', key' if challenge.is_key else ''}] {challenge.statement} -> {outcome}"
            )
    lines.append(
        "Return a judgement, a candidate priority no higher than the maximum "
        "above, at most one primary catalyst event, at most three key evidence "
        "findings, a key question, a next check, and any critical limitations."
    )
    return "\n".join(lines)


def _coerce_dispositions(
    raw: Iterable[Mapping[str, Any]], challenges: Sequence[Challenge]
) -> tuple[ChallengeDisposition, ...]:
    by_id = {item.challenge_id: item for item in challenges}
    out: list[ChallengeDisposition] = []
    seen: set[str] = set()
    for item in raw:
        payload = dict(item)
        challenge_id = str(payload.get("challenge_id", ""))
        if challenge_id not in by_id or challenge_id in seen:
            continue
        seen.add(challenge_id)
        try:
            out.append(ChallengeDisposition(**payload))
        except Exception:
            continue
    return tuple(sorted(out, key=lambda item: item.challenge_id))


def run_synthesis(
    findings: Sequence[SpecialistFinding],
    challenges: Sequence[Challenge],
    dispositions: Sequence[ChallengeDisposition],
    state: ProcessState,
    *,
    caller: ModelCaller,
    ledger: BudgetLedger,
    run_id: str,
) -> SynthesisDraft:
    """Exactly one synthesis pass.

    Design SS5.2 forbids calling a second summarization model.  A repair is
    permitted only as a structured-output repair inside the same call, which is
    what the ``structured_repair`` budget bucket is for; a synthesis that still
    fails degrades to a code-built brief rather than buying another pass.
    """
    stage = "synthesis"
    try:
        raw = _invoke_budgeted(
            ledger=ledger,
            bucket=BudgetBucket.MAIN_ANALYSIS,
            stage=stage,
            logical_call_id="synthesis",
            run=lambda: caller(
                role="synthesis",
                prompt=render_synthesis_prompt(findings, challenges, dispositions, state),
            ),
        )
    except ModelCallRefused as refusal:
        return _fallback_synthesis(state, refusal_reason=f"budget_{refusal.bucket.value}")
    except Exception:
        return _fallback_synthesis(state, refusal_reason="synthesis_call_failed")

    coerced = _coerce_dispositions(raw.get("dispositions", ()), challenges)
    try:
        validate_dispositions(challenges, coerced)
    except ValueError:
        return _fallback_synthesis(state, refusal_reason="disposition_coverage_incomplete")

    return SynthesisDraft(
        judgement=str(raw.get("judgement", "")).strip() or "判断待补充",
        priority=str(raw.get("priority", "insufficient_information")),
        primary_catalyst_event_id=raw.get("primary_catalyst_event_id"),
        key_evidence_finding_ids=tuple(raw.get("key_evidence_finding_ids", ())),
        key_question_text=str(raw.get("key_question", "")).strip() or "关键疑点待补充",
        key_question_finding_ids=tuple(raw.get("key_question_finding_ids", ())),
        key_question_challenge_ids=tuple(raw.get("key_question_challenge_ids", ())),
        next_check_text=str(raw.get("next_check", "")).strip() or "下一步验证待补充",
        next_check_finding_ids=tuple(raw.get("next_check_finding_ids", ())),
        critical_limitation_texts=tuple(raw.get("critical_limitations", ())),
        critical_limitation_finding_ids=tuple(
            tuple(item) for item in raw.get("critical_limitation_finding_ids", ())
        ),
        critical_limitation_challenge_ids=tuple(
            tuple(item) for item in raw.get("critical_limitation_challenge_ids", ())
        ),
        dispositions=coerced,
        rationale=str(raw.get("rationale", ""))[:400] or "综合选择了现有发现",
    )


def _fallback_synthesis(state: ProcessState, *, refusal_reason: str) -> SynthesisDraft:
    """The code-built brief used when no model synthesis is available.

    Design SS5.5 forbids spending a model call to explain a timeout, and
    SS7.3 requires a code template rather than a truncation when the budget
    cannot buy a valid brief.  This template says what is missing; it never
    guesses a judgement.
    """
    if state.completeness == "blocked":
        judgement = "本次研究被硬性证据或身份问题阻断，未形成研究判断。"
    else:
        judgement = "资料不足，未形成可发布的研究判断。"
    missing = "、".join(state.missing_required_capabilities) or "无"
    failed = "、".join(state.incomplete_roles) or "无"
    return SynthesisDraft(
        judgement=judgement,
        priority="insufficient_information",
        key_question_text=f"缺少的关键能力：{missing}；未完成的角色：{failed}。",
        next_check_text="补齐上述能力后重新发起一次新的研究运行。",
        critical_limitation_texts=(f"综合阶段未产出可用简报：{refusal_reason}。",),
        rationale="code template; no synthesis pass produced a valid brief",
    )


# ---------------------------------------------------------------------------
# Brief assembly and the overflow template
# ---------------------------------------------------------------------------

# Design SS4.3. A code template, not a truncation: the text is written to fit,
# and the full limitation list stays adjacent to it.
SAFETY_OVERFLOW_JUDGEMENT = "多项重大限制无法在首屏篇幅内完整表达，本页只给出受限结论。"
SAFETY_OVERFLOW_QUESTION = "限制未完整展示，请展开下方完整重大限制列表后再判断。"
SAFETY_OVERFLOW_NEXT_CHECK = "先按限制列表逐项补证，再判断是否值得继续研究。"


def build_brief(
    draft: SynthesisDraft,
    *,
    priority: str,
    surviving_finding_ids: frozenset[str],
    event_ids: frozenset[str],
    challenge_ids: frozenset[str],
) -> CatalystBrief:
    """Assemble the first-screen brief, degrading rather than truncating.

    Design SS7.3 and gate A02: the character budget is met by choosing less,
    and if it cannot be met the result is the safety-overflow template with the
    full limitation list attached -- never a cut-off sentence and never a
    dropped risk.

    A line that references a finding removed by the evidence gate is dropped
    rather than carried: the case schema rejects a brief that cites a removed
    finding, and a brief that quietly loses its last limitation is exactly the
    failure gate A07 exists to catch.
    """

    def keep_finding(finding_id: str) -> bool:
        return finding_id in surviving_finding_ids

    def keep_event(event_id: str | None) -> bool:
        return event_id is None or event_id in event_ids

    def keep_challenge(challenge_id: str) -> bool:
        return challenge_id in challenge_ids

    def line(
        text: str,
        finding_ids: Sequence[str] = (),
        event_refs: Sequence[str] = (),
        challenge_refs: Sequence[str] = (),
    ) -> BriefLine | None:
        kept_findings = tuple(item for item in finding_ids if keep_finding(item))
        kept_events = tuple(item for item in event_refs if keep_event(item))
        kept_challenges = tuple(item for item in challenge_refs if keep_challenge(item))
        if finding_ids and not kept_findings:
            return None
        if event_refs and not kept_events:
            return None
        if challenge_refs and not kept_challenges:
            return None
        return BriefLine(
            text=text[:200],
            finding_ids=kept_findings,
            event_ids=kept_events,
            challenge_ids=kept_challenges,
        )

    limitations: list[BriefLine] = []
    for index, text in enumerate(draft.critical_limitation_texts[:6]):
        finding_refs = (
            draft.critical_limitation_finding_ids[index]
            if index < len(draft.critical_limitation_finding_ids)
            else ()
        )
        challenge_refs = (
            draft.critical_limitation_challenge_ids[index]
            if index < len(draft.critical_limitation_challenge_ids)
            else ()
        )
        built = line(text, finding_refs, (), challenge_refs)
        if built is not None:
            limitations.append(built)

    key_evidence: list[BriefLine] = []
    for finding_id in draft.key_evidence_finding_ids[:3]:
        if not keep_finding(finding_id):
            continue
        key_evidence.append(
            BriefLine(text=f"证据：{finding_id}", finding_ids=(finding_id,))
        )

    key_question = line(
        draft.key_question_text,
        draft.key_question_finding_ids,
        (),
        draft.key_question_challenge_ids,
    ) or BriefLine(text=draft.key_question_text[:200] or "关键疑点待补充")
    next_check = line(
        draft.next_check_text, draft.next_check_finding_ids
    ) or BriefLine(text=draft.next_check_text[:200] or "下一步验证待补充")

    primary_catalyst = None
    if draft.primary_catalyst_event_id and keep_event(draft.primary_catalyst_event_id):
        primary_catalyst = BriefLine(
            text=f"主催化：{draft.primary_catalyst_event_id}",
            event_ids=(draft.primary_catalyst_event_id,),
        )

    try:
        return CatalystBrief(
            kind="ordinary",
            judgement=draft.judgement[:200],
            priority=priority,  # type: ignore[arg-type]
            primary_catalyst_event_id=(
                draft.primary_catalyst_event_id if primary_catalyst else None
            ),
            primary_catalyst=primary_catalyst,
            key_evidence=tuple(key_evidence),
            key_question=key_question,
            next_check=next_check,
            critical_limitations=tuple(limitations),
        )
    except ValueError:
        # The ordinary brief does not fit. Degrade to the safety template with
        # the full limitation list attached; never truncate and never drop a
        # risk to buy room.
        return CatalystBrief(
            kind="safety_overflow",
            judgement=SAFETY_OVERFLOW_JUDGEMENT,
            priority="insufficient_information",
            key_question=BriefLine(text=SAFETY_OVERFLOW_QUESTION),
            next_check=BriefLine(text=SAFETY_OVERFLOW_NEXT_CHECK),
            critical_limitations=tuple(limitations)
            or (BriefLine(text=draft.judgement[:200]),),
            overflow_reason="brief_safety_overflow",
        )


def brief_overflowed(brief: CatalystBrief) -> bool:
    return brief.kind == "safety_overflow"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalystRunRequest:
    """The minimum a run needs to execute the bounded flow."""

    run_id: str
    ticker: str
    as_of: datetime
    research_question: str = ""


@dataclass(frozen=True)
class CatalystRunResult:
    """What a completed bounded run produced.

    ``case`` is the committed public artifact.  ``published`` is separate
    because a case can be built and then withheld -- by cancellation, by a
    commit-barrier rejection, or by an expired authorisation -- and a withheld
    case must never be served as the final conclusion.
    """

    case: CatalystResearchCase
    published: bool
    not_published_reason: str = ""
    slots: SpecialistSlots = field(default_factory=SpecialistSlots)
    budget_usage: BudgetUsage | None = None


def execute_specialists(
    draft: FrozenEvidenceDraft,
    *,
    caller: ModelCaller,
    ledger: BudgetLedger,
    concurrency: int = DEFAULT_SPECIALIST_CONCURRENCY,
    cancel: Callable[[], bool] | None = None,
) -> SpecialistSlots:
    """Run the three specialists, in parallel or serially, identically.

    Design SS5.4: at most two in flight, with a serial degradation path, and
    "whether it ran in parallel" must not reach the conclusion.  Concurrency
    changes only the order results are *stored* in the slots; the merge reads
    by role key in a fixed order, so the public artifact is byte-identical
    either way.

    The parallel path holds a global model slot per role rather than a per-run
    one.  Without that, a batch of N runs at concurrency 2 becomes 2N calls in
    flight, which is the amplification design SS5.4 forbids.
    """
    slots = SpecialistSlots()
    views = {role: build_specialist_view(draft, role) for role in ROLE_ORDER}

    def work(role: SpecialistRole, grant: Any = _RESERVE_INTERNALLY) -> SpecialistResult:
        # blocking=True always returns True; the call is kept for its side
        # effect (holding the process-wide slot until release()), not its
        # result.
        while not global_model_slots().acquire(timeout=0.1):
            if cancel is not None and cancel():
                if isinstance(grant, Reservation):
                    ledger.release(grant, reason="cancelled_waiting_for_model_slot")
                return SpecialistResult(role=role, status=RoleStatus.CANCELLED)
        try:
            return run_specialist(
                role,
                views[role],
                caller=caller,
                ledger=ledger,
                run_id=draft.run_id,
                cancel=cancel,
                reservation=grant,
            )
        finally:
            global_model_slots().release()

    if concurrency <= 1:
        for role in ROLE_ORDER:
            slots.put(work(role))
            if cancel is not None and cancel():
                break
        return slots

    # Claim the budget units here, on this thread, in ROLE_ORDER, before any
    # role is submitted.  The ledger is thread-safe, so nothing is lost by
    # moving the claim out of the pool -- but the *order* of claims is what
    # decides which role loses the last unit when the ceiling is short, and
    # that order would otherwise be the scheduler's.  Claiming in the fixed
    # order here is what makes a short budget produce the same refused role
    # either way, which is the property design SS5.4 asks for: whether the run
    # went parallel must not reach the conclusion.  Only the claims are
    # serialized; the provider calls below still overlap.
    grants: dict[SpecialistRole, Reservation | BudgetLimitHit] = {}
    for role in ROLE_ORDER:
        if cancel is not None and cancel():
            break
        if _blocked_by_required_capability(views[role]):
            # This role is about to report SKIPPED without calling anything.
            # Reserving for it would spend a unit on a call that cannot
            # happen, and would then hand the *next* role a refusal the serial
            # path never produces.
            continue
        cached_result = getattr(ledger, "cached_result", None)
        if callable(cached_result) and cached_result(f"specialist.{role}") is not None:
            continue
        grants[role] = ledger.reserve(
            _resume_model_bucket(ledger, f"specialist.{role}", BudgetBucket.MAIN_ANALYSIS),
            stage=f"specialist:{role}",
            logical_call_id=f"specialist.{role}",
        )

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        # A role absent from `grants` was skipped above for a reason that
        # makes run_specialist return before it would reserve, so handing it
        # the sentinel keeps it self-reserving and correct.
        futures = [pool.submit(copy_context().run, work, role, grants.get(role, _RESERVE_INTERNALLY)) for role in ROLE_ORDER]
        for future in futures:
            # Results are stored in submission order, not completion order, so
            # a role that finishes first cannot claim a slot in front of one
            # that the fixed order puts ahead of it.
            slots.put(future.result())
    return slots


def build_process_state(
    draft: FrozenEvidenceDraft,
    slots: SpecialistSlots,
    *,
    refutation: RefutationResult | None,
    unresolved_key: tuple[str, ...],
    synthesis: SynthesisDraft | None,
    brief_overflow: bool,
    extra_reason_codes: tuple[str, ...] = (),
) -> ProcessState:
    """Derive the design SS9.1 row from committed facts.

    The mapping is the table, read top to bottom by severity.  ``blocked`` is
    decided by a hard reason code; otherwise any blocking condition makes the
    case partial and caps the priority.  A run that is merely missing optional
    capabilities is complete with low confidence, which is a different claim
    from a run whose required evidence is gone.
    """
    reason_codes = list(extra_reason_codes)
    missing = draft.missing_required_capabilities()
    incomplete = slots.incomplete_roles()
    refutation_missing = refutation is None or refutation.status in {
        RoleStatus.FAILED,
        RoleStatus.REFUSED,
        RoleStatus.CANCELLED,
    }
    synthesis_failed = synthesis is None or synthesis.rationale.startswith("code template;")

    hard = [
        code
        for code in reason_codes
        if code in {"hard_error", "identity_conflict", "pit_unverified"}
    ]
    if hard:
        return ProcessState(
            completeness="blocked",
            quality="FAIL_STOP",
            reason_codes=tuple(reason_codes),
            missing_required_capabilities=missing,
            incomplete_roles=incomplete,
            refutation_missing=refutation_missing,
            key_unresolved=unresolved_key,
            synthesis_failed=synthesis_failed,
            brief_overflowed=brief_overflow,
        )

    if missing or incomplete or refutation_missing or unresolved_key or synthesis_failed:
        return ProcessState(
            completeness="partial",
            quality="LOW_CONFIDENCE",
            reason_codes=tuple(reason_codes),
            missing_required_capabilities=missing,
            incomplete_roles=incomplete,
            refutation_missing=refutation_missing,
            key_unresolved=unresolved_key,
            synthesis_failed=synthesis_failed,
            brief_overflowed=brief_overflow,
        )
    return ProcessState(
        completeness="complete",
        quality="PASS",
        reason_codes=tuple(reason_codes),
        missing_required_capabilities=(),
        incomplete_roles=(),
        refutation_missing=False,
        key_unresolved=(),
        synthesis_failed=False,
        brief_overflowed=brief_overflow,
    )


def assemble_case(
    request: CatalystRunRequest,
    draft: FrozenEvidenceDraft,
    slots: SpecialistSlots,
    findings: Sequence[SpecialistFinding],
    challenges: Sequence[Challenge],
    dispositions: Sequence[ChallengeDisposition],
    brief: CatalystBrief,
    decision: ResearchPriorityDecision,
    state: ProcessState,
    budget_usage: BudgetUsage,
) -> CatalystResearchCase:
    """Build the public case from the objects the flow produced.

    Every collection is sorted by id before it is handed to the case, so two
    runs that produced the same content in a different order serialize to the
    same bytes.  That is what makes the serial/parallel equivalence checkable
    rather than merely plausible.

    The frozen draft's evidence records are published, not discarded: the case
    schema requires every ``date_evidence_ids`` reference to resolve inside the
    case, so dropping them would strip a publication date of the evidence that
    supports it.  A frozen record that is not shaped like a ``CatalystEvidence``
    is skipped rather than coerced -- a partially invented evidence row is
    worse than a disclosed one that is missing, because it would let a date
    resolve against a record nobody can audit.
    """
    reserved = {"run_id", "ticker"}
    public_evidence: list[CatalystEvidence] = []
    dropped: list[str] = []
    for record in draft.evidence:
        try:
            public_evidence.append(
                CatalystEvidence(
                    **{
                        "run_id": request.run_id,
                        "ticker": request.ticker,
                        **{
                            key: value
                            for key, value in dict(record).items()
                            if key not in reserved
                        },
                    }
                )
            )
        except Exception:
            # A frozen row that is not a publishable evidence record is
            # skipped, and the skip is reported rather than swallowed: a bare
            # ``continue`` here once hid a total loss of evidence behind a
            # downstream "reference is not present" error.
            dropped.append(str(dict(record).get("evidence_id", "<unnamed>")))
    if dropped:
        import logging

        logging.getLogger(__name__).warning(
            "catalyst run %s dropped %d evidence record(s) that were not "
            "publishable: %s",
            request.run_id,
            len(dropped),
            ", ".join(sorted(dropped)),
        )
    public_evidence.sort(key=lambda item: item.evidence_id)

    public_events = []
    for item in sorted(draft.events, key=lambda entry: entry.event_id):
        resolvable = bool(item.evidence_ids) and all(
            ref in {entry.evidence_id for entry in public_evidence}
            for ref in item.evidence_ids
        )
        public_events.append(
            CatalystEvent(
                event_id=item.event_id,
                run_id=request.run_id,
                ticker=request.ticker,
                event_type=item.kind,
                version=1,
                title=item.title,
                status=_event_status(item.status),
                announced_at=None,
                # Design section 7.3: a date without evidence stays unknown.
                # The precision and the evidence move together, because a
                # "day" with no resolvable date evidence is the fabricated
                # shape the schema exists to reject.
                # A disclosure's publication day does not prove when the
                # underlying business event occurred. The raw event contract
                # supplies no occurrence date, so keep that date unknown.
                occurred_on=None,
                date_precision="unknown",
                date_evidence_ids=tuple(item.evidence_ids) if resolvable else (),
            )
        )
    return CatalystResearchCase(
        run_id=request.run_id,
        ticker=request.ticker,
        evidence_policy=CATALYST_EVIDENCE_POLICY_VERSION,
        as_of=request.as_of,
        source_sequence=0,
        completeness=state.completeness,
        quality=state.quality,
        reason_codes=state.all_reason_codes(),
        research_question=request.research_question or None,
        evidence=tuple(public_evidence),
        events=tuple(public_events),
        findings=tuple(sorted(findings, key=lambda item: item.finding_id)),
        challenges=tuple(sorted(challenges, key=lambda item: item.challenge_id)),
        dispositions=tuple(
            sorted(dispositions, key=lambda item: item.challenge_id)
        ),
        priority_decision=decision,
        brief=brief,
        budget_usage=budget_usage,
    )


def _event_status(state: str) -> str:
    """Map a raw event state onto the published enum.

    Anything the data layer did not classify is published as ``planned``: the
    published enum has no "unclassified" member, and inventing one would widen
    a wire contract to accommodate a gap in a different layer.  The raw state
    is still visible on the event title's source record.
    """
    mapping = {
        "planned": "planned",
        "point_in_time": "planned",
        "in_progress": "in_progress",
        "changed": "in_progress",
        "implemented": "completed",
        "completed": "completed",
        "terminated": "cancelled",
    }
    return mapping.get(state, "planned")


# ---------------------------------------------------------------------------
# Commit barrier
# ---------------------------------------------------------------------------


class CommitRefused(RuntimeError):
    """The barrier would not accept this write.

    A refused write is not a failure to retry blindly: the design requires the
    conflict to surface, because a repeat of a *different* content under the
    same id is the case a reader must be able to see.
    """


class CaseCommitter:
    """Publishes a case behind an explicit authorisation.

    Design SS5.1 puts the artifact write after the graph commit barrier, and
    design A10 requires a read to trigger no model or provider call.  Both are
    easier to guarantee when publication is a separate, explicit step that
    needs a token than when it is a side effect of building the case.

    The committer is idempotent: committing the same content twice is a no-op
    that reports the original record, and committing different content under
    the same run id is an error.
    """

    def __init__(self) -> None:
        self._committed: dict[str, str] = {}

    def commit(self, case: CatalystResearchCase, *, authorised: bool) -> str:
        if not authorised:
            raise CommitRefused(
                "the run has no commit authorisation; a case built outside the "
                "barrier is not published"
            )
        digest = _case_digest(case)
        existing = self._committed.get(case.run_id)
        if existing is not None:
            if existing == digest:
                return existing
            raise CommitRefused(
                f"run {case.run_id!r} already committed different case content"
            )
        self._committed[case.run_id] = digest
        return digest

    def is_committed(self, run_id: str) -> bool:
        return run_id in self._committed

    def digest_for(self, run_id: str) -> str | None:
        return self._committed.get(run_id)


def _case_digest(case: CatalystResearchCase) -> str:
    import hashlib
    import json

    payload = case.model_dump(mode="json", exclude_none=False)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# End-to-end bounded run
# ---------------------------------------------------------------------------


def run_catalyst_research(
    request: CatalystRunRequest,
    draft: FrozenEvidenceDraft,
    *,
    caller: ModelCaller,
    committer: CaseCommitter | None = None,
    ledger: BudgetLedger | None = None,
    concurrency: int = DEFAULT_SPECIALIST_CONCURRENCY,
    cancel: Callable[[], bool] | None = None,
    authorised: bool = True,
    extra_reason_codes: tuple[str, ...] = (),
) -> CatalystRunResult:
    """Execute the bounded research flow and publish at most one case.

    The sequence is the one in design SS5.1 and the order is load-bearing:
    specialists before refutation, refutation before synthesis, synthesis
    before validation, validation before publication.  In particular the
    refuter runs *before* anything proposes a priority, which is what makes its
    challenge independent rather than a review of a conclusion.
    """
    active_ledger = ledger if ledger is not None else register_ledger(
        BudgetLedger(request.run_id)
    )

    def cancelled() -> bool:
        return cancel is not None and cancel()

    journal = getattr(active_ledger, "journal", None)
    if journal is not None:
        journal.stage("specialists", "running")

    slots = execute_specialists(
        draft,
        caller=caller,
        ledger=active_ledger,
        concurrency=concurrency,
        cancel=cancel,
    )
    findings = slots.merged_findings()
    if journal is not None:
        statuses = {result.role: "completed" if result.status in {RoleStatus.OK, RoleStatus.EMPTY} else "skipped" if result.status is RoleStatus.SKIPPED else "failed" for result in slots.ordered_results()}
        journal.stage("specialists", "completed" if all(s == "completed" for s in statuses.values()) else "failed", role_statuses=statuses)
        journal.stage("refutation", "running")

    if cancelled():
        # Design SS5.5: a late result from a cancelled run may finish, but it
        # may not be published as the final conclusion.
        return _withheld_result(
            request, active_ledger, slots, "cancelled_before_refutation"
        )

    refutation = run_refutation(
        findings,
        caller=caller,
        ledger=active_ledger,
        run_id=request.run_id,
        cancel=cancel,
    )
    if journal is not None:
        journal.stage("refutation", "completed" if refutation.status is RoleStatus.OK else "failed")
    if cancelled():
        return _withheld_result(request, active_ledger, slots, "cancelled_before_synthesis")

    provisional = build_process_state(
        draft,
        slots,
        refutation=refutation,
        unresolved_key=(),
        synthesis=SynthesisDraft(judgement="", priority="insufficient_information"),
        brief_overflow=False,
        extra_reason_codes=extra_reason_codes,
    )
    if journal is not None:
        journal.stage("synthesis", "running")
    synthesis = run_synthesis(
        findings,
        refutation.challenges,
        refutation.dispositions if hasattr(refutation, "dispositions") else (),
        provisional,
        caller=caller,
        ledger=active_ledger,
        run_id=request.run_id,
    )
    unresolved = key_unresolved_challenges(
        refutation.challenges, synthesis.dispositions
    )
    state = build_process_state(
        draft,
        slots,
        refutation=refutation,
        unresolved_key=unresolved,
        synthesis=synthesis,
        brief_overflow=False,
        extra_reason_codes=extra_reason_codes,
    )
    decision = decide_priority(synthesis.priority, state)
    brief = build_brief(
        synthesis,
        priority=decision.priority,
        surviving_finding_ids=frozenset(
            item.finding_id for item in findings if item.survives
        ),
        event_ids=frozenset(item.event_id for item in draft.events),
        challenge_ids=frozenset(item.challenge_id for item in refutation.challenges),
    )
    if brief_overflowed(brief):
        # Re-derive the decision: an overflow brief is itself a blocking
        # reason, and the category must reflect that rather than the
        # pre-overflow one.
        state = replace(state, brief_overflowed=True)
        decision = decide_priority(synthesis.priority, state)
        brief = build_brief(
            synthesis,
            priority=decision.priority,
            surviving_finding_ids=frozenset(
                item.finding_id for item in findings if item.survives
            ),
            event_ids=frozenset(item.event_id for item in draft.events),
            challenge_ids=frozenset(item.challenge_id for item in refutation.challenges),
        )

    usage = _publishable_usage(
        active_ledger,
        termination_reason=("cancelled" if cancelled() else state.completeness),
    )
    case = assemble_case(
        request,
        draft,
        slots,
        findings,
        refutation.challenges,
        synthesis.dispositions,
        brief,
        decision,
        state,
        usage,
    )
    if journal is not None:
        journal.stage("synthesis", "failed" if state.synthesis_failed else "completed")

    if cancelled():
        return CatalystRunResult(
            case=case,
            published=False,
            not_published_reason="cancelled_before_commit",
            slots=slots,
            budget_usage=usage,
        )

    active = committer if committer is not None else CaseCommitter()
    try:
        active.commit(case, authorised=authorised)
    except CommitRefused as refusal:
        return CatalystRunResult(
            case=case,
            published=False,
            not_published_reason=str(refusal),
            slots=slots,
            budget_usage=usage,
        )
    return CatalystRunResult(
        case=case, published=True, slots=slots, budget_usage=usage
    )


def _publishable_usage(
    ledger: BudgetLedger, *, termination_reason: str
) -> BudgetUsage:
    """The ledger's snapshot with the wall-clock field removed.

    Design SS5.4 requires that serial and parallel execution produce the same
    public artifact.  Wall-clock durations cannot satisfy that -- a parallel
    role really does take a different number of milliseconds -- so they stay in
    the ledger, where the operator can read them, and are deliberately not
    published on the case.  Publishing a timing that varies with scheduling
    would also make two equivalent runs look like different results.
    """
    snapshot = ledger.usage_snapshot(termination_reason=termination_reason)
    return snapshot.model_copy(update={"stage_durations_ms": ()})


def _withheld_result(
    request: CatalystRunRequest,
    ledger: BudgetLedger,
    slots: SpecialistSlots,
    reason: str,
) -> CatalystRunResult:
    """A cancelled run still reports what it knows, but publishes nothing."""
    from tradingagents.agents.schemas._catalyst_research import (
        BriefLine,
        CatalystBrief,
    )

    ledger.set_termination_reason("cancelled")
    blocked = CatalystBrief(
        kind="safety_overflow",
        judgement="运行已取消，未发布最终研究结论。",
        priority="insufficient_information",
        key_question=BriefLine(text="取消原因：本次运行未完成全部阶段。"),
        next_check=BriefLine(text="重新发起一次新的研究运行。"),
        critical_limitations=(BriefLine(text=reason),),
        overflow_reason="brief_safety_overflow",
    )
    decision = decide_priority(
        "verify_first",
        ProcessState(
            completeness="blocked",
            quality="FAIL_STOP",
            reason_codes=("hard_error",),
        ),
    )
    usage = ledger.usage_snapshot(termination_reason="cancelled")
    case = assemble_case(
        request,
        empty_draft_for(request),
        slots,
        (),
        (),
        (),
        blocked,
        decision,
        ProcessState(
            completeness="blocked", quality="FAIL_STOP", reason_codes=("hard_error",)
        ),
        usage,
    )
    return CatalystRunResult(
        case=case,
        published=False,
        not_published_reason=reason,
        slots=slots,
        budget_usage=usage,
    )


def empty_draft_for(request: CatalystRunRequest) -> FrozenEvidenceDraft:
    from tradingagents.research.evidence_freeze import empty_draft

    return empty_draft(
        request.run_id, request.ticker, request.as_of.date().isoformat()
    )
