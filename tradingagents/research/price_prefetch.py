"""Translate HorizonPolicy into deterministic adjusted-price fetch windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from tradingagents.research.horizon_policy import (
    POLICY_VERSION,
    InvestmentHorizon,
    MarketKind,
    build_data_window_plan,
)


@dataclass(frozen=True)
class PricePrefetchPlanV1:
    policy_version: str
    horizon: InvestmentHorizon
    market: MarketKind
    as_of: str
    start_date: str
    requested_windows: tuple[dict[str, object], ...]
    granularities: tuple[str, ...]
    required_trading_days: int | None
    price_basis: str


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def build_price_prefetch_plan(
    horizon: InvestmentHorizon,
    analysis_date: str,
    *,
    market: MarketKind,
) -> PricePrefetchPlanV1:
    """Resolve one widest fetch range while preserving every policy window."""
    plan = build_data_window_plan(horizon, analysis_date, market=market)
    capability = plan.capability_index()["adjusted_price_history"]
    as_of = date.fromisoformat(analysis_date)
    starts: list[date] = []
    trading_days: list[int] = []
    for window in capability.windows:
        if window.unit == "years":
            starts.append(_subtract_years(as_of, window.value))
        elif window.unit == "calendar_days":
            starts.append(as_of - timedelta(days=window.value))
        elif window.unit == "trading_days":
            trading_days.append(window.value)
            # Calendar-safe deterministic overfetch; retained bar counts remain
            # visible so no exchange calendar is fabricated.
            calendar_days = (window.value * 365 + 249) // 250 + 14
            starts.append(as_of - timedelta(days=calendar_days))
        else:
            raise ValueError(f"unsupported price window unit: {window.unit}")
    return PricePrefetchPlanV1(
        policy_version=POLICY_VERSION,
        horizon=horizon,
        market=market,
        as_of=analysis_date,
        start_date=min(starts).isoformat(),
        requested_windows=tuple(
            {
                "window_id": window.window_id,
                "value": window.value,
                "unit": window.unit,
            }
            for window in capability.windows
        ),
        granularities=tuple(capability.granularities),
        required_trading_days=max(trading_days) if trading_days else None,
        price_basis=capability.price_basis,
    )
