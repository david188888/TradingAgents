"""Read-only F04 input/usage inventory. Run with python -m scripts.profile_native_inputs.

Only hashes, IDs, counts and sizes leave the profiler, never prompts/source text.
No model/provider request, verification dispatch, run store or migration is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts.eval_benchmark import (
    MODEL_BUCKETS,
    RUN_ID,
    MeasurementUnavailable,
    _artifact,
    _count,
    _events,
)
from scripts.native_input_inventory import (
    composition,
    digest,
    inventory,
    inventory_summary,
    repetitions,
    size,
)
from scripts.replay_synthesis_input import _MemoryJournal, capture_contexts
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.native_model import NativeModelCaller

PROFILE_VERSION = "native-input-profile-v1"


def prompt_parts(prompt):
    """Decode exact prompt spans, respecting markers embedded in untrusted JSON."""
    prefix, marker, rest = prompt.partition("Schema:\n")
    if not marker:
        raise ValueError("prompt_layout_unknown")
    decoder = json.JSONDecoder()
    schema, end = decoder.raw_decode(rest)
    separator = "\nSaved research context:\n"
    if not rest[end:].startswith(separator):
        raise ValueError("prompt_layout_unknown")
    tail = rest[end + len(separator):]
    context, stop = decoder.raw_decode(tail)
    parts = {"instructions": prefix + marker, "schema": rest[:end],
             "context_separator": separator, "context": tail[:stop], "guidance": tail[stop:]}
    return {"sha256": hashlib.sha256(prompt.encode()).hexdigest(), **size(prompt),
            "parts": {key: size(text) for key, text in parts.items()}}, schema, context


def usage_rows(state):
    """One row per dispatched request, plus unmatched saved usage; never add both."""
    usage = state.get("native.model_usage", {})
    attempts = [r for r in state.get("records", [])
                if r.get("bucket") in MODEL_BUCKETS and r.get("dispatched_at") is not None]
    keys = [r["logical_call_id"].removeprefix("native.") for r in attempts]
    if len(keys) != len(set(keys)):
        raise MeasurementUnavailable("duplicate_request_identity")
    rows = []
    for key in sorted(set(keys) | usage.keys()):
        record = next((r for r in attempts if r["logical_call_id"] == "native." + key), None)
        value = usage.get(key, {})
        stage, _, phase = key.partition(".")
        rows.append({"request_key": key, "stage": stage,
            "phase": "repair" if phase.startswith("repair") else "main",
            "retry": "retry" in phase, "ledger_dispatched": record is not None,
            "sdk_main_dispatch_marker": state.get("native.model." + stage + ".dispatched") is True,
            "bucket": record["bucket"] if record else None,
            "input_tokens": _count(value.get("input_tokens")),
            "output_tokens": _count(value.get("output_tokens"))})
    return rows


def usage_summary(rows):
    inputs = [r["input_tokens"] for r in rows if r["input_tokens"] is not None]
    outputs = [r["output_tokens"] for r in rows if r["output_tokens"] is not None]
    unknown_inputs = sum(r["ledger_dispatched"] and r["input_tokens"] is None for r in rows)
    unknown_outputs = sum(r["ledger_dispatched"] and r["output_tokens"] is None for r in rows)
    unmatched = sum(not r["ledger_dispatched"] for r in rows)
    dispatched = sum(r["ledger_dispatched"] for r in rows)
    return {"dispatched_ledger_attempts": dispatched, "unmatched_usage_entries": unmatched,
        "unknown_input_attempts": unknown_inputs, "unknown_output_attempts": unknown_outputs,
        "measured_input_tokens": sum(inputs) if inputs else None,
        "measured_output_tokens": sum(outputs) if outputs else None,
        "usage_complete": bool(dispatched) and not (unknown_inputs or unknown_outputs or unmatched)}


def profile_state(state, *, include_inventory=False):
    try:
        contexts = capture_contexts(state)
        journal = _MemoryJournal(state)
        journal.last_event = SimpleNamespace(sequence=0)
        config = state["identity"].get("config", {})
        # Construction only validates config/identity and observes the private
        # in-memory ledger. _prompt/_repair_prompt never create an SDK client.
        caller = NativeModelCaller(effective_config=config, run_id=state["run_id"],
            ledger=journal.ledger, cancelled=lambda: False, deadline=lambda: 0)
        stages = []
        for stage, context in sorted(contexts.items()):
            actual = canonical_sha256(context)
            if actual != state.get("native." + stage + ".input", {}).get("sha256"):
                raise MeasurementUnavailable("kernel_input_hash_mismatch")
            entry = {"stage": stage, "kernel_context_sha256": actual,
                "kernel_context": composition(context), "prompts": {}}
            main = caller._prompt(stage, context)
            for phase in ("main", "repair"):
                key = "native.prompt." + stage + (".repair" if phase == "repair" else "")
                saved = state.get(key)
                if saved is None:
                    entry["prompts"][phase] = {"availability": "not_recorded"}
                    continue
                prompt = main if phase == "main" else caller._repair_prompt(stage, main, context)
                info, schema, model_context = prompt_parts(prompt)
                if info["sha256"] != saved:
                    entry["prompts"][phase] = {"availability": "hash_mismatch",
                        "saved_sha256": saved, "reconstructed_sha256": info["sha256"]}
                    continue
                manifest = inventory({"schema": schema, "context": model_context})
                entry["prompts"][phase] = {"availability": "hash_verified", **info,
                    "model_context": composition(model_context), "repetition": repetitions(model_context),
                    "required_evidence": inventory_summary(manifest),
                    **({"inventory": manifest} if include_inventory else {})}
            stages.append(entry)
        rows = usage_rows(state)
        by_stage = {s["stage"]: s for s in stages}
        for row in rows:
            prompt = by_stage.get(row["stage"], {}).get("prompts", {}).get(row["phase"], {})
            row["prompt_availability"] = prompt.get("availability", "context_not_reconstructed")
            row["prompt_sha256"] = prompt.get("sha256")
        for entry in stages:
            entry["usage"] = usage_summary([r for r in rows if r["stage"] == entry["stage"]])
            for phase, prompt in entry["prompts"].items():
                prompt["dispatched_ledger_attempts"] = sum(r["ledger_dispatched"] and r["stage"] == entry["stage"]
                    and r["phase"] == phase for r in rows)
        return {"schema_version": PROFILE_VERSION, "run_id": state["run_id"],
            "checkpoint_content_sha256": digest(state), "digest_encoding": "sorted_compact_utf8_json",
            "identity": {k: v for k, v in state["identity"].items()
                if k.endswith("policy") or k in {"workflow_version", "ticker", "cutoff", "mode"}},
            "models": {k: config.get(k) for k in ("llm_provider", "quick_think_llm", "deep_think_llm")},
            "measurement": "reconstructed_kernel_and_hash_verified_prompt_sizes_not_tokens",
            "attempt_count_basis": "dispatched_ledger_entries_not_proof_of_sdk_delivery_or_billing",
            "stages": stages, "requests": rows,
            "usage": usage_summary(rows),
            "semantic_evidence_selection": "not_assessed",
            "budget_policy_changed": False, "production_input_changed": False}
    except MeasurementUnavailable:
        raise
    except Exception:
        raise MeasurementUnavailable("input_profile_unavailable") from None


def profile_run(root, run_id, *, include_inventory=False):
    if not RUN_ID.fullmatch(run_id) or (root / run_id).is_symlink():
        raise MeasurementUnavailable("invalid_run_directory")
    directory = root / run_id
    state, _ = _artifact(directory, _events(directory, run_id), "catalyst-checkpoint")
    if state is None or state.get("run_id") != run_id:
        raise MeasurementUnavailable("checkpoint_identity_mismatch")
    return profile_state(state, include_inventory=include_inventory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path.home() / ".tradingagents/web/runs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--include-inventory", action="store_true")
    args = parser.parse_args()
    try:
        result = profile_run(args.runs_root, args.run_id, include_inventory=args.include_inventory)
    except MeasurementUnavailable as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if any(r["ledger_dispatched"] and r["prompt_availability"] != "hash_verified"
                    for r in result["requests"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
