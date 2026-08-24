from __future__ import annotations

import json
from datetime import datetime, timezone

from tradingagents.agents.utils import market_data_validation_tools, news_data_tools
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.runner import prepare_v3_research_scaffold
from tradingagents.research.analysis_cutoff import (
    InstrumentIdentityPreflightV1,
    resolve_analysis_cutoff,
    resolve_bounded_analysis_cutoff,
)
from tradingagents.research.horizon_policy import build_data_window_plan


def test_a_share_cutoff_uses_shanghai_end_of_day() -> None:
    result = resolve_analysis_cutoff("600519.SH", "2026-08-13")

    assert result.status == "resolved"
    assert result.timezone_name == "Asia/Shanghai"
    assert result.analysis_cutoff_at == datetime(
        2026, 8, 13, 15, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_global_cutoff_uses_verified_exchange_timezone() -> None:
    result = resolve_analysis_cutoff(
        "AAPL",
        "2026-08-13",
        identity={"exchange": "NMS", "company_name": "Apple Inc."},
    )

    assert result.status == "resolved"
    assert result.timezone_name == "America/New_York"
    assert result.analysis_cutoff_at == datetime(
        2026, 8, 14, 3, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_explicit_verified_timezone_takes_precedence_over_exchange_map() -> None:
    result = resolve_analysis_cutoff(
        "TEST",
        "2026-08-13",
        identity={"exchange": "NMS", "exchange_timezone": "Europe/London"},
    )

    assert result.status == "resolved"
    assert result.timezone_name == "Europe/London"
    assert result.analysis_cutoff_at == datetime(
        2026, 8, 13, 22, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_unknown_global_exchange_produces_invalid_cutoff() -> None:
    result = resolve_analysis_cutoff(
        "UNKNOWN", "2026-08-13", identity={"exchange": "UNMAPPED"}
    )

    assert result.status == "invalid"
    assert result.analysis_cutoff_at is None
    assert result.reason_code == "analysis_cutoff_resolution_failed"


def test_v3_bounded_cutoff_uses_past_eod_and_same_day_capture() -> None:
    past = resolve_bounded_analysis_cutoff(
        "600519.SH",
        "2026-08-12",
        captured_at=datetime(2026, 8, 13, 2, 0, tzinfo=timezone.utc),
    )
    intraday = resolve_bounded_analysis_cutoff(
        "600519.SH",
        "2026-08-13",
        captured_at=datetime(2026, 8, 13, 2, 0, tzinfo=timezone.utc),
    )
    after_close = resolve_bounded_analysis_cutoff(
        "600519.SH",
        "2026-08-13",
        captured_at=datetime(2026, 8, 13, 18, 0, tzinfo=timezone.utc),
    )

    assert past.analysis_cutoff_at == datetime(
        2026, 8, 12, 15, 59, 59, 999999, tzinfo=timezone.utc
    )
    assert intraday.analysis_cutoff_at == datetime(
        2026, 8, 13, 2, 0, tzinfo=timezone.utc
    )
    assert after_close.analysis_cutoff_at == datetime(
        2026, 8, 13, 15, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_v3_bounded_cutoff_handles_new_york_dst_and_future_date() -> None:
    identity = _global_preflight()
    same_day = resolve_bounded_analysis_cutoff(
        "AAPL",
        "2026-07-15",
        identity=identity,
        captured_at=datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc),
    )
    future = resolve_bounded_analysis_cutoff(
        "AAPL",
        "2026-07-16",
        identity=identity,
        captured_at=datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc),
    )

    assert same_day.analysis_cutoff_at == datetime(
        2026, 7, 15, 15, 30, tzinfo=timezone.utc
    )
    assert future.status == "invalid"
    assert future.analysis_cutoff_at is None
    assert future.reason_code == "analysis_cutoff_resolution_failed"


def test_v3_scaffold_is_pure_and_repeatable_with_injected_inputs(monkeypatch) -> None:
    def provider_must_not_run(*_args, **_kwargs):
        raise AssertionError("v3 scaffold must not resolve an identity provider")

    monkeypatch.setattr(
        "tradingagents.research.analysis_cutoff._resolve_identity",
        provider_must_not_run,
    )
    request = AnalysisRequest(
        ticker="AAPL",
        analysis_date="2026-07-15",
        horizon="medium",
    )
    captured_at = datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc)
    identity = _global_preflight()

    first = prepare_v3_research_scaffold(
        request,
        captured_at=captured_at,
        identity_preflight=identity,
    )
    second = prepare_v3_research_scaffold(
        request,
        captured_at=captured_at,
        identity_preflight=identity,
    )

    assert first == second
    assert first.verified_identity is None
    assert first.resolved_plan is None
    assert first.analysis_cutoff.analysis_cutoff_at == captured_at
    assert "captured_at" not in first.model_dump(mode="json")


def test_cutoff_policy_is_declared_before_resolution() -> None:
    plan = build_data_window_plan("medium", "2026-08-13", market="global")

    assert plan.cutoff_resolution_policy.policy_version == "analysis-cutoff-v1"
    assert plan.cutoff_resolution_policy.global_verified_exchange_required is True


def test_invalid_cutoff_blocks_price_and_news_provider_calls(monkeypatch) -> None:
    cutoff = resolve_analysis_cutoff(
        "UNKNOWN", "2026-08-13", identity={"exchange": "UNMAPPED"}
    )
    state = {
        "company_of_interest": "UNKNOWN",
        "trade_date": "2026-08-13",
        "horizon": "medium",
        "analysis_cutoff": cutoff.model_dump(mode="json"),
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("time-sensitive provider path must not run")

    monkeypatch.setattr(
        market_data_validation_tools, "run_adjusted_price_prefetch", fail_if_called
    )
    monkeypatch.setattr(news_data_tools, "run_news_windows", fail_if_called)

    price = market_data_validation_tools.create_adjusted_price_prefetch_node()(state)
    news = news_data_tools.create_news_window_prefetch_node()(state)

    price_bundle = json.loads(price["adjusted_price_bundle"])
    news_bundle = json.loads(news["news_window_bundle"])
    assert price_bundle["status"] == "invalid"
    assert news_bundle["status"] == "invalid"
    assert price_bundle["reason_code"] == "analysis_cutoff_resolution_failed"
    assert news_bundle["reason_code"] == "analysis_cutoff_resolution_failed"
    assert {
        item["capability"]: item["capability_result"]["availability"]
        for item in price_bundle["results"]
    } == {
        "verified_identity": "invalid",
        "verified_market_snapshot": "invalid",
        "adjusted_price_history": "invalid",
    }
    typed = {
        item["capability"]: item["capability_result"]
        for item in news_bundle["results"]
    }
    assert typed["company_event_window"]["availability"] == "invalid"
    assert typed["official_disclosures"]["availability"] == "invalid"
    assert all(
        attempt["outcome"] == "skipped_unobserved"
        for result in typed.values()
        for attempt in result["attempts"]
    )


def _global_preflight() -> InstrumentIdentityPreflightV1:
    return InstrumentIdentityPreflightV1(
        ticker="AAPL",
        market="global",
        candidate_exchange="NMS",
        candidate_timezone="America/New_York",
        regulatory_scope_candidate="us_sec_candidate",
        source_id="fixture.identity",
        derivation="explicit_fixture",
    )
