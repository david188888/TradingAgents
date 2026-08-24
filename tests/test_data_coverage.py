"""Deterministic requested-versus-observed data coverage contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tradingagents.dataflows.coverage import (
    BundleCoverageV1,
    CoveredText,
    SourceCoverageV1,
    SourceGroupRequirementV1,
    aggregate_bundle_completeness,
)


def _source(source_id: str, completeness: str, *, item_count: int = 1) -> SourceCoverageV1:
    usable = completeness != "unavailable"
    actual_start = "2026-07-01" if completeness == "complete" else "2026-07-20"
    return SourceCoverageV1(
        capability="company_event_window",
        source_id=source_id,
        requested_start="2026-07-01",
        requested_end="2026-07-31",
        actual_start=actual_start if usable else None,
        actual_end="2026-07-31" if usable else None,
        item_count=item_count if usable else 0,
        page_count=None,
        pagination_exhausted=None,
        completeness=completeness,
        sources=[source_id],
        degradations=[] if completeness == "complete" else ["coverage_not_proven"],
        as_of="2026-07-31",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (("complete", "complete"), "complete"),
        (("complete", "partial"), "partial"),
        (("unknown", "unavailable"), "partial"),
        (("unknown", "unknown"), "unknown"),
        (("unavailable", "unavailable"), "unavailable"),
    ],
)
def test_required_source_aggregation(statuses, expected):
    records = [_source(f"source-{index}", status) for index, status in enumerate(statuses)]

    assert (
        aggregate_bundle_completeness(
            records,
            required_source_ids=[record.source_id for record in records],
            optional_source_ids=[],
        )
        == expected
    )


@pytest.mark.unit
def test_optional_failure_does_not_lower_complete_required_source():
    required = _source("required", "complete")
    optional = _source("optional", "unavailable", item_count=0)

    bundle = BundleCoverageV1.build(
        capability="company_event_window",
        records=[required, optional],
        required_source_ids=["required"],
        optional_source_ids=["optional"],
    )

    assert bundle.bundle_completeness == "complete"
    assert bundle.records == (required, optional)


@pytest.mark.unit
def test_required_source_group_accepts_one_complete_real_provider():
    tushare = _source("tushare", "unavailable", item_count=0)
    akshare = _source("akshare", "complete")
    group = SourceGroupRequirementV1(
        group_id="adjusted_price_provider",
        minimum_usable=1,
        source_ids=("tushare", "akshare"),
    )

    bundle = BundleCoverageV1.build(
        capability="company_event_window",
        records=[tushare, akshare],
        required_source_ids=[],
        required_source_groups=[group],
        optional_source_ids=[],
    )

    assert bundle.bundle_completeness == "complete"


@pytest.mark.unit
def test_paginated_complete_requires_exhaustion():
    with pytest.raises(ValidationError, match="pagination_exhausted"):
        SourceCoverageV1(
            capability="official_disclosures",
            source_id="cninfo",
            requested_start="2025-01-01",
            requested_end="2026-01-01",
            actual_start="2025-01-01",
            actual_end="2026-01-01",
            item_count=30,
            page_count=1,
            pagination_exhausted=False,
            completeness="complete",
            sources=["cninfo"],
            degradations=[],
            as_of="2026-01-01",
        )


@pytest.mark.unit
def test_complete_coverage_rejects_incomplete_observed_window():
    with pytest.raises(ValidationError, match="full requested window"):
        SourceCoverageV1(
            capability="official_disclosures",
            source_id="cninfo",
            requested_start="2025-01-01",
            requested_end="2026-01-01",
            actual_start="2025-02-01",
            actual_end="2025-12-31",
            item_count=30,
            page_count=1,
            pagination_exhausted=True,
            completeness="complete",
            sources=["cninfo"],
            degradations=[],
            as_of="2026-01-01",
        )


@pytest.mark.unit
def test_unavailable_source_has_no_observed_window_or_items():
    with pytest.raises(ValidationError, match="unavailable"):
        SourceCoverageV1(
            capability="company_event_window",
            source_id="eastmoney",
            requested_start="2026-07-01",
            requested_end="2026-07-31",
            actual_start=None,
            actual_end=None,
            item_count=3,
            page_count=None,
            pagination_exhausted=None,
            completeness="unavailable",
            sources=["eastmoney"],
            degradations=["source_unavailable"],
            as_of="2026-07-31",
        )


@pytest.mark.unit
def test_covered_text_remains_string_compatible_and_exposes_typed_coverage():
    coverage = _source("eastmoney", "unknown")

    result = CoveredText("rendered report", coverage)

    assert isinstance(result, str)
    assert str(result) == "rendered report"
    assert result.coverage is coverage
