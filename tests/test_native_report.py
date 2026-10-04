"""Saved-record Markdown is deterministic, atomic and independent of models."""

import hashlib

import pytest

from tests.test_native_publication import native_record
from tradingagents.agents.schemas._research_record import (
    RecordClaimV1,
    SourceContentV1,
    SourceEvidenceV1,
    make_evidence_snapshot,
)
from tradingagents.runtime.reports import (
    ReportArtifactWriter,
    ReportPublicationError,
    build_markdown_from_native_record,
)
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore


def setup(tmp_path, mode):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker="600519", analysis_date="2026-09-30")
    store.create_run(snapshot)
    return store, native_record(snapshot.run_id, mode)


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_native_report_three_modes_exact_saved_record_and_idempotent_tree(tmp_path, mode, monkeypatch):
    store, record = setup(tmp_path, mode)
    writer = ReportArtifactWriter(store)
    import tradingagents.runtime.reports as reports
    monkeypatch.setattr(reports, "write_report_tree", lambda *a: pytest.fail("used legacy report writer"))
    state = {"native_research_record": record.model_dump(mode="json")}
    first = writer.publish_final(record.run_id, state, record.ticker)
    second = writer.publish_final(record.run_id, state, record.ticker)
    assert first.complete_report.read_text() == build_markdown_from_native_record(record)
    assert first.artifacts == second.artifacts
    assert first.complete_report.read_text().index("最大疑点与下一步") < first.complete_report.read_text().index("脚本计算与量化背景")
    assert first.complete_report.read_text().index("脚本计算与量化背景") < first.complete_report.read_text().index("事实、假设与未知项")
    assert ("84 个自然日" in first.complete_report.read_text()) == (mode == "catalyst_research")
    assert list((store._run_dir(record.run_id) / "reports").iterdir()) == [first.complete_report]


def test_native_report_conflict_keeps_original_and_checks_identity(tmp_path):
    store, record = setup(tmp_path, "company_research")
    writer = ReportArtifactWriter(store)
    publication = writer.publish_final(record.run_id, {"native_research_record": record.model_dump(mode="json")}, record.ticker)
    original = publication.complete_report.read_bytes()
    changed = record.model_copy(update={"assessment": record.assessment.model_copy(update={"judgement": "不同结论"})})
    with pytest.raises(ReportPublicationError, match="content conflict"):
        writer.publish_final(record.run_id, {"native_research_record": changed.model_dump(mode="json")}, record.ticker)
    with pytest.raises(ReportPublicationError, match="identity mismatch"):
        writer.publish_final(record.run_id, {"native_research_record": record.model_dump(mode="json")}, "000001")
    assert publication.complete_report.read_bytes() == original


def test_native_report_fsync_failure_leaves_no_canonical_tree(tmp_path, monkeypatch):
    store, record = setup(tmp_path, "company_research")
    writer = ReportArtifactWriter(store)
    monkeypatch.setattr(writer, "_fsync_tree", lambda _: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError):
        writer.publish_final(record.run_id, {"native_research_record": record.model_dump(mode="json")}, record.ticker)
    run_dir = store._run_dir(record.run_id)
    assert not (run_dir / "reports").exists()
    assert not list(run_dir.glob(".reports.*.tmp"))


def test_raw_source_excerpt_is_visible_and_inert_in_saved_markdown(tmp_path):
    _, record = setup(tmp_path, "company_research")
    raw = '<script>alert(1)</script> [execute](javascript:alert(1))'
    source = SourceEvidenceV1(evidence_id="e.source", source_name="披露", source_kind="official",
        availability="available", public_url="https://example.com/a(b)",
        content=SourceContentV1(kind="excerpt", text=raw, locator_label="第 8 页 / 经营概况",
            content_sha256=hashlib.sha256(raw.encode()).hexdigest()))
    snapshot = make_evidence_snapshot((source,))
    claim = RecordClaimV1(claim_id="f.source", kind="fact", statement="原文中有明确内容。", evidence_ids=(source.evidence_id,))
    record = record.model_copy(update={"evidence": (source,), "snapshots": (snapshot,), "claims": (claim,),
        "assessment": record.assessment.model_copy(update={"input_snapshot_id": snapshot.snapshot_id, "key_claim_ids": (claim.claim_id,)})})
    markdown = build_markdown_from_native_record(record)
    assert "&lt;script&gt;" in markdown
    assert "<script>" not in markdown
    assert "\\[execute\\]" in markdown
    assert "https://example.com/a%28b%29" in markdown
    assert "第 8 页 / 经营概况" in markdown
