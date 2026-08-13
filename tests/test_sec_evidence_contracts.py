from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.dataflows.capability_result import ProviderAttemptV1
from tradingagents.dataflows.coverage import (
    BundleCoverageV1,
    SecDisclosureCoverageV1,
    SourceCoverageV1,
)
from tradingagents.research.instrument_identity import (
    IdentityFieldFactV1,
    VerifiedInstrumentIdentityV1,
)
from tradingagents.research.pit_snapshot import (
    ArtifactClosureRefV1,
    EvidenceSelectionV1,
    PointInTimeEvidenceSnapshotV1,
)
from tradingagents.research.sec_filings import (
    SecFilingDocumentV1,
    SecFilingIndexCoverageV1,
    SecFilingIndexV1,
    SecFilingRecordV1,
    SecSourceArtifactRefV1,
)

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 8, 13, 7, 0, tzinfo=timezone.utc)


def _sec_coverage(
    *,
    search_complete: bool,
    observed: int,
    targets: int,
    rejected: int,
    usable: int,
) -> SecDisclosureCoverageV1:
    if search_complete and targets == 0 and rejected == 0:
        completeness = "unavailable"
        degradations = ("no_target_filings_in_window",)
    elif search_complete and rejected == 0 and usable == targets:
        completeness = "complete"
        degradations = ()
    else:
        completeness = "partial" if search_complete else "unknown"
        degradations = ("sec_search_incomplete",)
    return SecDisclosureCoverageV1(
        capability="official_disclosures",
        source_id="sec.company_filings",
        requested_start="2025-08-13",
        requested_end="2026-08-13",
        actual_start="2025-08-13" if usable else None,
        actual_end="2026-08-13" if usable else None,
        item_count=usable,
        page_count=1,
        pagination_exhausted=search_complete,
        completeness=completeness,
        sources=("sec.company_filings",),
        degradations=degradations,
        as_of="2026-08-13",
        observed_unit_count=observed,
        search_complete=search_complete,
        target_filing_count=targets,
        rejected_target_count=rejected,
        required_document_count=0,
        completed_document_count=0,
    )


@pytest.mark.parametrize(
    ("record", "expected"),
    (
        (_sec_coverage(search_complete=False, observed=1, targets=0, rejected=0, usable=0), "unknown"),
        (_sec_coverage(search_complete=True, observed=1, targets=1, rejected=1, usable=0), "partial"),
        (_sec_coverage(search_complete=True, observed=1, targets=0, rejected=0, usable=0), "unavailable"),
        (_sec_coverage(search_complete=True, observed=1, targets=1, rejected=0, usable=1), "complete"),
    ),
)
def test_sec_zero_item_coverage_roundtrips_without_weakening_generic(
    record: SecDisclosureCoverageV1,
    expected: str,
) -> None:
    envelope = BundleCoverageV1.build(
        capability="official_disclosures",
        records=(record,),
        required_source_ids=(record.source_id,),
        optional_source_ids=(),
    )

    replayed = BundleCoverageV1.model_validate(envelope.model_dump(mode="json"))

    assert replayed.bundle_completeness == expected
    assert isinstance(replayed.records[0], SecDisclosureCoverageV1)


def test_generic_zero_item_partial_or_unknown_remains_invalid() -> None:
    for completeness in ("partial", "unknown"):
        with pytest.raises(ValidationError, match="usable retained items"):
            SourceCoverageV1(
                capability="company_event_window",
                source_id="example.news",
                item_count=0,
                completeness=completeness,
                sources=("example.news",),
                as_of="2026-08-13",
            )


def test_sec_incomplete_zero_item_requires_an_observed_index_unit() -> None:
    with pytest.raises(ValidationError, match="usable retained items"):
        _sec_coverage(
            search_complete=False,
            observed=0,
            targets=0,
            rejected=0,
            usable=0,
        )


def _identity() -> VerifiedInstrumentIdentityV1:
    facts = tuple(
        IdentityFieldFactV1(
            field_name=field,
            value=value,
            source_id="sec.company_tickers",
            observed_at=NOW,
            effective_at=CUTOFF,
        )
        for field, value in (
            ("ticker", "AAPL"),
            ("company_name", "Apple Inc."),
            ("security_type", "equity"),
            ("listing_status", "listed"),
            ("exchange", "NASDAQ"),
            ("regulatory_authority", "sec"),
            ("cik", "0000320193"),
        )
    )
    return VerifiedInstrumentIdentityV1(
        ticker="AAPL",
        market="global",
        analysis_date="2026-08-13",
        analysis_cutoff_at=CUTOFF,
        company_name="Apple Inc.",
        security_type="equity",
        listing_status="listed",
        exchange="NASDAQ",
        regulatory_authority="sec",
        cik="0000320193",
        availability="available",
        verification_level="full",
        field_facts=facts,
        provider_attempts=(
            ProviderAttemptV1(
                source_id="sec.company_tickers",
                provider="sec",
                outcome="observed",
                reason_code="identity_observed",
                recorded_at=NOW,
                started_at=NOW,
                ended_at=NOW,
            ),
        ),
    )


def test_identity_hash_is_stable_and_rejects_cross_identity_facts() -> None:
    identity = _identity()
    replayed = VerifiedInstrumentIdentityV1.model_validate(
        dict(reversed(list(identity.semantic_payload().items())))
    )
    assert identity.content_hash == replayed.content_hash

    facts = list(identity.field_facts)
    ticker_position = next(
        index for index, fact in enumerate(facts) if fact.field_name == "ticker"
    )
    facts[ticker_position] = facts[ticker_position].model_copy(update={"value": "MSFT"})
    with pytest.raises(ValidationError, match="ticker field fact"):
        VerifiedInstrumentIdentityV1.model_validate(
            {
                **identity.semantic_payload(),
                "field_facts": [fact.model_dump(mode="json") for fact in facts],
            }
        )


def test_identity_requires_exact_field_level_provenance() -> None:
    identity = _identity()
    without_company_fact = tuple(
        fact for fact in identity.field_facts if fact.field_name != "company_name"
    )
    with pytest.raises(ValidationError, match="company_name requires"):
        VerifiedInstrumentIdentityV1.model_validate(
            {**identity.semantic_payload(), "field_facts": without_company_fact}
        )

    with pytest.raises(ValidationError, match="exchange facts require"):
        VerifiedInstrumentIdentityV1.model_validate(
            {**identity.semantic_payload(), "exchange": None}
        )


def _source_ref(
    role: str,
    digest: str,
    *,
    logical_name: str | None = None,
) -> SecSourceArtifactRefV1:
    return SecSourceArtifactRefV1(
        role=role,
        artifact_id=f"{role}:{digest}",
        content_sha256=digest,
        logical_name=logical_name,
    )


def test_sec_index_enforces_forms_cutoff_and_document_closure() -> None:
    raw = _source_ref("primary_document_raw", "b" * 64)
    normalized = _source_ref("primary_document_text", "c" * 64)
    document = SecFilingDocumentV1(
        accession="0000320193-26-000001",
        form="10-Q",
        accepted_at=datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc),
        raw_artifact_ref=raw,
        normalized_text_artifact_ref=normalized,
        parser_status="complete",
    )
    source = _source_ref("submissions_current", "a" * 64)
    filing = SecFilingRecordV1(
        form="10-Q",
        accession="0000320193-26-000001",
        filing_date="2026-08-12",
        accepted_at=document.accepted_at,
        report_date="2026-06-30",
        primary_document="aapl-20260630.htm",
        sec_urls=("https://www.sec.gov/Archives/edgar/data/320193/example.htm",),
        source_artifact_ref=source,
        document=document,
    )
    coverage = SecFilingIndexCoverageV1(
        index_search_complete=True,
        observed_index_count=1,
        target_filing_count=1,
        rejected_target_count=0,
        required_document_count=1,
        completed_document_count=1,
    )
    index = SecFilingIndexV1(
        ticker="AAPL",
        cik="0000320193",
        company_name="Apple Inc.",
        analysis_cutoff_at=CUTOFF,
        requested_start="2025-08-13",
        requested_end="2026-08-13",
        fetched_history_files=(),
        pagination_exhausted=True,
        source_artifacts=(source, raw, normalized),
        coverage=coverage,
        filings=(filing,),
    )

    replayed = SecFilingIndexV1.model_validate(index.semantic_payload())
    assert index.content_hash == replayed.content_hash

    with pytest.raises(ValidationError, match="accepted_at cannot exceed cutoff"):
        SecFilingIndexV1.model_validate(
            {
                **index.semantic_payload(),
                "filings": [
                    {
                        **filing.model_dump(mode="json", exclude={"document"}),
                        "accepted_at": "2026-08-13T08:01:00Z",
                        "document": {
                            **document.semantic_payload(),
                            "accepted_at": "2026-08-13T08:01:00Z",
                        },
                    }
                ],
            }
        )


def test_sec_index_closes_history_and_full_artifact_identity() -> None:
    source = _source_ref("submissions_current", "a" * 64)
    history = _source_ref(
        "submissions_history",
        "b" * 64,
        logical_name="CIK0000320193-submissions-001.json",
    )
    filing = SecFilingRecordV1(
        form="8-K",
        accession="0000320193-26-000001",
        filing_date="2026-08-12",
        accepted_at=datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc),
        primary_document="aapl-event.htm",
        sec_urls=("https://www.sec.gov/Archives/edgar/data/320193/event.htm",),
        source_artifact_ref=history,
    )
    payload = {
        "ticker": "AAPL",
        "cik": "0000320193",
        "company_name": "Apple Inc.",
        "analysis_cutoff_at": CUTOFF,
        "requested_start": "2025-08-13",
        "requested_end": "2026-08-13",
        "fetched_history_files": (history.logical_name,),
        "pagination_exhausted": True,
        "source_artifacts": (source, history),
        "coverage": SecFilingIndexCoverageV1(
            index_search_complete=True,
            observed_index_count=1,
            target_filing_count=1,
            rejected_target_count=0,
            required_document_count=0,
            completed_document_count=0,
        ),
        "filings": (filing,),
    }
    SecFilingIndexV1.model_validate(payload)

    with pytest.raises(ValidationError, match="fetched history files"):
        SecFilingIndexV1.model_validate(
            {**payload, "fetched_history_files": ("unexpected.json",)}
        )

    conflicting_history = history.model_copy(update={"content_sha256": "c" * 64})
    with pytest.raises(ValidationError, match="exactly match"):
        SecFilingIndexV1.model_validate(
            {
                **payload,
                "filings": (filing.model_copy(
                    update={"source_artifact_ref": conflicting_history}
                ),),
            }
        )

    raw = _source_ref("primary_document_raw", "d" * 64)
    masquerading = raw.model_copy(update={"role": "submissions_current"})
    document = SecFilingDocumentV1(
        accession="0000320193-26-000002",
        form="10-Q",
        accepted_at=datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc),
        raw_artifact_ref=raw,
        parser_status="parser_timeout",
    )
    with pytest.raises(ValidationError, match="exactly match"):
        SecFilingIndexV1.model_validate(
            {
                **payload,
                "source_artifacts": (source, history, masquerading),
                "coverage": SecFilingIndexCoverageV1(
                    index_search_complete=True,
                    observed_index_count=1,
                    target_filing_count=1,
                    rejected_target_count=0,
                    required_document_count=1,
                    completed_document_count=0,
                ),
                "filings": (
                    filing.model_copy(
                        update={
                            "form": "10-Q",
                            "accession": "0000320193-26-000002",
                            "document": document,
                        }
                    ),
                ),
            }
        )


def test_new_durable_refs_reject_opaque_or_mismatched_ids() -> None:
    with pytest.raises(ValidationError, match="content-addressed"):
        _source_ref("submissions_current", "a" * 64).model_copy(
            update={"artifact_id": "opaque"}
        ).__class__.model_validate(
            {
                "role": "submissions_current",
                "artifact_id": "opaque",
                "content_sha256": "a" * 64,
            }
        )
    with pytest.raises(ValidationError, match="does not match"):
        ArtifactClosureRefV1(
            artifact_id="evidence:" + "a" * 64,
            content_sha256="b" * 64,
            role="capability_result",
        )


def test_downloaded_but_unparsed_documents_require_raw_artifact() -> None:
    for parser_status in ("parser_timeout", "normalized_text_unavailable"):
        with pytest.raises(ValidationError, match="require a raw ref"):
            SecFilingDocumentV1(
                accession="0000320193-26-000001",
                form="10-Q",
                accepted_at=CUTOFF,
                parser_status=parser_status,
            )


def test_snapshot_hash_excludes_publication_boundary_but_binds_semantics() -> None:
    closure = ArtifactClosureRefV1(
        artifact_id="evidence:" + "d" * 64,
        content_sha256="d" * 64,
        role="capability_result",
    )
    identity_closure = ArtifactClosureRefV1(
        artifact_id="identity:" + "a" * 64,
        content_sha256="a" * 64,
        role="verified_identity",
    )
    selection = EvidenceSelectionV1(
        capability="verified_identity",
        capability_result_id="e" * 64,
        artifact_id=closure.artifact_id,
        evidence_ref_ids=("f" * 64,),
        coverage_ref_ids=("coverage_verified_identity",),
    )
    snapshot = PointInTimeEvidenceSnapshotV1(
        run_id="run_test",
        ticker="AAPL",
        analysis_cutoff_at=CUTOFF,
        identity_artifact_id="identity:" + "a" * 64,
        identity_content_hash="a" * 64,
        source_committed_sequence=42,
        resolved_plan_id="plan:" + "b" * 64,
        resolved_plan_hash="b" * 64,
        selections=(selection,),
        artifact_closure=(identity_closure, closure),
        missing_capabilities=(),
        degraded_capabilities=(),
    )

    assert snapshot.snapshot_hash == snapshot.model_copy().snapshot_hash
    changed = snapshot.model_copy(update={"source_committed_sequence": 43})
    assert changed.snapshot_hash != snapshot.snapshot_hash
    assert "registry_through_sequence" not in snapshot.semantic_payload()
