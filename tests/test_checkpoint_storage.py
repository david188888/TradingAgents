import json
from dataclasses import asdict

import pytest

from tests.v9_fixtures import journal_setup
from tradingagents.execution.budget import AttemptOutcome, BudgetBucket
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity
from tradingagents.observability.events import RunEventDraft
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.research_checkpoint import (
    CHECKPOINT_BLOB_KIND,
    CHECKPOINT_KIND,
    ResearchCheckpointConflict,
    ResearchJournal,
    load_checkpoint,
)
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore


def test_index_deduplicates_without_reencoding_on_budget_changes(tmp_path, monkeypatch):
    observer, journal, _ = journal_setup(tmp_path)
    payload = {"body": "财报正文" * 12_000, "api_key": "not-a-real-key"}
    journal.put("native_seed", payload)
    seed_sequence = journal.last_event.sequence
    journal.put("insight.report", payload)
    journal.ledger.record_result("probe.saved", {"report": payload})
    journal.put("stage_marker", "before")
    run_dir = tmp_path / observer.run_id
    blobs = run_dir / CHECKPOINT_BLOB_KIND
    assert len(list(blobs.iterdir())) == 2
    assert all(b"not-a-real-key" not in f.read_bytes() for f in blobs.iterdir())

    def unexpected_encoding(*_args):
        pytest.fail("unchanged large fields must not be serialized again")

    monkeypatch.setattr(journal, "_store_blob", unexpected_encoding)
    for i in range(8):
        attempt = journal.ledger.reserve_or_raise(BudgetBucket.DATA_HTTP_ATTEMPTS, stage="probe", logical_call_id=f"call.{i}")
        journal.ledger.mark_dispatched(attempt)
        journal.ledger.settle(attempt, ok=True)
    disk = [f.stat().st_size for f in (run_dir / CHECKPOINT_KIND).glob("*.json")]
    assert max(disk) < 10_000
    assert sum(disk) < len(payload["body"].encode())
    refs = json.loads(observer.store.read_artifact(observer.run_id, journal.last_event.payload["artifact_id"]))
    assert refs["version"] == 2
    assert refs["blobs"]["native_seed"] == refs["blobs"]["insight.report"]
    assert refs["state"]["native_seed"] is None
    read = load_checkpoint(observer.store, observer.run_id)
    assert read["version"] == 1
    assert read["native_seed"] == {**payload, "api_key": "[REDACTED]"}
    assert read["insight.report"] == read["native_seed"]
    assert read["insight.report"] is not read["native_seed"]
    assert len(read["records"]) == 8
    earlier = load_checkpoint(observer.store, observer.run_id, through=seed_sequence)
    assert earlier["native_seed"] == read["native_seed"]
    assert "insight.report" not in earlier and earlier["records"] == []
    assert all(e.payload.get("kind") != CHECKPOINT_BLOB_KIND for e in observer.store.read_events(observer.run_id))


def test_catalog_growth_keeps_previous_object_and_rejects_in_place_edits(tmp_path, monkeypatch):
    observer, journal, _ = journal_setup(tmp_path)
    old = {"sources": [{"body": "A" * 5000}]}
    field = "insight.catalog_history"
    journal.put(field, {"first": old})
    before = journal.last_event.sequence
    with pytest.raises(TypeError):
        journal.state[field]["first"]["sources"][0]["body"] = "untracked edit"
    with pytest.raises(TypeError):
        journal.state[field]["first"]["sources"].append({})
    with pytest.raises(TypeError):
        journal.state[field] = {}

    encode, written = journal._store_blob, []

    def track(key, item):
        written.append(key)
        return encode(key, item)

    monkeypatch.setattr(journal, "_store_blob", track)
    second = {"sources": [{"body": "B" * 5000}]}
    journal.put(field, {"first": old, "second": second})
    assert written == ["second"]
    assert load_checkpoint(observer.store, observer.run_id, through=before)[field] == {"first": old}
    assert load_checkpoint(observer.store, observer.run_id)[field] == {"first": old, "second": second}
    journal.put(field, {"first": second})
    assert written == ["second", "first"]
    assert load_checkpoint(observer.store, observer.run_id)[field] == {"first": second}


def test_reopen_recovers_budget_and_fails_if_required_object_is_missing(tmp_path):
    observer, journal, _ = journal_setup(tmp_path)
    payload = {"body": "evidence" * 1000}
    journal.ledger.record_result("probe.saved", payload)
    ledger = journal.ledger
    sent = ledger.reserve_or_raise(BudgetBucket.DATA_HTTP_ATTEMPTS, stage="probe", logical_call_id="sent")
    ledger.mark_dispatched(sent)
    ledger.reserve_or_raise(BudgetBucket.DATA_HTTP_ATTEMPTS, stage="probe", logical_call_id="held")
    fresh = RunStore(tmp_path)
    resume_observer = DurableRunObserver(fresh, observer.run_id, development_assertions=False)
    resumed = ResearchJournal(resume_observer, journal.state["identity"], require_existing=True)
    assert [r.outcome for r in resumed.ledger.records()] == [AttemptOutcome.UNKNOWN, AttemptOutcome.RELEASED]
    assert resumed.ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 1
    assert resumed.ledger.cached_result("probe.saved") == payload
    blob, = (tmp_path / observer.run_id / CHECKPOINT_BLOB_KIND).glob("*.json")
    blob.unlink()
    with pytest.raises(ResearchCheckpointConflict):
        load_checkpoint(fresh, observer.run_id)
    with pytest.raises(ResearchCheckpointConflict):
        ResearchJournal(resume_observer, journal.state["identity"], require_existing=True)


def test_legacy_inline_checkpoint_stays_inline_on_resume(tmp_path):
    request = AnalysisRequest("002130.SZ", "2026-10-28")
    identity = native_identity(request)
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date)
    store.create_run(snapshot)
    run_id = snapshot.run_id
    observer = DurableRunObserver(store, run_id, development_assertions=False)
    payload = {"body": "legacy" * 1000}
    old_state = {"version": 1, "run_id": run_id, "identity": identity, "records": [], "results": {},
                 "stages": {}, "native_seed": payload}
    old = store.store_artifact(run_id, kind=CHECKPOINT_KIND, value=old_state)
    event = observer.emit(RunEventDraft(run_id, "artifact.written", asdict(old), status="committed"))
    original = store.read_artifact(run_id, old.artifact_id)
    assert load_checkpoint(store, run_id, through=event.sequence) == json.loads(original)
    resumed = ResearchJournal(observer, identity, require_existing=True)
    resumed.put("native_seed", {"body": "revised" * 1000})
    current = json.loads(store.read_artifact(run_id, resumed.last_event.payload["artifact_id"]))
    assert current["version"] == 1 and current["native_seed"] != payload
    assert not (tmp_path / run_id / CHECKPOINT_BLOB_KIND).exists()
    assert store.read_artifact(run_id, old.artifact_id) == original
