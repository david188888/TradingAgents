from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.dataflows.capability_result import (
    CapabilityResultV1,
    ProviderAttemptV1,
    aggregate_capability_availability,
)
from tradingagents.dataflows.coverage import (
    BundleCoverageV1,
    SourceCoverageV1,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)


def _attempt(source_id: str, outcome: str) -> ProviderAttemptV1:
    reached = outcome in {
        "observed",
        "not_covered",
        "provider_failed",
        "invalid_payload",
    }
    return ProviderAttemptV1(
        source_id=source_id,
        provider=source_id.split(".", 1)[0],
        outcome=outcome,
        reason_code=f"test_{outcome}",
        recorded_at=NOW,
        started_at=NOW if reached else None,
        ended_at=NOW if reached else None,
    )


def _coverage(source_id: str, completeness: str) -> SourceCoverageV1:
    usable = completeness != "unavailable"
    return SourceCoverageV1(
        capability="fundamentals_annual",
        source_id=source_id,
        requested_start="2022-01-01",
        requested_end="2026-08-13",
        actual_start="2022-01-01" if usable else None,
        actual_end="2026-08-13" if usable else None,
        item_count=5 if usable else 0,
        completeness=completeness,
        sources=(source_id,),
        degradations=() if usable else ("test_unavailable",),
        as_of="2026-08-13",
    )


def _bundle(*records: SourceCoverageV1) -> BundleCoverageV1:
    return BundleCoverageV1.build(
        capability="fundamentals_annual",
        records=records,
        required_source_ids=tuple(record.source_id for record in records),
        required_source_groups=(),
        optional_source_ids=(),
    )


def _result(
    *,
    coverage: BundleCoverageV1,
    attempts: tuple[ProviderAttemptV1, ...],
    availability: str,
    freshness: str,
    cutoff: datetime | None = NOW,
    degradations: tuple[str, ...] = (),
) -> CapabilityResultV1:
    reached = any(attempt.reached_provider for attempt in attempts)
    return CapabilityResultV1(
        capability="fundamentals_annual",
        symbol="AAPL",
        market="global",
        analysis_date="2026-08-13",
        analysis_cutoff_at=cutoff,
        availability=availability,
        freshness=freshness,
        coverage=coverage,
        source_ids=tuple(attempt.source_id for attempt in attempts),
        attempts=attempts,
        fetched_at=NOW if reached else None,
        degradation_codes=degradations,
    )


def test_available_requires_complete_coverage() -> None:
    source = "yfinance.income_statement"
    attempts = (_attempt(source, "observed"),)
    partial = _bundle(_coverage(source, "unknown"))

    with pytest.raises(ValidationError, match="available results require complete"):
        _result(
            coverage=partial,
            attempts=attempts,
            availability="available",
            freshness="current",
        )

    assert aggregate_capability_availability(partial, attempts) == "partial"


def test_non_payload_result_requires_unknown_freshness() -> None:
    source = "sec.submissions"
    attempts = (_attempt(source, "not_supported"),)
    bundle = _bundle(_coverage(source, "unavailable"))

    with pytest.raises(ValidationError, match="unknown freshness"):
        _result(
            coverage=bundle,
            attempts=attempts,
            availability="not_supported",
            freshness="current",
        )


def test_unobserved_required_source_prevents_not_covered() -> None:
    yahoo = "yfinance.income_statement"
    alpha = "alpha_vantage.INCOME_STATEMENT"
    attempts = (
        _attempt(yahoo, "not_covered"),
        _attempt(alpha, "skipped_unobserved"),
    )
    bundle = _bundle(
        _coverage(yahoo, "unavailable"),
        _coverage(alpha, "unavailable"),
    )

    assert aggregate_capability_availability(bundle, attempts) == "provider_unavailable"
    with pytest.raises(ValidationError, match="availability does not match"):
        _result(
            coverage=bundle,
            attempts=attempts,
            availability="not_covered",
            freshness="unknown",
        )


def test_all_observed_negative_sources_allow_not_covered() -> None:
    yahoo = "yfinance.income_statement"
    alpha = "alpha_vantage.INCOME_STATEMENT"
    attempts = (
        _attempt(yahoo, "not_covered"),
        _attempt(alpha, "not_covered"),
    )
    bundle = _bundle(
        _coverage(yahoo, "unavailable"),
        _coverage(alpha, "unavailable"),
    )

    assert aggregate_capability_availability(bundle, attempts) == "not_covered"


def test_cutoff_resolution_failure_has_no_fetch_timestamp() -> None:
    source = "identity.exchange_timezone"
    attempts = (_attempt(source, "skipped_unobserved"),)
    bundle = _bundle(_coverage(source, "unavailable"))

    result = _result(
        coverage=bundle,
        attempts=attempts,
        availability="invalid",
        freshness="unknown",
        cutoff=None,
        degradations=("analysis_cutoff_resolution_failed",),
    )

    assert result.analysis_cutoff_at is None
    assert result.fetched_at is None
    assert not any(attempt.reached_provider for attempt in result.attempts)


def test_semantic_id_is_stable_and_excludes_itself() -> None:
    source = "yfinance.income_statement"
    attempts = (_attempt(source, "observed"),)
    complete = _bundle(_coverage(source, "complete"))
    first = _result(
        coverage=complete,
        attempts=attempts,
        availability="available",
        freshness="current",
    )
    second = CapabilityResultV1.model_validate(
        first.model_dump(exclude_computed_fields=True)
    )

    assert first.capability_result_id == second.capability_result_id
    assert len(first.capability_result_id) == 64
