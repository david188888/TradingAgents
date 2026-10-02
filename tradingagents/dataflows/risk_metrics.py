"""Deterministic risk metrics from verified adjusted price series."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DEFAULT_MINIMUM_RETURNS = 20
RISK_CALCULATION_VERSION = "local-risk-v2"


@dataclass(frozen=True)
class ReturnRiskMetrics:
    """Individual-security statistics; no benchmark is required.

    VaR/ES use signed simple daily returns, preserving the original local API.
    ``tail_observation_count`` exposes how little evidence a small tail has.
    These are descriptive statistics, not valuation or future loss bounds.
    """

    observation_count: int
    window_start: str
    window_end: str
    annualized_volatility: float
    max_drawdown: float
    historical_var_95: float
    historical_es_95: float
    tail_observation_count: int
    sharpe_ratio: float | None
    calculation_version: str = RISK_CALCULATION_VERSION


def calculate_return_risk_metrics(
    adjusted_close: pd.Series,
    *,
    minimum_returns: int = DEFAULT_MINIMUM_RETURNS,
    expected_sessions: pd.DatetimeIndex | None = None,
) -> ReturnRiskMetrics:
    """Compute from qualified daily closes without filling missing sessions.

    Calendar qualification remains the caller's responsibility. When supplied,
    ``expected_sessions`` must cover the input window and may expose gaps; the
    two returns adjacent to a missing session are excluded, never bridged.
    Annualization assumes 252 sessions and zero risk-free return.
    """
    _validate_minimum_returns(minimum_returns)
    asset = _normalized_close(adjusted_close, label="asset")
    grid = _session_grid(expected_sessions, asset.index)
    returns = _finite_returns(asset.reindex(grid)).dropna()
    _require_returns(returns, minimum_returns)
    standard_deviation = float(returns.std(ddof=1))
    threshold = float(returns.quantile(0.05, interpolation="linear"))
    tail = returns[returns <= threshold]
    _require_finite(standard_deviation, threshold, float(tail.mean()))
    return ReturnRiskMetrics(
        observation_count=len(returns),
        window_start=asset.index[0].date().isoformat(),
        window_end=asset.index[-1].date().isoformat(),
        annualized_volatility=standard_deviation * sqrt(TRADING_DAYS_PER_YEAR),
        max_drawdown=float((asset / asset.cummax() - 1).min()),
        historical_var_95=threshold,
        historical_es_95=float(tail.mean()),
        tail_observation_count=len(tail),
        sharpe_ratio=(
            float(returns.mean() / standard_deviation * sqrt(TRADING_DAYS_PER_YEAR))
            if standard_deviation > 0 else None
        ),
    )


class RiskMetricsUnavailableError(ValueError):
    """Inputs cannot support a truthful local risk calculation."""


@dataclass(frozen=True)
class AtrMetrics:
    value: float
    period: int
    observation_count: int
    window_start: str
    window_end: str
    calculation_version: str = "wilder-atr-v1"


def calculate_wilder_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, *, period: int = 14,
    expected_sessions: pd.DatetimeIndex | None = None,
) -> AtrMetrics:
    """Wilder smoothing; seed is the first N true ranges with prior closes.

    The first price row has no prior close and is excluded from the seed.
    OHLC must share the same adjustment anchor. Known missing sessions make
    this path unavailable rather than joining a range across a gap.
    """
    _validate_minimum_returns(period)
    highest, lowest, last = (_normalized_close(value, label=label) for value, label in
        ((high, "high"), (low, "low"), (close, "close")))
    if not highest.index.equals(last.index) or not lowest.index.equals(last.index):
        raise RiskMetricsUnavailableError("ATR OHLC dates do not match")
    grid = _session_grid(expected_sessions, last.index)
    if not grid.equals(last.index):
        raise RiskMetricsUnavailableError("ATR requires complete session OHLC")
    if ((lowest > last) | (last > highest)).any():
        raise RiskMetricsUnavailableError("ATR OHLC ranges are inconsistent")
    true_range = pd.concat((highest - lowest, (highest - last.shift()).abs(),
        (lowest - last.shift()).abs()), axis=1).max(axis=1).iloc[1:]
    _require_returns(true_range, period)
    value = float(true_range.iloc[:period].mean())
    for observed in true_range.iloc[period:]:
        value = value * ((period - 1) / period) + float(observed) / period
    _require_finite(value)
    return AtrMetrics(value=value, period=period, observation_count=len(true_range),
        window_start=last.index[0].date().isoformat(), window_end=last.index[-1].date().isoformat())


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
    expected_sessions: pd.DatetimeIndex | None = None,
) -> LocalRiskMetrics:
    """Calculate return statistics without I/O or source substitution.

    ``historical_var_95`` is a signed daily return quantile: a negative value
    represents a loss threshold. Inputs must already be source-verified and
    adjusted according to the caller's coverage contract. Returns are aligned
    on a shared session grid before missing pairs are removed: joining prices
    first would manufacture multi-session returns after a missing date. The
    optional calendar also detects dates missing from both sources.
    """
    if not benchmark_name.strip():
        raise ValueError("benchmark_name must be non-empty")
    _validate_minimum_returns(minimum_returns)

    asset = _normalized_close(adjusted_close, label="asset")
    benchmark = _normalized_close(benchmark_adjusted_close, label="benchmark")
    grid = _session_grid(expected_sessions, asset.index.union(benchmark.index))
    returns = pd.concat((
        _finite_returns(asset.reindex(grid)).rename("asset"),
        _finite_returns(benchmark.reindex(grid)).rename("benchmark"),
    ), axis=1).dropna()
    _require_returns(returns, minimum_returns)

    asset_returns = returns["asset"]
    benchmark_returns = returns["benchmark"]
    benchmark_variance = float(benchmark_returns.var(ddof=1))
    _require_finite(benchmark_variance)
    if benchmark_variance <= 0:
        raise RiskMetricsUnavailableError("benchmark returns have zero variance")
    asset_standard_deviation = float(asset_returns.std(ddof=1))
    _require_finite(asset_standard_deviation)
    if asset_standard_deviation <= 0:
        raise RiskMetricsUnavailableError("asset returns have zero variance")

    beta = float(asset_returns.cov(benchmark_returns) / benchmark_variance)
    excess_return = asset_returns - beta * benchmark_returns
    annualized_alpha = float(excess_return.mean() * TRADING_DAYS_PER_YEAR)
    annualized_volatility = float(asset_standard_deviation * sqrt(TRADING_DAYS_PER_YEAR))
    sharpe_ratio = float(
        asset_returns.mean() / asset_standard_deviation * sqrt(TRADING_DAYS_PER_YEAR)
    )
    # Keep the initial price and the whole observed asset path, independently
    # of benchmark coverage. Cumprod(returns) omits the first drawdown.
    max_drawdown = float((asset / asset.cummax() - 1).min())
    _require_finite(beta, annualized_alpha, annualized_volatility, sharpe_ratio, max_drawdown)

    return LocalRiskMetrics(
        observation_count=len(returns),
        annualized_volatility=annualized_volatility,
        max_drawdown=max_drawdown,
        historical_var_95=float(asset_returns.quantile(0.05, interpolation="linear")),
        beta=beta,
        annualized_alpha=annualized_alpha,
        sharpe_ratio=sharpe_ratio,
        benchmark_name=benchmark_name,
    )


def _normalized_close(values: pd.Series, *, label: str) -> pd.Series:
    if not isinstance(values, pd.Series):
        raise TypeError(f"{label} adjusted close must be a pandas Series")
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or any(not isfinite(value) or value <= 0 for value in numeric):
        raise RiskMetricsUnavailableError(f"{label} adjusted close contains missing, non-finite or non-positive values")
    if numeric.index.has_duplicates:
        raise RiskMetricsUnavailableError(f"{label} adjusted close has duplicate dates")
    if pd.api.types.is_numeric_dtype(numeric.index.dtype):
        raise RiskMetricsUnavailableError(f"{label} adjusted close index is not date-like")
    try:
        normalized_index = pd.to_datetime(numeric.index, errors="raise")
    except (TypeError, ValueError) as exc:
        raise RiskMetricsUnavailableError(f"{label} adjusted close index is not date-like") from exc
    if not isinstance(normalized_index, pd.DatetimeIndex) or normalized_index.hasnans:
        raise RiskMetricsUnavailableError(f"{label} adjusted close index contains invalid dates")
    # Daily labels are local exchange dates, not UTC instants.
    if normalized_index.tz is not None:
        normalized_index = normalized_index.tz_localize(None)
    if not normalized_index.equals(normalized_index.normalize()):
        raise RiskMetricsUnavailableError(f"{label} adjusted close requires daily date labels")
    if normalized_index.has_duplicates:
        raise RiskMetricsUnavailableError(f"{label} adjusted close has duplicate dates")
    normalized = pd.Series(numeric.to_numpy(dtype=float), index=normalized_index).sort_index()
    if normalized.empty:
        raise RiskMetricsUnavailableError(f"{label} adjusted close is empty")
    return normalized


def _validate_minimum_returns(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise ValueError("minimum_returns must be at least 2 and an integer")


def _require_returns(values: pd.Series | pd.DataFrame, minimum: int) -> None:
    if len(values) < minimum:
        raise RiskMetricsUnavailableError(f"need at least {minimum} aligned returns, got {len(values)}")


def _finite_returns(prices: pd.Series) -> pd.Series:
    values = prices.pct_change(fill_method=None)
    if any(not isfinite(value) for value in values.dropna()):
        raise RiskMetricsUnavailableError("price ratios produced non-finite returns")
    return values


def _require_finite(*values: float) -> None:
    if any(not isfinite(value) for value in values):
        raise RiskMetricsUnavailableError("statistics produced non-finite values")


def _session_grid(expected: pd.DatetimeIndex | None, observed: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if expected is None:
        return observed.sort_values()
    calendar = _normalized_close(pd.Series(1.0, index=expected), label="calendar").index
    if not observed.isin(calendar).all():
        raise RiskMetricsUnavailableError("expected sessions do not cover observed dates")
    return calendar[(calendar >= observed.min()) & (calendar <= observed.max())]
