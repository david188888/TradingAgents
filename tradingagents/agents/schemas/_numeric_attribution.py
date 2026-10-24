"""Public, replayable numeric attribution; absent on historical records."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ._numeric_narrative import NumericCatalogV1


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NumericRecordedStageV1(_Frozen):
    stage: str = Field(min_length=1, max_length=40)
    proposal: dict[str, Any]
    proof: dict[str, Any]
    context: dict[str, Any]


class NumericRecordFieldV1(_Frozen):
    path: tuple[str | int, ...] = Field(min_length=1, max_length=10)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["stage", "host", "composite"]
    # Full accepted fields, never guessed numeric spans or a truncated number.
    sources: tuple[dict[str, Any], ...] = Field(default=(), max_length=8)


class NumericAttributionV1(_Frozen):
    policy: Literal["anchored-narrative-v1"]
    input_identity: dict[str, Any] = Field(default_factory=dict)
    catalog: NumericCatalogV1
    stages: tuple[NumericRecordedStageV1, ...] = Field(default=(), max_length=8)
    final_fields: tuple[NumericRecordFieldV1, ...] = Field(default=(), max_length=256)


class NumericRecordedStageV2(NumericRecordedStageV1):
    stage: str = Field(min_length=1, max_length=160)


class NumericAttributionV2(NumericAttributionV1):
    """V8 preserves base receipts plus up to nine supplemental reviews."""
    stages: tuple[NumericRecordedStageV2, ...] = Field(default=(), max_length=17)
