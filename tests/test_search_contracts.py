"""Current evidence revisions retain immutable source and numeric lineage."""
from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from tests.test_insight_protocol import catalog
from tradingagents.agents.schemas._evidence import RecordClaimV1, SourceEvidenceV1
from tradingagents.agents.schemas._evidence_record import EvidenceRecord, make_evidence_snapshot
from tradingagents.agents.schemas._search import EvidenceGapV1, QualifiedFieldV1


def record_payload():
    source = catalog().sources[0]
    return EvidenceRecord(run_id="test-evidence", ticker="600519.SH", analysis_date=date(2026, 10, 28),
        evidence=(source,), snapshots=(make_evidence_snapshot((source,)),), claims=(
            RecordClaimV1(claim_id="fact-1", kind="fact", statement="保存的原始资料。", evidence_ids=(source.evidence_id,)),)).model_dump(mode="json")


def test_eight_snapshots_preserve_source_hash_and_parent():
    payload = record_payload()
    for version in range(1, 8):
        payload["evidence"].append({**payload["evidence"][0], "evidence_id": f"e{version}"})
        snapshot = make_evidence_snapshot(tuple(SourceEvidenceV1.model_validate(e) for e in payload["evidence"]),
            version=version, parent_snapshot_id=payload["snapshots"][-1]["snapshot_id"])
        payload["snapshots"].append(snapshot.model_dump(mode="json"))
    assert len(EvidenceRecord.model_validate(payload).snapshots) == 8
    for field in ("content_sha256", "parent_snapshot_id"):
        tampered = deepcopy(payload)
        tampered["snapshots"][-1][field] = "tampered"
        with pytest.raises(ValidationError):
            EvidenceRecord.model_validate(tampered)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_qualified_field_rejects_nonfinite_values(value):
    with pytest.raises(ValidationError):
        QualifiedFieldV1(ticker="600519.SH", field="revenue", period="2026-06-30", unit="CNY", currency="CNY",
            basis="consolidated_actual", evidence_id="e1", source_content_sha256="a"*64, value=value)


def test_gap_cannot_include_executable_arguments():
    with pytest.raises(ValidationError):
        EvidenceGapV1(gap_id="g", question="何种原文仍然缺失？", capability="financial", role="operating_quality",
            priority="material", cutoff="2026-10-28", evidence_needed="原文", rationale="核对口径", url="https://example.com")
