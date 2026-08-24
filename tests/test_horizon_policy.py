"""Versioned, deterministic investment-horizon data window plans."""

from __future__ import annotations

import pytest

from tradingagents.research.horizon_policy import build_data_window_plan

EXPECTED_REQUIRED = {
    "short": {
        "verified_identity",
        "verified_market_snapshot",
        "adjusted_price_history",
    },
    "medium": {
        "verified_identity",
        "verified_market_snapshot",
        "adjusted_price_history",
        "official_disclosures",
        "fundamentals_quarterly",
    },
    "long": {
        "verified_identity",
        "verified_market_snapshot",
        "adjusted_price_history",
        "official_disclosures",
        "fundamentals_annual",
    },
}


@pytest.mark.unit
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_horizon_policy_has_exact_required_capability_matrix(horizon):
    plan = build_data_window_plan(horizon, "2026-07-31")

    required = {
        capability.capability_id
        for capability in plan.capabilities
        if capability.requirement == "required"
    }
    assert required == EXPECTED_REQUIRED[horizon]


@pytest.mark.unit
def test_short_requires_market_and_treats_news_as_optional_enrichment():
    plan = build_data_window_plan("short", "2026-07-31")

    assert plan.required_lenses == ("market",)
    assert plan.optional_lenses == ("fundamentals", "news", "sentiment")
    assert plan.required_lens_groups == ()


@pytest.mark.unit
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_adjusted_price_history_is_always_qfq_and_other_capabilities_are_not(horizon):
    plan = build_data_window_plan(horizon, "2026-07-31")

    for capability in plan.capabilities:
        if capability.capability_id == "adjusted_price_history":
            assert capability.price_basis == "qfq"
            assert "mootdx.daily_bars" not in capability.optional_source_ids
        elif capability.capability_id == "raw_price_audit":
            assert capability.price_basis == "raw"
            assert capability.optional_source_ids == ("mootdx.daily_bars",)
        else:
            assert capability.price_basis == "not_applicable"


@pytest.mark.unit
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_capabilities_sources_windows_and_budgets_are_well_formed(horizon):
    plan = build_data_window_plan(horizon, "2026-07-31")

    capability_ids = [capability.capability_id for capability in plan.capabilities]
    assert len(capability_ids) == len(set(capability_ids))
    for capability in plan.capabilities:
        grouped_sources = tuple(
            source_id
            for group in capability.required_source_groups
            for source_id in group.source_ids
        )
        all_sources = (
            capability.required_source_ids
            + grouped_sources
            + capability.optional_source_ids
        )
        assert len(all_sources) == len(set(all_sources))
        assert capability.windows
        assert len({window.window_id for window in capability.windows}) == len(
            capability.windows
        )
        assert capability.budget.max_calls > 0
        assert capability.budget.max_items > 0
        assert capability.budget.max_pages > 0


@pytest.mark.unit
def test_horizon_policy_is_replay_deterministic():
    first = build_data_window_plan("medium", "2026-07-31")
    second = build_data_window_plan("medium", "2026-07-31")

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.unit
def test_horizon_specific_news_and_price_windows_match_product_policy():
    short = build_data_window_plan("short", "2026-07-31").capability_index()
    medium = build_data_window_plan("medium", "2026-07-31").capability_index()
    long = build_data_window_plan("long", "2026-07-31").capability_index()

    assert [window.value for window in short["company_event_window"].windows] == [7, 30, 90]
    assert [window.value for window in medium["company_event_window"].windows] == [7, 30, 180]
    assert [window.value for window in long["company_event_window"].windows] == [7, 30, 90, 365]
    assert short["adjusted_price_history"].windows[0].value == 365
    assert medium["adjusted_price_history"].granularities == ("daily", "weekly")
    assert long["adjusted_price_history"].windows[0].value == 5
    assert long["adjusted_price_history"].windows[0].unit == "years"


@pytest.mark.unit
def test_long_horizon_prioritizes_structural_sentiment_sources():
    sentiment = build_data_window_plan("long", "2026-07-31").capability_index()[
        "sentiment_pulse"
    ]

    assert sentiment.optional_source_ids[:3] == (
        "eastmoney.shareholder_counts",
        "cninfo.announcements",
        "eastmoney.insider_trades",
    )


@pytest.mark.unit
def test_annual_fundamentals_do_not_use_mootdx_quarterly_snapshot():
    for horizon in ("medium", "long"):
        annual = build_data_window_plan(horizon, "2026-07-31").capability_index()[
            "fundamentals_annual"
        ]
        sources = annual.optional_source_ids + tuple(
            source_id
            for group in annual.required_source_groups
            for source_id in group.source_ids
        )
        assert "mootdx.finance_snapshot" not in sources


@pytest.mark.unit
def test_a_share_source_contracts_match_live_provider_datasets():
    capabilities = build_data_window_plan(
        "long", "2026-07-31", market="a_share"
    ).capability_index()

    identity = capabilities["verified_identity"].required_source_groups[0]
    assert identity.source_ids == (
        "validated_ticker.exchange",
        "tushare.stock_basic",
        "eastmoney.stock_profile",
        "akshare.stock_individual_info",
        "sina.stock_code_name",
        "yfinance.company_profile",
    )

    snapshot = capabilities["verified_market_snapshot"].required_source_groups[0]
    assert "tencent.snapshot" not in snapshot.source_ids
    assert snapshot.source_ids == (
        "mootdx.daily_bars",
        "tushare.tushare_get_stock",
        "akshare.daily_bars",
    )

    event_sources = capabilities["company_event_window"].optional_source_ids
    assert "ths.hot_list" in event_sources
    assert "eastmoney.hot_concept" in event_sources
    assert "akshare.hot_list" not in event_sources
    assert "akshare.hot_concept" not in event_sources


@pytest.mark.unit
def test_global_market_uses_global_identity_snapshot_and_price_routes():
    capabilities = build_data_window_plan(
        "medium", "2026-07-31", market="global"
    ).capability_index()

    identity = capabilities["verified_identity"].required_source_groups[0]
    snapshot = capabilities["verified_market_snapshot"].required_source_groups[0]
    adjusted = capabilities["adjusted_price_history"].required_source_groups[0]

    assert identity.source_ids == ("yfinance.company_profile",)
    assert snapshot.source_ids == (
        "yfinance.ohlcv",
        "alpha_vantage.TIME_SERIES_DAILY",
    )
    assert adjusted.source_ids == (
        "yfinance.adjusted_ohlcv",
        "alpha_vantage.TIME_SERIES_DAILY_ADJUSTED",
    )


@pytest.mark.unit
@pytest.mark.parametrize("market", ["a_share", "global"])
def test_required_annual_fundamentals_require_all_three_statement_families(market):
    annual = build_data_window_plan(
        "long", "2026-07-31", market=market
    ).capability_index()["fundamentals_annual"]

    assert [group.group_id for group in annual.required_source_groups] == [
        "fundamentals_annual_balance_sheet_provider",
        "fundamentals_annual_cash_flow_provider",
        "fundamentals_annual_income_statement_provider",
    ]
    assert all(group.minimum_usable == 1 for group in annual.required_source_groups)
    assert all(
        all("fundamentals" not in source_id for source_id in group.source_ids)
        for group in annual.required_source_groups
    )


@pytest.mark.unit
def test_market_is_part_of_replay_contract():
    a_share = build_data_window_plan("medium", "2026-07-31", market="a_share")
    global_plan = build_data_window_plan("medium", "2026-07-31", market="global")

    assert a_share.market == "a_share"
    assert global_plan.market == "global"
    assert a_share.model_dump(mode="json") != global_plan.model_dump(mode="json")


@pytest.mark.unit
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_global_plan_contains_no_a_share_only_sources_or_empty_capabilities(horizon):
    plan = build_data_window_plan(horizon, "2026-07-31", market="global")
    forbidden_prefixes = (
        "akshare.",
        "china_exchange.",
        "cls.",
        "cninfo.",
        "eastmoney.",
        "mootdx.",
        "sina.",
        "ths.",
        "tushare.",
    )

    for capability in plan.capabilities:
        source_ids = capability.required_source_ids + capability.optional_source_ids
        source_ids += tuple(
            source_id
            for group in capability.required_source_groups
            for source_id in group.source_ids
        )
        assert source_ids
        assert not any(
            source_id.startswith(forbidden_prefixes) for source_id in source_ids
        )


@pytest.mark.unit
@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_required_capability_matrix_is_market_invariant(horizon):
    matrices = []
    for market in ("a_share", "global"):
        plan = build_data_window_plan(horizon, "2026-07-31", market=market)
        matrices.append(
            {
                capability.capability_id
                for capability in plan.capabilities
                if capability.requirement == "required"
            }
        )

    assert matrices == [EXPECTED_REQUIRED[horizon], EXPECTED_REQUIRED[horizon]]
