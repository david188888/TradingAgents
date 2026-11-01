"""Optional caller-provided ticker context for data-provider identity guards.

Adapters compare their requested ticker with an explicitly set target to label
comparison-company results. ContextVar isolates this context within the calling
thread. V9 sources carry their own request identity; callers of these standalone
adapters may set and clear the context around a sequence of related calls.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetTicker:
    ticker: str
    company_name: str | None


_target_ticker: contextvars.ContextVar[TargetTicker | None] = contextvars.ContextVar(
    "tradingagents_target_ticker", default=None
)


def set_target_ticker(ticker: str, company_name: str | None = None) -> None:
    """Set the analysis target ticker for the current run context."""
    _target_ticker.set(TargetTicker(ticker=str(ticker), company_name=company_name))


def get_target_ticker() -> TargetTicker | None:
    """Return the current run's target ticker, or None when unset."""
    return _target_ticker.get()


def clear_target_ticker() -> None:
    """Clear the target ticker at run end."""
    _target_ticker.set(None)
