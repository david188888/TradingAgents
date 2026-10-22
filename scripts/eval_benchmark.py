#!/usr/bin/env python3
"""Read saved benchmark runs without models, network calls or run-store writes.

Artifact selection follows committed events and verifies content hashes. This
is a measurement tool, not a replacement for Reader/publication validation.
Missing measurements stay null; uncommitted artifacts never enter the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MODEL_BUCKETS = {"main_analysis", "focus_response", "semantic_preprocess",
                 "structured_repair", "network_retry"}
SUCCESS_STATUSES = {"synthesized", "analysis_unrated"}
RUN_ID = re.compile(r"run_[A-Za-z0-9_]+\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class MeasurementUnavailable(ValueError):
    """Closed reasons only: never print source payloads or exception messages."""


def _object(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise MeasurementUnavailable("unreadable_json") from None
    if not isinstance(value, dict):
        raise MeasurementUnavailable("invalid_object")
    return value


def _events(directory: Path, run_id: str) -> list[dict]:
    try:
        lines = (directory / "events.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
        events = [json.loads(line) for line in lines]
    except (OSError, ValueError):
        raise MeasurementUnavailable("unreadable_event_log") from None
    if any(not line.endswith("\n") for line in lines):
        raise MeasurementUnavailable("incomplete_event_log")
    if any(not isinstance(event, dict) or event.get("sequence") != index
           or event.get("run_id") != run_id for index, event in enumerate(events, 1)):
        raise MeasurementUnavailable("invalid_event_sequence")
    return events


def _artifact(directory: Path, events: list[dict], kind: str) -> tuple[dict | None, int | None]:
    candidates = [event for event in events
                  if event.get("type") == "artifact.written"
                  and event.get("status") == "committed"
                  and event.get("payload", {}).get("kind") == kind
                  and (kind != "research-record-v1" or (
                      event["payload"].get("public_contract") == kind
                      and type(event["payload"].get("committed_sequence")) is int
                      and 0 < event["payload"]["committed_sequence"] < event["sequence"]))]
    if not candidates:
        return None, None
    event = max(candidates, key=lambda item: (
        item["payload"].get("committed_sequence", item["sequence"]), item["sequence"]))
    payload = event["payload"]
    artifact_id = payload.get("artifact_id", "")
    prefix, _, digest = artifact_id.partition(":")
    if prefix != kind or not DIGEST.fullmatch(digest) or payload.get("content_sha256") != digest:
        raise MeasurementUnavailable("invalid_artifact_reference")
    path = directory / kind / (digest + ".json")
    if not path.resolve().is_relative_to(directory.resolve()):
        raise MeasurementUnavailable("artifact_path_escape")
    try:
        raw = path.read_bytes()
    except OSError:
        raise MeasurementUnavailable("unreadable_artifact") from None
    if hashlib.sha256(raw).hexdigest() != digest:
        raise MeasurementUnavailable("artifact_hash_mismatch")
    try:
        value = json.loads(raw)
    except ValueError:
        raise MeasurementUnavailable("unreadable_json") from None
    if not isinstance(value, dict):
        raise MeasurementUnavailable("invalid_object")
    return value, len(raw)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _elapsed(snapshot):
    try:
        # Creation-to-completion includes queue time; never substitute updated_at.
        elapsed = (datetime.fromisoformat(snapshot["completed_at"].replace("Z", "+00:00"))
                   - datetime.fromisoformat(snapshot["created_at"].replace("Z", "+00:00"))).total_seconds()
        return elapsed if elapsed >= 0 else None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def measure_run(directory: Path) -> dict:
    if not RUN_ID.fullmatch(directory.name) or directory.is_symlink():
        raise MeasurementUnavailable("invalid_run_directory")
    snapshot = _object(directory / "run.json")
    if snapshot.get("run_id") != directory.name:
        raise MeasurementUnavailable("run_identity_mismatch")
    events = _events(directory, directory.name)
    checkpoint, _ = _artifact(directory, events, "catalyst-checkpoint")
    record, record_bytes = _artifact(directory, events, "research-record-v1")
    if checkpoint and checkpoint.get("run_id") != directory.name:
        raise MeasurementUnavailable("checkpoint_identity_mismatch")
    if record and any(record.get(key) != snapshot.get(key) for key in ("run_id", "ticker", "analysis_date")):
        raise MeasurementUnavailable("record_identity_mismatch")
    checkpoint = checkpoint or {}
    identity = checkpoint.get("identity", {})
    assessment = (record or {}).get("assessment") or {}
    attempts = [item for item in checkpoint.get("records", [])
                if item.get("bucket") in MODEL_BUCKETS and item.get("dispatched_at") is not None]
    synthesis_attempts = [item for item in attempts
                          if item.get("logical_call_id", "").startswith("native.synthesis")]
    overhead = sum(item["bucket"] in {"structured_repair", "network_retry"} for item in attempts)
    usage = checkpoint.get("native.model_usage", {})
    inputs = [_count(item.get("input_tokens")) for item in usage.values()]
    outputs = [_count(item.get("output_tokens")) for item in usage.values()]
    input_sum = sum(value for value in inputs if value is not None) if inputs else None
    output_sum = sum(value for value in outputs if value is not None) if outputs else None
    # Failed responses can have usage even when the ledger has no usage. Count
    # each saved SDK usage key once; do not add it to ledger token totals.
    synthesis_tokens = [item for key, item in usage.items() if key == "synthesis" or key.startswith("synthesis.")]
    synthesis_total = sum((item.get("input_tokens") or 0) + (item.get("output_tokens") or 0)
                          for item in synthesis_tokens) if synthesis_tokens else None
    total = input_sum + output_sum if input_sum is not None and output_sum is not None else None
    claims = {item["claim_id"]: item for item in (record or {}).get("claims", [])}
    facts = {key for key, item in claims.items() if item.get("kind") == "fact"}
    referenced = {key for hypothesis in (record or {}).get("hypotheses", [])
                  for key in claims.get(hypothesis["claim_id"], {}).get("supporting_fact_ids", [])}
    report_status = assessment.get("report_status")
    synthesis_status = None if not synthesis_attempts else bool(record) and (
        report_status in SUCCESS_STATUSES or (
            report_status is None and "native.synthesis" in checkpoint.get("results", {})))
    expected_usage = {item["logical_call_id"].removeprefix("native.") for item in attempts}
    delivery = assessment.get("synthesis_sections") or {}
    sections = delivery.get("sections") if delivery.get("policy") == "synthesis-sections-v1" else None
    accepted_sections = sum(item.get("status") == "accepted" for item in sections) if sections else None
    unavailable_sections = sum(item.get("status") == "unavailable" for item in sections) if sections else None
    from tradingagents.agents.schemas._research_record import ResearchRecordV1
    from tradingagents.research.challenge_metrics import (
        challenge_admission_counts,
        challenge_metrics,
    )
    try:
        directed = challenge_metrics(ResearchRecordV1.model_validate(record)
            if record and record.get("challenge_check_policy") else None)
        if directed["availability"] == "recorded":
            directed["admission"] = challenge_admission_counts(checkpoint)
    except ValueError:
        raise MeasurementUnavailable("challenge_contract_invalid") from None
    return {
        "run_id": directory.name, "ticker": snapshot.get("ticker"),
        "analysis_date": snapshot.get("analysis_date"), "run_status": snapshot.get("status"),
        "workflow": identity.get("workflow_version"), "provider": snapshot.get("llm_provider"),
        "specialist_model": snapshot.get("quick_think_llm"), "synthesis_model": snapshot.get("deep_think_llm"),
        "record_available": record is not None, "report_status": report_status,
        "synthesis_success": synthesis_status, "stance": assessment.get("investment_stance"),
        "synthesis_accepted_sections": accepted_sections,
        "synthesis_unavailable_sections": unavailable_sections,
        "synthesis_sections_complete": unavailable_sections == 0 if sections else None,
        "stance_formed": assessment.get("investment_stance") in {"favorable", "neutral", "unfavorable"},
        "model_attempts": len(attempts), "repair_retry_attempts": overhead,
        "repair_retry_ratio": _ratio(overhead, len(attempts)),
        "measured_usage_entries": len(usage),
        "usage_complete": bool(attempts) and set(usage) == expected_usage
            and all(value is not None for value in [*inputs, *outputs]),
        "measured_input_tokens": input_sum, "measured_output_tokens": output_sum,
        "synthesis_measured_token_share": _ratio(synthesis_total, total) if synthesis_total is not None else None,
        "created_to_completed_seconds": _elapsed(snapshot),
        "fact_count": len(facts) if record else None,
        "hypothesis_referenced_fact_count": len(facts & referenced) if record else None,
        "hypothesis_fact_ratio": _ratio(len(facts & referenced), len(facts)) if record else None,
        "saved_metric_count": len(record.get("metrics", [])) if record else None,
        "derived_metric_count": None,
        "verification_record_count": len(record.get("verifications", [])) if record else None,
        "executed_verification_count": sum(item.get("status") in {"supports", "contradicts", "inconclusive"}
                                            for item in record.get("verifications", [])) if record else None,
        "local_evidence_check_count": len((record.get("evidence_checks") or {}).get("checks", [])) if record else None,
        "challenge_count": len(record.get("challenges", [])) if record else None,
        "record_bytes": record_bytes,
        "synthesis_diagnostics": {phase: {key: value for key, value in diagnostic.items()
                                          if key in {"category", "detail_code"}}
                                  for phase, diagnostic in checkpoint.get("native.model_diagnostics", {}).items()
                                  if phase in {"synthesis.main", "synthesis.repair"}},
        "hypothesis_rubric_score": None, "challenge_test_request_ratio": None,
        "hypothesis_directed_checks": directed,
    }


def evaluate(root: Path, *, run_ids=(), workflow=None) -> dict:
    if not root.is_dir():
        raise MeasurementUnavailable("runs_root_missing")
    rows, errors = [], []
    for name in sorted(set(run_ids) if run_ids else (item.name for item in root.iterdir() if RUN_ID.fullmatch(item.name))):
        if not RUN_ID.fullmatch(name):
            raise MeasurementUnavailable("invalid_run_id")
        try:
            row = measure_run(root / name)
        except (MeasurementUnavailable, KeyError, TypeError, AttributeError) as exc:
            errors.append({"run_id": name, "reason": str(exc) if isinstance(exc, MeasurementUnavailable) else "invalid_saved_shape"})
            continue
        if workflow is None or row["workflow"] == workflow:
            rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["workflow"], row["provider"], row["specialist_model"], row["synthesis_model"])].append(row)
    cohorts = []
    for key, members in groups.items():
        attempted = [row for row in members if row["synthesis_success"] is not None]
        cohorts.append({"workflow": key[0], "provider": key[1], "specialist_model": key[2],
                        "synthesis_model": key[3], "run_count": len(members),
                        "synthesis_attempted_runs": len(attempted),
                        "synthesis_successes": sum(row["synthesis_success"] for row in attempted),
                        "synthesis_success_rate": _ratio(sum(row["synthesis_success"] for row in attempted), len(attempted))})
    return {"schema_version": "evidence-benchmark-v1", "rubric_version": "hypothesis-quality-v1",
            "validation_scope": "committed_event_and_artifact_integrity_only",
            "runs": rows, "cohorts": cohorts, "errors": errors}


def markdown(report: dict) -> str:
    lines = ["# Saved-run benchmark", "", "Token totals are measured subtotals; missing usage is not zero.",
             "Artifact integrity is checked; this report does not certify publication eligibility or research quality.", "",
             "| Run | Ticker | Workflow | Model | Report | Stance | Synthesis | Input tokens | Usage complete | Repair/retry | Code checks |",
             "| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | ---: |"]
    for row in report["runs"]:
        values = [row[key] for key in ("run_id", "ticker", "workflow", "synthesis_model", "report_status", "stance",
                                       "synthesis_success", "measured_input_tokens", "usage_complete")]
        values += [f'{row["repair_retry_attempts"]}/{row["model_attempts"]}', row["executed_verification_count"]]
        lines.append("| " + " | ".join("unknown" if value is None else str(value).replace("|", "\\|").replace("\n", " ") for value in values) + " |")
    typed = [row for row in report["runs"] if row.get("hypothesis_directed_checks", {}).get("availability") == "recorded"]
    if typed:
        def rate(value):
            if value is None:
                return "unknown"
            if value["ratio"] is None:
                return "not applicable"
            return f'{value["numerator"]}/{value["denominator"]}'
        lines += ["", "## Typed important-challenge checks", "",
            "Accepted-item completeness is not frozen-case coverage; missing annotations remain unknown.", "",
            "| Run | Accepted classification | Frozen coverage | Correct task generation | Executed/generated | Successful/executed | Rejected | Repair-deleted slots |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: |"]
        for row in typed:
            checks = row["hypothesis_directed_checks"]
            deleted = checks.get("admission", {}).get("repair_removed_slots")
            cells = [row["run_id"], *(rate(checks[key]) for key in (
                "accepted_classification_completeness", "classification_coverage", "task_generation_rate",
                "actual_execution_rate", "successful_result_rate")), str(checks["rejected_items"]),
                "unknown" if deleted is None else str(deleted)]
            lines.append("| " + " | ".join(cells) + " |")
    if report["errors"]:
        lines += ["", "Unavailable runs: " + json.dumps(report["errors"], ensure_ascii=False)]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path.home() / ".tradingagents/web/runs")
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--workflow")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    try:
        report = evaluate(args.runs_root, run_ids=args.run_id, workflow=args.workflow)
    except MeasurementUnavailable as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else markdown(report), end="\n")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
