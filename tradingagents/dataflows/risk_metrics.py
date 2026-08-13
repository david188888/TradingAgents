"""Deterministic risk metrics from verified adjusted price series."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DEFAULT_MINIMUM_RETURNS = 20


class RiskMetricsUnavailableError(ValueError):
    """Inputs cannot support a truthful local risk calculation."""


@dataclass(frozen=True)
class LocalRiskMetrics:
    observation_count: int
    annualized_volatility: float
    max_drawdown: float
    historical_var_95: float
    beta: float
    annualized_alpha: float
    sharpe_ratio: float
    benchmark_name: str
    risk_free_rate: float = 0.0


def calculate_local_risk_metrics(
    adjusted_close: pd.Series,
    benchmark_adjusted_close: pd.Series,
    *,
    benchmark_name: str,
    minimum_returns: int = DEFAULT_MINIMUM_RETURNS,
) -> LocalRiskMetrics:
    """Calculate return statistics without I/O or source substitution.

    ``historical_var_95`` is a signed daily return quantile: a negative value
    represents a loss threshold. Inputs must already be source-verified and
    adjusted according to the caller's coverage contract.
    """
    if not benchmark_name.strip():
        raise ValueError("benchmark_name must be non-empty")
    if minimum_returns < 2:
        raise ValueError("minimum_returns must be at least 2")

    asset = _normalized_close(adjusted_close, label="asset")
    benchmark = _normalized_close(benchmark_adjusted_close, label="benchmark")
    aligned = pd.concat((asset.rename("asset"), benchmark.rename("benchmark")), axis=1, join="inner")
    if aligned.empty:
        raise RiskMetricsUnavailableError("asset and benchmark have no aligned adjusted-close dates")
    returns = aligned.pct_change(fill_method=None).dropna()
    if len(returns) < minimum_returns:
        raise RiskMetricsUnavailableError(
            f"need at least {minimum_returns} aligned returns, got {len(returns)}"
        )

    asset_returns = returns["asset"]
    benchmark_returns = returns["benchmark"]
    benchmark_variance = float(benchmark_returns.var(ddof=1))
    if benchmark_variance <= 0:
        raise RiskMetricsUnavailableError("benchmark returns have zero variance")
    asset_standard_deviation = float(asset_returns.std(ddof=1))
    if asset_standard_deviation <= 0:
        raise RiskMetricsUnavailableError("asset returns have zero variance")

    beta = float(asset_returns.cov(benchmark_returns) / benchmark_variance)
    excess_return = asset_returns - beta * benchmark_returns
    annualized_alpha = float(excess_return.mean() * TRADING_DAYS_PER_YEAR)
    annualized_volatility = float(asset_standard_deviation * sqrt(TRADING_DAYS_PER_YEAR))
    sharpe_ratio = float(
        asset_returns.mean() / asset_standard_deviation * sqrt(TRADING_DAYS_PER_YEAR)
    )
    wealth = (1 + asset_returns).cumprod()
    max_drawdown = float((wealth / wealth.cummax() - 1).min())

    return LocalRiskMetrics(
        observation_count=len(returns),
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        historical_var_95=float(asset_returns.quantile(0.05)),
        beta=beta,
        annualized_alpha=annualized_alpha,
        sharpe_ratio=sharpe_ratio,
        benchmark_name=benchmark_name,
    )


def _normalized_close(values: pd.Series, *, label: str) -> pd.Series:
    if not isinstance(values, pd.Series):
        raise TypeError(f"{label} adjusted close must be a pandas Series")
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or (numeric <= 0).any():
        raise RiskMetricsUnavailableError(f"{label} adjusted close contains missing or non-positive values")
    if numeric.index.has_duplicates:
        raise RiskMetricsUnavailableError(f"{label} adjusted close has duplicate dates")
    try:
        normalized_index = pd.to_datetime(numeric.index, errors="raise")
    except (TypeError, ValueError) as exc:
        raise RiskMetricsUnavailableError(f"{label} adjusted close index is not date-like") from exc
    normalized = pd.Series(numeric.to_numpy(), index=normalized_index).sort_index()
    if normalized.empty:
        raise RiskMetricsUnavailableError(f"{label} adjusted close is empty")
    return normalized
