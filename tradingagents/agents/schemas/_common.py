"""Shared schema primitives (rating enums, reader claims)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class ModelClaimInput(BaseModel):
    """Public reader claim emitted during the same structured decision call."""

    text: str = Field(min_length=1, max_length=600)
    evidence_ref_ids: list[str] = Field(min_length=1, max_length=8)

