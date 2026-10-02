"""Offline, deterministic synthetic metrics for the reader mockup only.

Run with Python 3.10+: python reader_sample_metrics.py
No market data, external calls, forecasts, or production calculators are used.
"""

import hashlib
import json
import math
import statistics
from pathlib import Path


def quantile_linear(values, probability):
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    left = math.floor(index)
    right = math.ceil(index)
    return ordered[left] + (ordered[right] - ordered[left]) * (index - left)


def calculate():
    benchmark = [0.008 * math.sin(i * 1.7) + 0.003 * math.cos(i * 0.4) for i in range(60)]
    asset = [1.15 * r + 0.011 * math.sin(i * 2.3) + 0.0003 for i, r in enumerate(benchmark)]
    inputs = {"asset_simple_returns": asset, "benchmark_simple_returns": benchmark}
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    losses = [-r for r in asset]
    var = max(0.0, quantile_linear(losses, 0.95))
    tail = [loss for loss in losses if loss >= var]
    asset_mean, benchmark_mean = statistics.mean(asset), statistics.mean(benchmark)
    covariance = sum(
        (a - asset_mean) * (b - benchmark_mean)
        for a, b in zip(asset, benchmark, strict=True)
    ) / (len(asset) - 1)
    return {
        "dataset": "synthetic-reader-v1",
        "qualification": "synthetic only; no security, real dates, or market-data qualification",
        "input_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "inputs": inputs,
        "methods": {
            "observations": 60,
            "return_type": "simple returns; paired by synthetic observation index",
            "annualization": "sample standard deviation (ddof=1) * sqrt(252); illustrative factor",
            "var": "one-observation historical loss VaR 95%; linear quantile at (n-1)*p; floor at zero",
            "es": "mean observed losses >= VaR threshold; not interpolated tail integration",
            "beta": "sample covariance(asset, synthetic benchmark) / sample variance(benchmark)",
            "valuation": "hypothetical annual EPS 2.0 CNY/share * PE [20,26]; not TTM",
        },
        "results": {
            "annualized_volatility": statistics.stdev(asset) * math.sqrt(252),
            "historical_var_95_one_observation": var,
            "historical_es_95_one_observation": statistics.mean(tail),
            "tail_observations": len(tail),
            "beta": covariance / statistics.variance(benchmark),
            "conditional_value_cny": [40.0, 52.0],
            "illustrative_price_cny": 48.0,
        },
        "limits": "Synthetic 60-observation distribution is not a real risk estimate, confidence interval, or future loss bound.",
    }


if __name__ == "__main__":
    output = Path(__file__).with_name("reader_sample_metrics.json")
    output.write_text(json.dumps(calculate(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
