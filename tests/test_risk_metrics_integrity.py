"""Research risk statistics against hand-computed counterexamples, no I/O."""

import math

import pandas as pd
import pytest

from tradingagents.dataflows.risk_metrics import (
    RiskMetricsUnavailableError,
    calculate_local_risk_metrics,
    calculate_return_risk_metrics,
    calculate_wilder_atr,
)


def prices(values, dates=None):
    return pd.Series(values, index=dates if dates is not None else pd.date_range("2026-01-01", periods=len(values)))


def test_drawdown_retains_initial_peak_and_full_asset_path():
    asset = prices([100, 90, 81, 89.1])
    benchmark = prices([100, 102, 101, 103])
    result = calculate_local_risk_metrics(asset, benchmark, benchmark_name="synthetic", minimum_returns=2)
    assert result.max_drawdown == pytest.approx(-0.19)
    solo = calculate_return_risk_metrics(asset, minimum_returns=2)
    assert solo.max_drawdown == pytest.approx(-0.19)
    assert solo.window_start == "2026-01-01"
    assert solo.window_end == "2026-01-04"


def test_joining_returns_never_bridges_missing_benchmark_date():
    dates = pd.date_range("2026-01-01", periods=6)
    asset = prices([100, 110, 132, 118.8, 130.68, 156.816], dates)
    benchmark = prices([100, 110, 121, 145.2, 159.72], dates.delete(2))
    result = calculate_local_risk_metrics(asset, benchmark, benchmark_name="synthetic", minimum_returns=2)
    # Only day 2, day 5 and day 6 have matching one-session intervals.
    assert result.observation_count == 3
    # A=(.1,.1,.2), B=(.1,.2,.1): covariance/variance = -0.5.
    assert result.beta == pytest.approx(-0.5)
    assert result.historical_var_95 == pytest.approx(0.1)
    # The asset drawdown on day 4 is retained even though beta excludes it.
    assert result.max_drawdown == pytest.approx(-0.1)


def test_calendar_detects_a_session_missing_from_both_sources():
    dates = pd.date_range("2026-01-01", periods=6)
    observed = prices([100, 110, 121, 145.2, 159.72], dates.delete(2))
    result = calculate_return_risk_metrics(observed, expected_sessions=dates, minimum_returns=2)
    assert result.observation_count == 3
    paired = calculate_local_risk_metrics(observed, observed, benchmark_name="synthetic", expected_sessions=dates, minimum_returns=2)
    assert paired.observation_count == 3
    assert paired.beta == pytest.approx(1)


def test_signed_tail_statistics_use_explicit_linear_quantile():
    # Simple returns -20%, -10%, +10%, +20%: q(.05) = -18.5%, ES = -20%.
    result = calculate_return_risk_metrics(prices([100, 80, 72, 79.2, 95.04]), minimum_returns=2)
    assert result.historical_var_95 == pytest.approx(-0.185)
    assert result.historical_es_95 == pytest.approx(-0.2)
    assert result.tail_observation_count == 1
    assert result.max_drawdown == pytest.approx(-0.28)
    assert result.annualized_volatility == pytest.approx(math.sqrt(0.1 / 3) * math.sqrt(252))


def test_constant_price_keeps_zero_risk_without_manufacturing_sharpe():
    result = calculate_return_risk_metrics(prices([100, 100, 100, 100]), minimum_returns=2)
    assert result.annualized_volatility == 0
    assert result.max_drawdown == 0
    assert result.historical_var_95 == 0
    assert result.historical_es_95 == 0
    assert result.sharpe_ratio is None


@pytest.mark.parametrize("values", [[100, float("inf"), 102], [100, float("nan"), 102], [100, 0, 102], [100, -1, 102]])
def test_non_finite_or_invalid_prices_fail_closed(values):
    with pytest.raises(RiskMetricsUnavailableError):
        calculate_return_risk_metrics(prices(values), minimum_returns=2)


@pytest.mark.parametrize("index", [
    [0, 1, 2],
    ["2026-01-01", "2026-01-01T00:00:00", "2026-01-02"],
    pd.DatetimeIndex(["2026-01-01", pd.NaT, "2026-01-03"]),
    pd.date_range("2026-01-01T15:00:00", periods=3),
])
def test_dates_cannot_be_numeric_invalid_duplicate_or_intraday(index):
    with pytest.raises(RiskMetricsUnavailableError):
        calculate_return_risk_metrics(prices([100, 101, 103], index), minimum_returns=2)


def test_exchange_dates_do_not_shift_to_previous_utc_day():
    result = calculate_return_risk_metrics(prices([100, 101, 103], pd.date_range("2026-01-01", periods=3, tz="Asia/Shanghai")), minimum_returns=2)
    assert result.window_start == "2026-01-01"
    assert result.window_end == "2026-01-03"


def test_supplied_calendar_cannot_silently_drop_observed_dates():
    with pytest.raises(RiskMetricsUnavailableError, match="cover observed dates"):
        calculate_return_risk_metrics(prices([100, 101, 103]), minimum_returns=2, expected_sessions=pd.date_range("2026-01-02", periods=3))


def test_wilder_atr_seed_and_smoothing_against_hand_calculation():
    # TR after initial row: 2, 21, 2. ATR(2) seed=11.5, final=6.75.
    close = prices([100, 101, 121, 122])
    result = calculate_wilder_atr(close + 1, close - 1, close, period=2)
    assert result.value == pytest.approx(6.75)
    assert result.observation_count == 3


def test_atr_never_bridges_a_missing_session():
    dates = pd.date_range("2026-01-01", periods=5)
    close = prices([100, 101, 121, 122], dates.delete(2))
    with pytest.raises(RiskMetricsUnavailableError, match="complete session"):
        calculate_wilder_atr(close + 1, close - 1, close, period=2, expected_sessions=dates)


def test_risk_statistics_overflow_does_not_become_infinity():
    with pytest.raises(RiskMetricsUnavailableError, match="non-finite"):
        calculate_return_risk_metrics(prices([1, 1e200, 1e200, 1e200]), minimum_returns=2)
