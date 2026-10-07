"""A bounded supplementary interpretation, never a baseline research mutation."""

from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._research_record import ResearchRecordV1
from ._verification_plan import canonical_sha256

FOCUS_RESPONSE_CONTRACT = "research-focus-response-v1"
FocusReason = Literal[
    "base_synthesis_unavailable", "budget_exhausted", "deadline_exceeded",
    "response_unknown", "model_failed", "invalid_response",
]


class FocusProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    answer: str = Field(min_length=1, max_length=1200)
    answerability: Literal["answered", "partial", "unresolved"]
    claim_ids: tuple[str, ...] = Field(default=(), max_length=8)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=8)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=300)], ...] = Field(default=(), max_length=6)
    suggested_next_check: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def justified_answer(self):
        if any(len(set(ids)) != len(ids) for ids in (self.claim_ids, self.evidence_ids)):
            raise ValueError("duplicate focus references")
        if self.answerability != "unresolved" and not (self.claim_ids or self.evidence_ids):
            raise ValueError("focus answer requires saved support")
        if self.answerability == "unresolved" and not self.limitations:
            raise ValueError("unresolved focus requires an explicit gap")
        return self


class ResearchFocusResponseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["research-focus-response-v1"] = FOCUS_RESPONSE_CONTRACT
    run_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    mode: Literal["company_research", "catalyst_research", "holding_review"]
    analysis_date: date
    input_snapshot_id: str = Field(min_length=1)
    base_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    focus: str = Field(min_length=1, max_length=400)
    status: Literal["available", "unavailable"]
    proposal: FocusProposalV1 | None = None
    reason_code: FocusReason | None = None

    @model_validator(mode="after")
    def closed_status(self):
        if self.status == "available":
            if self.proposal is None or self.reason_code is not None:
                raise ValueError("available focus requires exactly one proposal")
        elif self.proposal is not None or self.reason_code is None:
            raise ValueError("unavailable focus requires a reason, not a proposal")
        if self.focus != self.focus.strip():
            raise ValueError("focus must be normalized")
        return self


def validate_focus_proposal(record: ResearchRecordV1, proposal: FocusProposalV1) -> None:
    """Validate citations against frozen, time-qualified saved research."""
    claims = {c.claim_id: c for c in record.claims}
    sources = {s.evidence_id: s for s in record.evidence}
    cited = set(proposal.evidence_ids)
    for key in proposal.claim_ids:
        claim = claims.get(key)
        if claim is None or claim.kind == "unknown":
            raise ValueError("focus claim is not qualified")
        cited.update(claim.evidence_ids)
        for fact_id in claim.supporting_fact_ids:
            cited.update(claims[fact_id].evidence_ids)
    for key in cited:
        source = sources.get(key)
        if (source is None or source.availability != "available" or source.content is None
                or source.usable_as_of is None
                or source.usable_as_of.astimezone(ZoneInfo("Asia/Shanghai")).date() > record.analysis_date
                or (source.published_at is not None
                    and source.published_at.astimezone(ZoneInfo("Asia/Shanghai")).date() > record.analysis_date)):
            raise ValueError("focus source is not qualified at cutoff")


def validate_focus_response(record: ResearchRecordV1, response: ResearchFocusResponseV1) -> None:
    if record.assessment is None or (
        response.run_id, response.ticker, response.mode, response.analysis_date,
        response.input_snapshot_id, response.base_record_sha256,
    ) != (
        record.run_id, record.ticker, record.mode, record.analysis_date,
        record.assessment.input_snapshot_id, canonical_sha256(record),
    ):
        raise ValueError("focus baseline binding mismatch")
    if response.proposal is not None:
        validate_focus_proposal(record, response.proposal)
