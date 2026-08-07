"""Risk-debate structured-output signal schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from tradingagents.portfolio import ConvictionSignal

from ._common import ModelClaimInput


class RiskDebateSignal(BaseModel):
    role: Literal["aggressive", "conservative", "neutral"]
    conviction: float | None = Field(default=None, ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    abstain: bool = False
    evidence_summary: str = Field(
        default="",
        description="Short public evidence summary, not a reasoning trace.",
    )
    evidence_summary_ref: ModelClaimInput | None = Field(
        default=None,
        description="Optional referenced public risk summary using only system-supplied evidence IDs.",
    )

    @model_validator(mode="after")
    def _require_abstain_semantics(self):
        if self.abstain and self.conviction is not None:
            raise ValueError("an abstaining risk role must not supply conviction")
        if not self.abstain and self.conviction is None:
            raise ValueError("a non-abstaining risk role must supply conviction")
        return self

    def to_domain(self) -> ConvictionSignal:
        return ConvictionSignal(
            role=self.role,
            conviction=None if self.abstain else self.conviction,
            confidence=self.confidence,
            evidence_summary=self.evidence_summary,
        )

