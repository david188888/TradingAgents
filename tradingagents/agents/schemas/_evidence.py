"""Qualified source, factual claim, metric and valuation contracts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.research.valuation import (
    ValuationAssessmentV1,
    ValuationInputsV1,
    assess_valuation,
)

from ._verification_plan import canonical_sha256


class _RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SourceContentV1(_RecordModel):
    kind: Literal["excerpt", "source_fields", "saved_summary"]
    text: str = Field(min_length=1, max_length=4000)
    locator_label: str = Field(min_length=1, max_length=200)
    # Digest of the saved public content, not a private storage path.
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    truncated: bool = False

    @model_validator(mode="after")
    def content_matches_digest(self):
        import hashlib
        if hashlib.sha256(self.text.encode()).hexdigest() != self.content_sha256:
            raise ValueError("source content digest mismatch")
        return self


class SourceEvidenceV1(_RecordModel):
    evidence_id: str = Field(min_length=1, max_length=512)
    source_name: str = Field(min_length=1, max_length=512)
    source_kind: Literal["official", "vendor", "media", "derived", "analysis_report", "unknown"]
    source_family_id: str | None = Field(default=None, max_length=512)
    availability: Literal["available", "unavailable", "unverified"]
    public_url: str | None = Field(default=None, max_length=1024)
    published_at: datetime | None = None
    usable_as_of: datetime | None = None
    captured_at: datetime | None = None
    content: SourceContentV1 | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def public_source_is_safe(self):
        if self.public_url:
            parsed = urlsplit(self.public_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("unsafe public source URL")
            if any(any(part in key.lower() for part in ("token", "secret", "key", "signature", "auth"))
                   for key, _ in parse_qsl(parsed.query)):
                raise ValueError("credential-shaped source URL")
        for timestamp in (self.published_at, self.usable_as_of, self.captured_at):
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError("source timestamps require a timezone")
        if self.content is None and not self.limitations:
            raise ValueError("missing source content requires an explicit limitation")
        return self


class RecordClaimV1(_RecordModel):
    claim_id: str = Field(min_length=1, max_length=512)
    kind: Literal["fact", "inference", "unknown"]
    statement: str = Field(min_length=1, max_length=1200)
    evidence_ids: tuple[str, ...] = ()
    supporting_fact_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def kind_is_not_strengthened(self):
        if self.kind == "unknown":
            if self.evidence_ids or self.supporting_fact_ids or not self.limitations:
                raise ValueError("unknowns carry requirements, not evidence or supporting facts")
        elif not self.evidence_ids:
            raise ValueError("known claims require evidence")
        if self.kind == "fact" and self.supporting_fact_ids:
            raise ValueError("a fact cannot depend on an inference")
        if self.kind == "inference" and not self.supporting_fact_ids:
            raise ValueError("an inference requires supporting facts")
        return self


class QuantitativeMetricV1(_RecordModel):
    metric_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    availability: Literal["available", "unavailable"]
    value: float | None = None
    unit: str = Field(min_length=1, max_length=80)
    method: str = Field(min_length=1, max_length=300)
    calculation_version: str = Field(min_length=1, max_length=120)
    input_evidence_ids: tuple[str, ...] = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    window_start: date | None = None
    window_end: date | None = None
    sample_size: int | None = Field(default=None, ge=0)
    tail_sample_size: int | None = Field(default=None, ge=0)
    unavailable_reason: str | None = Field(default=None, max_length=400)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def availability_requires_provenance(self):
        if self.availability == "available":
            if self.value is None or self.sample_size is None or self.window_start is None or self.window_end is None or self.unavailable_reason:
                raise ValueError("available metrics require a value, sample and window")
        elif self.value is not None or not self.unavailable_reason:
            raise ValueError("unavailable metrics cannot carry an estimated value")
        if self.window_start and self.window_end and self.window_start > self.window_end:
            raise ValueError("metric window is reversed")
        if self.tail_sample_size is not None and (self.sample_size is None or self.tail_sample_size > self.sample_size):
            raise ValueError("tail sample exceeds return sample")
        return self


class NativeValuationV1(_RecordModel):
    inputs: ValuationInputsV1
    assessment: ValuationAssessmentV1
    input_evidence_ids: tuple[str, ...] = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def deterministic_assessment(self):
        if self.input_sha256 != canonical_sha256(self.inputs):
            raise ValueError("native valuation input hash mismatch")
        if self.assessment != assess_valuation(self.inputs):
            raise ValueError("native valuation arithmetic or input identity changed")
        return self

