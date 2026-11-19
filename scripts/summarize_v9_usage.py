"""Read a saved V9 run and apply an explicitly selected experiment rate table."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from tradingagents.runtime.research_checkpoint import load_checkpoint
from tradingagents.runtime.store import RunStore

_COUNTERS = {
    "input_tokens": (),
    "output_tokens": (),
    "cached_tokens": ("input_token_details", "cache_read"),
    "cache_creation_tokens": ("input_token_details", "cache_creation"),
    "reasoning_tokens": ("output_token_details", "reasoning"),
}
_MILLION = Decimal(1_000_000)


def parse_rates(table):
    rates = {}
    for model, spec in table["models"].items():
        rates[model] = {key: Decimal(str(value)) for key, value in spec.items()}
        if not {"input", "output"} <= rates[model].keys() or any(
            not value.is_finite() or value < 0 for value in rates[model].values()
        ):
            raise ValueError(f"Invalid per-million-token rates for {model}")
    return rates


def subtotal(values):
    known = [value for value in values if value is not None]
    return {"priced_attempts": len(known), "known_subtotal": str(sum(known)) if known else None}


def summarize(checkpoint, table):
    rates = parse_rates(table)
    saved_usage = checkpoint.get("insight.model_usage", {})
    attempts, standard_costs, adjusted_costs = [], [], []
    for record in checkpoint["records"]:
        logical = record["logical_call_id"]
        if (not record["dispatched_at"] or not logical.startswith("insight.")
                or logical.startswith(("insight.jev_verify.", "insight.search."))):
            continue
        phase = logical.removeprefix("insight.")
        stage = checkpoint.get(logical + ".structured", {})
        reported = saved_usage.get(phase, {})
        usage = {}
        for key, legacy in _COUNTERS.items():
            value = record.get(key)
            if value is None:
                value = reported.get(key)
            if value is None and legacy:
                value = (reported.get(legacy[0]) or {}).get(legacy[1])
            usage[key] = value if type(value) is int and value >= 0 else None
        inp, out = usage["input_tokens"], usage["output_tokens"]
        read, write = usage["cached_tokens"], usage["cache_creation_tokens"]
        model_rates = rates.get(f'{stage.get("provider")}/{stage.get("model")}')
        standard = adjusted = None
        if model_rates and inp is not None and out is not None:
            standard = (inp * model_rates["input"] + out * model_rates["output"]) / _MILLION
            if (read is not None and write is not None and read + write <= inp
                    and {"cache_read", "cache_creation"} <= model_rates.keys()):
                # Only for rate scenarios where cache reads and writes are disjoint subsets of input.
                adjusted = ((inp - read - write) * model_rates["input"] + read * model_rates["cache_read"]
                            + write * model_rates["cache_creation"] + out * model_rates["output"]) / _MILLION
        standard_costs.append(standard)
        adjusted_costs.append(adjusted)
        attempts.append({
            "stage": phase, "attempt_id": record["attempt_id"], "outcome": record["outcome"],
            "provider": stage.get("provider"), "model": stage.get("model"), **usage,
            "standard_price_reference": str(standard) if standard is not None else None,
            "cache_adjusted_estimate": str(adjusted) if adjusted is not None else None,
        })
    measured_cache = [
        (row["cached_tokens"], row["input_tokens"]) for row in attempts
        if row["cached_tokens"] is not None and row["input_tokens"] is not None
        and row["cached_tokens"] <= row["input_tokens"]
    ]
    cached = sum(hit for hit, _ in measured_cache)
    cache_input = sum(total for _, total in measured_cache)
    usage_totals = {}
    for key in _COUNTERS:
        values = [row[key] for row in attempts if row[key] is not None]
        usage_totals[key] = {"known_attempts": len(values), "known_tokens": sum(values) if values else None}
    return {
        "run_id": checkpoint["run_id"], "rate_table": table, "dispatched_insight_attempts": len(attempts),
        "usage": usage_totals,
        "cache_hit_rate": {"measured_attempts": len(measured_cache),
                           "input_tokens": cache_input if measured_cache else None,
                           "cached_tokens": cached if measured_cache else None,
                           "share": cached / cache_input if cache_input else None},
        "standard_price_reference": subtotal(standard_costs), "cache_adjusted_estimate": subtotal(adjusted_costs),
        "attempts": attempts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--rates", type=Path, required=True, help="Explicit scenario, not current provider pricing")
    parser.add_argument("run_id")
    args = parser.parse_args()
    if not args.runs_root.is_dir():
        parser.error("--runs-root must be an existing CLI or Web run store")
    checkpoint = load_checkpoint(RunStore(args.runs_root), args.run_id)
    if checkpoint is None:
        parser.error("No committed research checkpoint for this run")
    print(json.dumps(summarize(checkpoint, json.loads(args.rates.read_text(encoding="utf-8"))),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
