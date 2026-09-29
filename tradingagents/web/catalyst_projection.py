"""Read-only projection of a committed ``catalyst-research-case-v1`` artifact.

Design section 7.4 fixes the boundary this module implements: the endpoint
answers from committed catalyst facts only, with a discriminated
``ready | unavailable | unsupported`` body, and a version field so a consumer
can tell which contract it is holding.

Two properties are load-bearing and are asserted in
``tests/web/test_catalyst_projection.py``:

* **A readable response is not a sufficient result.** ``ready`` means the
  artifact parses; the public case may still be ``blocked`` with an
  insufficient-information priority, and a consumer that reads ``ready`` as
  "research passed" would be wrong. Run lifecycle and case completeness stay
  two separate axes.
* **Reading calls nothing.** This module imports no LLM, no provider, and no
  dataflow. Every byte it returns came from the run store. The test asserts
  zero model and zero provider calls around a read.

Nothing here writes. A run with no committed catalyst artifact is reported,
never recomputed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.schemas import (
    CATALYST_CASE_SCHEMA_NUMBER,
    CATALYST_CASE_SCHEMA_VERSION,
    CatalystResearchCase,
)
from tradingagents.runtime.store import RunNotFound, RunStore

logger = logging.getLogger(__name__)

CATALYST_CONTRACT = CATALYST_CASE_SCHEMA_VERSION
CATALYST_ENDPOINT_VERSION = 1

CatalystReadState = Literal["ready", "unavailable", "unsupported"]

# Reason codes for the ``unavailable`` and ``unsupported`` states. These are
# new-contract codes; the old reader's ``research_case_unavailable`` string is
# deliberately not reused here, because a strict old client must keep parsing
# the old endpoint's shape.
UNAVAILABLE_REASONS = (
    "run_running",
    "not_committed",
    "missing",
    "corrupt",
)
UNSUPPORTED_REASONS = (
    "classic_profile",
    "unknown_profile",
)


class _ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CatalystUnavailableV1(_ReadModel):
    state: Literal["unavailable"] = "unavailable"
    schema_version: Literal[1] = CATALYST_ENDPOINT_VERSION
    run_id: str
    ticker: str
    run_status: str
    reason_code: str
    reason_codes: tuple[str, ...] = ()


class CatalystUnsupportedV1(_ReadModel):
    state: Literal["unsupported"] = "unsupported"
    schema_version: Literal[1] = CATALYST_ENDPOINT_VERSION
    run_id: str
    ticker: str
    reason_code: str


class CatalystReadyV1(_ReadModel):
    """A parseable committed catalyst case.

    ``completeness`` and ``priority`` are surfaced at the top level on
    purpose: a consumer must be able to render "insufficient information"
    without re-walking the case, and must not have to infer it from
    ``state == "ready"``.
    """

    state: Literal["ready"] = "ready"
    schema_version: Literal[1] = CATALYST_ENDPOINT_VERSION
    case_schema_version: Literal["catalyst-research-case-v1"] = CATALYST_CASE_SCHEMA_VERSION
    case_schema_number: Literal[1] = CATALYST_CASE_SCHEMA_NUMBER
    run_id: str
    ticker: str
    run_status: str
    completeness: Literal["complete", "partial", "blocked"]
    quality: Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"]
    priority: str
    research_question: str | None = None
    brief: dict[str, Any]
    limitations: tuple[str, ...] = ()
    brief_character_count: int = Field(ge=0)
    case: dict[str, Any]


def project_catalyst(store: RunStore, run_id: str) -> dict[str, Any]:
    """Return the catalyst endpoint body for one run.

    ``RunNotFound`` propagates so the API layer keeps its existing 404
    contract for a run that does not exist; a run that exists but has no
    usable catalyst artifact is an HTTP 200 ``unavailable``.
    """
    snapshot = store.read_snapshot(run_id)
    profile = _run_profile(snapshot)
    if profile != "catalyst_v1":
        return CatalystUnsupportedV1(
            run_id=run_id,
            ticker=snapshot.ticker,
            reason_code=(
                "unknown_profile"
                if profile not in {"classic", "catalyst_v1"}
                else "classic_profile"
            ),
        ).model_dump(mode="json")

    events = store.read_events(run_id)
    artifact_id = _latest_catalyst_artifact(events)
    if artifact_id is None:
        reason = "run_running" if snapshot.status not in _TERMINAL_STATUSES else "missing"
        return CatalystUnavailableV1(
            run_id=run_id,
            ticker=snapshot.ticker,
            run_status=snapshot.status,
            reason_code=reason,
            reason_codes=(reason,),
        ).model_dump(mode="json")

    try:
        raw = store.read_artifact(run_id, artifact_id)
        case = CatalystResearchCase.model_validate(json.loads(raw))
    except Exception as exc:  # noqa: BLE001 - a projection must not raise
        logger.warning("catalyst projection failed for run %s: %s", run_id, exc)
        return CatalystUnavailableV1(
            run_id=run_id,
            ticker=snapshot.ticker,
            run_status=snapshot.status,
            reason_code="corrupt",
            reason_codes=("corrupt",),
        ).model_dump(mode="json")

    if case.run_id != run_id or case.ticker != snapshot.ticker:
        # A committed artifact belonging to a different run is not this run's
        # result. Reporting it as ready would cross run boundaries, which
        # design section 4.6 forbids.
        return CatalystUnavailableV1(
            run_id=run_id,
            ticker=snapshot.ticker,
            run_status=snapshot.status,
            reason_code="corrupt",
            reason_codes=("corrupt",),
        ).model_dump(mode="json")

    return CatalystReadyV1(
        run_id=run_id,
        ticker=snapshot.ticker,
        run_status=snapshot.status,
        completeness=case.completeness,
        quality=case.quality,
        priority=case.priority_decision.priority,
        research_question=case.research_question,
        brief=case.brief.model_dump(mode="json"),
        limitations=_limitation_texts(case),
        brief_character_count=case.brief.character_count,
        case=case.model_dump(mode="json"),
    ).model_dump(mode="json")


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


def _run_profile(snapshot) -> str:
    """Read the research profile without importing the request contract.

    Agent B owns the request-side ``research_profile`` field. This read path
    only needs the value that is already recorded on the run, and reads it
    from snapshot metadata so the two sides cannot drift into a cycle.
    """
    metadata = getattr(snapshot, "metadata", None) or {}
    profile = metadata.get("research_profile")
    if isinstance(profile, str) and profile:
        return profile
    if metadata.get("catalyst_v1") is True:
        return "catalyst_v1"
    return "classic"


def _latest_catalyst_artifact(events) -> str | None:
    """Return the highest committed_sequence catalyst artifact id."""
    best: tuple[int, str] | None = None
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("public_contract") != CATALYST_CONTRACT:
            continue
        sequence = payload.get("committed_sequence")
        artifact_id = payload.get("artifact_id")
        if not isinstance(sequence, int) or not isinstance(artifact_id, str):
            continue
        if best is None or sequence > best[0]:
            best = (sequence, artifact_id)
    return best[1] if best is not None else None


def _limitation_texts(case: CatalystResearchCase) -> tuple[str, ...]:
    """Collect the limitation text the first screen must keep adjacent.

    Two sources feed it: the brief's own critical-limitation lines, and the
    limitations a challenge disposition retained. A disposition limitation is
    not optional context -- an unresolved challenge's retained limitation is
    what caps the priority, so a reader must be able to see it even when the
    brief carried no line for it.

    Deduplicated in a stable order so the projection is deterministic: the
    same committed case must produce byte-identical output on every read, or
    a refresh would look like a changed result.
    """
    texts: list[str] = [
        line.text for line in case.brief.critical_limitations if line.text
    ]
    for disposition in case.dispositions:
        for limitation in disposition.retained_limitations:
            if limitation and limitation not in texts:
                texts.append(limitation)
    return tuple(texts)


__all__ = [
    "CATALYST_CONTRACT",
    "CATALYST_ENDPOINT_VERSION",
    "CatalystReadState",
    "CatalystReadyV1",
    "CatalystUnavailableV1",
    "CatalystUnsupportedV1",
    "RunNotFound",
    "project_catalyst",
]
