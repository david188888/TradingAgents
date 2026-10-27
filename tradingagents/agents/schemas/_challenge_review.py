"""Source-bound model review coverage, separate from actual counterarguments."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HypothesisReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hypothesis_id: str = Field(min_length=1, max_length=512)
    disposition: Literal["challenged", "no_additional_counterevidence"]
    rationale: str = Field(min_length=1, max_length=360)
    supporting_fact_ids: tuple[str, ...] = Field(default=(), max_length=6)


class HypothesisReviewsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reviews: tuple[HypothesisReviewV1, ...] = Field(max_length=9)
