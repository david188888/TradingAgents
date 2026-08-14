"""Deterministic, horizon-bounded financial-statement prefetch."""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from tradingagents.dataflows.capability_result import (
    CapabilityResultV1,
    ProviderAttemptV1,
    aggregate_capability_availability,
)
from tradingagents.dataflows.coverage import (
    BundleCoverageV1,
    SourceCoverageV1,
)
from tradingagents.dataflows.interface import route_to_vendor_with_trace
from tradingagents.dataflows.routing_trace import RoutedVendorCall
from tradingagents.research.analysis_cutoff import AnalysisCutoffV1
from tradingagents.research.horizon_policy import (
    CapabilityPlanV1,
    InvestmentHorizon,
    build_data_window_plan,
)

MAX_STATEMENT_CHARS = 30_000
_STATEMENT_METHODS = {
    "balance_sheet": "get_balance_sheet",
    "cash_flow": "get_cashflow",
    "income_statement": "get_income_statement",
}
_SOURCE_ID_BY_METHOD_VENDOR = {
    ("get_balance_sheet", "tushare"): "tushare.tushare_get_balance_sheet",
    ("get_balance_sheet", "sina"): "sina.sina_get_balance_sheet",
    ("get_balance_sheet", "yfinance"): "yfinance.balance_sheet",
    ("get_balance_sheet", "alpha_vantage"): "alpha_vantage.BALANCE_SHEET",
    ("get_cashflow", "tushare"): "tushare.tushare_get_cashflow",
    ("get_cashflow", "sina"): "sina.sina_get_cashflow",
    ("get_cashflow", "yfinance"): "yfinance.cash_flow",
    ("get_cashflow", "alpha_vantage"): "alpha_vantage.CASH_FLOW",
    ("get_income_statement", "tushare"): "tushare.tushare_get_income_statement",
    ("get_income_statement", "sina"): "sina.sina_get_income_statement",
    ("get_income_statement", "yfinance"): "yfinance.income_statement",
    ("get_income_statement", "alpha_vantage"): "alpha_vantage.INCOME_STATEMENT",
}
_PERIOD_COLUMNS = (
    "end_date",
    "fiscaldateending",
    "报告期",
    "报告日",
)
_FILING_COLUMNS = (
    "ann_date",
    "f_ann_date",
    "reporteddate",
    "filingdate",
    "公告日期",
)

FetchStatements = Callable[[str, str, str, str], RoutedVendorCall]


@dataclass(frozen=True)
class StatementMetadata:
    periods: tuple[str, ...]
    filing_dates: tuple[str, ...]
    public_data: str
    limitations: tuple[str, ...] = ()


def build_fundamentals_cutoff_failure_bundle(
    symbol: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    cutoff: AnalysisCutoffV1 | None,
    include_optional: bool = True,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Return typed negative statement results without touching providers."""

    from tradingagents.dataflows.ticker_utils import is_a_share_ticker

    market = cutoff.market if cutoff is not None else (
        "a_share" if is_a_share_ticker(symbol) else "global"
    )
    plan = build_data_window_plan(horizon, analysis_date, market=market)
    captured = recorded_at or datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    for capability in plan.capabilities:
        if not capability.capability_id.startswith("fundamentals_"):
            continue
        if not include_optional and capability.requirement != "required":
            continue
        source_ids = (
            tuple(capability.required_source_ids)
            + tuple(
                source_id
                for group in capability.required_source_groups
                for source_id in group.source_ids
            )
            + tuple(capability.optional_source_ids)
        )
        attempts = tuple(
            ProviderAttemptV1(
                source_id=source_id,
                provider=source_id.split(".", 1)[0],
                outcome="skipped_unobserved",
                reason_code="analysis_cutoff_resolution_failed",
                recorded_at=captured,
            )
            for source_id in source_ids
        )
        records = tuple(
            SourceCoverageV1(
                capability=capability.capability_id,
                source_id=source_id,
                item_count=0,
                completeness="unavailable",
                sources=(source_id,),
                degradations=("analysis_cutoff_resolution_failed",),
                as_of=analysis_date,
            )
            for source_id in source_ids
        )
        coverage = BundleCoverageV1.build(
            capability=capability.capability_id,
            records=records,
            required_source_ids=capability.required_source_ids,
            required_source_groups=capability.required_source_groups,
            optional_source_ids=capability.optional_source_ids,
        )
        typed = CapabilityResultV1(
            capability=capability.capability_id,
            symbol=symbol,
            market=market,
            analysis_date=analysis_date,
            analysis_cutoff_at=None,
            availability="invalid",
            freshness="unknown",
            coverage=coverage,
            source_ids=source_ids,
            attempts=attempts,
            degradation_codes=("analysis_cutoff_resolution_failed",),
            limitations=("analysis_cutoff_resolution_failed",),
        )
        results.append(
            {
                "capability": capability.capability_id,
                "requirement": capability.requirement,
                "status": "unavailable",
                "statements": [],
                "capability_result_id": typed.capability_result_id,
                "capability_result": typed.semantic_payload(),
            }
        )
    return {
        "schema_version": 1,
        "policy_version": plan.policy_version,
        "ticker": symbol,
        "market": market,
        "horizon": horizon,
        "as_of": analysis_date,
        "status": "invalid",
        "reason_code": "analysis_cutoff_resolution_failed",
        "analysis_cutoff": cutoff.model_dump(mode="json") if cutoff else {},
        "results": results,
    }


def build_fundamentals_prefetch_bundle(
    symbol: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    cutoff: AnalysisCutoffV1,
    fetch: FetchStatements | None = None,
    recorded_at: datetime | None = None,
    include_optional: bool = True,
) -> dict[str, Any]:
    """Fetch statement capabilities once and return canonical bundle content."""

    market = "a_share" if cutoff.market == "a_share" else "global"
    plan = build_data_window_plan(horizon, analysis_date, market=market)
    fetcher = fetch or _route_statement
    captured = recorded_at or datetime.now(timezone.utc)
    results = [
        _build_capability(
            symbol=symbol,
            analysis_date=analysis_date,
            cutoff=cutoff,
            plan=capability,
            fetch=fetcher,
            recorded_at=captured,
        )
        for capability in plan.capabilities
        if capability.capability_id.startswith("fundamentals_")
        and (include_optional or capability.requirement == "required")
    ]
    return {
        "schema_version": 1,
        "policy_version": plan.policy_version,
        "cutoff_policy_version": cutoff.policy_version,
        "ticker": symbol,
        "market": market,
        "horizon": horizon,
        "as_of": analysis_date,
        "analysis_cutoff": cutoff.model_dump(mode="json"),
        "results": results,
    }


def canonical_fundamentals_bundle(bundle: Mapping[str, Any]) -> str:
    return json.dumps(
        bundle,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def fundamentals_from_prefetch_bundle(
    raw_bundle: str | Mapping[str, Any] | None,
) -> str | None:
    """Return the frozen comprehensive fundamentals payload, if present."""

    if isinstance(raw_bundle, str):
        try:
            bundle = json.loads(raw_bundle)
        except (TypeError, ValueError):
            return None
    elif isinstance(raw_bundle, Mapping):
        bundle = raw_bundle
    else:
        return None
    if not isinstance(bundle, Mapping):
        return None

    results = tuple(
        result
        for result in bundle.get("results", ())
        if isinstance(result, Mapping)
        and str(result.get("capability", "")).startswith("fundamentals_")
    )
    if not results:
        return None

    usable = tuple(
        result
        for result in results
        if str(result.get("status", "")).lower() in {"ok", "partial"}
    )
    if usable:
        payload = {
            "ticker": bundle.get("ticker"),
            "horizon": bundle.get("horizon"),
            "as_of": bundle.get("as_of"),
            "results": list(usable),
        }
        return "PREFETCHED_FUNDAMENTALS_BUNDLE:\n" + json.dumps(
            payload, sort_keys=True, ensure_ascii=False
        )

    reason = "prefetched_fundamentals_unavailable"
    for result in results:
        for statement in result.get("statements", ()):
            if isinstance(statement, Mapping) and statement.get("reason_code"):
                reason = str(statement["reason_code"])
                break
        if reason != "prefetched_fundamentals_unavailable":
            break
        capability_result = result.get("capability_result")
        if isinstance(capability_result, Mapping):
            codes = capability_result.get("degradation_codes", ())
            if codes:
                reason = str(next(iter(codes)))
                break
    return f"PREFETCHED_FUNDAMENTALS_UNAVAILABLE: {reason}"


def statement_from_prefetch_bundle(
    raw_bundle: str | Mapping[str, Any] | None,
    *,
    statement: str,
    frequency: str,
) -> str | None:
    """Return one frozen statement payload for an injected Analyst tool call."""

    if isinstance(raw_bundle, str):
        try:
            bundle = json.loads(raw_bundle)
        except (TypeError, ValueError):
            return None
    elif isinstance(raw_bundle, Mapping):
        bundle = raw_bundle
    else:
        return None
    capability = (
        "fundamentals_quarterly"
        if frequency.lower() == "quarterly"
        else "fundamentals_annual"
    )
    for result in bundle.get("results", ()):
        if not isinstance(result, Mapping) or result.get("capability") != capability:
            continue
        for item in result.get("statements", ()):
            if isinstance(item, Mapping) and item.get("statement") == statement:
                data = str(item.get("data") or "").strip()
                if data:
                    return data
                status = str(item.get("status") or "unavailable")
                reason = str(item.get("reason_code") or "prefetched_statement_unavailable")
                return f"PREFETCHED_STATEMENT_{status.upper()}: {reason}"
    return None


def _build_capability(
    *,
    symbol: str,
    analysis_date: str,
    cutoff: AnalysisCutoffV1,
    plan: CapabilityPlanV1,
    fetch: FetchStatements,
    recorded_at: datetime,
) -> dict[str, Any]:
    frequency = "quarterly" if plan.capability_id.endswith("quarterly") else "annual"
    window = plan.windows[0]
    declared_sources = tuple(
        source_id
        for group in plan.required_source_groups
        for source_id in group.source_ids
    ) + tuple(plan.required_source_ids) + tuple(plan.optional_source_ids)
    attempts_by_source: dict[str, ProviderAttemptV1] = {}
    coverage_by_source: dict[str, SourceCoverageV1] = {}
    statements: list[dict[str, Any]] = []
    filing_dates: list[str] = []
    limitations: list[str] = []

    for statement, method in _STATEMENT_METHODS.items():
        routed = fetch(method, symbol, frequency, analysis_date)
        traces = []
        for trace in routed.attempts:
            source_id = _SOURCE_ID_BY_METHOD_VENDOR.get((method, trace.vendor))
            if source_id is None or source_id not in declared_sources:
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
            attempts_by_source[source_id] = attempt
            traces.append((source_id, attempt))

        observed = [item for item in traces if item[1].outcome == "observed"]
        selected_source = observed[-1][0] if observed else None
        metadata = None
        if selected_source is not None and routed.result is not None:
            metadata = _statement_metadata(
                str(routed.result),
                analysis_date=analysis_date,
                cutoff=cutoff,
                fetched_at=recorded_at,
                requested_periods=window.value,
            )
            filing_dates.extend(metadata.filing_dates)
            limitations.extend(metadata.limitations)

        for source_id, attempt in traces:
            if attempt.outcome == "observed":
                source_metadata = metadata if source_id == selected_source else None
                coverage_by_source[source_id] = _observed_coverage(
                    plan.capability_id,
                    source_id,
                    analysis_date,
                    source_metadata,
                    requested_periods=window.value,
                )
            else:
                coverage_by_source[source_id] = _unavailable_coverage(
                    plan.capability_id,
                    source_id,
                    analysis_date,
                    attempt.reason_code,
                )

        statements.append(
            {
                "statement": statement,
                "method": method,
                "frequency": frequency,
                "status": (
                    "ok"
                    if metadata is not None and metadata.public_data
                    else "unavailable"
                ),
                "source_id": selected_source,
                "data": metadata.public_data[:MAX_STATEMENT_CHARS] if metadata else "",
                "periods": list(metadata.periods) if metadata else [],
                "filing_dates": list(metadata.filing_dates) if metadata else [],
                "limitations": list(metadata.limitations) if metadata else [],
                "reason_code": (
                    None
                    if metadata is not None
                    else type(routed.error).__name__
                    if routed.error is not None
                    else "prefetched_statement_unavailable"
                ),
            }
        )

    for source_id in declared_sources:
        if source_id in attempts_by_source:
            continue
        attempts_by_source[source_id] = ProviderAttemptV1(
            source_id=source_id,
            provider=source_id.split(".", 1)[0],
            outcome="skipped_unobserved",
            reason_code="route_stopped_before_source",
            recorded_at=recorded_at,
        )
        coverage_by_source[source_id] = _unavailable_coverage(
            plan.capability_id,
            source_id,
            analysis_date,
            "route_stopped_before_source",
        )

    records = tuple(coverage_by_source[source_id] for source_id in declared_sources)
    attempts = tuple(attempts_by_source[source_id] for source_id in declared_sources)
    coverage = BundleCoverageV1.build(
        capability=plan.capability_id,
        records=records,
        required_source_ids=plan.required_source_ids,
        required_source_groups=plan.required_source_groups,
        optional_source_ids=plan.optional_source_ids,
    )
    availability = aggregate_capability_availability(coverage, attempts)
    reached = [attempt for attempt in attempts if attempt.reached_provider]
    result = CapabilityResultV1(
        capability=plan.capability_id,
        symbol=symbol,
        market=cutoff.market,
        analysis_date=analysis_date,
        analysis_cutoff_at=cutoff.analysis_cutoff_at,
        availability=availability,
        freshness="current" if availability in {"available", "partial"} else "unknown",
        coverage=coverage,
        source_ids=declared_sources,
        attempts=attempts,
        fallback_from=tuple(
            attempt.source_id
            for attempt in attempts
            if attempt.outcome in {"provider_failed", "not_covered"}
        ),
        effective_period=f"{window.value}_{window.unit}",
        published_at_or_filing_at=(
            _as_utc(max(filing_dates)) if filing_dates else None
        ),
        fetched_at=min(
            attempt.started_at for attempt in reached if attempt.started_at is not None
        )
        if reached
        else None,
        degradation_codes=tuple(
            dict.fromkeys(
                limitation
                for limitation in limitations
                if re.fullmatch(r"[a-z][a-z0-9_]*", limitation)
            )
        ),
        limitations=tuple(dict.fromkeys(limitations)),
    )
    return {
        "capability": plan.capability_id,
        "requirement": plan.requirement,
        "frequency": frequency,
        "requested_periods": window.value,
        "requested_unit": window.unit,
        "status": "ok" if availability in {"available", "partial"} else "unavailable",
        "statements": statements,
        "capability_result_id": result.capability_result_id,
        "capability_result": result.semantic_payload(),
    }


def _route_statement(
    method: str, symbol: str, frequency: str, analysis_date: str
) -> RoutedVendorCall:
    return route_to_vendor_with_trace(method, symbol, frequency, analysis_date)


def _statement_metadata(
    rendered: str,
    *,
    analysis_date: str,
    cutoff: AnalysisCutoffV1,
    fetched_at: datetime,
    requested_periods: int,
) -> StatementMetadata:
    periods, filing_dates = _extract_statement_dates(rendered)
    historical = date.fromisoformat(analysis_date) < fetched_at.date()
    limitations: list[str] = []
    public_data = rendered
    if historical and not filing_dates:
        limitations.append("historical_filing_time_unverified")
        public_data = (
            "Historical statement rows withheld because their filing/publication "
            "time cannot be proven at the analysis cutoff."
        )
    if cutoff.analysis_cutoff_at is not None and filing_dates:
        after_cutoff = [
            value
            for value in filing_dates
            if _as_utc(value) > cutoff.analysis_cutoff_at
        ]
        if after_cutoff:
            limitations.append("post_cutoff_statement_excluded")
            public_data = (
                "Statement payload withheld because it contains a filing published "
                "after the frozen analysis cutoff."
            )
            filing_dates = tuple(
                value for value in filing_dates if value not in after_cutoff
            )
    if len(periods) < requested_periods:
        limitations.append("requested_statement_window_incomplete")
    return StatementMetadata(
        periods=periods,
        filing_dates=filing_dates,
        public_data=public_data,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _extract_statement_dates(rendered: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        payload = json.loads(rendered)
    except (TypeError, ValueError):
        payload = None
    periods: set[str] = set()
    filings: set[str] = set()
    if isinstance(payload, Mapping):
        for key in ("annualReports", "quarterlyReports"):
            for row in payload.get(key, ()):
                if not isinstance(row, Mapping):
                    continue
                _add_date(periods, row.get("fiscalDateEnding"))
                for name in ("reportedDate", "filingDate"):
                    _add_date(filings, row.get(name))
        return tuple(sorted(periods)), tuple(sorted(filings))

    lines = [line for line in rendered.splitlines() if not line.startswith("#")]
    csv_text = "\n".join(lines).strip()
    if not csv_text:
        return (), ()
    try:
        rows = list(csv.reader(io.StringIO(csv_text)))
    except csv.Error:
        return (), ()
    if not rows:
        return (), ()
    headers = [str(value).strip() for value in rows[0]]
    normalized = [value.lower().replace(" ", "") for value in headers]
    period_indexes = [
        index for index, value in enumerate(normalized) if value in _PERIOD_COLUMNS
    ]
    filing_indexes = [
        index for index, value in enumerate(normalized) if value in _FILING_COLUMNS
    ]
    if period_indexes:
        for row in rows[1:]:
            for index in period_indexes:
                if index < len(row):
                    _add_date(periods, row[index])
            for index in filing_indexes:
                if index < len(row):
                    _add_date(filings, row[index])
    else:
        for value in headers[1:]:
            _add_date(periods, value)
    return tuple(sorted(periods)), tuple(sorted(filings))


def _observed_coverage(
    capability: str,
    source_id: str,
    analysis_date: str,
    metadata: StatementMetadata | None,
    *,
    requested_periods: int,
) -> SourceCoverageV1:
    periods = metadata.periods if metadata is not None else ()
    if not periods:
        completeness = "unknown"
        item_count = 1
    elif len(periods) >= requested_periods and not (
        metadata and metadata.limitations
    ):
        completeness = "complete"
        item_count = len(periods)
    else:
        completeness = "partial"
        item_count = len(periods)
    return SourceCoverageV1(
        capability=capability,
        source_id=source_id,
        actual_start=min(periods) if periods else None,
        actual_end=max(periods) if periods else None,
        item_count=item_count,
        completeness=completeness,
        sources=(source_id,),
        degradations=metadata.limitations if metadata is not None else (
            "statement_period_coverage_unknown",
        ),
        as_of=analysis_date,
    )


def _unavailable_coverage(
    capability: str, source_id: str, analysis_date: str, reason: str
) -> SourceCoverageV1:
    stable_reason = re.sub(r"[^a-z0-9_]+", "_", reason.lower()).strip("_")
    return SourceCoverageV1(
        capability=capability,
        source_id=source_id,
        item_count=0,
        completeness="unavailable",
        sources=(source_id,),
        degradations=(stable_reason or "source_unavailable",),
        as_of=analysis_date,
    )


def _add_date(target: set[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        return
    parsed = None
    for candidate in (text, text.replace("/", "-")):
        try:
            parsed = date.fromisoformat(candidate)
            break
        except ValueError:
            pass
    if parsed is None and re.fullmatch(r"\d{8}", text):
        try:
            parsed = datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return
    if parsed is not None:
        target.add(parsed.isoformat())


def _as_utc(value: str) -> datetime:
    return datetime.combine(
        date.fromisoformat(value), datetime.max.time(), tzinfo=timezone.utc
    )
