import logging
import time
from datetime import datetime, timezone
from typing import Any

# Configuration and routing logic
from tradingagents.observability.provenance import (
    CacheOrigin,
    DataRequestObservation,
    begin_data_request,
)

from .china_data import ChinaDataUnavailableError
from .china_supplemental import (  # noqa: F401  - re-exported for callers that import from interface
    _format_incomplete_primary_result,
    _format_supplemental_result,
    _is_china_supplemental_vendor,
    _next_china_supplemental_vendor,
)
from .errors import (  # noqa: F401  - DataUnavailableError re-exported for callers
    DataSourceUnavailableError,
    DataUnavailableError,
    VendorError,
    VendorRateLimitError,
)
from .health import (  # noqa: F401  - _vendor_health/set/clear re-exported for callers
    RATE_LIMIT_COOLDOWN_SECONDS,
    TRANSIENT_FAILURE_COOLDOWN_SECONDS,
    VendorHealthRegistry,
    _vendor_health,
    clear_vendor_health,
    set_vendor_health_registry,
)
from .news_curator import (  # noqa: F401  - re-exported for callers that import from interface
    _company_short_form,
    _dedupe_news_items,
    _extract_json_news_items,
    _extract_markdown_news_items,
    _extract_news_items,
    _filter_stale_items,
    _format_curated_news,
    _is_empty_news_result,
    _is_error_news_result,
    _is_relevant_news_item,
    _mark_news_relevance,
    _news_dedupe_key,
    _parse_date_best_effort,
    _summarize_empty_news_result,
    _summarize_error_news_result,
    _summarize_news_result,
    _summarize_vendor_error_for_news,
)

# News routing and run-scoped news cache live in ``news_router.py``; the
# shared market-skip helpers live in ``router.py``. New code should import
# from those modules directly; these re-exports keep existing callers and
# tests working.
from .news_router import (
    _build_news_cache_key,
    _is_news_failure_result,
    _news_cache_namespace,  # noqa: F401 - facade re-export (tests access via interface)
    _news_result_cache,
    _NewsCacheEntry,
    _route_news_to_vendors,
    news_cache_scope,  # noqa: F401 - facade re-export (cli/manager import from here)
)
from .progress import (  # noqa: F401  - re-exported for callers that import from interface
    _emit_data_progress,
    _emit_supplement_progress,
    _format_progress_context,
    _sanitize_progress_text,
)

# Static registry: tool categories, vendor names, market capability matrix,
# and method -> vendor implementations. New vendors/tools are registered in
# ``registry.py``; this module re-exports the same symbols for callers that
# still import them from here.
from .registry import (
    TOOLS_CATEGORIES,  # noqa: F401 - facade re-export
    VENDOR_LIST,
    VENDOR_MARKETS,  # noqa: F401 - facade re-export (tests import from here)
    VENDOR_METHODS,
    get_category_for_method,
    get_vendor,
)
from .router import (
    _market_for_request,
    _should_skip_vendor_for_symbol,
)
from .routing_trace import (
    RouteAttemptTrace,
    RoutedVendorCall,
    capture_route_attempts,
    record_route_attempt,
)
from .symbol_utils import NoMarketDataError
from .vendor_errors import (  # noqa: F401  - re-exported for callers that import from interface
    _cooldown_for_exception,
    _format_vendor_unavailable_message,
    _http_status_code,
    _is_missing_required_data_result,
    _is_recoverable_vendor_error,
    _is_transient_vendor_error,
    _record_vendor_failure,
    _record_vendor_success,
    _should_halt_on_missing_data,
    _summarize_vendor_error,
    public_vendor_reason_code,
)
from .yfinance_incompleteness import (  # noqa: F401  - re-exported for callers that import from interface
    _expected_weekday_count,
    _parse_csv_from_report,
    _should_supplement_yfinance_result,
    _summarize_data_result,
    _summarize_yfinance_fundamentals_incompleteness,
    _summarize_yfinance_incompleteness,
    _summarize_yfinance_statement_incompleteness,
    _summarize_yfinance_stock_incompleteness,
)

logger = logging.getLogger("tradingagents.dataflows.interface")




def route_to_vendor(method: str, *args, **kwargs):
    """Route one request and persist its normalized provenance when observed."""
    provenance = begin_data_request(method, args, kwargs)
    cache_key = _build_news_cache_key(method, args, kwargs)
    if cache_key is not None and cache_key in _news_result_cache:
        entry = _news_result_cache[cache_key]
        origin_is_complete = bool(entry.origin.vendor_call_ids and entry.origin.artifact_ids)
        if not provenance.active or origin_is_complete:
            provenance.cache_hit(cache_key=cache_key, origin=entry.origin)
            return entry.result
    try:
        result = _route_to_vendor_impl(method, *args, _provenance=provenance, **kwargs)
    except Exception as exc:
        provenance.request_failed(exc)
        raise
    origin = provenance.complete(result)
    if (
        cache_key is not None
        and (not provenance.active or origin is not None)
        # The all-sources-failed sentinel must stay uncached: a transient
        # outage would otherwise be frozen for the rest of the run.
        and not _is_news_failure_result(result)
    ):
        _news_result_cache[cache_key] = _NewsCacheEntry(
            result=result,
            origin=origin or CacheOrigin((), (), time.monotonic()),
        )
    return result


def route_to_vendor_with_trace(method: str, *args, **kwargs) -> RoutedVendorCall:
    """Compatibility-preserving route call plus typed per-provider outcomes."""
    with capture_route_attempts() as attempts:
        try:
            result = route_to_vendor(method, *args, **kwargs)
        except Exception as exc:  # caller decides whether the capability degrades
            return RoutedVendorCall(None, exc, tuple(attempts))
    return RoutedVendorCall(result, None, tuple(attempts))


def _route_to_vendor_impl(
    method: str,
    *args,
    _provenance: DataRequestObservation,
    **kwargs,
):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(",") if v.strip()]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # An explicit vendor choice that names no real vendor is a config error:
    # surface it instead of silently trying every vendor in VENDOR_METHODS.
    if vendor_config != "default":
        # A vendor name that is not a known vendor at all (typo, e.g.
        # "bogus_vendor") is a config error: surface it. Vendors that are
        # valid but not wired for this particular method (e.g. tushare for
        # get_indicators) are handled by the fallback chain below, not here.
        known_vendors = set(VENDOR_LIST)
        unknown = [v for v in primary_vendors if v not in known_vendors]
        if unknown:
            raise ValueError(
                f"Unknown vendor(s) configured for '{method}': {', '.join(unknown)}. "
                f"Known vendors: {', '.join(VENDOR_LIST)}"
            )

    if method in {"get_news", "get_global_news"}:
        return _route_news_to_vendors(
            method,
            primary_vendors,
            *args,
            _provenance=_provenance,
            **kwargs,
        )

    # Build fallback chain. "default" keeps the resilient full-chain behavior.
    # An explicit vendor choice is honored strictly: only the configured
    # vendors are tried, so a healthy unchosen vendor is NOT silently used
    # (#988). Transient errors (rate limit / network) still opt in to the
    # remaining vendors as an implicit safety net - see the recoverable branch.
    if vendor_config == "default":
        fallback_vendors = list(VENDOR_METHODS[method].keys())
    else:
        fallback_vendors = primary_vendors.copy()

    recoverable_errors = []
    incomplete_primary: tuple[str, Any, str] | None = None
    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    # Vendors skipped because a prior failure put them in cooldown.  A
    # cooldown is not fresh evidence about the data: when EVERY vendor was
    # skipped this way (nothing new attempted or failed), the tail degrades
    # to a retry-later sentinel instead of raising under halt semantics.
    cooldown_skips = 0
    # True once a transient error (rate limit / network) pulled in a vendor
    # outside the explicit chain. When the whole chain still fails after that,
    # we surface an aggregated DataUnavailableError rather than re-raising the
    # single primary error, because more than one vendor was actually tried.
    implicit_fallback_triggered = False

    for index, vendor in enumerate(fallback_vendors):
        if vendor not in VENDOR_METHODS[method]:
            continue
        if _should_skip_vendor_for_symbol(method, vendor, args):
            continue

        cooldown = _vendor_health.cooldown_for(
            vendor=vendor,
            market=_market_for_request(args, method),
            capability=method,
        )
        if cooldown is not None:
            attempt = _provenance.start_attempt(
                vendor,
                fallback_chain=tuple(fallback_vendors),
                emit_started=False,
            )
            reason = (
                f"cooldown active for {cooldown.remaining_seconds(time.monotonic()):.0f}s "
                f"after {cooldown.reason}"
            )
            _provenance.skip(attempt, reason=reason)
            record_route_attempt(
                RouteAttemptTrace(
                    vendor=vendor,
                    outcome="skipped_unobserved",
                    reason_code="provider_cooldown_active",
                    recorded_at=datetime.now(timezone.utc),
                    vendor_call_id=attempt.vendor_call_id,
                )
            )
            _emit_data_progress(
                "skipped",
                method,
                vendor,
                args,
                reason,
                vendor_call_id=attempt.vendor_call_id,
            )
            recoverable_errors.append((vendor, DataSourceUnavailableError(reason)))
            cooldown_skips += 1
            # A stored cooldown only represents a prior transient failure. It
            # gets the same implicit safety-net fallback as a live 429/network
            # failure, even when the user explicitly selected one primary.
            for extra in VENDOR_METHODS[method]:
                if extra not in fallback_vendors:
                    fallback_vendors.append(extra)
                    implicit_fallback_triggered = True
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        attempt = _provenance.start_attempt(vendor, fallback_chain=tuple(fallback_vendors))
        trace_started_at = datetime.now(timezone.utc)
        try:
            with _provenance.attempt_scope(attempt):
                _emit_data_progress("start", method, vendor, args)
                result = impl_func(*args, **kwargs)
        except NoMarketDataError as e:
            artifact_id = _provenance.fail(attempt, e)
            record_route_attempt(
                RouteAttemptTrace(
                    vendor=vendor,
                    outcome="not_covered",
                    reason_code="provider_reported_no_data",
                    recorded_at=datetime.now(timezone.utc),
                    started_at=trace_started_at,
                    ended_at=datetime.now(timezone.utc),
                    vendor_call_id=attempt.vendor_call_id,
                    provenance_artifact_id=artifact_id,
                )
            )
            last_no_data = e
            _emit_data_progress(
                "failure",
                method,
                vendor,
                args,
                str(e),
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            logger.warning("vendor %s reported no market data for %s: %s", vendor, method, e)
            recoverable_errors.append((vendor, e))
            if first_error is None:
                first_error = e
            continue
        except Exception as exc:
            artifact_id = _provenance.fail(attempt, exc)
            if _is_recoverable_vendor_error(vendor, exc):
                record_route_attempt(
                    RouteAttemptTrace(
                        vendor=vendor,
                        outcome="provider_failed",
                        reason_code=public_vendor_reason_code(exc),
                        recorded_at=datetime.now(timezone.utc),
                        started_at=trace_started_at,
                        ended_at=datetime.now(timezone.utc),
                        vendor_call_id=attempt.vendor_call_id,
                        provenance_artifact_id=artifact_id,
                    )
                )
                _record_vendor_failure(vendor, method, args, exc)
                _emit_data_progress(
                    "failure",
                    method,
                    vendor,
                    args,
                    _summarize_vendor_error(exc),
                    vendor_call_id=attempt.vendor_call_id,
                    artifact_id=artifact_id,
                )
                # Log the real error so a broken primary is visible in logs,
                # not masked by a later fallback's no-data sentinel (#989).
                logger.warning("vendor %s failed for %s: %s", vendor, method, exc)
                recoverable_errors.append((vendor, exc))
                if first_error is None:
                    first_error = exc
                # Transient errors (rate limit / network) opt in to the
                # remaining vendors even under an explicit single-vendor
                # config: a throttle is temporary, so an unchosen vendor is
                # worth trying. NoMarketDataError / not-configured errors do
                # NOT trigger this - they reflect data/config state that
                # trying another unchosen vendor would mask (#988).
                if _is_transient_vendor_error(exc):
                    for extra in VENDOR_METHODS[method]:
                        if extra not in fallback_vendors:
                            fallback_vendors.append(extra)
                            implicit_fallback_triggered = True
                continue
            record_route_attempt(
                RouteAttemptTrace(
                    vendor=vendor,
                    outcome="invalid_payload",
                    reason_code=public_vendor_reason_code(exc),
                    recorded_at=datetime.now(timezone.utc),
                    started_at=trace_started_at,
                    ended_at=datetime.now(timezone.utc),
                    vendor_call_id=attempt.vendor_call_id,
                    provenance_artifact_id=artifact_id,
                )
            )
            raise

        if _is_missing_required_data_result(result):
            summary = str(result).strip()[:300]
            artifact_id = _provenance.fail(attempt, summary)
            _emit_data_progress(
                "failure",
                method,
                vendor,
                args,
                summary,
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            recoverable_errors.append((vendor, ChinaDataUnavailableError(summary)))
            record_route_attempt(
                RouteAttemptTrace(
                    vendor=vendor,
                    outcome="invalid_payload",
                    reason_code="provider_payload_missing_required_data",
                    recorded_at=datetime.now(timezone.utc),
                    started_at=trace_started_at,
                    ended_at=datetime.now(timezone.utc),
                    vendor_call_id=attempt.vendor_call_id,
                    provenance_artifact_id=artifact_id,
                )
            )
            continue

        if _should_supplement_yfinance_result(method, vendor, args, result):
            artifact_id = _provenance.succeed(attempt, result)
            record_route_attempt(
                RouteAttemptTrace(
                    vendor=vendor,
                    outcome="observed",
                    reason_code="provider_payload_incomplete",
                    recorded_at=datetime.now(timezone.utc),
                    started_at=trace_started_at,
                    ended_at=datetime.now(timezone.utc),
                    vendor_call_id=attempt.vendor_call_id,
                    provenance_artifact_id=artifact_id,
                )
            )
            reason = _summarize_yfinance_incompleteness(method, args, result)
            incomplete_primary = (vendor, result, reason)
            recoverable_errors.append((vendor, ChinaDataUnavailableError(reason)))
            next_vendor = _next_china_supplemental_vendor(fallback_vendors[index + 1 :])
            if next_vendor:
                _emit_supplement_progress(method, vendor, next_vendor)
            continue

        if incomplete_primary and _is_china_supplemental_vendor(vendor):
            artifact_id = _provenance.succeed(attempt, result)
            record_route_attempt(
                RouteAttemptTrace(
                    vendor=vendor,
                    outcome="observed",
                    reason_code="provider_payload_observed",
                    recorded_at=datetime.now(timezone.utc),
                    started_at=trace_started_at,
                    ended_at=datetime.now(timezone.utc),
                    vendor_call_id=attempt.vendor_call_id,
                    provenance_artifact_id=artifact_id,
                )
            )
            _record_vendor_success(vendor, method, args)
            _emit_data_progress(
                "success",
                method,
                vendor,
                args,
                _summarize_data_result(method, result),
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            return _format_supplemental_result(
                method=method,
                primary_vendor=incomplete_primary[0],
                primary_result=incomplete_primary[1],
                reason=incomplete_primary[2],
                supplemental_vendor=vendor,
                supplemental_result=result,
            )

        artifact_id = _provenance.succeed(attempt, result)
        record_route_attempt(
            RouteAttemptTrace(
                vendor=vendor,
                outcome="observed",
                reason_code="provider_payload_observed",
                recorded_at=datetime.now(timezone.utc),
                started_at=trace_started_at,
                ended_at=datetime.now(timezone.utc),
                vendor_call_id=attempt.vendor_call_id,
                provenance_artifact_id=artifact_id,
            )
        )
        _record_vendor_success(vendor, method, args)
        _emit_data_progress(
            "success",
            method,
            vendor,
            args,
            _summarize_data_result(method, result),
            vendor_call_id=attempt.vendor_call_id,
            artifact_id=artifact_id,
        )
        return result

    # If any vendor reported "no data", the symbol is genuinely unavailable.
    # Return one explicit, instructive sentinel rather than a vendor-specific
    # empty string, so the agent reports "unavailable" instead of inventing a
    # value. This takes precedence over incidental fallback errors.
    only_authoritative_no_data = bool(recoverable_errors) and all(
        isinstance(error, NoMarketDataError) for _vendor, error in recoverable_errors
    )
    if last_no_data is not None and only_authoritative_no_data:
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        detail = (last_no_data.detail or "").strip()
        detail_part = f" Last observed detail: {detail}." if detail else ""
        return (
            f"NO_DATA_AVAILABLE: No market data found for '{sym}'{resolved} from "
            f"any configured vendor. The symbol may be invalid, delisted, or not "
            f"covered by Yahoo Finance / Alpha Vantage. Do not estimate or "
            f"fabricate values — report that data is unavailable for this symbol."
            f"{detail_part}"
        )

    if incomplete_primary:
        message = _format_incomplete_primary_result(
            method=method,
            primary_vendor=incomplete_primary[0],
            primary_result=incomplete_primary[1],
            reason=incomplete_primary[2],
            errors=recoverable_errors,
        )
        if _should_halt_on_missing_data(method):
            raise DataUnavailableError(message)
        return message

    if recoverable_errors:
        # Optional categories degrade to a sentinel so the analysis proceeds.
        if not _should_halt_on_missing_data(method):
            return _format_vendor_unavailable_message(method, recoverable_errors, category)
        # Pure cooldown exhaustion: every vendor was skipped for a PRIOR
        # transient failure and nothing new was attempted.  A cooldown is
        # temporary by definition, so halting a whole run on it would turn
        # one rate limit into a dead analysis; degrade to an instructive
        # sentinel instead (the cooldown table itself already limits retry
        # pressure on the throttled provider).
        if len(recoverable_errors) == cooldown_skips:
            details = "; ".join(
                f"{vendor}: {_summarize_vendor_error(exc)}"
                for vendor, exc in recoverable_errors
            )
            return (
                f"NO_DATA_AVAILABLE: All configured data vendors for '{method}' "
                f"(category: {category}) are temporarily cooling down after "
                f"transient failures: {details}. Report the data as unavailable "
                "and retry later — do not estimate or fabricate values."
            )
        # Core category: a single configured vendor that fails with no fallback
        # tried must surface its real error (a broken primary should be loud,
        # not silently repackaged). When more than one vendor was tried - either
        # an explicit multi-vendor chain or an implicit fallback - aggregate the
        # failures into DataUnavailableError so every vendor's reason is visible.
        if (
            len(recoverable_errors) == 1
            and not implicit_fallback_triggered
            and first_error is not None
        ):
            raise recoverable_errors[0][1]
        message = _format_vendor_unavailable_message(method, recoverable_errors, category)
        raise DataUnavailableError(message)

    raise RuntimeError(f"No available vendor for '{method}'")
