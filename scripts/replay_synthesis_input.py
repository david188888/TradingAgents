"""Reconstruct a V7 synthesis input in memory, stopping before model dispatch.

Run with ``python -m scripts.replay_synthesis_input --run-id RUN_ID``.
Only hashes leave the replay; no prompt/source/response is exported.
"""

from __future__ import annotations

import argparse
import json
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.eval_benchmark import DIGEST, RUN_ID, MeasurementUnavailable, _artifact, _events
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution import verification_executor
from tradingagents.graph import native_research as kernel
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal, DurableBudgetLedger


class _Captured(Exception):
    pass


class _DispatchBlocked(BaseException):
    """Escape the kernel's ordinary failed-proposal catch without a request."""


class _MemoryJournal(CatalystJournal):
    def __init__(self, state):
        self.state = deepcopy(state)
        # Bypass only the terminal cache in this private copy. Every earlier
        # cached proposal, receipt and context binding is still validated.
        self.state["results"].pop("native.output", None)
        self.lock = threading.RLock()
        self.failed = False
        self.observer = SimpleNamespace(run_id=state["run_id"])
        self.ledger = DurableBudgetLedger(self)

    def persist(self):
        # No store or observer is constructed. All frontier updates are local.
        pass


def capture_contexts(state: dict) -> dict:
    """Private in-memory inputs for offline profilers; never dispatch missing work."""
    if state.get("identity", {}).get("workflow_version") != "evidence-production-v7":
        raise MeasurementUnavailable("unsupported_replay_workflow")
    captured = {}
    original = kernel._call

    def capture(stage, context, schema, **kwargs):
        with kwargs["ledger"].journal.lock:
            captured[stage] = deepcopy(context)
        if stage == "synthesis":
            raise _Captured()
        return original(stage, context, schema, **kwargs)

    def no_model(*args, **kwargs):
        raise _DispatchBlocked()

    try:
        journal = _MemoryJournal(state)
        seed = ResearchRecordV1.model_validate(state["native_seed"])
        # A process-local patch is intentional: this is a standalone offline
        # command, never a component called by the live Web server.
        with (patch.object(kernel, "_call", capture),
              patch.object(verification_executor, "evaluate_condition", no_model)):
            kernel.run_native_research(seed, caller=no_model, ledger=journal.ledger,
                                       scoped=True, valuation=True, minimum=True,
                                       independent=True, unified=True)
    except _Captured:
        return captured
    except _DispatchBlocked:
        raise MeasurementUnavailable("replay_requires_uncached_stage") from None
    except Exception:
        raise MeasurementUnavailable("reconstruction_failed") from None
    raise MeasurementUnavailable("synthesis_input_not_reached")


def reconstruct(state: dict) -> dict:
    if state.get("identity", {}).get("workflow_version") != "evidence-production-v7":
        raise MeasurementUnavailable("unsupported_replay_workflow")
    expected = state.get("native.synthesis.input", {}).get("sha256")
    if not isinstance(expected, str) or not DIGEST.fullmatch(expected):
        raise MeasurementUnavailable("synthesis_input_hash_missing")
    contexts = capture_contexts(state)
    actual = canonical_sha256(contexts["synthesis"])
    return {"run_id": state["run_id"], "saved_sha256": expected,
            "reconstructed_sha256": actual, "matches": expected == actual}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path.home() / ".tradingagents/web/runs")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        if not RUN_ID.fullmatch(args.run_id):
            raise MeasurementUnavailable("invalid_run_id")
        directory = args.runs_root / args.run_id
        if directory.is_symlink():
            raise MeasurementUnavailable("invalid_run_directory")
        state, _ = _artifact(directory, _events(directory, args.run_id), "catalyst-checkpoint")
        if state is None or state.get("run_id") != args.run_id:
            raise MeasurementUnavailable("checkpoint_identity_mismatch")
        result = reconstruct(state)
    except MeasurementUnavailable as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
