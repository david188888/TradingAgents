# Local price statistics

Status: Current

`dataflows/risk_metrics.py` owns deterministic calculations. No function fetches
data or qualifies provider identity, adjustment, cutoff or calendar coverage.
`dataflows/tushare_price_history.py` qualifies bounded Tushare payloads;
`dataflows/native_sources.py` also admits Tencent raw bars with dated Sina factors
under the native source policy. `research/price_statistics.py` calculates
descriptive statistics inside the qualified payload. Native collectors and
`NativeRunner` freeze/persist this evidence for the market specialist;
`CatalystSources`/`CatalystRunner` retain the legacy path. Saved qualified
results are published inside [research-record-v1](research-record.md) and shown
as quantitative context in the native Reader or below the legacy catalyst brief.
This is separate from valuation. Classic records do not yet publish these local
price metrics.

## Methods and degradation

- Simple daily returns, with no filling. An expected session calendar exposes
  missing dates; adjacent returns are dropped rather than bridged. Without a
  supplied calendar the caller has not proved sessions absent from both inputs.
- Sample standard deviation (`ddof=1`), annualized with 252 sessions. VaR is
  the signed 5th-percentile daily return, with linear interpolation. ES is the
  mean of observed returns at/below that threshold; tail sample count is saved.
  A positive VaR remains positive; display must not invent a negative loss.
- Single-security return statistics require at least 20 valid returns. Sharpe
  assumes zero risk-free rate and is unavailable for zero standard deviation;
  constant prices still have zero volatility/VaR/ES/drawdown.
- Maximum drawdown uses the complete observed price path including the initial
  peak, independent of benchmark availability. With a price gap it is an
  observed-path statistic, not proof of the unobserved intragap trough.
- Beta joins one-session asset and benchmark returns after placing prices on
  their union/calendar grid. Benchmark gaps do not create cross-session returns.
  Zero benchmark variance is unavailable. Existing paired API returns retain
  their names and types.
- ATR uses high/low/close on one adjustment anchor, a seed of the first 14 true
  ranges with previous closes, then Wilder smoothing. The initial price row is
  excluded from the seed. Known missing sessions or inconsistent ranges fail.
- Non-finite/non-positive prices, invalid/duplicate/intraday dates, non-finite
  calculated statistics and insufficient samples fail explicitly.

Metrics degrade independently: unavailable benchmark statistics do not disable
asset risk; absent OHLC does not disable close-based risk; insufficient return
samples do not necessarily disable ATR. Prices must first satisfy their source
qualification. Methods, units, windows, samples, versions and source input hash
are saved; no LLM estimates missing metrics.

These describe historical prices. They do not establish intrinsic value,
valuation percentiles, forecast intervals or future maximum loss. Wind's
provider-reported risk endpoint is a separate capability and is not relabelled
as a local calculation.
