"""Bounded source collection windows for current A-share research."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

COLLECTION_POLICY_VERSION = "source-collection-policy-v1"
class CollectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy_version: Literal["source-collection-policy-v1"] = COLLECTION_POLICY_VERSION
    profile: Literal["evidence_v1"] = "evidence_v1"
    forward_window_max_calendar_days: int = Field(default=84, gt=0)
    event_lookback_calendar_days: tuple[int, ...] = (7, 30, 90)
    price_history_trading_days: int = Field(default=250, gt=0)
    fundamentals_quarters: int = Field(default=8, gt=0)
    max_source_calls: int = Field(default=40, gt=0)
    max_model_calls: int = Field(default=20, gt=0)
    max_supplement_rounds: int = Field(default=1, ge=0)
    max_supplement_capabilities: int = Field(default=3, gt=0)
    def as_identity(self):
        return self.model_dump(mode="json")

def collection_policy():
    return CollectionPolicy()
