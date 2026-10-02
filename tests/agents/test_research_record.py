"""Shared contract rejects fabricated verification, loose IDs and numbers."""

import hashlib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas._research_record import (
    ResearchRecordV1,
    SourceContentV1,
    SourceEvidenceV1,
    make_evidence_snapshot,
)
from tradingagents.research.record_assembly import record_from_catalyst, record_from_classic


def native_payload():
    payload = {
        "run_id": "run-record", "ticker": "600519", "mode": "company_research",
        "analysis_date": "2026-09-30", "construction": "native",
        "snapshots": [{"version": 0, "snapshot_id": "v0", "evidence_ids": ["e1"]}],
        "evidence": [{"evidence_id": "e1", "source_name": "fixture", "source_kind": "official",
            "availability": "available", "limitations": ["document_body_not_saved"]}],
        "claims": [
            {"claim_id": "f1", "kind": "fact", "statement": "披露收入上升", "evidence_ids": ["e1"]},
            {"claim_id": "i1", "kind": "inference", "statement": "改善可能延续", "evidence_ids": ["e1"], "supporting_fact_ids": ["f1"]},
        ],
        "hypotheses": [{"hypothesis_id": "h1", "claim_id": "i1", "input_snapshot_id": "v0",
            "origin": "hypothesis_stage", "invalidation_conditions": ["下一期收入回落"]}],
        "challenges": [{"challenge_id": "c1", "target_claim_ids": ["i1"], "statement": "改善是否只来自一次性事项",
            "severity": "critical", "risk_type": "operations", "proposed_test": "核对收入分项"}],
    }
    snapshot = make_evidence_snapshot(tuple(SourceEvidenceV1.model_validate(item) for item in payload["evidence"]))
    payload["snapshots"] = [snapshot.model_dump(mode="json")]
    payload["hypotheses"][0]["input_snapshot_id"] = snapshot.snapshot_id
    return payload


def add_v1(payload):
    v1 = make_evidence_snapshot(tuple(SourceEvidenceV1.model_validate(item) for item in payload["evidence"]),
        version=1, parent_snapshot_id=payload["snapshots"][0]["snapshot_id"])
    payload["snapshots"].append(v1.model_dump(mode="json"))
    return v1.snapshot_id


def test_v0_hypothesis_is_explicitly_not_an_executed_verification():
    record = ResearchRecordV1.model_validate(native_payload())
    assert record.verifications == ()
    assert record.snapshots[0].version == 0


def test_executed_verification_creates_v1_without_replacing_v0():
    payload = native_payload()
    v1_id = add_v1(payload)
    payload["verifications"] = [{"verification_id": "t1", "challenge_id": "c1", "input_snapshot_id": payload["snapshots"][0]["snapshot_id"],
        "output_snapshot_id": v1_id, "method": "source_check", "status": "inconclusive", "executed_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
        "result": "披露未提供所需分项"}]
    record = ResearchRecordV1.model_validate(payload)
    assert len(record.verifications) == 1
    payload["snapshots"][1]["evidence_ids"] = []
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


@pytest.mark.parametrize("defect", ["dangling_evidence", "duplicate_evidence", "inference_support", "hypothesis_snapshot", "unfalsifiable", "fake_v1", "future_source", "private_url"])
def test_contract_integrity_failures(defect):
    payload = native_payload()
    if defect == "dangling_evidence":
        payload["claims"][0]["evidence_ids"] = ["other-run-evidence"]
    elif defect == "duplicate_evidence":
        payload["evidence"].append(payload["evidence"][0])
    elif defect == "inference_support":
        payload["claims"][1]["supporting_fact_ids"] = ["i1"]
    elif defect == "hypothesis_snapshot":
        payload["hypotheses"][0]["input_snapshot_id"] = "v8"
    elif defect == "unfalsifiable":
        payload["hypotheses"][0]["invalidation_conditions"] = []
    elif defect == "fake_v1":
        add_v1(payload)
    elif defect == "future_source":
        payload["evidence"][0]["usable_as_of"] = "2026-10-01T00:00:00+08:00"
    else:
        payload["evidence"][0]["public_url"] = "https://example.com/?api_key=private"
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


@pytest.mark.parametrize("value, availability", [(float("nan"), "available"), (float("inf"), "available"), (42, "unavailable")])
def test_metrics_cannot_publish_nonfinite_or_estimated_unavailable_values(value, availability):
    payload = native_payload()
    payload["metrics"] = [{"metric_id": "risk", "label": "波动率", "availability": availability,
        "value": value, "unit": "return_fraction", "method": "std", "calculation_version": "test-v1",
        "input_evidence_ids": ["e1"], "input_sha256": "a" * 64, "window_start": "2026-09-01",
        "window_end": "2026-09-30", "sample_size": 20, "unavailable_reason": "missing" if availability == "unavailable" else None}]
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


def test_source_content_digest_rejects_silent_edit():
    digest = hashlib.sha256(b"original").hexdigest()
    with pytest.raises(ValidationError, match="digest"):
        SourceContentV1(kind="excerpt", text="edited", locator_label="正文", content_sha256=digest)


def test_new_content_digest_cannot_silently_replace_frozen_snapshot_content():
    payload = native_payload()
    payload["evidence"][0]["content"] = {
        "kind": "excerpt", "text": "changed", "locator_label": "正文",
        "content_sha256": hashlib.sha256(b"changed").hexdigest(),
    }
    with pytest.raises(ValidationError, match="snapshot"):
        ResearchRecordV1.model_validate(payload)


def test_v0_hypothesis_cannot_depend_on_later_verification_evidence():
    payload = native_payload()
    payload["evidence"].append({**payload["evidence"][0], "evidence_id": "new"})
    output = add_v1(payload)
    payload["claims"][0]["evidence_ids"] = ["new"]
    payload["verifications"] = [{"verification_id": "t1", "challenge_id": "c1",
        "input_snapshot_id": payload["snapshots"][0]["snapshot_id"], "output_snapshot_id": output,
        "method": "source_check", "status": "supports", "evidence_ids": ["new"],
        "executed_at": "2026-09-30T00:00:00Z", "result": "new source"}]
    with pytest.raises(ValidationError, match="reference"):
        ResearchRecordV1.model_validate(payload)


def test_saved_price_statistics_become_public_metrics_without_recomputation():
    from tests.test_price_statistics_context import context
    from tradingagents.research.price_statistics import build_price_statistics
    from tradingagents.research.record_assembly import _price_metrics
    bars, provenance = context(30)
    provenance["input_sha256"] = "a" * 64
    payload = {"bars": bars, "provenance": provenance,
        "computed_statistics": build_price_statistics(bars, provenance)}
    metrics = _price_metrics("e1", payload)
    assert len(metrics) == 6
    assert [item.availability for item in metrics] == ["available"] * 5 + ["unavailable"]
    assert metrics[1].value > 0  # A rising sample is not relabelled as a loss.
    assert metrics[1].tail_sample_size == 2
    assert metrics[4].value == pytest.approx(2)
    assert metrics[-1].value is None
    payload["computed_statistics"]["input_sha256"] = "b" * 64
    assert _price_metrics("e1", payload) == ()


@pytest.mark.parametrize("statement", ["income_statement", "balance_sheet", "cash_flow"])
def test_classic_saved_fields_require_matching_bundle_and_exclude_arbitrary_provider_text(statement):
    import json

    from tradingagents.research.record_assembly import _classic_financial_content
    bundle = {"results": [{"statements": [
        {"statement": statement, "status": "ok", "data": "ann_date,revenue,n_income,private_note\n20260830,100,nan,secret-value"},
        {"statement": "secret-name", "status": "ok", "data": "revenue\n100"},
    ]}], "headers": {"authorization": "secret-token"}}
    digest = hashlib.sha256(json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    content = _classic_financial_content(bundle, digest)
    assert content is not None
    assert "100" in content.text and "20260830" in content.text
    assert "secret" not in content.text and "n_income" not in content.text
    assert _classic_financial_content(bundle, "b" * 64) is None


def test_catalyst_disposition_is_not_promoted_into_tool_execution():
    from tests.agents.test_catalyst_research_schema import _case
    case = _case()
    record = record_from_catalyst(case, {})
    assert len(record.challenges) == len(case.challenges)
    assert record.verifications == ()
    assert all(item.origin == "adapted_inference" for item in record.hypotheses)
    assert all(item.content is None for item in record.evidence)


@pytest.mark.parametrize("mode", ["company_research", "holding_review"])
def test_classic_two_modes_share_contract_without_inventing_original_thesis(mode):
    from tests.test_reader_companion import _case
    case = _case("run-record", evidence_artifact_id="evidence-bundle:" + "a" * 64,
        evidence_locator="private-store/path.json", available_ref_id="a" * 64,
        unavailable_artifact_id="evidence-bundle:" + "b" * 64, unavailable_locator="private/path.json", unavailable_ref_id="b" * 64)
    record = record_from_classic(case, mode=mode, analysis_date="2026-08-10")
    assert record.mode == mode
    assert len(record.hypotheses) == 1
    assert record.verifications == ()
    assert "private-store" not in record.model_dump_json()
    assert all(item.content is None for item in record.evidence)
