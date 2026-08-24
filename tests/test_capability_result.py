from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.dataflows.capability_result import (
    CapabilityResultV1,
    ProviderAttemptV1,
    VerifiedIdentityCapabilityResultV1,
    aggregate_capability_availability,
    parse_capability_result,
    parse_capability_result_entry,
)
from tradingagents.dataflows.coverage import (
    BundleCoverageV1,
    SourceCoverageV1,
)
from tradingagents.execution.output_publisher import (
    _extract_bundle_capabilities,
    _extract_bundle_result_ids,
    _extract_bundle_result_summaries,
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
    second = CapabilityResultV1.model_validate(first.semantic_payload())

    assert first.capability_result_id == second.capability_result_id
    assert len(first.capability_result_id) == 64


def test_legacy_capability_result_hash_is_frozen() -> None:
    source = "yfinance.income_statement"
    attempts = (_attempt(source, "observed"),)
    complete = _bundle(_coverage(source, "complete"))
    result = _result(
        coverage=complete,
        attempts=attempts,
        availability="available",
        freshness="current",
    )

    assert result.capability_result_id == (
        "498ea26cccae215eea9c7d920054a527f84d5c742fe758e8d242ac6dca13332f"
    )


def _identity_result() -> VerifiedIdentityCapabilityResultV1:
    source = "sec.company_tickers"
    record = SourceCoverageV1(
        capability="verified_identity",
        source_id=source,
        requested_start="2026-08-13",
        requested_end="2026-08-13",
        actual_start="2026-08-13",
        actual_end="2026-08-13",
        item_count=1,
        completeness="complete",
        sources=(source,),
        as_of="2026-08-13",
    )
    coverage = BundleCoverageV1.build(
        capability="verified_identity",
        records=(record,),
        required_source_ids=(source,),
        optional_source_ids=(),
    )
    return VerifiedIdentityCapabilityResultV1(
        capability="verified_identity",
        symbol="AAPL",
        market="global",
        analysis_date="2026-08-13",
        analysis_cutoff_at=NOW,
        availability="available",
        freshness="current",
        coverage=coverage,
        source_ids=(source,),
        attempts=(_attempt(source, "observed"),),
        fetched_at=NOW,
        identity_artifact_id="identity:" + "a" * 64,
        identity_content_sha256="a" * 64,
        verification_level="full",
    )


def test_identity_result_parser_preserves_subtype_and_hashes_subtype_fields() -> None:
    full = _identity_result()
    partial = full.model_copy(update={"verification_level": "partial"})

    parsed = parse_capability_result(full.semantic_payload())

    assert isinstance(parsed, VerifiedIdentityCapabilityResultV1)
    assert parsed.verification_level == "full"
    assert full.capability_result_id != partial.capability_result_id


def test_identity_result_rejects_opaque_or_mismatched_artifact_ids() -> None:
    payload = _identity_result().semantic_payload()
    payload["identity_artifact_id"] = "opaque"
    with pytest.raises(ValidationError, match="content-addressed"):
        VerifiedIdentityCapabilityResultV1.model_validate(payload)

    payload["identity_artifact_id"] = "identity:" + "b" * 64
    with pytest.raises(ValidationError, match="does not match"):
        VerifiedIdentityCapabilityResultV1.model_validate(payload)


def test_result_parser_keeps_legacy_identity_without_discriminator() -> None:
    payload = _identity_result().semantic_payload()
    payload.pop("contract_kind")
    payload.pop("identity_artifact_id")
    payload.pop("identity_content_sha256")
    payload.pop("verification_level")

    parsed = parse_capability_result(payload)

    assert type(parsed) is CapabilityResultV1
    assert parsed.capability == "verified_identity"


def test_result_parser_rejects_unknown_or_malformed_discriminator() -> None:
    unknown = _identity_result().semantic_payload()
    unknown["contract_kind"] = "future-result-v9"
    with pytest.raises(ValueError, match="unsupported capability result contract"):
        parse_capability_result(unknown)

    malformed = _identity_result().semantic_payload()
    malformed.pop("identity_artifact_id")
    with pytest.raises(ValidationError):
        parse_capability_result(malformed)


def test_entry_parser_requires_matching_id_and_outer_capability() -> None:
    result = _identity_result()
    entry = {
        "capability": "verified_identity",
        "capability_result_id": result.capability_result_id,
        "capability_result": result.semantic_payload(),
    }
    assert parse_capability_result_entry(entry) == result

    with pytest.raises(ValueError, match="declared capability"):
        parse_capability_result_entry({**entry, "capability": "company_event_window"})
    with pytest.raises(ValueError, match="declared result ID"):
        parse_capability_result_entry({**entry, "capability_result_id": "b" * 64})
    missing_id = dict(entry)
    missing_id.pop("capability_result_id")
    with pytest.raises(ValueError, match="declared result ID"):
        parse_capability_result_entry(missing_id)


def test_publisher_preserves_identity_contract_summary() -> None:
    result = _identity_result()
    bundle = {
        "results": [
            {
                "capability": result.capability,
                "capability_result_id": result.capability_result_id,
                "capability_result": result.semantic_payload(),
            }
        ]
    }

    assert _extract_bundle_capabilities("a_share_supplement_bundle", bundle) == (
        "verified_identity",
    )
    assert _extract_bundle_result_ids(bundle) == {
        "verified_identity": result.capability_result_id
    }
    summary = _extract_bundle_result_summaries(bundle)[0]
    assert summary["contract_kind"] == "verified-identity-capability-result-v1"
    assert summary["verification_level"] == "full"


def test_publisher_rejects_half_typed_wrapper() -> None:
    bundle = {
        "results": [
            {
                "capability": "verified_identity",
                "capability_result_id": "a" * 64,
            }
        ]
    }

    with pytest.raises(ValueError, match="requires semantic content"):
        _extract_bundle_result_ids(bundle)
