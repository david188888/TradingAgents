"""News-specific routing and the run-scoped news cache.

News has a different fallback contract than OHLCV/statements: every
configured vendor is tried and successes are curated into one
source-labelled package, with a keyless official-exchange fallback for
A-share tickers. The cache is owned by one explicit run scope so results
are not reused across runs.

When ``news_parallel_fetch_enabled`` is set (default), the vendor HTTP
calls fan out concurrently over a small thread pool.  Correctness rules
for the fan-out:

* Only the vendor call (plus its in-call raw capture) runs in a worker.
* Each worker receives a ``contextvars.copy_context()`` snapshot so the
  observation context and attempt refs set by the router stay visible to
  ``capture_vendor_raw`` / progress correlation inside the thread.
* All shared-state mutation - provenance attempt counters, the health
  registry, progress events, result collection - happens on the main
  thread, in configured-vendor order, so event streams and fallback
  semantics stay deterministic and identical to serial execution.
"""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from tradingagents.observability.context import current_observation_context
from tradingagents.observability.provenance import CacheOrigin, DataRequestObservation

from .config import get_config
from .health import _vendor_health
from .news_curator import (
    _format_curated_news,
    _is_empty_news_result,
    _is_error_news_result,
    _summarize_empty_news_result,
    _summarize_error_news_result,
    _summarize_news_result,
    _summarize_vendor_error_for_news,
)
from .progress import _emit_data_progress
from .registry import VENDOR_METHODS, get_category_for_method, get_vendor
from .router import _market_for_request, _should_skip_vendor_for_symbol
from .ticker_utils import is_a_share_ticker
from .vendor_errors import (
    _record_vendor_failure,
    _record_vendor_success,
)

logger = logging.getLogger("tradingagents.dataflows.news_router")


# News results may be reused only inside one explicitly owned analysis run.
# The localhost process is long-lived, so module lifetime is not a run boundary.
# News results may be reused only inside one explicitly owned analysis run.
# The localhost process is long-lived, so module lifetime is not a run boundary.
@dataclass(frozen=True)
class _NewsCacheEntry:
    result: str
    origin: CacheOrigin


@dataclass
class _VendorOutcome:
    """One vendor attempt's terminal state, processed on the main thread."""

    vendor: str
    attempt: Any  # VendorAttemptRef
    result: Any = None
    error: BaseException | None = None


def _run_vendor_attempt(
    method: str,
    vendor: str,
    attempt: Any,
    args: tuple[Any, ...],
    call_kwargs: dict[str, Any],
    provenance: DataRequestObservation,
    ctx: contextvars.Context,
) -> Any:
    """Worker-body: run only the vendor call inside a copied context."""

    def _call() -> Any:
        with provenance.attempt_scope(attempt):
            return VENDOR_METHODS[method][vendor](*args, **call_kwargs)

    return ctx.run(_call)


def _run_vendor_attempt_inline(
    method: str,
    vendor: str,
    attempt: Any,
    args: tuple[Any, ...],
    call_kwargs: dict[str, Any],
    provenance: DataRequestObservation,
) -> _VendorOutcome:
    """Serial path: same worker body, executed on the calling thread."""
    try:
        result = _run_vendor_attempt(
            method, vendor, attempt, args, call_kwargs, provenance, contextvars.copy_context()
        )
        return _VendorOutcome(vendor=vendor, attempt=attempt, result=result)
    except Exception as exc:
        return _VendorOutcome(vendor=vendor, attempt=attempt, error=exc)


def _fan_out_vendor_calls(
    method: str,
    plan: list[tuple[str, Any, dict[str, Any]]],
    args: tuple[Any, ...],
    provenance: DataRequestObservation,
) -> dict[str, Future]:
    """Dispatch vendor calls concurrently, preserving per-vendor context."""
    cfg = get_config()
    max_workers = max(1, int(cfg.get("news_parallel_max_workers", 4)))
    executor = ThreadPoolExecutor(
        max_workers=min(max_workers, len(plan)), thread_name_prefix="news-fetch"
    )
    try:
        futures: dict[str, Future] = {}
        for vendor, attempt, call_kwargs in plan:
            ctx = contextvars.copy_context()
            futures[vendor] = executor.submit(
                _run_vendor_attempt,
                method,
                vendor,
                attempt,
                args,
                call_kwargs,
                provenance,
                ctx,
            )
        # Wait for every submitted task so worker threads have finished all
        # shared-state-adjacent work (raw capture) before phase 3 reads it.
        # Exceptions stay stored on the futures: phase 3 (_collect_outcome)
        # owns failure semantics, so a worker error must not re-raise here.
        for future in futures.values():
            with suppress(BaseException):
                future.result()
        return futures
    finally:
        executor.shutdown(wait=True)


def _collect_outcome(vendor: str, future: Future) -> _VendorOutcome:
    try:
        return _VendorOutcome(vendor=vendor, attempt=None, result=future.result())
    except BaseException as exc:  # noqa: BLE001 - router records all failures
        return _VendorOutcome(vendor=vendor, attempt=None, error=exc)


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


_news_result_cache: dict[tuple, _NewsCacheEntry] = {}
_news_cache_namespace: ContextVar[str | None] = ContextVar(
    "tradingagents_news_cache_namespace",
    default=None,
)


@contextmanager
def news_cache_scope(run_id: str):
    """Own and destroy one run's news cache namespace."""
    token = _news_cache_namespace.set(run_id)
    try:
        yield
    finally:
        stale_keys = [key for key in _news_result_cache if key[0] == run_id]
        for key in stale_keys:
            _news_result_cache.pop(key, None)
        _news_cache_namespace.reset(token)


def _build_news_cache_key(method: str, args: tuple[Any, ...], kwargs: dict[str, Any]):
    if method not in {"get_news", "get_global_news"}:
        return None
    context = current_observation_context()
    namespace = _news_cache_namespace.get()
    if namespace is None:
        return None
    if context is not None and context.run_id != namespace:
        raise RuntimeError("news cache scope does not match the active observation run")
    vendor_config = get_vendor(get_category_for_method(method), method)
    return (
        namespace,
        method,
        vendor_config,
        tuple(str(arg) for arg in args),
        tuple(sorted((key, str(value)) for key, value in kwargs.items() if value is not None)),
    )




def _route_news_to_vendors(
    method: str,
    vendors: list[str],
    *args,
    _provenance: DataRequestObservation,
    **kwargs,
) -> str:
    """Fetch news from configured sources and curate a compact source-labeled package."""
    configured_vendors = [
        vendor
        for vendor in vendors
        if vendor != "default" and not _should_skip_vendor_for_symbol(method, vendor, args)
    ]
    if not configured_vendors:
        configured_vendors = [
            vendor
            for vendor in ("tavily", "eastmoney", "yfinance", "alpha_vantage")
            if not _should_skip_vendor_for_symbol(method, vendor, args)
        ]
    successes: list[tuple[str, Any]] = []
    errors: list[tuple[str, Exception | str]] = []

    # ---- Phase 1 (serial): validate vendors, check cooldowns, open attempts.
    # All shared-state mutation stays on this thread in configured order.
    plan: list[tuple[str, Any, dict[str, Any]]] = []
    for vendor in configured_vendors:
        if vendor not in VENDOR_METHODS[method]:
            message = f"vendor does not support {method}"
            attempt = _provenance.start_attempt(vendor, fallback_chain=tuple(configured_vendors))
            artifact_id = _provenance.fail(attempt, message)
            _emit_data_progress(
                "failure",
                method,
                vendor,
                args,
                message,
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            errors.append((vendor, message))
            continue

        cooldown = _vendor_health.cooldown_for(
            vendor=vendor,
            market=_market_for_request(args, method),
            capability=method,
        )
        if cooldown is not None:
            attempt = _provenance.start_attempt(
                vendor,
                fallback_chain=tuple(configured_vendors),
                emit_started=False,
            )
            reason = (
                f"cooldown active for {cooldown.remaining_seconds(time.monotonic()):.0f}s "
                f"after {cooldown.reason}"
            )
            _provenance.skip(attempt, reason=reason)
            _emit_data_progress(
                "skipped",
                method,
                vendor,
                args,
                reason,
                vendor_call_id=attempt.vendor_call_id,
            )
            errors.append((vendor, reason))
            continue

        attempt = _provenance.start_attempt(vendor, fallback_chain=tuple(configured_vendors))
        _emit_data_progress("start", method, vendor, args)
        plan.append((vendor, attempt, _news_vendor_kwargs(method, vendor, kwargs)))

    # ---- Phase 2 (parallel fan-out): run the vendor HTTP calls concurrently.
    futures: dict[str, Future] = {}
    if plan:
        parallel = (
            _config_bool(get_config().get("news_parallel_fetch_enabled", True))
            and len(plan) > 1
        )
        if parallel:
            futures = _fan_out_vendor_calls(method, plan, args, _provenance)

    # ---- Phase 3 (serial): collect outcomes in configured order with the
    # same success/error/empty semantics as the previous serial loop.
    for vendor, attempt, call_kwargs in plan:
        if vendor in futures:
            outcome = _collect_outcome(vendor, futures[vendor])
        else:
            outcome = _run_vendor_attempt_inline(
                method, vendor, attempt, args, call_kwargs, _provenance
            )
        if outcome.error is not None:
            exc = outcome.error
            artifact_id = _provenance.fail(attempt, exc)
            _record_vendor_failure(vendor, method, args, exc)
            _emit_data_progress(
                "failure",
                method,
                vendor,
                args,
                _summarize_vendor_error_for_news(exc),
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            errors.append((vendor, exc))
            continue

        result = outcome.result
        if _is_error_news_result(result):
            message = _summarize_error_news_result(result)
            artifact_id = _provenance.fail(attempt, result)
            _emit_data_progress(
                "failure",
                method,
                vendor,
                args,
                message,
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            errors.append((vendor, message))
            continue

        if _is_empty_news_result(result):
            message = _summarize_empty_news_result(result)
            artifact_id = _provenance.fail(attempt, result)
            _emit_data_progress(
                "failure",
                method,
                vendor,
                args,
                message,
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            errors.append((vendor, message))
            continue

        artifact_id = _provenance.succeed(attempt, result)
        _record_vendor_success(vendor, method, args)
        _emit_data_progress(
            "success",
            method,
            vendor,
            args,
            _summarize_news_result(result),
            vendor_call_id=attempt.vendor_call_id,
            artifact_id=artifact_id,
        )
        successes.append((vendor, result))

    # Public exchange announcements use a different protocol and intentionally
    # sit behind normal news search: they are authoritative disclosures, not a
    # silent replacement for broader market coverage.  The adapter is only
    # eligible for A shares and only after every configured news provider is
    # unavailable or empty.  This is an explicit, source-labelled degradation.
    if not successes:
        fallback_vendors = _news_official_fallback_vendors(
            method, args, already_attempted=configured_vendors
        )
        for vendor in fallback_vendors:
            attempt = _provenance.start_attempt(
                vendor,
                fallback_chain=(*configured_vendors, *fallback_vendors),
            )
            try:
                with _provenance.attempt_scope(attempt):
                    _emit_data_progress("start", method, vendor, args)
                    call_kwargs = _news_vendor_kwargs(method, vendor, kwargs)
                    result = VENDOR_METHODS[method][vendor](*args, **call_kwargs)
            except Exception as exc:
                artifact_id = _provenance.fail(attempt, exc)
                _record_vendor_failure(vendor, method, args, exc)
                _emit_data_progress(
                    "failure",
                    method,
                    vendor,
                    args,
                    _summarize_vendor_error_for_news(exc),
                    vendor_call_id=attempt.vendor_call_id,
                    artifact_id=artifact_id,
                )
                errors.append((vendor, exc))
                continue
            if _is_empty_news_result(result) or _is_error_news_result(result):
                message = (
                    _summarize_empty_news_result(result)
                    if _is_empty_news_result(result)
                    else _summarize_error_news_result(result)
                )
                artifact_id = _provenance.fail(attempt, message)
                _emit_data_progress(
                    "failure",
                    method,
                    vendor,
                    args,
                    message,
                    vendor_call_id=attempt.vendor_call_id,
                    artifact_id=artifact_id,
                )
                errors.append((vendor, message))
                continue
            artifact_id = _provenance.succeed(attempt, result)
            _record_vendor_success(vendor, method, args)
            _emit_data_progress(
                "success",
                method,
                vendor,
                args,
                _summarize_news_result(result),
                vendor_call_id=attempt.vendor_call_id,
                artifact_id=artifact_id,
            )
            successes.append((vendor, result))

    if successes:
        # Extract date window for staleness filtering (args are ticker, start_date, end_date for get_news)
        start_date = str(args[1]) if len(args) >= 2 else ""
        end_date = str(args[2]) if len(args) >= 3 else ""
        return _format_curated_news(method, successes, errors, start_date, end_date)

    details = (
        "; ".join(f"{vendor}: {err}" for vendor, err in errors) or "no news vendors configured"
    )
    return _no_curated_news_sentinel(method, details)


def _no_curated_news_sentinel(method: str, details: str) -> str:
    return f"No curated news found for '{method}'. Source status: {details}."


def _is_news_failure_result(result: object) -> bool:
    """True when the routed package is the all-sources-failed sentinel.

    Transient outages must not be cached: the run-scoped cache has no TTL,
    so freezing this sentinel would serve the failure text to every later
    identical call in the same run even after sources recover.
    """
    return isinstance(result, str) and result.startswith("No curated news found for '")


def _news_vendor_kwargs(
    method: str,
    vendor: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Pass bounded pagination only to adapters that implement it."""
    call_kwargs = dict(kwargs)
    if method == "get_news" and vendor != "eastmoney":
        call_kwargs.pop("max_pages", None)
    return call_kwargs


def _news_official_fallback_vendors(
    method: str,
    args: tuple[Any, ...],
    *,
    already_attempted: list[str],
) -> list[str]:
    """Return only public, configured source-priority cross-protocol fallbacks."""
    if method != "get_news" or not args or not is_a_share_ticker(str(args[0])):
        return []
    if not get_config().get("a_share_news_official_fallback_enabled", True):
        return []
    return [
        vendor
        for vendor in ("china_exchange",)
        if vendor not in already_attempted and vendor in VENDOR_METHODS[method]
    ]

