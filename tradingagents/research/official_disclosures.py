"""Typed official-disclosure capability results for deterministic prefetch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from tradingagents.dataflows.capability_result import (
    CapabilityResultV1,
    ProviderAttemptV1,
    aggregate_capability_availability,
)
from tradingagents.dataflows.coverage import BundleCoverageV1, CoveredText, SourceCoverageV1
from tradingagents.dataflows.interface import route_to_vendor_with_trace
from tradingagents.dataflows.routing_trace import RoutedVendorCall
from tradingagents.research.analysis_cutoff import AnalysisCutoffV1
from tradingagents.research.horizon_policy import InvestmentHorizon, build_data_window_plan

FetchOfficialDisclosures = Callable[[str, str, int], RoutedVendorCall]

_SOURCE_BY_VENDOR = {
    "cninfo": "cninfo.announcements",
    "china_exchange": "exchange.announcements",
}
_PROVIDER_BY_SOURCE = {
    source_id: provider for provider, source_id in _SOURCE_BY_VENDOR.items()
}


def build_official_disclosure_result(
    symbol: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    cutoff: AnalysisCutoffV1,
    fetch: FetchOfficialDisclosures | None = None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Return one durable result that preserves every policy-declared source."""

    plan = build_data_window_plan(
        horizon,
        analysis_date,
        market=cutoff.market,
    ).capability_index()["official_disclosures"]
    source_ids = (
        tuple(plan.required_source_ids)
        + tuple(
            source_id
            for group in plan.required_source_groups
            for source_id in group.source_ids
        )
        + tuple(plan.optional_source_ids)
    )
    captured = recorded_at or datetime.now(timezone.utc)

    if cutoff.market == "global":
        attempts = tuple(
            ProviderAttemptV1(
                source_id=source_id,
                provider=source_id.split(".", 1)[0],
                outcome="not_supported",
                reason_code="official_filings_provider_not_implemented",
                recorded_at=captured,
            )
            for source_id in source_ids
        )
        records = tuple(
            _unavailable_coverage(
                source_id,
                analysis_date,
                "official_filings_provider_not_implemented",
                requested_start=_official_start(plan.windows[0].value, analysis_date),
            )
            for source_id in source_ids
        )
        routed = None
    else:
        requested_start = _official_start(plan.windows[0].value, analysis_date)
        routed = (
            fetch(symbol, requested_start, plan.budget.max_pages)
            if fetch is not None
            else _fetch_a_share_official(
                symbol,
                requested_start,
                analysis_date,
                plan.budget.max_pages,
            )
        )
        attempt_by_source: dict[str, ProviderAttemptV1] = {}
        coverage_by_source: dict[str, SourceCoverageV1] = {}
        for trace in routed.attempts:
            source_id = _SOURCE_BY_VENDOR.get(trace.vendor)
            if source_id is None or source_id not in source_ids:
                continue
            attempt = ProviderAttemptV1(
                source_id=source_id,
                provider=trace.vendor,
                outcome=trace.outcome,
                reason_code=trace.reason_code,
                recorded_at=trace.recorded_at,
                started_at=trace.started_at,
                ended_at=trace.ended_at,
                vendor_call_id=trace.vendor_call_id,
                provenance_artifact_id=trace.provenance_artifact_id,
            )
            attempt_by_source[source_id] = attempt
            if attempt.outcome == "observed":
                coverage_by_source[source_id] = _observed_coverage(
                    routed.result,
                    source_id=source_id,
                    analysis_date=analysis_date,
                    requested_start=_official_start(
                        plan.windows[0].value, analysis_date
                    ),
                )
            else:
                coverage_by_source[source_id] = _unavailable_coverage(
                    source_id,
                    analysis_date,
                    attempt.reason_code,
                    requested_start=_official_start(
                        plan.windows[0].value, analysis_date
                    ),
                )
        for source_id in source_ids:
            if source_id in attempt_by_source:
                continue
            attempt_by_source[source_id] = ProviderAttemptV1(
                source_id=source_id,
                provider=_PROVIDER_BY_SOURCE.get(
                    source_id, source_id.split(".", 1)[0]
                ),
                outcome="skipped_unobserved",
                reason_code="source_not_attempted",
                recorded_at=captured,
            )
            coverage_by_source[source_id] = _unavailable_coverage(
                source_id,
                analysis_date,
                "source_not_attempted",
                requested_start=_official_start(plan.windows[0].value, analysis_date),
            )
        attempts = tuple(attempt_by_source[source_id] for source_id in source_ids)
        records = tuple(coverage_by_source[source_id] for source_id in source_ids)

    coverage = BundleCoverageV1.build(
        capability="official_disclosures",
        records=records,
        required_source_ids=plan.required_source_ids,
        required_source_groups=plan.required_source_groups,
        optional_source_ids=plan.optional_source_ids,
    )
    availability = aggregate_capability_availability(coverage, attempts)
    reached = tuple(attempt for attempt in attempts if attempt.reached_provider)
    reason_codes = tuple(
        dict.fromkeys(
            attempt.reason_code
            for attempt in attempts
            if attempt.outcome != "observed"
        )
    )
    result = CapabilityResultV1(
        capability="official_disclosures",
        symbol=symbol,
        market=cutoff.market,
        analysis_date=analysis_date,
        analysis_cutoff_at=cutoff.analysis_cutoff_at,
        availability=availability,
        freshness=(
            "current" if availability in {"available", "partial"} else "unknown"
        ),
        coverage=coverage,
        source_ids=source_ids,
        attempts=attempts,
        fallback_from=tuple(
            attempt.source_id
            for attempt in attempts
            if attempt.outcome in {"provider_failed", "not_covered"}
        ),
        effective_period=f"{plan.windows[0].value}_{plan.windows[0].unit}",
        fetched_at=(
            min(
                attempt.started_at
                for attempt in reached
                if attempt.started_at is not None
            )
            if reached
            else None
        ),
        degradation_codes=reason_codes,
        limitations=reason_codes,
    )
    return {
        "capability": "official_disclosures",
        "requirement": plan.requirement,
        "status": (
            "ok" if availability in {"available", "partial"} else "unavailable"
        ),
        "capability_result_id": result.capability_result_id,
        "capability_result": result.semantic_payload(),
        "data": str(routed.result) if routed is not None and routed.result is not None else "",
        "error_type": (
            type(routed.error).__name__
            if routed is not None and routed.error is not None
            else None
        ),
    }


def _fetch_a_share_official(
    symbol: str, start_date: str, end_date: str, max_pages: int
) -> RoutedVendorCall:
    return route_to_vendor_with_trace(
        "get_a_share_cninfo_announcements",
        symbol,
        start_date,
        # The public contract is inclusive of the frozen analysis date.
        end_date,
        max_pages=max_pages,
    )


def _official_start(years: int, analysis_date: str) -> str:
    from datetime import date

    value = date.fromisoformat(analysis_date)
    try:
        return value.replace(year=value.year - years).isoformat()
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28).isoformat()


def _observed_coverage(
    raw: object,
    *,
    source_id: str,
    analysis_date: str,
    requested_start: str,
) -> SourceCoverageV1:
    if isinstance(raw, CoveredText) and raw.coverage.source_id == source_id:
        return raw.coverage
    return SourceCoverageV1(
        capability="official_disclosures",
        source_id=source_id,
        requested_start=requested_start,
        requested_end=analysis_date,
        item_count=1,
        completeness="unknown",
        sources=(source_id,),
        degradations=("source_coverage_not_reported",),
        as_of=analysis_date,
    )


def _unavailable_coverage(
    source_id: str,
    analysis_date: str,
    reason_code: str,
    *,
    requested_start: str,
) -> SourceCoverageV1:
    return SourceCoverageV1(
        capability="official_disclosures",
        source_id=source_id,
        requested_start=requested_start,
        requested_end=analysis_date,
        item_count=0,
        completeness="unavailable",
        sources=(source_id,),
        degradations=(reason_code,),
        as_of=analysis_date,
    )
