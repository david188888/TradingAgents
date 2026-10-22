"""Offline benchmark accounting must not inflate success or hide missing usage."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.eval_benchmark import MeasurementUnavailable, evaluate, measure_run

RUN = "run_20261018T010000000000Z_ab123456"


def saved_run(root, *, run_id=RUN, status="specialist_summary", model="gpt-6-luna", sections=None):
    directory = root / run_id
    directory.mkdir()
    snapshot = {"run_id": run_id, "ticker": "300750.SZ", "analysis_date": "2026-10-17",
                "status": "completed", "llm_provider": "chatgpt", "quick_think_llm": model,
                "deep_think_llm": model, "created_at": "2026-10-18T01:00:00Z",
                "completed_at": "2026-10-18T01:05:00Z"}
    (directory / "run.json").write_text(json.dumps(snapshot))
    checkpoint = {
        "run_id": run_id, "identity": {"workflow_version": "evidence-production-v7"},
        "results": {},
        "records": [
            {"bucket": "main_analysis", "logical_call_id": "native.operating_quality", "dispatched_at": "t"},
            {"bucket": "main_analysis", "logical_call_id": "native.synthesis", "dispatched_at": "t"},
            {"bucket": "structured_repair", "logical_call_id": "native.synthesis.repair", "dispatched_at": "t"},
            {"bucket": "network_retry", "logical_call_id": "native.synthesis.retry", "dispatched_at": None},
            {"bucket": "data_http_attempts", "logical_call_id": "http", "dispatched_at": "t"},
        ],
        "native.model_usage": {"synthesis": {"input_tokens": 120, "output_tokens": 10},
                               "synthesis.repair": {"input_tokens": 130, "output_tokens": 20}},
        "native.model_diagnostics": {"synthesis.main": {"category": "reference_validation",
                                                       "detail_code": "dimension_claim_reference",
                                                       "response": "PRIVATE_RESPONSE"}},
    }
    record = {
        "run_id": run_id, "ticker": snapshot["ticker"], "analysis_date": snapshot["analysis_date"],
        "assessment": {"report_status": status, "investment_stance": None},
        "claims": [{"claim_id": "f1", "kind": "fact"}, {"claim_id": "f2", "kind": "fact"},
                   {"claim_id": "i1", "kind": "inference", "supporting_fact_ids": ["f1"]}],
        "hypotheses": [{"claim_id": "i1"}], "metrics": [], "challenges": [],
        "verifications": [{"status": "unavailable"}, {"status": "contradicts"}],
        "evidence_checks": {"checks": [{"status": "unavailable"}]},
    }
    if sections:
        record["assessment"]["synthesis_sections"] = {"policy": "synthesis-sections-v1", "sections": sections}
    events = []
    for kind, value in (("catalyst-checkpoint", checkpoint), ("research-record-v1", record)):
        raw = json.dumps(value).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (directory / kind).mkdir()
        (directory / kind / (digest + ".json")).write_bytes(raw)
        payload = {"kind": kind, "artifact_id": kind + ":" + digest, "content_sha256": digest}
        if kind == "research-record-v1":
            payload.update(public_contract=kind, committed_sequence=1)
        events.append({"sequence": len(events) + 1, "run_id": run_id, "type": "artifact.written",
                       "status": "committed", "payload": payload})
    (directory / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    return directory


def test_failed_synthesis_missing_usage_and_unavailable_checks_are_distinct(tmp_path):
    directory = saved_run(tmp_path)
    before = {str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
    row = measure_run(directory)
    assert row["synthesis_success"] is False
    assert row["record_available"] is True
    assert row["synthesis_sections_complete"] is None
    assert row["model_attempts"] == 3
    assert row["repair_retry_ratio"] == pytest.approx(1 / 3)
    assert row["measured_input_tokens"] == 250
    assert row["usage_complete"] is False
    assert row["hypothesis_fact_ratio"] == 0.5
    assert row["executed_verification_count"] == 1
    assert row["verification_record_count"] == 2
    assert row["local_evidence_check_count"] == 1
    assert row["created_to_completed_seconds"] == 300
    assert "PRIVATE_RESPONSE" not in json.dumps(row)
    assert {str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("status", ["synthesized", "analysis_unrated"])
def test_delivered_synthesis_does_not_imply_a_formed_stance(tmp_path, status):
    row = measure_run(saved_run(tmp_path, status=status))
    assert row["synthesis_success"] is True
    assert row["stance_formed"] is False


def test_partial_section_delivery_does_not_count_as_all_sections_complete(tmp_path):
    sections = [{"section_id": str(i), "status": "accepted"} for i in range(6)]
    sections.append({"section_id": "overall", "status": "unavailable"})
    row = measure_run(saved_run(tmp_path, status="analysis_unrated", sections=sections))
    assert row["synthesis_success"] is True
    assert row["synthesis_accepted_sections"] == 6
    assert row["synthesis_unavailable_sections"] == 1
    assert row["synthesis_sections_complete"] is False


def test_committed_event_wins_over_unreferenced_artifact_and_mtime(tmp_path):
    directory = saved_run(tmp_path)
    (directory / "research-record-v1" / ("a" * 64 + ".json")).write_text('{"assessment":{"report_status":"synthesized"}}')
    assert measure_run(directory)["synthesis_success"] is False


def test_corruption_is_reported_without_falling_back_to_older_data(tmp_path):
    directory = saved_run(tmp_path)
    next((directory / "research-record-v1").glob("*.json")).write_text('{"private":"SECRET"}')
    report = evaluate(tmp_path)
    assert report["runs"] == []
    assert report["errors"] == [{"run_id": RUN, "reason": "artifact_hash_mismatch"}]
    assert "SECRET" not in json.dumps(report)


def test_rejects_incomplete_events_and_path_traversal(tmp_path):
    directory = saved_run(tmp_path)
    events = directory / "events.jsonl"
    events.write_text(events.read_text().rstrip("\n"))
    assert evaluate(tmp_path)["errors"][0]["reason"] == "incomplete_event_log"
    with pytest.raises(MeasurementUnavailable, match="invalid_run_id"):
        evaluate(tmp_path, run_ids=["../outside"])


def test_model_cohorts_are_separate_and_missing_root_is_not_created(tmp_path):
    saved_run(tmp_path, status="synthesized")
    saved_run(tmp_path, run_id=RUN + "b", model="gpt-6.1-sol")
    report = evaluate(tmp_path)
    assert len(report["cohorts"]) == 2
    assert {row["synthesis_success_rate"] for row in report["cohorts"]} == {0, 1}
    absent = tmp_path / "absent"
    with pytest.raises(MeasurementUnavailable, match="runs_root_missing"):
        evaluate(absent)
    assert not absent.exists()


def test_evaluation_never_uses_write_apis(tmp_path, monkeypatch):
    saved_run(tmp_path)
    original = Path.open

    def read_only(path, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in "wa+x")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", read_only)
    assert evaluate(tmp_path)["errors"] == []
