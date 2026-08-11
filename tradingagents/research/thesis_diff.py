"""Deterministic cross-run thesis diffing for the learning research reader.

The ``ThesisLedger`` is not a separate mutable database.  It is a deterministic
selection over already-committed runs: given the current run's ``ResearchCaseV2``
it finds the immediately preceding, same-ticker/same-horizon, completed and
parseable research case and produces an immutable ``ThesisDiffV1`` artifact.

The diff is structural, not semantic: claim keys are matched exactly (no fuzzy
similarity), text/evidence/confidence/status changes are derived from the public
claim fields, and a claim that simply disappears from the new case is recorded as
``not_reassessed`` rather than guessed to be invalidated.  No LLM is involved and
a diff failure must never affect the research case or run completion.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from tradingagents.agents.schemas._research_case import (
    PublicClaim,
    ResearchCaseV2,
    _PublicModel,
)

logger = logging.getLogger(__name__)

RESEARCH_CASE_CONTRACT = "research-case-v2"
THESIS_DIFF_CONTRACT = "thesis-diff-v1"

DiffKind = Literal[
    "new", "maintained", "invalidated", "unresolved", "not_reassessed"
]
ClaimType = Literal["fact", "inference", "unknown"]
ClaimLifecycle = Literal["active", "resolved", "invalidated"]
ChangeFlag = Literal[
    "text_changed", "evidence_changed", "confidence_changed", "status_changed"
]

# confidence is considered changed only when it moves by more than this much
_CONFIDENCE_EPSILON = 0.01
_WHITESPACE_RE = re.compile(r"\s+")


class ThesisDiffEntry(_PublicModel):
    """One claim's structural change between two research cases."""

    claim_key: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){3}$")
    diff_kind: DiffKind
    previous_claim_type: ClaimType | None = None
    current_claim_type: ClaimType | None = None
    previous_text: str | None = Field(default=None, max_length=1200)
    current_text: str | None = Field(default=None, max_length=1200)
    previous_confidence: float | None = Field(default=None, ge=0, le=1)
    current_confidence: float | None = Field(default=None, ge=0, le=1)
    previous_lifecycle_status: ClaimLifecycle | None = None
    current_lifecycle_status: ClaimLifecycle | None = None
    change_flags: tuple[ChangeFlag, ...] = ()
    counter_evidence_ref_ids: tuple[str, ...] = ()


class ThesisDiffV1(_PublicModel):
    """Immutable comparison of a research case against its prior baseline."""

    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    horizon: Literal["short", "medium", "long"]
    current_research_case_artifact_id: str = Field(min_length=1, max_length=512)
    previous_research_case_artifact_id: str | None = None
    previous_run_id: str | None = Field(default=None, max_length=128)
    baseline_completed_at: str | None = None
    entries: tuple[ThesisDiffEntry, ...] = ()

    @model_validator(mode="after")
    def _validate_invalidation(self) -> ThesisDiffV1:
        for entry in self.entries:
            if entry.diff_kind == "invalidated" and not entry.counter_evidence_ref_ids:
                raise ValueError(
                    "invalidated thesis entries must cite counter evidence"
                )
        return self


def _normalize_text(value: str) -> str:
    """Trim, Unicode-NFC normalize and collapse internal whitespace."""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", value)).strip()


def _evidence_set(claim: PublicClaim) -> tuple[str, ...]:
    return tuple(sorted(claim.evidence_ref_ids))


def _confidence_changed(previous: float | None, current: float | None) -> bool:
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    return abs(previous - current) > _CONFIDENCE_EPSILON


def _diff_one_claim(
    *,
    key: str,
    current: PublicClaim | None,
    previous: PublicClaim | None,
) -> ThesisDiffEntry:
    if current is None:
        # A key present in the baseline but absent in the new case is never
        # auto-invalidated; it simply was not reassessed this run.
        assert previous is not None
        return ThesisDiffEntry(
            claim_key=key,
            diff_kind="not_reassessed",
            previous_claim_type=previous.claim_type,
            current_claim_type=None,
            previous_text=previous.text,
            current_text=None,
            previous_confidence=previous.confidence,
            current_confidence=None,
            previous_lifecycle_status=previous.lifecycle_status,
            current_lifecycle_status=None,
            change_flags=(),
        )

    if previous is None:
        if current.claim_type == "unknown":
            kind: DiffKind = "unresolved"
        elif current.lifecycle_status == "invalidated":
            kind = "invalidated"
        else:
            kind = "new"
        return ThesisDiffEntry(
            claim_key=key,
            diff_kind=kind,
            previous_claim_type=None,
            current_claim_type=current.claim_type,
            previous_text=None,
            current_text=current.text,
            previous_confidence=None,
            current_confidence=current.confidence,
            previous_lifecycle_status=None,
            current_lifecycle_status=current.lifecycle_status,
            change_flags=(),
            counter_evidence_ref_ids=(
                tuple(current.evidence_ref_ids) if kind == "invalidated" else ()
            ),
        )

    # Key exists in both cases -> derive the kind and change flags.
    if previous.lifecycle_status == "invalidated" and current.lifecycle_status == "invalidated":
        kind = "maintained"
    elif current.claim_type == "unknown" and previous.lifecycle_status != "invalidated":
        kind = "unresolved"
    elif current.lifecycle_status == "invalidated":
        kind = "invalidated"
    else:
        kind = "maintained"

    flags: list[ChangeFlag] = []
    if _normalize_text(previous.text) != _normalize_text(current.text):
        flags.append("text_changed")
    if _evidence_set(previous) != _evidence_set(current):
        flags.append("evidence_changed")
    if _confidence_changed(previous.confidence, current.confidence):
        flags.append("confidence_changed")
    if previous.lifecycle_status != current.lifecycle_status:
        flags.append("status_changed")

    return ThesisDiffEntry(
        claim_key=key,
        diff_kind=kind,
        previous_claim_type=previous.claim_type,
        current_claim_type=current.claim_type,
        previous_text=previous.text,
        current_text=current.text,
        previous_confidence=previous.confidence,
        current_confidence=current.confidence,
        previous_lifecycle_status=previous.lifecycle_status,
        current_lifecycle_status=current.lifecycle_status,
        change_flags=tuple(flags),
        counter_evidence_ref_ids=(
            tuple(current.evidence_ref_ids)
            if kind == "invalidated"
            or (
                kind == "maintained"
                and current.lifecycle_status == "invalidated"
            )
            else ()
        ),
    )


def compute_thesis_diff(
    *,
    run_id: str,
    current_case: ResearchCaseV2,
    current_case_artifact_id: str,
    previous_case: ResearchCaseV2 | None,
    previous_case_artifact_id: str | None = None,
    previous_run_id: str | None = None,
    baseline_completed_at: str | None = None,
) -> ThesisDiffV1:
    """Pure deterministic diff of two research cases.

    When ``previous_case`` is None every current claim becomes ``new`` (or
    ``unresolved`` for unknowns), which is the first-run baseline behaviour.
    """
    previous_by_key = {
        claim.claim_key: claim for claim in (previous_case.claims if previous_case else ())
    }
    current_by_key = {claim.claim_key: claim for claim in current_case.claims}

    entries: list[ThesisDiffEntry] = []
    # Current claims in their authored order.
    for claim in current_case.claims:
        entries.append(
            _diff_one_claim(
                key=claim.claim_key,
                current=claim,
                previous=previous_by_key.get(claim.claim_key),
            )
        )
    # Baseline keys that disappeared, in baseline order, appended at the end.
    for claim in (previous_case.claims if previous_case else ()):
        if claim.claim_key not in current_by_key:
            entries.append(
                _diff_one_claim(
                    key=claim.claim_key,
                    current=None,
                    previous=claim,
                )
            )

    return ThesisDiffV1(
        run_id=run_id,
        ticker=current_case.ticker,
        horizon=current_case.horizon,
        current_research_case_artifact_id=current_case_artifact_id,
        previous_research_case_artifact_id=previous_case_artifact_id,
        previous_run_id=previous_run_id,
        baseline_completed_at=baseline_completed_at,
        entries=tuple(entries),
    )


@dataclass(frozen=True)
class BaselineCase:
    """A resolved previous research case eligible as a diff baseline."""

    run_id: str
    completed_at: str
    research_case_artifact_id: str
    case: ResearchCaseV2


def _latest_research_case_artifact_id(events) -> str | None:
    """Return the artifact_id of the highest-sequence research-case-v2 event."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != RESEARCH_CASE_CONTRACT:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if not isinstance(sequence, int) or not isinstance(artifact_id, str):
            continue
        if best is None or sequence > best[0]:
            best = (sequence, artifact_id)
    return best[1] if best is not None else None


def _completed_at(events) -> str | None:
    for event in reversed(events):
        if event.type == "run.completed":
            value = event.payload.get("completed_at")
            if isinstance(value, str) and value:
                return value
    return None


def select_baseline(
    store,
    *,
    current_run_id: str,
    current_case: ResearchCaseV2,
    current_completed_at: str,
) -> BaselineCase | None:
    """Select the immediately preceding eligible research case.

    A baseline is a different run that: has a ``run.completed`` event, shares
    the same (case-insensitive) ticker and horizon, carries a parseable
    ``research-case-v2`` artifact, and whose ``(completed_at, run_id)`` is
    strictly less than the current run's tuple.  Among eligible baselines the
    greatest tuple wins; ties break by run_id for stable replay.
    """
    current_key = (current_completed_at, current_run_id)
    target_ticker = current_case.ticker.strip().upper()
    best: tuple[tuple[str, str], BaselineCase] | None = None

    for summary in store.list_runs():
        candidate_run_id = summary.run_id
        if candidate_run_id == current_run_id:
            continue
        # Cheap pre-filter on the summary before reading its snapshot/events.
        if summary.status != "completed":
            continue
        if (summary.ticker or "").strip().upper() != target_ticker:
            continue
        try:
            snapshot = store.read_snapshot(candidate_run_id)
        except Exception:  # noqa: BLE001 - unreadable snapshot is simply skipped
            continue
        if snapshot.horizon != current_case.horizon:
            continue
        try:
            events = store.read_events(candidate_run_id)
        except Exception:  # noqa: BLE001
            continue
        completed_at = _completed_at(events)
        if completed_at is None:
            continue
        candidate_key = (completed_at, candidate_run_id)
        if not candidate_key < current_key:
            continue
        artifact_id = _latest_research_case_artifact_id(events)
        if artifact_id is None:
            continue
        try:
            raw = store.read_artifact(candidate_run_id, artifact_id)
            case = ResearchCaseV2.model_validate(json.loads(raw))
        except Exception as exc:  # noqa: BLE001 - unparseable case is not a baseline
            logger.info(
                "skipping unparseable research case %s/%s as baseline: %s",
                candidate_run_id,
                artifact_id,
                exc,
            )
            continue
        baseline = BaselineCase(
            run_id=candidate_run_id,
            completed_at=completed_at,
            research_case_artifact_id=artifact_id,
            case=case,
        )
        if best is None or candidate_key > best[0]:
            best = (candidate_key, baseline)

    return best[1] if best is not None else None


def build_thesis_diff_for_run(
    store,
    *,
    run_id: str,
    current_case: ResearchCaseV2,
    current_case_artifact_id: str,
    current_completed_at: str,
) -> ThesisDiffV1:
    """Select a baseline (if any) and produce the diff for a completed run."""
    baseline = select_baseline(
        store,
        current_run_id=run_id,
        current_case=current_case,
        current_completed_at=current_completed_at,
    )
    if baseline is None:
        return compute_thesis_diff(
            run_id=run_id,
            current_case=current_case,
            current_case_artifact_id=current_case_artifact_id,
            previous_case=None,
        )
    return compute_thesis_diff(
        run_id=run_id,
        current_case=current_case,
        current_case_artifact_id=current_case_artifact_id,
        previous_case=baseline.case,
        previous_case_artifact_id=baseline.research_case_artifact_id,
        previous_run_id=baseline.run_id,
        baseline_completed_at=baseline.completed_at,
    )
