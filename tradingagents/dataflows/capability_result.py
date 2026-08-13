"""Typed availability and provider-attempt contracts for research data.

Coverage answers *how much of the requested window was observed*.  This module
keeps that separate from *why* a capability is usable or unavailable, so a
provider outage cannot be mistaken for authoritative symbol non-coverage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from tradingagents.dataflows.coverage import BundleCoverageV1

Availability = Literal[
    "available",
    "partial",
    "not_covered",
    "not_supported",
    "provider_unavailable",
    "invalid",
]
Freshness = Literal["current", "stale", "unknown"]
AttemptOutcome = Literal[
    "observed",
    "not_covered",
    "provider_failed",
    "not_supported",
    "invalid_payload",
    "skipped_unobserved",
]
MarketKind = Literal["a_share", "global"]

_REACHED_PROVIDER = frozenset(
    {"observed", "not_covered", "provider_failed", "invalid_payload"}
)
_NON_PAYLOAD_AVAILABILITY = frozenset(
    {"not_covered", "not_supported", "provider_unavailable", "invalid"}
)
_REASON_PATTERN = r"^[a-z][a-z0-9_]*$"


class ProviderAttemptV1(BaseModel):
    """One durable outcome for an eligible source in a capability request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=120)
    outcome: AttemptOutcome
    reason_code: str = Field(pattern=_REASON_PATTERN)
    recorded_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    vendor_call_id: str | None = Field(default=None, min_length=1, max_length=160)
    provenance_artifact_id: str | None = Field(
        default=None, min_length=1, max_length=256
    )

    @field_validator("recorded_at", "started_at", "ended_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("attempt timestamps must be timezone-aware")
        return value

    @computed_field
    @property
    def reached_provider(self) -> bool:
        return self.outcome in _REACHED_PROVIDER

    @model_validator(mode="after")
    def validate_attempt(self) -> ProviderAttemptV1:
        if self.reached_provider:
            if self.started_at is None or self.ended_at is None:
                raise ValueError(
                    "provider-reaching attempts require started_at and ended_at"
                )
            if self.started_at > self.ended_at:
                raise ValueError("started_at cannot be after ended_at")
        elif self.started_at is not None or self.ended_at is not None:
            raise ValueError("skipped or unsupported attempts cannot carry call times")
        return self


class CapabilityResultV1(BaseModel):
    """Semantic result for one normalized data capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    capability: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=1, max_length=80)
    market: MarketKind
    analysis_date: str
    analysis_cutoff_at: datetime | None
    availability: Availability
    freshness: Freshness
    coverage: BundleCoverageV1
    source_ids: tuple[str, ...] = Field(min_length=1)
    attempts: tuple[ProviderAttemptV1, ...] = Field(min_length=1)
    fallback_from: tuple[str, ...] = ()
    effective_period: str | None = Field(default=None, max_length=160)
    published_at_or_filing_at: datetime | None = None
    source_observed_at: datetime | None = None
    fetched_at: datetime | None = None
    degradation_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("analysis_date")
    @classmethod
    def validate_analysis_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("analysis_date must use YYYY-MM-DD") from exc
        if parsed.isoformat() != value:
            raise ValueError("analysis_date must use YYYY-MM-DD")
        return value

    @field_validator(
        "analysis_cutoff_at",
        "published_at_or_filing_at",
        "source_observed_at",
        "fetched_at",
    )
    @classmethod
    def validate_result_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("capability timestamps must be timezone-aware")
        return value

    @field_validator("degradation_codes")
    @classmethod
    def validate_degradation_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not value or not value[0].isalpha() or not all(
                char.islower() or char.isdigit() or char == "_" for char in value
            ):
                raise ValueError("degradation codes must be stable snake_case")
        return values

    @computed_field
    @property
    def capability_result_id(self) -> str:
        payload = self.semantic_payload()
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def semantic_payload(self) -> dict[str, Any]:
        """Return JSON-compatible semantic fields without computed/envelope IDs."""
        return _json_value(
            {name: getattr(self, name) for name in type(self).model_fields}
        )

    @model_validator(mode="after")
    def validate_result(self) -> CapabilityResultV1:
        if self.coverage.capability != self.capability:
            raise ValueError("coverage capability must match the result capability")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        attempt_ids = tuple(attempt.source_id for attempt in self.attempts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("attempt source IDs must be unique")
        coverage_ids = tuple(record.source_id for record in self.coverage.records)
        if set(self.source_ids) != set(coverage_ids) or set(attempt_ids) != set(
            coverage_ids
        ):
            raise ValueError(
                "source_ids, attempt sources, and coverage sources must match"
            )
        if len(set(self.fallback_from)) != len(self.fallback_from):
            raise ValueError("fallback_from must be unique")
        if not set(self.fallback_from).issubset(set(self.source_ids)):
            raise ValueError("fallback_from must reference declared sources")

        completeness = self.coverage.bundle_completeness
        if self.availability == "available":
            if completeness != "complete":
                raise ValueError("available results require complete coverage")
            if self.freshness not in {"current", "stale"}:
                raise ValueError("available results require current or stale freshness")
        elif self.availability == "partial":
            if completeness not in {"partial", "unknown"}:
                raise ValueError("partial results require partial or unknown coverage")
        else:
            if completeness != "unavailable":
                raise ValueError("non-payload results require unavailable coverage")
            if self.freshness != "unknown":
                raise ValueError("non-payload results require unknown freshness")

        reached = tuple(attempt for attempt in self.attempts if attempt.reached_provider)
        if reached and self.fetched_at is None:
            raise ValueError("fetched_at is required when a provider was reached")
        if not reached and self.fetched_at is not None:
            raise ValueError("fetched_at must be absent when no provider was reached")

        cutoff_failed = "analysis_cutoff_resolution_failed" in self.degradation_codes
        if self.analysis_cutoff_at is None:
            if self.availability != "invalid" or not cutoff_failed:
                raise ValueError(
                    "analysis_cutoff_at may be absent only for cutoff resolution failure"
                )
            if reached:
                raise ValueError(
                    "cutoff resolution failure cannot include provider-reaching attempts"
                )
        elif cutoff_failed:
            raise ValueError(
                "analysis_cutoff_resolution_failed requires a missing cutoff"
            )
        expected_availability = aggregate_capability_availability(
            self.coverage, self.attempts
        )
        if cutoff_failed:
            expected_availability = "invalid"
        if self.availability != expected_availability:
            raise ValueError(
                "availability does not match coverage and provider attempts"
            )
        return self


def aggregate_capability_availability(
    coverage: BundleCoverageV1,
    attempts: tuple[ProviderAttemptV1, ...],
) -> Availability:
    """Return availability without inferring a negative result from text."""

    by_source = {attempt.source_id: attempt for attempt in attempts}
    coverage_sources = {record.source_id for record in coverage.records}
    if set(by_source) != coverage_sources or len(by_source) != len(attempts):
        raise ValueError("attempts must cover every declared source exactly once")

    if coverage.bundle_completeness == "complete":
        return "available"
    if coverage.bundle_completeness in {"partial", "unknown"}:
        return "partial"

    required_sources = set(coverage.required_source_ids)
    required_sources.update(
        source_id
        for group in coverage.required_source_groups
        for source_id in group.source_ids
    )
    relevant = tuple(by_source[source_id] for source_id in required_sources)
    outcomes = {attempt.outcome for attempt in relevant}
    if "invalid_payload" in outcomes:
        return "invalid"
    if "not_supported" in outcomes:
        return "not_supported"
    if outcomes and outcomes == {"not_covered"}:
        return "not_covered"
    return "provider_unavailable"


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            name: _json_value(getattr(value, name))
            for name in type(value).model_fields
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
