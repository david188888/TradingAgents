"""Closed observations and per-field premise receipts; never semantic entailment."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FACTUAL_PREMISE_POLICY = "factual-premises-v1"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactualObservationV1(_Frozen):
    observation_id: str
    kind: Literal["source", "comparison", "sign"]
    text: str
    fact_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    anchor_id: str | None = None
    limitations: tuple[str, ...] = ()


class PremiseBindingV1(_Frozen):
    field_path: str = Field(min_length=1, max_length=200)
    observation_ids: tuple[str, ...] = Field(max_length=6)
    pending_questions: tuple[Annotated[str, Field(min_length=1, max_length=180)], ...] = Field(max_length=3)

    @model_validator(mode="after")
    def unique_observations(self):
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("duplicate premise observation")
        return self


class PremiseReceiptV1(_Frozen):
    policy: Literal["factual-premises-v1"] = FACTUAL_PREMISE_POLICY
    status: Literal["interpretation", "open_question"]
    observations: tuple[FactualObservationV1, ...] = Field(max_length=6)
    pending_questions: tuple[str, ...] = Field(max_length=3)


class PublicPremiseV1(PremiseReceiptV1):
    text: str
