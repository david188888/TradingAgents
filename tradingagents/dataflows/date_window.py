"""Shared look-ahead-safe date-window filtering for dated content.

News, StockTwits, and Reddit all pull recent items that must be trimmed to the
analysis window so a historical/backtest run never sees content published after
its as-of date. Centralizing the rule keeps every source consistent (#1126,
#1220): every timestamp is normalized to UTC, the upper bound is exclusive at
midnight after ``end`` (so an item stamped exactly then can't leak), and an
undated item is kept only when the window reaches the present (a live run), since
in a backtest we can't prove it isn't future.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _parse_date(value: str, *, field_name: str) -> date:
    """Parse a canonical analysis date with a useful fail-closed error."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must use yyyy-mm-dd format: {value!r}") from exc


def trade_date_from_state(state: Mapping[str, Any] | None) -> str:
    """Return the run cutoff, failing closed for malformed non-empty state.

    Direct Python callers that provide no graph state retain their legacy
    behavior. A graph state with a missing or malformed trade date must not
    silently bypass the point-in-time boundary.
    """
    if state is None:
        return ""
    value = state.get("trade_date")
    if value is None or value == "":
        raise ValueError("trade_date is required when tool state is injected")
    if not isinstance(value, str):
        raise ValueError("trade_date must be a yyyy-mm-dd string")
    return _parse_date(value, field_name="trade_date").isoformat()


def as_of(requested: str | None, trade_date: str) -> str | None:
    """Bound a model-requested date to a run date, retaining direct-call use."""
    if not trade_date:
        return requested
    cutoff = _parse_date(trade_date, field_name="trade_date")
    if not requested:
        return cutoff.isoformat()
    try:
        requested_date = _parse_date(requested, field_name="requested date")
    except ValueError:
        return cutoff.isoformat()
    return min(requested_date, cutoff).isoformat()


def as_of_window(start_date: str, end_date: str, trade_date: str) -> tuple[str, str]:
    """Bound a date window without creating an inverted request.

    If the requested window lies wholly in the future, retain its duration and
    shift it back so that it ends on the run date. Invalid model-provided
    endpoints fail safe to a one-day window ending on the run date.
    """
    if not trade_date:
        return start_date, end_date
    cutoff = _parse_date(trade_date, field_name="trade_date")
    try:
        start = _parse_date(start_date, field_name="start_date")
        end = _parse_date(end_date, field_name="end_date")
    except ValueError:
        return cutoff.isoformat(), cutoff.isoformat()
    if end <= cutoff and start <= end:
        return start.isoformat(), end.isoformat()
    if start > cutoff:
        duration = max((end - start).days, 0)
        return (cutoff - timedelta(days=duration)).isoformat(), cutoff.isoformat()
    return start.isoformat(), cutoff.isoformat()


def to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC-aware; a naive value is assumed to be UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def in_window(pub_dt: datetime | None, start_dt: datetime, end_dt: datetime) -> bool:
    """Whether an item belongs in the half-open window ``[start, end + 1 day)``.

    ``pub_dt`` None means undated: kept only when the window reaches the present.
    """
    end = to_utc(end_dt)
    if pub_dt is not None:
        return to_utc(start_dt) <= to_utc(pub_dt) < end + timedelta(days=1)
    return end >= datetime.now(timezone.utc) - timedelta(days=1)
