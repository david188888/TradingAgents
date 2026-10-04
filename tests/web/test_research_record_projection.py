"""Real store publication, compatibility and zero-dispatch record reads."""

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.execution.record_publisher import promote_research_record
from tradingagents.observability.events import RunEventDraft
from tradingagents.research.record_assembly import record_from_catalyst, record_from_classic
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunNotFound, RunStore
from tradingagents.web.api import create_app
from tradingagents.web.manager import SingleRunManager
from tradingagents.web.research_record_projection import project_research_record

RUN_ID = "run_20260930T010203000000Z_abcd1234"


class Observer:
    def __init__(self, store):
        self.run_id, self.store = RUN_ID, store
    def emit(self, draft):
        return self.store.append_event(draft)


def setup(store, mode="catalyst_research"):
    snapshot = RunSnapshot.create(run_id=RUN_ID, ticker="600519" if mode == "catalyst_research" else "000338.SZ",
        analysis_date="2026-09-29" if mode == "catalyst_research" else "2026-08-10",
        mode="company_research" if mode == "catalyst_research" else mode,
        holding_context={"ticker": "000338.SZ", "quantity": 100, "average_cost": 10} if mode == "holding_review" else None,
        selected_analysts=("market",), llm_provider="openai", quick_think_llm="quick", deep_think_llm="deep",
        metadata={"research_profile": "catalyst_v1"} if mode == "catalyst_research" else {})
    store.create_run(snapshot)
    return Observer(store)


def source_case(mode):
    if mode == "catalyst_research":
        from tests.agents.test_catalyst_research_schema import _case
        return _case(run_id=RUN_ID)
    from tests.test_reader_companion import _case
    return _case(RUN_ID, evidence_artifact_id="evidence-bundle:" + "a" * 64,
        evidence_locator="private/path.json", available_ref_id="a" * 64,
        unavailable_artifact_id="evidence-bundle:" + "b" * 64,
        unavailable_locator="private/other.json", unavailable_ref_id="b" * 64)


def publish(store, mode="catalyst_research"):
    observer = setup(store, mode)
    case = source_case(mode)
    if mode == "catalyst_research":
        contract = "catalyst-research-case-v1"
        record = record_from_catalyst(case, {})
    else:
        contract = "research-case-v2"
        record = record_from_classic(case, mode=mode, analysis_date="2026-08-10")
    kwargs = {"graph_task_id": "source.final", "checkpoint_event_id": "committed-barrier", "committed_sequence": 5}
    promote_derived_public_artifact(observer, contract=contract, value=case, promoted=set(), **kwargs)
    artifact = promote_research_record(observer, build=lambda: record, promoted=set(), **kwargs)
    return observer, case, record, artifact, kwargs


@pytest.mark.parametrize("mode", ["company_research", "holding_review", "catalyst_research"])
def test_all_modes_publish_idempotent_record_and_read_without_writes(tmp_path, mode, monkeypatch):
    store = RunStore(tmp_path)
    observer, case, record, artifact, kwargs = publish(store, mode)
    assert artifact is not None
    before_events = list(store.read_events(RUN_ID))
    assert promote_research_record(observer, build=lambda: record, promoted=set(), **kwargs) == artifact
    assert list(store.read_events(RUN_ID)) == before_events
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("read wrote an artifact"))
    for _ in range(3):
        response = project_research_record(store, RUN_ID)
        assert response["state"] == "ready"
        assert response["record"]["mode"] == mode
        assert response["record"]["verifications"] == []
        assert "private/path" not in str(response)
    assert list(store.read_events(RUN_ID)) == before_events


def test_missing_historical_record_remains_missing_without_backfill(tmp_path):
    store = RunStore(tmp_path)
    setup(store)
    before = list(store.read_events(RUN_ID))
    assert project_research_record(store, RUN_ID)["reason_code"] == "not_published"
    assert list(store.read_events(RUN_ID)) == before
    with pytest.raises(RunNotFound):
        project_research_record(store, "run_20260930T010203000000Z_deadbeef")


def test_edited_record_bytes_are_not_readable_even_if_still_valid_json(tmp_path):
    store = RunStore(tmp_path)
    _, _, _, artifact, _ = publish(store)
    kind, digest = artifact.split(":")
    path = store._run_dir(RUN_ID) / kind / (digest + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    assert project_research_record(store, RUN_ID)["reason_code"] == "corrupt"


def test_changed_source_case_cannot_be_paired_with_old_record(tmp_path):
    store = RunStore(tmp_path)
    observer, case, _, _, kwargs = publish(store)
    changed = case.model_copy(update={"research_question": "new question"})
    promote_derived_public_artifact(observer, contract="catalyst-research-case-v1", value=changed,
        promoted=set(), **{**kwargs, "graph_task_id": "different.final", "committed_sequence": 6})
    assert project_research_record(store, RUN_ID)["reason_code"] == "source_case_mismatch"


def test_projection_ignores_uncommitted_newer_record(tmp_path):
    store = RunStore(tmp_path)
    observer, _, record, artifact, _ = publish(store)
    raw = store.read_artifact(RUN_ID, artifact)
    original = next(e for e in store.read_events(RUN_ID) if e.payload.get("public_contract") == "research-record-v1")
    observer.emit(RunEventDraft(RUN_ID, "artifact.written", {
        **original.payload, "committed_sequence": 99,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }, status="observed"))
    assert project_research_record(store, RUN_ID)["record"] == record.model_dump(mode="json")


def test_record_failure_preserves_source_case_and_reports_safe_status(tmp_path):
    store = RunStore(tmp_path)
    observer = setup(store)
    promote_derived_public_artifact(observer, contract="catalyst-research-case-v1", value=source_case("catalyst_research"),
        graph_task_id="source.final", checkpoint_event_id="barrier", committed_sequence=5, promoted=set())
    def fail():
        raise ValueError("private payload must never appear")
    assert promote_research_record(observer, build=fail, graph_task_id="source.final",
        checkpoint_event_id="barrier", committed_sequence=5, promoted=set()) is None
    response = project_research_record(store, RUN_ID)
    assert response["reason_code"] == "publication_failed"
    assert "private payload" not in str(response)
    from tradingagents.web.catalyst_projection import project_catalyst
    assert project_catalyst(store, RUN_ID)["state"] == "ready"


def test_conflicting_replay_does_not_replace_committed_record(tmp_path):
    store = RunStore(tmp_path)
    observer, _, record, artifact, kwargs = publish(store)
    changed = record.model_copy(update={"limitations": ("different record",)})
    assert promote_research_record(observer, build=lambda: changed, promoted=set(), **kwargs) is None
    assert project_research_record(store, RUN_ID)["record"] == record.model_dump(mode="json")
    assert sum(e.payload.get("public_contract") == "research-record-v1" and e.type == "artifact.written" for e in store.read_events(RUN_ID)) == 1


def test_http_reads_are_only_committed_records_and_missing_run_is_404(tmp_path):
    store = RunStore(tmp_path)
    publish(store)
    # This fixture stores committed artifacts without executing a real run.
    # Leaving its snapshot "created" would let normal app startup enqueue a
    # background production run that survives this read-only test.
    store.write_snapshot_atomic(store.read_snapshot(RUN_ID).evolve(status="completed"))
    dispatches = []

    def unexpected_runner(request, observer):
        dispatches.append(request)
        raise AssertionError("HTTP record reads must not dispatch research")

    manager = SingleRunManager(store, runner_factory=unexpected_runner)
    before_events = list(store.read_events(RUN_ID))
    with TestClient(create_app(manager=manager)) as client:
        assert client.get(f"/api/runs/{RUN_ID}/reader/record").json()["state"] == "ready"
        assert client.get("/api/runs/run_20260930T010203000000Z_deadbeef/reader/record").status_code == 404
        assert manager.scheduler.active_run_ids == ()
        assert not manager.scheduler.pending
    assert dispatches == []
    assert list(store.read_events(RUN_ID)) == before_events


@pytest.mark.parametrize("mode", ["company_research", "holding_review"])
def test_classic_commit_boundary_publishes_shared_record_and_replay_does_not_duplicate(tmp_path, monkeypatch, mode):
    import tradingagents.execution.runner as module
    from tradingagents.observability.observer import DurableRunObserver
    store = RunStore(tmp_path)
    setup(store, mode)
    observer = DurableRunObserver(store, RUN_ID, development_assertions=False)
    case = source_case(mode)
    # The case assembly has separate coverage. Exercise the real commit,
    # package/record producers and store publication from a validated case.
    monkeypatch.setattr(module, "_assemble_research_case_or_fallback", lambda *args: case)
    monkeypatch.setattr(module, "_promote_valuation_assessment", lambda *args, **kwargs: None)
    artifact = store.store_artifact(RUN_ID, kind="candidate", value={"research_case_candidate": {"draft": {}}})
    commit = SimpleNamespace(graph_task_id="classic.final", task_kind="maintenance", turn_id=None,
        node_id="manager.research", tool_call_ids=())
    candidates = {commit.graph_task_id: SimpleNamespace(artifact_id=artifact.artifact_id)}
    marker = SimpleNamespace(event_id="committed-barrier", sequence=5)
    for _ in range(2):
        module.AnalysisRunner._promote_commits(observer, (commit,), candidates, marker)
        response = project_research_record(store, RUN_ID)
        assert response["state"] == "ready", response
        assert response["record"]["mode"] == mode
    assert sum(e.payload.get("public_contract") == "research-record-v1" for e in store.read_events(RUN_ID)) == 1
