"""Versioned, field-level instrument identity evidence contracts."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from tradingagents.dataflows.capability_result import (
    Availability,
    ProviderAttemptV1,
    semantic_model_payload,
)
from tradingagents.observability.canonical import canonical_sha256

IdentityFieldName = Literal[
    "ticker",
    "company_name",
    "security_type",
    "listing_status",
    "exchange",
    "regulatory_authority",
    "cik",
]


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


class IdentityFieldFactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    field_name: IdentityFieldName
    value: str = Field(min_length=1, max_length=500)
    source_id: str = Field(min_length=1, max_length=160)
    observed_at: datetime
    effective_at: datetime | None = None

    @field_validator("value", "source_id")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = _normalized_text(value)
        if not normalized:
            raise ValueError("identity fact text cannot be empty")
        return normalized

    @field_validator("observed_at", "effective_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("identity fact timestamps must be timezone-aware")
        return value.astimezone(timezone.utc) if value is not None else None


class VerifiedInstrumentIdentityV1(BaseModel):
    """One cutoff-bound identity assembled from explicitly observed facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    contract_kind: Literal["verified-instrument-identity-v1"] = (
        "verified-instrument-identity-v1"
    )
    ticker: str = Field(min_length=1, max_length=80)
    market: Literal["a_share", "global"]
    analysis_date: str
    analysis_cutoff_at: datetime
    company_name: str | None = Field(default=None, max_length=500)
    security_type: str | None = Field(default=None, max_length=120)
    listing_status: str | None = Field(default=None, max_length=120)
    exchange: str | None = Field(default=None, max_length=120)
    regulatory_authority: str | None = Field(default=None, max_length=120)
    cik: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    availability: Availability
    verification_level: Literal["full", "partial", "unverified"]
    field_facts: tuple[IdentityFieldFactV1, ...]
    provider_attempts: tuple[ProviderAttemptV1, ...] = Field(min_length=1)

    @field_validator("analysis_date")
    @classmethod
    def validate_analysis_date(cls, value: str) -> str:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("analysis_date must use YYYY-MM-DD")
        return value

    @field_validator("analysis_cutoff_at")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("identity cutoff must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator(
        "ticker",
        "company_name",
        "security_type",
        "listing_status",
        "exchange",
        "regulatory_authority",
    )
    @classmethod
    def normalize_identity_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalized_text(value)
        if not normalized:
            raise ValueError("identity text cannot be empty")
        return normalized

    @field_validator("field_facts")
    @classmethod
    def canonical_facts(
        cls, values: tuple[IdentityFieldFactV1, ...]
    ) -> tuple[IdentityFieldFactV1, ...]:
        return tuple(
            sorted(
                values,
                key=lambda fact: (
                    fact.field_name,
                    fact.source_id,
                    fact.effective_at or datetime.min.replace(tzinfo=timezone.utc),
                ),
            )
        )

    @field_validator("provider_attempts")
    @classmethod
    def canonical_attempts(
        cls, values: tuple[ProviderAttemptV1, ...]
    ) -> tuple[ProviderAttemptV1, ...]:
        return tuple(sorted(values, key=lambda attempt: attempt.source_id))

    def semantic_payload(self) -> dict[str, Any]:
        return semantic_model_payload(self)

    @computed_field
    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.semantic_payload())

    @model_validator(mode="after")
    def validate_identity(self) -> VerifiedInstrumentIdentityV1:
        fact_keys = [
            (fact.field_name, fact.source_id, fact.effective_at)
            for fact in self.field_facts
        ]
        if len(set(fact_keys)) != len(fact_keys):
            raise ValueError("identity field facts must be unique")
        attempts = {attempt.source_id: attempt for attempt in self.provider_attempts}
        if len(attempts) != len(self.provider_attempts):
            raise ValueError("identity provider attempts must have unique sources")
        for fact in self.field_facts:
            attempt = attempts.get(fact.source_id)
            if attempt is None or attempt.outcome != "observed":
                raise ValueError("identity facts require a successful provider attempt")
            if fact.effective_at is not None and fact.effective_at > self.analysis_cutoff_at:
                raise ValueError("identity facts cannot be effective after cutoff")

        expected = {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "security_type": self.security_type,
            "listing_status": self.listing_status,
            "exchange": self.exchange,
            "regulatory_authority": self.regulatory_authority,
            "cik": self.cik,
        }
        for field_name, value in expected.items():
            facts = [fact.value for fact in self.field_facts if fact.field_name == field_name]
            if value is None:
                if facts:
                    raise ValueError(f"{field_name} facts require an aggregate value")
                continue
            if not facts:
                raise ValueError(f"{field_name} requires a matching field fact")
            if any(fact != value for fact in facts):
                raise ValueError(f"{field_name} field fact conflicts with identity")
        return self
