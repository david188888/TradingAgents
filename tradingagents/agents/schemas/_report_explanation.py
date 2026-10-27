"""Additive reading aids; never part of the professional research record."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

EXPLANATION_POLICY = "plain-language-report-v1"
BATCH_EXPLANATION_POLICY = "batched-explanations-v1"
BATCH_TARGET_LIMIT = 16
BATCH_CHAR_LIMIT = 32000
EXPLANATION_REQUEST_LIMIT = 24
EXPLANATION_TIMEOUT_SECONDS = 300


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
    batch_index: int | None = Field(default=None, ge=0)
    target_ids: tuple[str, ...] = ()


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
    batch_policy: Literal["batched-explanations-v1"] | None = None
    deadline_at: datetime | None = None

    @model_validator(mode="after")
    def bounded_batches(self):
        if self.batch_policy is not None:
            if self.deadline_at is None or self.deadline_at.utcoffset() is None:
                raise ValueError("batched explanation deadline must be timezone aware")
            if len(self.attempts) > EXPLANATION_REQUEST_LIMIT:
                raise ValueError("explanation request limit exceeded")
            for attempt in self.attempts:
                if (attempt.batch_index is None or not attempt.target_ids
                        or len(attempt.target_ids) > BATCH_TARGET_LIMIT
                        or len(set(attempt.target_ids)) != len(attempt.target_ids)
                        or not set(attempt.target_ids) <= self.target_hashes.keys()):
                    raise ValueError("explanation batch attempt invalid")
        return self


class ExplanationCoverage(_Model):
    total: int = Field(ge=0)
    explained: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    pending: int = Field(ge=0)

    @model_validator(mode="after")
    def complete_partition(self):
        if self.explained + self.unavailable + self.pending != self.total:
            raise ValueError("explanation coverage mismatch")
        return self


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
    coverage: ExplanationCoverage | None = None

    @model_serializer(mode="wrap")
    def compatible_coverage_shape(self, handler):
        value = handler(self)
        if self.coverage is None:
            value.pop("coverage", None)
        return value
