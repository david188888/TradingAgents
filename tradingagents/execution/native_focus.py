"""One optional, durable response after the independent baseline is frozen."""

import time

from pydantic import ValidationError

from tradingagents.agents.schemas._research_focus import (
    FocusProposalV1,
    ResearchFocusResponseV1,
    validate_focus_proposal,
    validate_focus_response,
)
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.budget import BudgetBucket, BudgetConflictError, BudgetLimitHit
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.execution.native_model import NativeFocusInvalid, NativeModelCancelled
from tradingagents.research.focus_context import focus_context, focus_identity
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

FOCUS_LOGICAL = "native.focus_response"


def bind_focus(journal, key, value):
    with journal.lock:
        if key in journal.state and journal.state[key] != value:
            raise CatalystCheckpointConflict("native focus frontier changed")
        if key not in journal.state:
            journal.put(key, value)


def execute_focus_response(record, focus, *, ledger, caller, cancelled, deadline,
                           output_language="Chinese", model_policy_sha256=None):
    """No collector or baseline writer is exposed to this execution unit."""
    if focus is None:
        return None
    if not isinstance(focus, str) or focus != focus.strip() or not 1 <= len(focus) <= 400:
        raise ValueError("focus requires normalized 1..400 characters")
    journal = ledger.journal
    digest = canonical_sha256(record)
    baseline = ledger.cached_result("native.output")
    if (record.assessment is None or baseline is None
            or canonical_sha256(ResearchRecordV1.model_validate(baseline["record"])) != digest):
        raise CatalystCheckpointConflict("focus requires a durable assessed baseline")
    bind_focus(journal, "native_base_record_sha256", digest)
    context = focus_context(record, focus, output_language)
    identity = focus_identity(context, model_policy_sha256)
    bind_focus(journal, "native_focus_input", identity)
    cached = ledger.cached_result(FOCUS_LOGICAL)
    if cached is not None:
        if cached.get("identity") != identity:
            raise CatalystCheckpointConflict("native focus output identity mismatch")
        response = ResearchFocusResponseV1.model_validate(cached["response"])
        validate_focus_response(record, response)
        if response.focus != focus:
            raise CatalystCheckpointConflict("native focus text mismatch")
        return response

    def save(proposal=None, reason=None):
        if canonical_sha256(record) != digest:
            raise CatalystCheckpointConflict("native focus changed baseline")
        response = ResearchFocusResponseV1(
            run_id=record.run_id, ticker=record.ticker, mode=record.mode,
            analysis_date=record.analysis_date, input_snapshot_id=record.assessment.input_snapshot_id,
            base_record_sha256=digest, focus=focus,
            status="available" if proposal is not None else "unavailable",
            proposal=proposal, reason_code=reason,
        )
        validate_focus_response(record, response)
        ledger.record_result(FOCUS_LOGICAL, {"identity": identity, "response": response.model_dump(mode="json")})
        return response

    if cancelled():
        raise AnalysisCancelled()
    recover = getattr(caller, "recover_cached", None)
    saved = recover("focus_response", context) if callable(recover) else None
    if saved is not None:
        proposal = FocusProposalV1.model_validate(saved)
        validate_focus_proposal(record, proposal)
        return save(proposal)
    if any(r.logical_call_id == FOCUS_LOGICAL and r.dispatched_at is not None for r in ledger.records()):
        return save(reason="response_unknown")
    if "native_synthesis_unavailable" in record.limitations:
        return save(reason="base_synthesis_unavailable")
    if time.monotonic() >= deadline():
        return save(reason="deadline_exceeded")
    grant = ledger.reserve(BudgetBucket.FOCUS_RESPONSE, stage=FOCUS_LOGICAL, logical_call_id=FOCUS_LOGICAL)
    if isinstance(grant, BudgetLimitHit):
        return save(reason="budget_exhausted")
    try:
        if cancelled():
            ledger.release(grant)
            raise AnalysisCancelled()
        if time.monotonic() >= deadline():
            ledger.release(grant)
            return save(reason="deadline_exceeded")
        ledger.mark_dispatched(grant)
        value = caller("focus_response", context)
        if cancelled():
            raise AnalysisCancelled()
        proposal = FocusProposalV1.model_validate(value)
        validate_focus_proposal(record, proposal)
    except (AnalysisCancelled, CatalystCheckpointConflict, BudgetConflictError):
        raise
    except Exception as exc:
        if journal.failed:
            raise
        if cancelled():
            raise AnalysisCancelled() from None
        reason = ("deadline_exceeded" if time.monotonic() >= deadline() or isinstance(exc, (TimeoutError, NativeModelCancelled))
                  else "invalid_response" if isinstance(exc, (ValidationError, ValueError, NativeFocusInvalid))
                  else "model_failed")
        ledger.settle(grant, ok=False, usage_available=False, detail=reason)
        return save(reason=reason)
    ledger.settle(grant, ok=True, usage_available=False)
    return save(proposal)
