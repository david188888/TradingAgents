"""Current HTTP requests for A-share Insight research."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.llm_clients.chatgpt_errors import ModelFailureDiagnostic
from tradingagents.llm_clients.stage_models import stage_model_overrides
from tradingagents.research.native_evidence_policy import (
    NativeEvidencePolicyV1,
    is_native_stock_ticker,
)

SUPPORTED_OUTPUT_LANGUAGES = ("English", "Chinese")


def current_analysis_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


class StageModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=256)
    effort: str | None = Field(default=None, max_length=16)


class BatchRunConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    analysis_date: str = Field(default_factory=current_analysis_date)
    llm_provider: str = Field(min_length=1, max_length=64)
    chatgpt_account_ref: str | None = Field(default=None, pattern=r"^cg_[0-9a-f]{32}$")
    quick_think_llm: str = Field(min_length=1, max_length=256)
    deep_think_llm: str = Field(min_length=1, max_length=256)
    stage_models: dict[str, StageModelRequest] = Field(default_factory=dict, max_length=7)
    output_language: Literal["English", "Chinese"] = "English"
    research_profile: Literal["evidence_v1"] = "evidence_v1"
    research_question: str | None = Field(default=None, max_length=400)
    evidence_policy: NativeEvidencePolicyV1 | None = None
    jev_verification_enabled: bool = False
    jev_model: str = Field(default="typesafe/jev-1.14", min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_models_and_account(self):
        stages = {key: value.model_dump(exclude_none=True) for key, value in self.stage_models.items()}
        stage_model_overrides({"stage_models": stages})
        subscription = "chatgpt" in {self.llm_provider.lower(), *(v["provider"] for v in stages.values())}
        if subscription != (self.chatgpt_account_ref is not None):
            raise ValueError("chatgpt_account_ref is required only for ChatGPT subscription")
        self.research_question = self.research_question.strip() or None if self.research_question else None
        return self

    @field_validator("analysis_date")
    @classmethod
    def validate_analysis_date(cls, value):
        parsed = date.fromisoformat(value)
        if parsed > date.fromisoformat(current_analysis_date()):
            raise ValueError("analysis_date cannot be in the future")
        return value


class RunCreateRequest(BatchRunConfigRequest):
    ticker: str = Field(min_length=1, max_length=32)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value):
        if not is_native_stock_ticker(value):
            raise ValueError("research requires A-share common stocks")
        return value


class BatchEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    input: str = Field(min_length=1, max_length=128)
    config: BatchRunConfigRequest


class BatchValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    inputs: tuple[str, ...] = Field(min_length=1, max_length=8)


class BatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: tuple[BatchEntryRequest, ...] = Field(min_length=1, max_length=8)
    concurrency: Literal[1, 2, 3] = 3

    @model_validator(mode="after")
    def validate_unique_inputs(self) -> BatchCreateRequest:
        normalized = [item.input.strip().casefold() for item in self.entries]
        if len(normalized) != len(set(normalized)):
            raise ValueError("batch inputs must not contain duplicates")
        return self


class ArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    kind: str
    media_type: str
    content_sha256: str
    byte_size: int = Field(ge=0)
    locator: str


class ApiErrorDetail(BaseModel):
    """The response remains a stable JSON envelope for all API errors."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    fields: tuple[str, ...] = ()
    active_run_id: str | None = None
    diagnostic: ModelFailureDiagnostic | None = None


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: ApiErrorDetail
