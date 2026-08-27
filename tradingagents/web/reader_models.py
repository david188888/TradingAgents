"""Closed public reader DTOs for the learning-research reader endpoint.

These models are the read-only public contract for ``GET /api/runs/{run_id}/reader``.
They intentionally describe *learning research* only -- no Buy/Hold/Sell rating,
no current/target weight, no Add/Reduce/Exit semantics.  Two research modes are
projected (company_research / holding_review); the research verdict is a tilt, not
a trade action.  Evidence references here are slim public metadata and never expose
raw payload, locator, content_sha256, or byte_size of the underlying artifacts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.schemas._research_case import (
    AnalystCard,
    CoverageRefV1,
    DataQuality,
    PublicClaim,
    ResearchTilt,
    ReviewItem,
    ReviewPlan,
    ScenarioSet,
)
from tradingagents.research.valuation import ValuationAssessmentV1

ResearchMode = Literal["company_research", "holding_review"]


class _ReaderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ThesisDiffEntryDTO(_ReaderModel):
    claim_key: str
    diff_kind: Literal[
        "new", "maintained", "invalidated", "unresolved", "not_reassessed"
    ]
    previous_claim_type: Literal["fact", "inference", "unknown"] | None = None
    current_claim_type: Literal["fact", "inference", "unknown"] | None = None
    previous_text: str | None = None
    current_text: str | None = None
    previous_confidence: float | None = Field(default=None, ge=0, le=1)
    current_confidence: float | None = Field(default=None, ge=0, le=1)
    previous_lifecycle_status: Literal[
        "active", "resolved", "invalidated"
    ] | None = None
    current_lifecycle_status: Literal[
        "active", "resolved", "invalidated"
    ] | None = None
    change_flags: tuple[
        Literal[
            "text_changed",
            "evidence_changed",
            "confidence_changed",
            "status_changed",
        ],
        ...,
    ] = ()
    counter_evidence_ref_ids: tuple[str, ...] = ()


class ThesisDiffDTO(_ReaderModel):
    schema_version: Literal[1] = 1
    run_id: str
    ticker: str
    horizon: Literal["short", "medium", "long"]
    previous_run_id: str | None = None
    baseline_completed_at: str | None = None
    entries: tuple[ThesisDiffEntryDTO, ...] = ()


class ReaderEvidenceRef(_ReaderModel):
    """Slim public evidence metadata; deliberately omits raw payload/locator/hashes."""

    ref_id: str
    source_label: str
    resolution_status: Literal["available", "target_missing"] = "available"


class AuditEntryDTO(_ReaderModel):
    route: str = "reader"
    artifact_count: int = 0
    tool_call_count: int = 0
    degradation_count: int = 0


class CompanionSelection(_ReaderModel):
    kind: Literal["role", "claim", "evidence", "risk"]
    id: str = Field(min_length=1, max_length=512)


class CompanionDTO(_ReaderModel):
    schema_version: Literal[1] = 1
    run_id: str
    selection: CompanionSelection
    summary: str = Field(min_length=1, max_length=1600)
    actual_coverage: tuple[str, ...] = Field(min_length=1)
    conclusion_impact: str = Field(min_length=1, max_length=1200)
    next_validation: str = Field(min_length=1, max_length=1200)


class LearningReaderV2(_ReaderModel):
    """Typed learning-research reader for a research-case-v2 run."""

    kind: Literal["typed"] = "typed"
    schema_version: Literal[2] = 2
    run_id: str
    mode: ResearchMode
    ticker: str
    horizon: Literal["short", "medium", "long"]
    as_of: datetime
    availability: Literal["full", "partial"]
    decision_eligibility: Literal["full", "limited", "none"]
    evidence_verdict: Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"]
    research_tilt: ResearchTilt | None = None
    rating_confidence: float | None = Field(default=None, ge=0, le=1)
    claims: tuple[PublicClaim, ...] = ()
    scenarios: ScenarioSet | None = None
    catalysts: tuple[ReviewItem, ...] = ()
    invalidation_conditions: tuple[ReviewItem, ...] = ()
    review_plan: ReviewPlan | None = None
    analyst_cards: tuple[AnalystCard, ...] = ()
    data_quality: DataQuality
    evidence_refs: tuple[ReaderEvidenceRef, ...] = ()
    coverage_refs: tuple[CoverageRefV1, ...] = ()
    omissions: tuple[str, ...] = ()
    # M3: cross-run thesis diff against the previous same-ticker/horizon case.
    thesis_diff: ThesisDiffDTO | None = None
    # Deterministic valuation-position chain (price bucket + reference range).
    valuation: ValuationAssessmentV1 | None = None
    audit_entry: AuditEntryDTO


class LegacyDataQualityDTO(_ReaderModel):
    level: Literal["available", "limited", "unknown"]
    summary: str
    degradation_count: int = 0


class LegacyReaderV1(_ReaderModel):
    """Historical reader for runs that predate typed research cases."""

    kind: Literal["legacy"] = "legacy"
    schema_version: Literal[1] = 1
    run_id: str
    ticker: str
    as_of: datetime
    final_signal: str | None = None
    portfolio_report_markdown: str | None = None
    data_quality: LegacyDataQualityDTO
    stage_refs: tuple[str, ...] = ()
    audit_entry: AuditEntryDTO
    reason_codes: tuple[str, ...] = ()


class ReaderUnavailableV1(_ReaderModel):
    """Reader payload cannot be produced (missing or unreadable typed case)."""

    kind: Literal["unavailable"] = "unavailable"
    schema_version: Literal[1] = 1
    run_id: str
    ticker: str | None = None
    reason_code: Literal[
        "research_case_unavailable",
        "reader_projection_failed",
        "unsupported_research_case_major",
    ]
    audit_entry: AuditEntryDTO


ReaderResponse = Annotated[
    LearningReaderV2 | LegacyReaderV1 | ReaderUnavailableV1,
    Field(discriminator="kind"),
]
