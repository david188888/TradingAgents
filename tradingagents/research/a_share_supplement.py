"""Deterministic horizon budget for optional A-share research supplements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from tradingagents.research.horizon_policy import (
    POLICY_VERSION,
    InvestmentHorizon,
    build_data_window_plan,
)


@dataclass(frozen=True)
class AshareSupplementCapabilityV1:
    capability_id: str
    route_method: str
    max_chars: int


@dataclass(frozen=True)
class AshareSupplementPlanV1:
    policy_version: str
    horizon: InvestmentHorizon
    as_of: str
    capital_flow_start: str
    requested_flow_windows: tuple[dict[str, object], ...]
    board_period: str
    capabilities: tuple[AshareSupplementCapabilityV1, ...]


_CAPABILITY_BUDGETS: dict[
    InvestmentHorizon,
    tuple[tuple[str, str, int], ...],
] = {
    "short": (
        ("capital_flow", "get_a_share_capital_flow", 6_000),
        ("northbound_flow", "get_a_share_northbound_flow", 4_000),
        ("northbound_holdings", "get_a_share_northbound_holdings", 4_000),
        ("margin_financing", "get_a_share_margin_financing", 6_000),
        ("insider_trades", "get_a_share_insider_trades", 4_000),
        ("dragon_tiger", "get_a_share_dragon_tiger", 4_000),
        ("industry_board_flow", "get_a_share_board_fund_flow", 3_000),
        ("concept_board_flow", "get_a_share_board_fund_flow", 3_000),
        ("hot_list", "get_a_share_hot_list", 4_000),
        ("hot_concept", "get_a_share_hot_concept", 3_000),
        ("concept_blocks", "get_a_share_concept_blocks", 4_000),
        ("cls_telegraph", "get_cls_telegraph", 5_000),
        ("industry_research_reports", "industry_research_qtype1", 2_000),
    ),
    "medium": (
        ("capital_flow", "get_a_share_capital_flow", 8_000),
        ("northbound_flow", "get_a_share_northbound_flow", 5_000),
        ("northbound_holdings", "get_a_share_northbound_holdings", 4_000),
        ("margin_financing", "get_a_share_margin_financing", 8_000),
        ("insider_trades", "get_a_share_insider_trades", 5_000),
        ("dragon_tiger", "get_a_share_dragon_tiger", 4_000),
        ("industry_board_flow", "get_a_share_board_fund_flow", 4_000),
        ("concept_board_flow", "get_a_share_board_fund_flow", 4_000),
        ("hot_list", "get_a_share_hot_list", 4_000),
        ("hot_concept", "get_a_share_hot_concept", 3_000),
        ("concept_blocks", "get_a_share_concept_blocks", 4_000),
        ("interactive_questions", "get_a_share_interactive_questions", 6_000),
        ("cls_telegraph", "get_cls_telegraph", 5_000),
        ("industry_research_reports", "industry_research_qtype1", 2_000),
        # a-stock-data v3.7.0 supplement: valuation history + adjust factors
        ("valuation_history", "get_a_share_valuation_history", 6_000),
        ("adjust_factors", "get_a_share_adjust_factors", 2_000),
    ),
    "long": (
        ("capital_flow", "get_a_share_capital_flow", 8_000),
        ("northbound_holdings", "get_a_share_northbound_holdings", 4_000),
        ("margin_financing", "get_a_share_margin_financing", 8_000),
        ("insider_trades", "get_a_share_insider_trades", 5_000),
        ("industry_board_flow", "get_a_share_board_fund_flow", 4_000),
        ("concept_board_flow", "get_a_share_board_fund_flow", 4_000),
        ("hot_concept", "get_a_share_hot_concept", 3_000),
        ("concept_blocks", "get_a_share_concept_blocks", 4_000),
        ("interactive_questions", "get_a_share_interactive_questions", 6_000),
        ("industry_research_reports", "industry_research_qtype1", 2_000),
        # a-stock-data v3.7.0 supplement: full research-depth set
        ("adjust_factors", "get_a_share_adjust_factors", 2_000),
        ("valuation_history", "get_a_share_valuation_history", 8_000),
        ("listing_history", "get_a_share_listing_history", 2_000),
        ("chip_distribution", "get_a_share_chip_distribution", 3_000),
        ("sw_industry_history", "get_sw_industry_history", 5_000),
        ("china_social_financing", "get_china_social_financing", 5_000),
        ("china_pmi", "get_china_pmi", 3_000),
    ),
}


def build_a_share_supplement_plan(
    horizon: InvestmentHorizon,
    analysis_date: str,
) -> AshareSupplementPlanV1:
    """Resolve the executable supplement budget from HorizonPolicy v1."""
    policy = build_data_window_plan(horizon, analysis_date, market="a_share")
    sentiment = policy.capability_index()["sentiment_pulse"]
    flow_windows = tuple(
        {
            "window_id": window.window_id,
            "value": window.value,
            "unit": window.unit,
        }
        for window in sentiment.windows
        if "flow" in window.window_id or "pulse" in window.window_id
    )
    trading_days = [
        window.value for window in sentiment.windows if window.unit == "trading_days"
    ]
    max_trading_days = max(trading_days, default=20)
    # Deterministic calendar-safe overfetch. Coverage remains provider-owned;
    # this date is a request, not a claim that 120 observations were returned.
    calendar_days = (max_trading_days * 365 + 249) // 250 + 14
    as_of = date.fromisoformat(analysis_date)
    board_period = "5d" if horizon == "short" else "10d"
    return AshareSupplementPlanV1(
        policy_version=POLICY_VERSION,
        horizon=horizon,
        as_of=analysis_date,
        capital_flow_start=(as_of - timedelta(days=calendar_days)).isoformat(),
        requested_flow_windows=flow_windows,
        board_period=board_period,
        capabilities=tuple(
            AshareSupplementCapabilityV1(*definition)
            for definition in _CAPABILITY_BUDGETS[horizon]
        ),
    )
