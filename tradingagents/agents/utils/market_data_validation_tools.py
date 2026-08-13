import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any

from langchain_core.tools import tool

from tradingagents.agents.utils.tool_guard import guard_target_ticker
from tradingagents.dataflows.capability_result import (
    CapabilityResultV1,
    ProviderAttemptV1,
    aggregate_capability_availability,
)
from tradingagents.dataflows.coverage import BundleCoverageV1, CoveredText, SourceCoverageV1
from tradingagents.dataflows.interface import route_to_vendor, route_to_vendor_with_trace
from tradingagents.dataflows.market_data_validator import (
    build_verified_current_market_snapshot,
    build_verified_market_snapshot,
    get_verified_current_quote,
)
from tradingagents.dataflows.routing_trace import RoutedVendorCall
from tradingagents.dataflows.ticker_utils import is_a_share_ticker
from tradingagents.research.analysis_cutoff import (
    AnalysisCutoffV1,
    cutoff_failure_bundle,
    parse_analysis_cutoff,
    time_sensitive_fetch_blocked,
)
from tradingagents.research.horizon_policy import InvestmentHorizon, build_data_window_plan
from tradingagents.research.price_coverage import adjusted_price_capability_dict
from tradingagents.research.price_prefetch import build_price_prefetch_plan

MAX_PRICE_BUNDLE_CHARS = 24_000
_ADJUSTED_SOURCE_BY_VENDOR = {
    "tushare": "tushare.qfq_daily",
    "akshare": "akshare.qfq_daily",
    "yfinance": "yfinance.adjusted_ohlcv",
    "alpha_vantage": "alpha_vantage.TIME_SERIES_DAILY_ADJUSTED",
}


@tool
@guard_target_ticker("symbol")
def get_verified_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[
        int, "number of recent trading rows to include for sanity-checking"
    ] = 30,
) -> str:
    """Deterministic verification snapshot for exact market-data claims.

    Returns the latest OHLCV row on or before curr_date, common technical
    indicators, and recent closes. Call this before making exact claims about
    price levels, Bollinger bands, RSI, MACD, moving averages, support /
    resistance, or historical comparisons, and treat it as the source of truth.
    """
    return build_verified_market_snapshot(symbol, curr_date, look_back_days)


@tool
@guard_target_ticker("symbol")
def get_verified_current_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
) -> str:
    """Return only the latest verified OHLCV row for current-price facts.

    Historical rows and technical indicators are excluded by contract. Use
    the deterministic adjusted-price bundle for every historical or technical
    claim.
    """
    return build_verified_current_market_snapshot(symbol, curr_date)


def _state_horizon(state: Mapping[str, Any]) -> InvestmentHorizon:
    value = state.get("horizon")
    return value if value in {"short", "medium", "long"} else "medium"


def _price_result(raw: object, *, adjusted: bool) -> dict[str, object]:
    rendered = str(raw)
    truncated = len(rendered) > MAX_PRICE_BUNDLE_CHARS
    public_data = rendered
    if truncated:
        head_chars = MAX_PRICE_BUNDLE_CHARS // 6
        public_data = (
            rendered[:head_chars]
            + "\n... middle rows omitted by deterministic bundle limit ...\n"
            + rendered[-(MAX_PRICE_BUNDLE_CHARS - head_chars) :]
        )
    result: dict[str, object] = {
        "status": "ok" if isinstance(raw, CoveredText) or not adjusted else "degraded",
        "data": public_data,
        "truncated": truncated,
    }
    if isinstance(raw, CoveredText):
        result["coverage"] = raw.coverage.model_dump(mode="json")
    elif adjusted:
        result["degradations"] = ["adjusted_price_coverage_not_reported"]
    return result


def run_adjusted_price_prefetch(
    symbol: str,
    curr_date: str,
    *,
    horizon: InvestmentHorizon,
    analysis_cutoff: AnalysisCutoffV1 | None = None,
) -> str:
    """Fetch required adjusted history and a separately labelled raw audit."""
    market = "a_share" if is_a_share_ticker(symbol) else "global"
    plan = build_price_prefetch_plan(horizon, curr_date, market=market)
    adjusted_call: RoutedVendorCall | None = None
    try:
        if analysis_cutoff is not None:
            adjusted_call = route_to_vendor_with_trace(
                "get_adjusted_price_history",
                symbol,
                plan.start_date,
                curr_date,
            )
            if adjusted_call.error is not None:
                raise adjusted_call.error
            adjusted_raw = adjusted_call.result
        else:
            adjusted_raw = route_to_vendor(
                "get_adjusted_price_history", symbol, plan.start_date, curr_date
            )
        adjusted = _price_result(adjusted_raw, adjusted=True)
    except Exception as exc:
        adjusted = {
            "status": "unavailable",
            "degradations": ["adjusted_price_source_unavailable"],
            "error_type": type(exc).__name__,
        }
    quote_started_at = datetime.now(timezone.utc)
    try:
        current_quote = get_verified_current_quote(symbol, curr_date)
        quote_snapshot: dict[str, object] = {
            "status": "available",
            "market_price": current_quote.close,
            "price_as_of": current_quote.observed_on,
            "source_id": getattr(current_quote, "source_id", None),
            # Instrument identity establishes the A-share quote currency, but
            # never the user's cost/NAV currency. Global quote currency remains
            # deliberately unverified until a vendor declares it.
            "quote_currency": "CNY" if market == "a_share" else None,
        }
    except Exception as exc:
        quote_snapshot = {
            "status": "unavailable",
            "reason_code": "verified_market_price_unavailable",
            "error_type": type(exc).__name__,
        }
    try:
        raw_audit = _price_result(
            route_to_vendor("get_stock_data", symbol, plan.start_date, curr_date),
            adjusted=False,
        )
    except Exception as exc:
        raw_audit = {
            "status": "unavailable",
            "degradations": ["raw_price_audit_unavailable"],
            "error_type": type(exc).__name__,
        }
    typed_results = (
        _identity_and_snapshot_results(
            symbol,
            curr_date,
            horizon=horizon,
            cutoff=analysis_cutoff,
            quote=quote_snapshot,
            recorded_at=datetime.now(timezone.utc),
            quote_started_at=quote_started_at,
        )
        if analysis_cutoff is not None
        else []
    )
    if analysis_cutoff is not None and adjusted_call is not None:
        typed_results.append(
            _adjusted_price_typed_result(
                symbol,
                curr_date,
                horizon=horizon,
                cutoff=analysis_cutoff,
                routed=adjusted_call,
            )
        )
    bundle = {
        "schema_version": 1,
        "policy_version": plan.policy_version,
        "ticker": symbol,
        "market": market,
        "horizon": horizon,
        "as_of": curr_date,
        "start_date": plan.start_date,
        "requested_windows": plan.requested_windows,
        "granularities": plan.granularities,
        "required_trading_days": plan.required_trading_days,
        "adjusted": adjusted,
        "current_quote": quote_snapshot,
        "raw_audit": raw_audit,
        "results": typed_results,
    }
    # Expose a stable capability-level status for eligibility / DataQuality.
    bundle["adjusted"]["capability_status"] = adjusted_price_capability_dict(bundle)
    return json.dumps(bundle, ensure_ascii=False)


def create_adjusted_price_prefetch_node():
    """Create the deterministic graph task that precedes Market Analyst."""

    def prefetch(state: Mapping[str, Any]) -> dict[str, str]:
        if time_sensitive_fetch_blocked(state):
            return {
                "adjusted_price_bundle": _price_cutoff_failure_bundle(
                    state, _state_horizon(state)
                )
            }
        return {
            "adjusted_price_bundle": run_adjusted_price_prefetch(
                str(state["company_of_interest"]),
                str(state["trade_date"]),
                horizon=_state_horizon(state),
                analysis_cutoff=parse_analysis_cutoff(state.get("analysis_cutoff")),
            )
        }

    return prefetch


def _price_cutoff_failure_bundle(
    state: Mapping[str, Any], horizon: InvestmentHorizon
) -> str:
    legacy = json.loads(
        cutoff_failure_bundle(state, capability="adjusted_price_history")
    )
    cutoff = parse_analysis_cutoff(state.get("analysis_cutoff"))
    assert cutoff is not None and cutoff.status == "invalid"
    plan = build_data_window_plan(
        horizon,
        cutoff.analysis_date,
        market=cutoff.market,
    ).capability_index()
    captured = datetime.now(timezone.utc)
    results = []
    for capability_id in (
        "verified_identity",
        "verified_market_snapshot",
        "adjusted_price_history",
    ):
        capability = plan[capability_id]
        source_ids = tuple(
            source_id
            for group in capability.required_source_groups
            for source_id in group.source_ids
        ) + tuple(capability.required_source_ids) + tuple(capability.optional_source_ids)
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
                capability=capability_id,
                source_id=source_id,
                item_count=0,
                completeness="unavailable",
                sources=(source_id,),
                degradations=("analysis_cutoff_resolution_failed",),
                as_of=cutoff.analysis_date,
            )
            for source_id in source_ids
        )
        coverage = BundleCoverageV1.build(
            capability=capability_id,
            records=records,
            required_source_ids=capability.required_source_ids,
            required_source_groups=capability.required_source_groups,
            optional_source_ids=capability.optional_source_ids,
        )
        typed = CapabilityResultV1(
            capability=capability_id,
            symbol=cutoff.ticker,
            market=cutoff.market,
            analysis_date=cutoff.analysis_date,
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
                "capability": capability_id,
                "requirement": capability.requirement,
                "status": "unavailable",
                "capability_result_id": typed.capability_result_id,
                "capability_result": typed.semantic_payload(),
            }
        )
    legacy["results"] = results
    return json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity_and_snapshot_results(
    symbol: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    cutoff: AnalysisCutoffV1,
    quote: Mapping[str, object],
    recorded_at: datetime,
    quote_started_at: datetime,
) -> list[dict[str, object]]:
    plan = build_data_window_plan(
        horizon,
        analysis_date,
        market=cutoff.market,
    ).capability_index()
    identity_source = cutoff.identity_source_id
    quote_source = quote.get("source_id")
    results = []
    for capability_id, selected_source, started_at in (
        ("verified_identity", identity_source, recorded_at),
        ("verified_market_snapshot", quote_source, quote_started_at),
    ):
        capability = plan[capability_id]
        source_ids = tuple(
            source_id
            for group in capability.required_source_groups
            for source_id in group.source_ids
        ) + tuple(capability.required_source_ids) + tuple(capability.optional_source_ids)
        selected = str(selected_source) if selected_source in source_ids else None
        attempts = tuple(
            ProviderAttemptV1(
                source_id=source_id,
                provider=source_id.split(".", 1)[0],
                outcome="observed" if source_id == selected else "skipped_unobserved",
                reason_code=(
                    "verified_observation_available"
                    if source_id == selected
                    else "source_not_attempted"
                ),
                recorded_at=recorded_at,
                started_at=started_at if source_id == selected else None,
                ended_at=recorded_at if source_id == selected else None,
            )
            for source_id in source_ids
        )
        records = tuple(
            SourceCoverageV1(
                capability=capability_id,
                source_id=source_id,
                actual_start=analysis_date if source_id == selected else None,
                actual_end=analysis_date if source_id == selected else None,
                item_count=1 if source_id == selected else 0,
                completeness="complete" if source_id == selected else "unavailable",
                sources=(source_id,),
                degradations=() if source_id == selected else ("source_not_attempted",),
                as_of=analysis_date,
            )
            for source_id in source_ids
        )
        coverage = BundleCoverageV1.build(
            capability=capability_id,
            records=records,
            required_source_ids=capability.required_source_ids,
            required_source_groups=capability.required_source_groups,
            optional_source_ids=capability.optional_source_ids,
        )
        availability = aggregate_capability_availability(coverage, attempts)
        typed = CapabilityResultV1(
            capability=capability_id,
            symbol=symbol,
            market=cutoff.market,
            analysis_date=analysis_date,
            analysis_cutoff_at=cutoff.analysis_cutoff_at,
            availability=availability,
            freshness=("current" if availability == "available" else "unknown"),
            coverage=coverage,
            source_ids=source_ids,
            attempts=attempts,
            source_observed_at=(
                datetime.fromisoformat(str(quote["price_as_of"])).replace(
                    tzinfo=timezone.utc
                )
                if capability_id == "verified_market_snapshot"
                and quote.get("price_as_of")
                and selected is not None
                else None
            ),
            fetched_at=started_at if selected is not None else None,
            degradation_codes=() if selected is not None else ("source_unattributed",),
            limitations=() if selected is not None else ("source_unattributed",),
        )
        results.append(
            {
                "capability": capability_id,
                "requirement": capability.requirement,
                "status": "ok" if availability == "available" else "unavailable",
                "capability_result_id": typed.capability_result_id,
                "capability_result": typed.semantic_payload(),
            }
        )
    return results


def _adjusted_price_typed_result(
    symbol: str,
    analysis_date: str,
    *,
    horizon: InvestmentHorizon,
    cutoff: AnalysisCutoffV1,
    routed: RoutedVendorCall,
) -> dict[str, object]:
    capability = build_data_window_plan(
        horizon,
        analysis_date,
        market=cutoff.market,
    ).capability_index()["adjusted_price_history"]
    source_ids = tuple(
        source_id
        for group in capability.required_source_groups
        for source_id in group.source_ids
    ) + tuple(capability.required_source_ids) + tuple(capability.optional_source_ids)
    attempts_by_source: dict[str, ProviderAttemptV1] = {}
    for trace in routed.attempts:
        source_id = _ADJUSTED_SOURCE_BY_VENDOR.get(trace.vendor)
        if source_id is None or source_id not in source_ids:
            continue
        attempts_by_source[source_id] = ProviderAttemptV1(
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
    selected_coverage = (
        routed.result.coverage if isinstance(routed.result, CoveredText) else None
    )
    records = []
    attempts = []
    for source_id in source_ids:
        attempt = attempts_by_source.get(source_id)
        if attempt is None:
            attempt = ProviderAttemptV1(
                source_id=source_id,
                provider=source_id.split(".", 1)[0],
                outcome="skipped_unobserved",
                reason_code="source_not_attempted",
                recorded_at=datetime.now(timezone.utc),
            )
        attempts.append(attempt)
        if (
            attempt.outcome == "observed"
            and selected_coverage is not None
            and selected_coverage.source_id == source_id
        ):
            records.append(selected_coverage)
        else:
            records.append(
                SourceCoverageV1(
                    capability="adjusted_price_history",
                    source_id=source_id,
                    item_count=0,
                    completeness="unavailable",
                    sources=(source_id,),
                    degradations=(attempt.reason_code,),
                    as_of=analysis_date,
                )
            )
    coverage = BundleCoverageV1.build(
        capability="adjusted_price_history",
        records=tuple(records),
        required_source_ids=capability.required_source_ids,
        required_source_groups=capability.required_source_groups,
        optional_source_ids=capability.optional_source_ids,
    )
    attempt_tuple = tuple(attempts)
    availability = aggregate_capability_availability(coverage, attempt_tuple)
    reached = tuple(attempt for attempt in attempt_tuple if attempt.reached_provider)
    typed = CapabilityResultV1(
        capability="adjusted_price_history",
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
        attempts=attempt_tuple,
        fallback_from=tuple(
            attempt.source_id
            for attempt in attempt_tuple
            if attempt.outcome in {"provider_failed", "not_covered"}
        ),
        effective_period=f"{horizon}_policy_window",
        source_observed_at=(
            datetime.fromisoformat(selected_coverage.actual_end).replace(
                tzinfo=timezone.utc
            )
            if selected_coverage is not None and selected_coverage.actual_end
            else None
        ),
        fetched_at=(
            min(
                attempt.started_at
                for attempt in reached
                if attempt.started_at is not None
            )
            if reached
            else None
        ),
        degradation_codes=tuple(
            dict.fromkeys(
                degradation
                for record in records
                for degradation in record.degradations
            )
        ),
    )
    return {
        "capability": "adjusted_price_history",
        "requirement": capability.requirement,
        "status": "ok" if availability in {"available", "partial"} else "unavailable",
        "capability_result_id": typed.capability_result_id,
        "capability_result": typed.semantic_payload(),
    }
