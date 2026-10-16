"""Additive reading aids; never part of the professional research record."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EXPLANATION_POLICY = "plain-language-report-v1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class IndicatorExplanation(_Model):
    label: str
    value: str | None = None
    definition: str
    interpretation: str = ""
    caution: str = ""
    professional: str
    scope: str = ""
    raw_value: str | None = None
    raw_unit: str | None = None


class ExplanationEntry(_Model):
    target: str = Field(min_length=1, max_length=600)
    explanation: str = Field(min_length=1, max_length=240)
    uncertainty: str = Field(default="", max_length=240)
    references: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def bounded(self):
        if len(self.explanation) + len(self.uncertainty) > 240:
            raise ValueError("explanation too long")
        if len(set(self.references)) != len(self.references):
            raise ValueError("duplicate explanation reference")
        return self


class ExplanationProposal(_Model):
    entries: tuple[ExplanationEntry, ...] = Field(max_length=32)


class ExplanationAttempt(_Model):
    phase: Literal["main", "repair"]
    dispatched_at: str | None = None
    outcome: Literal["reserved", "unknown", "received", "failed"] = "reserved"
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ExplanationJob(_Model):
    policy: Literal["plain-language-report-v1"] = EXPLANATION_POLICY
    job_id: str
    run_id: str
    base_record_sha256: str
    focus_sha256: str | None = None
    targets_sha256: str
    config_sha256: str
    language: str
    model: str
    state: Literal["generating", "available", "partial", "failed"]
    reason_code: str | None = None
    generated_at: str | None = None
    attempts: tuple[ExplanationAttempt, ...] = ()
    entries: dict[str, ExplanationEntry] = Field(default_factory=dict)
    unavailable_targets: dict[str, str] = Field(default_factory=dict)
    target_hashes: dict[str, str] = Field(default_factory=dict)
    result_artifact_id: str | None = None
    result_sha256: str | None = None


class ReportExplanationView(_Model):
    schema_version: Literal[1] = 1
    run_id: str
    base_record_sha256: str | None = None
    state: Literal["not_generated", "generating", "available", "partial", "failed",
                   "interrupted", "unsupported", "corrupt"]
    reason_code: str | None = None
    eligible: bool = False
    indicators: dict[str, IndicatorExplanation] = Field(default_factory=dict)
    entries: dict[str, ExplanationEntry] = Field(default_factory=dict)
    unavailable_targets: dict[str, str] = Field(default_factory=dict)
    model: str | None = None
    generated_at: str | None = None
