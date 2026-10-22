"""Compare an offline lossless metadata view with hash-verified saved prompts.

Run with python -m scripts.compare_native_prompt_views --run-id RUN_ID.
No model/provider request or user-data write. Output contains no prompt text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts.eval_benchmark import DIGEST, RUN_ID, MeasurementUnavailable, _artifact, _events
from scripts.native_input_inventory import compare_inventory, digest, encoded, inventory, size
from scripts.profile_native_inputs import prompt_parts, usage_rows, usage_summary
from scripts.replay_synthesis_input import _MemoryJournal, capture_contexts
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.native_model import NativeModelCaller
from tradingagents.execution.native_prompt_view import (
    VIEW_GUIDANCE,
    VIEW_POLICY,
    PromptViewError,
    encode_context,
    verify_roundtrip,
)

COMPARISON_VERSION = "native-prompt-view-comparison-v1"


def _prompt_size(prompt):
    return {"sha256": hashlib.sha256(prompt.encode()).hexdigest(), **size(prompt)}


def compare_prompt(prompt, expected_sha256):
    """Measure full prompts, counting marker, aliases, newline and guidance."""
    original = _prompt_size(prompt)
    if not isinstance(expected_sha256, str) or not DIGEST.fullmatch(expected_sha256):
        return {"availability": "hash_invalid", "decision": "error", "reason": "prompt_hash_invalid",
                "reconstructed_sha256": original["sha256"]}
    if original["sha256"] != expected_sha256:
        return {"availability": "hash_mismatch", "decision": "error", "reason": "prompt_hash_mismatch",
                "saved_sha256": expected_sha256, "reconstructed_sha256": original["sha256"]}
    row = {"availability": "hash_verified", "baseline": original, "candidate_input_tokens": None}
    try:
        info, schema, context = prompt_parts(prompt)
        result = encode_context(context)
        if result.status == "identity_noop":
            row.update(decision="identity_noop", reason=result.reason, effective=original,
                       candidate=None, saved_utf8_bytes=0)
            return row
        restored = verify_roundtrip(context, result.context)
        retention = compare_inventory(inventory({"schema": schema, "context": context}),
                                      inventory({"schema": schema, "context": restored}))
        # Character spans came from structured raw_decode, never source markers.
        start = sum(info["parts"][key]["characters"] for key in
                    ("instructions", "schema", "context_separator"))
        stop = start + info["parts"]["context"]["characters"]
        candidate_prompt = prompt[:start] + encoded(result.context) + prompt[stop:] + "\n" + VIEW_GUIDANCE
        # Reparse the complete candidate as a second boundary/schema check.
        _, candidate_schema, candidate_context = prompt_parts(candidate_prompt)
        if encoded(candidate_schema) != encoded(schema):
            raise PromptViewError("schema_changed")
        verify_roundtrip(context, candidate_context)
        candidate = _prompt_size(candidate_prompt)
        adopted = candidate["utf8_bytes"] < original["utf8_bytes"]
        effective = candidate if adopted else original
        row.update(decision="packed" if adopted else "identity_noop",
            reason=None if adopted else "nonbeneficial", candidate=candidate, effective=effective,
            saved_utf8_bytes=original["utf8_bytes"] - effective["utf8_bytes"],
            metadata_count=len(context["numeric_meta"]), roundtrip_equal=True,
            baseline_context_sha256=digest(context), candidate_context_sha256=digest(result.context),
            restored_context_sha256=digest(restored), required_evidence=retention)
    except PromptViewError as exc:
        row.update(decision="error", reason=exc.code)
    except (ValueError, TypeError, KeyError):
        row.update(decision="error", reason="prompt_layout_invalid")
    return row


def _totals(prompts, *, dispatched_only=False):
    selected = [(r, r["dispatched_ledger_attempts"] if dispatched_only else 1) for r in prompts]
    selected = [(r, n) for r, n in selected if n]
    good = [(r, n) for r, n in selected if r["decision"] != "error"]
    baseline = sum(r["baseline"]["utf8_bytes"] * n for r, n in good)
    effective = sum(r["effective"]["utf8_bytes"] * n for r, n in good)
    return {"sample_count": sum(n for _, n in selected), "compared_count": sum(n for _, n in good),
        "failed_count": sum(n for r, n in selected if r["decision"] == "error"),
        "adopted_count": sum(n for r, n in good if r["decision"] == "packed"),
        "compared_baseline_utf8_bytes": baseline, "compared_effective_utf8_bytes": effective,
        "saved_utf8_bytes": baseline - effective,
        "saved_ratio": (baseline - effective) / baseline if baseline else None}


def compare_state(state):
    """Rebuild privately; absent work cannot dispatch or create stores/clients."""
    try:
        contexts = capture_contexts(state)
        journal = _MemoryJournal(state)
        journal.last_event = SimpleNamespace(sequence=0)
        caller = NativeModelCaller(effective_config=state["identity"].get("config", {}),
            run_id=state["run_id"], ledger=journal.ledger, cancelled=lambda: False, deadline=lambda: 0)
        requests = usage_rows(state)
        prompts = []
        for stage, context in sorted(contexts.items()):
            if canonical_sha256(context) != state.get("native." + stage + ".input", {}).get("sha256"):
                raise MeasurementUnavailable("kernel_input_hash_mismatch")
            main = caller._prompt(stage, context)
            for phase in ("main", "repair"):
                key = "native.prompt." + stage + (".repair" if phase == "repair" else "")
                attempts = sum(r["ledger_dispatched"] and r["stage"] == stage and r["phase"] == phase
                               for r in requests)
                saved = state.get(key)
                if phase == "repair" and saved is None and not attempts:
                    continue
                row = {"stage": stage, "phase": phase, "dispatched_ledger_attempts": attempts,
                       "candidate_input_tokens": None}
                if saved is None:
                    row.update(availability="not_recorded", decision="error", reason="prompt_hash_missing")
                else:
                    prompt = main if phase == "main" else caller._repair_prompt(stage, main, context)
                    row.update(compare_prompt(prompt, saved))
                prompts.append(row)
        # Preserve saved phases that reconstruction did not visit, instead of
        # silently reporting a smaller, apparently complete cohort.
        known = {(r["stage"], r["phase"]) for r in prompts}
        saved_pairs = set()
        for key in state:
            if key.startswith("native.prompt."):
                suffix = key.removeprefix("native.prompt.")
                saved_pairs.add((suffix.removesuffix(".repair"), "repair" if suffix.endswith(".repair") else "main"))
        requested_pairs = {(r["stage"], r["phase"]) for r in requests if r["ledger_dispatched"]}
        for pair in sorted(saved_pairs | requested_pairs):
            if pair not in known:
                prompts.append({"stage": pair[0], "phase": pair[1], "availability": "context_not_reconstructed",
                    "decision": "error", "reason": "context_not_reconstructed", "candidate_input_tokens": None,
                    "dispatched_ledger_attempts": sum(r["ledger_dispatched"] and (r["stage"], r["phase"]) == pair
                                                       for r in requests)})
                known.add(pair)
        by_phase = {(r["stage"], r["phase"]): r for r in prompts}
        for request in requests:
            row = by_phase.get((request["stage"], request["phase"]))
            request["comparison"] = row["decision"] if row else "unavailable"
            request["candidate_input_tokens"] = None
        complete = (all(r["decision"] != "error" for r in prompts)
                    and all(r["comparison"] != "unavailable" for r in requests if r["ledger_dispatched"]))
        return {"schema_version": COMPARISON_VERSION, "candidate_policy": VIEW_POLICY,
            "run_id": state["run_id"], "checkpoint_content_sha256": digest(state),
            "comparison_complete": complete, "prompts": prompts, "requests": requests,
            "all_prompt_samples": _totals(prompts), "dispatched_ledger_attempts": _totals(prompts, dispatched_only=True),
            "usage": usage_summary(requests), "candidate_input_tokens": None,
            "measurement": "offline_full_prompt_utf8_bytes_not_tokens_or_model_quality",
            "attempt_count_basis": "dispatched_ledger_entries_not_proof_of_sdk_delivery_or_billing",
            "production_input_changed": False, "budget_policy_changed": False}
    except MeasurementUnavailable:
        raise
    except Exception:
        raise MeasurementUnavailable("prompt_comparison_unavailable") from None


def compare_run(root, run_id):
    if not RUN_ID.fullmatch(run_id) or (root / run_id).is_symlink():
        raise MeasurementUnavailable("invalid_run_directory")
    directory = root / run_id
    state, _ = _artifact(directory, _events(directory, run_id), "catalyst-checkpoint")
    if state is None or state.get("run_id") != run_id:
        raise MeasurementUnavailable("checkpoint_identity_mismatch")
    return compare_state(state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path.home() / ".tradingagents/web/runs")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_run(args.runs_root, args.run_id)
    except MeasurementUnavailable as exc:
        print(json.dumps({"schema_version": COMPARISON_VERSION, "run_id": args.run_id,
                          "comparison_complete": False, "reason": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["comparison_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
