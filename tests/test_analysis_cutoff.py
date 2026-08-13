from __future__ import annotations

import json
from datetime import datetime, timezone

from tradingagents.agents.utils import market_data_validation_tools, news_data_tools
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
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
