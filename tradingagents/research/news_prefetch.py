"""Translate HorizonPolicy into deterministic news/disclosure fetch windows."""

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
class CompanyNewsWindowV1:
    window_id: str
    start_date: str
    lookback_days: int


@dataclass(frozen=True)
class NewsPrefetchPlanV1:
    policy_version: str
    horizon: InvestmentHorizon
    market: MarketKind
    as_of: str
    company_windows: tuple[CompanyNewsWindowV1, ...]
    event_start: str
    event_lookback_days: int
    theme_start: str
    theme_lookback_days: int
    official_start: str
    official_lookback_years: int
    research_reports_start: str | None
    research_reports_lookback_years: int | None
    company_news_max_pages: int
    official_max_pages: int
    research_reports_max_pages: int | None


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, month=2, day=28)


def build_news_prefetch_plan(
    horizon: InvestmentHorizon,
    analysis_date: str,
    *,
    market: MarketKind,
) -> NewsPrefetchPlanV1:
    """Resolve executable news dates without giving the model policy control."""
    plan = build_data_window_plan(horizon, analysis_date, market=market)
    capabilities = plan.capability_index()
    event_capability = capabilities["company_event_window"]
    event_windows = {
        window.window_id: window
        for window in event_capability.windows
        if window.unit == "calendar_days"
    }
    event_window = min(event_windows.values(), key=lambda window: window.value)
    theme_window = max(event_windows.values(), key=lambda window: window.value)

    official_capability = capabilities["official_disclosures"]
    official_window = official_capability.windows[0]
    if official_window.unit != "years":
        raise ValueError("official disclosure policy must use a year window")

    research_capability = capabilities.get("research_reports")
    research_window = research_capability.windows[0] if research_capability else None
    if research_window is not None and research_window.unit != "years":
        raise ValueError("research report policy must use a year window")

    as_of = date.fromisoformat(analysis_date)
    company_windows = tuple(
        CompanyNewsWindowV1(
            window_id=window.window_id,
            start_date=(as_of - timedelta(days=window.value)).isoformat(),
            lookback_days=window.value,
        )
        for window in event_capability.windows
        if window.unit == "calendar_days"
    )
    return NewsPrefetchPlanV1(
        policy_version=POLICY_VERSION,
        horizon=horizon,
        market=market,
        as_of=analysis_date,
        company_windows=company_windows,
        event_start=(as_of - timedelta(days=event_window.value)).isoformat(),
        event_lookback_days=event_window.value,
        theme_start=(as_of - timedelta(days=theme_window.value)).isoformat(),
        theme_lookback_days=theme_window.value,
        official_start=_subtract_years(as_of, official_window.value).isoformat(),
        official_lookback_years=official_window.value,
        research_reports_start=(
            _subtract_years(as_of, research_window.value).isoformat()
            if research_window is not None
            else None
        ),
        research_reports_lookback_years=(
            research_window.value if research_window is not None else None
        ),
        company_news_max_pages=max(
            1,
            event_capability.budget.max_pages // len(company_windows),
        ),
        official_max_pages=official_capability.budget.max_pages,
        research_reports_max_pages=(
            research_capability.budget.max_pages if research_capability is not None else None
        ),
    )
