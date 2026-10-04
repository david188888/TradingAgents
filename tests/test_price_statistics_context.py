"""Per-metric degradation of the frozen code-computed evidence payload."""

import pandas as pd
import pytest

from tradingagents.research.price_statistics import build_price_statistics


def context(size):
    dates = pd.bdate_range("2026-08-01", periods=size).strftime("%Y-%m-%d").tolist()
    bars = [{"Date": day, "Close": 100 + i, "High": 101 + i, "Low": 99 + i} for i, day in enumerate(dates)]
    provenance = {"input_sha256": "input-fixture", "source": "synthetic", "price_basis": "qfq",
        "adjustment_anchor": dates[-1], "price_unit": "CNY/share", "pit_status": "verified",
        "window_covered": True, "expected_sessions": dates}
    return bars, provenance


def test_asset_risk_and_atr_available_without_benchmark():
    result = build_price_statistics(*context(30))
    assert result["return_statistics"]["status"] == "available"
    assert result["return_statistics"]["observation_count"] == 29
    assert result["return_statistics"]["tail_observation_count"] == 2
    assert result["atr"]["value"] == pytest.approx(2)
    assert result["benchmark_statistics"]["reason"] == "qualified_benchmark_not_supplied"
    assert result["input_sha256"] == "input-fixture"
    assert "fewer_than_five_tail_observations" in result["limitations"]


def test_atr_and_return_sample_limits_degrade_independently():
    result = build_price_statistics(*context(16))
    assert result["return_statistics"]["status"] == "unavailable"
    assert result["atr"]["status"] == "available"


def test_missing_ohlc_does_not_disable_close_based_risk():
    bars, provenance = context(30)
    del bars[0]["High"]
    result = build_price_statistics(bars, provenance)
    assert result["return_statistics"]["status"] == "available"
    assert result["atr"] == {"status": "unavailable", "reason": "ohlc_not_supplied"}


def test_unverified_history_cannot_be_promoted_by_calculation():
    bars, provenance = context(30)
    provenance["pit_status"] = "unverified"
    result = build_price_statistics(bars, provenance)
    assert result["return_statistics"]["status"] == "unavailable"
    assert result["atr"]["status"] == "unavailable"
