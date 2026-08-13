"""Run-local capture of deterministic provider routing outcomes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

RouteOutcome = Literal[
    "observed",
    "not_covered",
    "provider_failed",
    "invalid_payload",
    "skipped_unobserved",
]


@dataclass(frozen=True)
class RouteAttemptTrace:
    vendor: str
    outcome: RouteOutcome
    reason_code: str
    recorded_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    vendor_call_id: str | None = None
    provenance_artifact_id: str | None = None


@dataclass(frozen=True)
class RoutedVendorCall:
    result: Any | None
    error: Exception | None
    attempts: tuple[RouteAttemptTrace, ...]


_TRACE_COLLECTOR: ContextVar[list[RouteAttemptTrace] | None] = ContextVar(
    "tradingagents_route_trace", default=None
)


@contextmanager
def capture_route_attempts() -> Iterator[list[RouteAttemptTrace]]:
    collector: list[RouteAttemptTrace] = []
    token = _TRACE_COLLECTOR.set(collector)
    try:
        yield collector
    finally:
        _TRACE_COLLECTOR.reset(token)


def record_route_attempt(attempt: RouteAttemptTrace) -> None:
    collector = _TRACE_COLLECTOR.get()
    if collector is not None:
        collector.append(attempt)
