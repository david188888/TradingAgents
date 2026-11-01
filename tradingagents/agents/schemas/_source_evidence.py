"""Qualified captured source identity, provenance and time basis."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
SourceTier = Literal["official", "vendor", "media", "derived"]

class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

class CapturedSourceEvidence(_PublicModel):
    """One source record observed during the current run.

    Carries the security identity it was resolved under, both the original
    publication/observation times and the local capture time, and the
    time/value basis the source is valid for.  ``source_family_id`` is what
    makes republication countable: three aggregators copying one filing are
    one independent source, not three.
    """

    evidence_id: str = Field(pattern=ID_PATTERN)
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    capability: str = Field(min_length=1, max_length=120)
    source_tier: SourceTier
    source_name: str = Field(min_length=1, max_length=160)
    public_url: str | None = Field(default=None, max_length=1024)
    source_family_id: str = Field(min_length=1, max_length=160)
    republished_from_evidence_id: str | None = Field(default=None, pattern=ID_PATTERN)
    published_at: datetime | None = None
    observed_at: datetime | None = None
    captured_at: datetime
    usable_as_of: datetime | None = None
    time_basis: str = Field(min_length=1, max_length=200)
    value_basis: str = Field(min_length=1, max_length=200)
    availability: Literal["available", "unavailable", "unverified"] = "available"

    @field_validator("public_url")
    @classmethod
    def _safe_public_url(cls, value: str | None) -> str | None:
        # A public citation is checked separately for a safe protocol and for
        # credential-shaped query parameters; a url that fails is dropped to
        # "source label plus limitation" by the assembler, not published.
        if value is None:
            return None
        if not value.startswith(("https://", "http://")):
            raise ValueError("public_url must use an http(s) scheme")
        return value

    @model_validator(mode="after")
    def _republication_is_not_self(self) -> CapturedSourceEvidence:
        if self.republished_from_evidence_id == self.evidence_id:
            raise ValueError("an evidence record cannot be a republication of itself")
        return self
