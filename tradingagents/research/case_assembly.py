"""Deterministic, commit-safe assembly of a minimum public Research Case."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from tradingagents.agents.schemas import DataQuality, ResearchCaseV2
from tradingagents.runtime.run_models import RunSnapshot


def assemble_partial_research_case(
    snapshot: RunSnapshot,
    *,
    source_sequence: int,
    evidence_verdict: str,
) -> ResearchCaseV2:
    """Create the honest fallback when no evidence-bound claim set exists.

    This function intentionally does not read analyst Markdown, prompts, or
    tool traces. A later assembler can replace this partial result only by
    validating public claims and their current-run evidence references.
    """
    verdict: Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"] = (
        evidence_verdict
        if evidence_verdict in {"PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"}
        else "GATE_ERROR"
    )
    as_of = datetime.fromisoformat(snapshot.analysis_date).replace(tzinfo=timezone.utc)
    return ResearchCaseV2(
        run_id=snapshot.run_id,
        ticker=snapshot.ticker,
        horizon=snapshot.horizon or "medium",
        source_sequence=source_sequence,
        as_of=as_of,
        availability="partial",
        decision_eligibility="none",
        evidence_verdict=verdict,
        data_quality=DataQuality(
            level="blocked",
            unavailable_capabilities=("evidence_bound_claims",),
        ),
        omissions=(
            "research_case.evidence_bound_claims_unavailable",
            "research_case.rating_withheld",
        ),
    )
