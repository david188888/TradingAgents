"""Actual-store native publication barriers, replay and failure propagation."""

from datetime import date

import pytest

from tradingagents.agents.schemas._research_assessment import (
    DIMENSIONS_BY_MODE,
    ResearchAssessmentV1,
)
from tradingagents.agents.schemas._research_record import ResearchRecordV1, make_evidence_snapshot
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.execution.native_publication import NativePublicationError, publish_native_record
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal, load_checkpoint
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore


def native_record(run_id, mode="company_research"):
    snapshot = make_evidence_snapshot(())
    return ResearchRecordV1(run_id=run_id, ticker="600519", mode=mode,
        analysis_date=date(2026, 9, 30), construction="native", snapshots=(snapshot,),
        assessment=ResearchAssessmentV1(input_snapshot_id=snapshot.snapshot_id,
            research_question="经营改善是否有充分证据？", judgement="资料不足，需先补证据。",
            dimensions=tuple({"dimension": dimension, "status": "unresolved", "judgement": "缺少合格资料。",
                "limitations": ["required_source_unavailable"]} for dimension in DIMENSIONS_BY_MODE[mode]),
            next_check="核对原始披露。", completeness="partial", quality="LOW_CONFIDENCE",
            forward_window_calendar_days=84 if mode == "catalyst_research" else None))


def setup(tmp_path):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker="600519", analysis_date="2026-09-30")
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    journal = CatalystJournal(observer, {"test": "native-publication"})
    return observer, journal, native_record(snapshot.run_id)


def authorize(journal):
    journal.put("publication_authorized", True)


@pytest.mark.parametrize("mode", list(DIMENSIONS_BY_MODE))
def test_candidate_and_authorization_precede_public_event_and_replay_is_read_only(tmp_path, mode):
    observer, journal, _ = setup(tmp_path)
    record = native_record(observer.run_id, mode)
    seen = []

    def inspect_and_authorize(value):
        persisted = load_checkpoint(observer.store, observer.run_id)
        assert persisted["native_publication_candidate"] == record.model_dump(mode="json")
        assert not any(event.payload.get("public_contract") == "research-record-v1" for event in observer.store.read_events(observer.run_id))
        seen.append(True)
        authorize(value)

    artifact_id = publish_native_record(observer, record=record, ledger=journal.ledger,
        publication_authorizer=inspect_and_authorize)
    events = observer.store.read_events(observer.run_id)
    public = next(event for event in events if event.payload.get("public_contract") == "research-record-v1")
    barrier = next(event for event in events if event.event_id == public.parent_event_id)
    assert barrier.sequence == public.payload["committed_sequence"]
    assert barrier.sequence < public.sequence
    assert barrier.status == "committed"
    saved = observer.store.read_artifact(observer.run_id, artifact_id)
    assert ResearchRecordV1.model_validate_json(saved) == record
    assert seen == [True]
    assert publish_native_record(observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda _: pytest.fail("replay reauthorized")) == artifact_id
    assert observer.store.read_events(observer.run_id) == events
    assert not any(event.type == "run.completed" for event in events)


def test_resume_after_public_artifact_write_failure_uses_frozen_candidate(tmp_path, monkeypatch):
    observer, journal, record = setup(tmp_path)
    original = observer.store.store_artifact

    def fail_public(run_id, *, kind, **kwargs):
        if kind == "research-record-v1":
            raise OSError("private model payload must not escape")
        return original(run_id, kind=kind, **kwargs)

    monkeypatch.setattr(observer.store, "store_artifact", fail_public)
    with pytest.raises(NativePublicationError, match="^native publication failed$"):
        publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=authorize)
    assert journal.state["native_publication_candidate"] == record.model_dump(mode="json")
    assert not any(event.type == "run.completed" or event.payload.get("public_contract") == "research-record-v1"
        for event in observer.store.read_events(observer.run_id))
    monkeypatch.setattr(observer.store, "store_artifact", original)
    resumed = CatalystJournal(observer, journal.state["identity"], require_existing=True)
    assert publish_native_record(observer, record=record, ledger=resumed.ledger, publication_authorizer=authorize)
    assert len(resumed.ledger.records()) == 0


def test_conflicting_candidate_and_tampered_artifact_are_not_overwritten(tmp_path):
    observer, journal, record = setup(tmp_path)
    artifact = publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=authorize)
    events = observer.store.read_events(observer.run_id)
    changed = record.model_copy(update={"assessment": record.assessment.model_copy(update={"judgement": "不同结论。"})})
    with pytest.raises(NativePublicationError, match="candidate conflict"):
        publish_native_record(observer, record=changed, ledger=journal.ledger, publication_authorizer=authorize)
    assert observer.store.read_events(observer.run_id) == events
    kind, digest = artifact.split(":")
    path = observer.store._run_dir(observer.run_id) / kind / (digest + ".json")
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(NativePublicationError, match="integrity mismatch"):
        publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=authorize)
    assert path.read_bytes() == original + b" "


def test_missing_assessment_and_noop_authorizer_cannot_publish(tmp_path):
    observer, journal, record = setup(tmp_path)
    without = record.model_copy(update={"assessment": None})
    with pytest.raises(NativePublicationError, match="requires a native assessment"):
        publish_native_record(observer, record=without, ledger=journal.ledger, publication_authorizer=authorize)
    with pytest.raises(NativePublicationError, match="authorization missing"):
        publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=lambda _: None)
    assert not any(event.payload.get("public_contract") == "research-record-v1" for event in observer.store.read_events(observer.run_id))


def test_cancel_authorizer_preserves_cancellation_type_without_publication(tmp_path):
    observer, journal, record = setup(tmp_path)

    def cancelled(_):
        raise AnalysisCancelled()

    with pytest.raises(AnalysisCancelled):
        publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=cancelled)
    assert not any(event.payload.get("public_contract") == "research-record-v1" for event in observer.store.read_events(observer.run_id))


def test_failed_candidate_barrier_never_enters_authorizer(tmp_path, monkeypatch):
    observer, journal, record = setup(tmp_path)
    monkeypatch.setattr(journal, "persist", lambda: (_ for _ in ()).throw(OSError("private")))
    with pytest.raises(NativePublicationError, match="^native publication failed$"):
        publish_native_record(observer, record=record, ledger=journal.ledger,
            publication_authorizer=lambda _: pytest.fail("authorized before persisted candidate"))


def test_public_event_failure_replays_content_addressed_artifact_once(tmp_path, monkeypatch):
    observer, journal, record = setup(tmp_path)
    original = observer.emit

    def fail_public_event(draft):
        if draft.payload.get("public_contract") == "research-record-v1":
            raise OSError("private event payload")
        return original(draft)

    monkeypatch.setattr(observer, "emit", fail_public_event)
    with pytest.raises(NativePublicationError, match="^native publication failed$"):
        publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=authorize)
    monkeypatch.setattr(observer, "emit", original)
    artifact = publish_native_record(observer, record=record, ledger=journal.ledger, publication_authorizer=authorize)
    events = [event for event in observer.store.read_events(observer.run_id)
        if event.payload.get("public_contract") == "research-record-v1"]
    assert len(events) == 1
    assert events[0].payload["artifact_id"] == artifact
    assert len(list((observer.store._run_dir(observer.run_id) / "research-record-v1").glob("*.json"))) == 1


def test_authorizer_can_acquire_journal_from_another_thread(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    observer, journal, record = setup(tmp_path)

    def authorize_without_lock_inversion(value):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(authorize, value).result(timeout=2)

    assert publish_native_record(observer, record=record, ledger=journal.ledger,
        publication_authorizer=authorize_without_lock_inversion)
