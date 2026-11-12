from datetime import date, timedelta

import pandas as pd
import pytest

from tradingagents.dataflows.risk_metrics import (
    RiskMetricsUnavailableError,
    calculate_local_risk_metrics,
)


def _series(values):
    start = date(2026, 1, 1)
    return pd.Series(
        values,
        index=[start + timedelta(days=offset) for offset in range(len(values))],
    )


def test_local_risk_metrics_are_deterministic_for_aligned_adjusted_prices():
    benchmark = _series([100 + 0.4 * i for i in range(25)])
    asset = _series([100 + 0.8 * i for i in range(25)])

    result = calculate_local_risk_metrics(
        asset,
        benchmark,
        benchmark_name="CSI300",
        minimum_returns=20,
    )

    assert result.observation_count == 24
    assert result.benchmark_name == "CSI300"
    assert result.annualized_volatility > 0
    assert result.sharpe_ratio > 0
    assert result.max_drawdown <= 0


def test_local_risk_metrics_fail_closed_for_insufficient_or_invalid_inputs():
    short = _series([100 + i for i in range(5)])
    with pytest.raises(RiskMetricsUnavailableError, match="at least 20"):
        calculate_local_risk_metrics(short, short, benchmark_name="CSI300")

    duplicate = pd.Series([100, 101], index=["2026-01-01", "2026-01-01"])
    with pytest.raises(RiskMetricsUnavailableError, match="duplicate"):
        calculate_local_risk_metrics(duplicate, duplicate, benchmark_name="CSI300")

    with pytest.raises(ValueError, match="benchmark_name"):
        calculate_local_risk_metrics(short, short, benchmark_name=" ")
