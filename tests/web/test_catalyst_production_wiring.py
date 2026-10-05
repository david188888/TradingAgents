"""Production boundary tests with isolated durable stores and no paid calls."""

import threading
from dataclasses import replace

import pytest

from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.catalyst_runner import (
    CatalystResumeGuard,
    CatalystRunner,
    validate_catalyst_resume,
)
from tradingagents.execution.models import AnalysisRequest
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.evidence_freeze import EvidenceFreezer, FreezeInputs
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.web.broker import EventBroker
from tradingagents.web.catalyst_projection import project_catalyst
from tradingagents.web.manager import (
    RunNotActive,
    SingleRunManager,
    _default_runner_factory,
    _request_from_snapshot,
)
from tradingagents.web.research_record_projection import project_research_record
from tradingagents.web.store import RunStore


def request():
    return AnalysisRequest("600519", "2026-09-30", research_profile="catalyst_v1", research_question="核验订单兑现", effective_config={
        "llm_provider": "openai", "quick_think_llm": "quick", "deep_think_llm": "deep", "checkpoint_enabled": False,
    })


class MissingSources:
    calls = 0

    def __init__(self, request, run_id, session, fetch):
        self.request, self.run_id = request, run_id

    def collect(self):
        type(self).calls += 1
        return EvidenceFreezer(FreezeInputs(self.run_id, self.request.ticker, self.request.analysis_date, self.request.catalyst_policy)).close(), {}


class ModelStub:
    calls = 0

    def __init__(self, *args):
        pass

    def __call__(self, *, role, prompt):
        type(self).calls += 1
        if role == "independent_refutation":
            return {"challenges": []}
        return {"judgement": "缺少合格证据", "priority": "insufficient_information", "key_question": "等待来源恢复", "next_check": "核验披露", "critical_limitations": ["来源不可用"], "dispositions": []}


def setup(tmp_path, *, runner_hook=None):
    store = RunStore(tmp_path / "runs")
    broker = EventBroker(store)
    def factory(req, observer):
        runner = CatalystRunner(observer, sources_factory=MissingSources, caller_factory=ModelStub)
        if runner_hook:
            runner_hook(runner)
        return runner
    return SingleRunManager(store, broker, runner_factory=factory)


def test_profile_routes_to_production_and_persists_readable_case(tmp_path):
    MissingSources.calls = ModelStub.calls = 0
    manager = setup(tmp_path)
    started = manager.start(request())
    snapshot = manager.wait(started.run_id, timeout=10)
    assert snapshot.status == "completed", snapshot.error_message
    assert _request_from_snapshot(snapshot).research_question == "核验订单兑现"
    assert isinstance(_default_runner_factory(request(), DurableRunObserver(manager.store, snapshot.run_id)), CatalystRunner)
    before = (MissingSources.calls, ModelStub.calls)
    for _ in range(3):
        read = project_catalyst(manager.store, snapshot.run_id)
        assert read["state"] == "ready"
        assert read["priority"] == "insufficient_information"
        assert read["completeness"] != "complete"
        assert read["research_question"] == "核验订单兑现"
    assert (MissingSources.calls, ModelStub.calls) == before
    record = project_research_record(manager.store, snapshot.run_id)
    assert record["state"] == "ready", record
    assert record["record"]["verifications"] == []
    assert record["record"]["mode"] == "catalyst_research"
    assert before == (1, 2)
    assert (manager.store._run_dir(snapshot.run_id) / "reports/complete_report.md").is_file()
    assert not any(e.type == "model.started" and e.payload.get("purpose") == "debate_summary" for e in manager.store.read_events(snapshot.run_id))


def test_resume_after_publication_authorization_reuses_candidate(tmp_path):
    manager = setup(tmp_path)
    started = manager.start(request())
    snapshot = manager.wait(started.run_id, timeout=10)
    restored = _request_from_snapshot(snapshot)
    validate_catalyst_resume(manager.store, snapshot.run_id, restored)
    before = (MissingSources.calls, ModelStub.calls)
    observer = DurableRunObserver(manager.store, snapshot.run_id, development_assertions=False)
    runner = CatalystRunner(observer, sources_factory=MissingSources, caller_factory=ModelStub)
    result = runner.run(restored, checkpoint_guard=CatalystResumeGuard(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    assert result.final_signal == "research_only"
    assert (MissingSources.calls, ModelStub.calls) == before
    from tradingagents.runtime.reports import ReportArtifactWriter
    ReportArtifactWriter(manager.store).publish_final(snapshot.run_id, dict(result.final_state), restored.ticker)
    assert sum(e.payload.get("public_contract") == "catalyst-research-case-v1" for e in manager.store.read_events(snapshot.run_id)) == 1
    assert sum(e.payload.get("public_contract") == "research-record-v1" for e in manager.store.read_events(snapshot.run_id)) == 1
    assert project_research_record(manager.store, snapshot.run_id)["state"] == "ready"
    with pytest.raises(ValueError):
        validate_catalyst_resume(manager.store, snapshot.run_id, replace(restored, research_question="changed"))
    assert (MissingSources.calls, ModelStub.calls) == before


def test_unknown_dispatched_attempt_inherits_spent_budget(tmp_path):
    manager = setup(tmp_path)
    started = manager.start(request())
    snapshot = manager.wait(started.run_id, timeout=10)
    from tradingagents.execution.catalyst_runner import catalyst_identity
    observer = DurableRunObserver(manager.store, snapshot.run_id, development_assertions=False)
    journal = CatalystJournal(observer, catalyst_identity(_request_from_snapshot(snapshot)))
    grant = journal.ledger.reserve_or_raise(BudgetBucket.NETWORK_RETRY, stage="refutation", logical_call_id="unknown")
    journal.ledger.mark_dispatched(grant)
    restored = CatalystJournal(observer, catalyst_identity(_request_from_snapshot(snapshot)), require_existing=True)
    assert restored.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 1


@pytest.mark.parametrize("cancel_first", [True, False])
def test_cancel_publication_linearization(tmp_path, cancel_first):
    reached, release = threading.Event(), threading.Event()
    manager = setup(tmp_path)
    original = manager._authorize_catalyst
    def authorizer(run_id, token, journal):
        if not cancel_first:
            original(run_id, token, journal)
        reached.set()
        assert release.wait(5)
        if cancel_first:
            original(run_id, token, journal)
    manager._authorize_catalyst = authorizer
    started = manager.start(request())
    assert reached.wait(5)
    if cancel_first:
        manager.cancel(started.run_id)
    else:
        with pytest.raises(RunNotActive):
            manager.cancel(started.run_id)
    release.set()
    snapshot = manager.wait(started.run_id, timeout=10)
    assert snapshot.status == ("cancelled" if cancel_first else "completed")
    assert project_catalyst(manager.store, snapshot.run_id)["state"] == ("unavailable" if cancel_first else "ready")


def test_http_create_read_report_and_retry_preserve_question(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.test_research_profile_contract import CATALYST_BODY
    from tradingagents.web.api import create_app
    monkeypatch.setenv("TRADINGAGENTS_CATALYST_PROFILE_ENABLED", "1")
    manager = setup(tmp_path)
    app = create_app(manager=manager, environment={"OPENAI_API_KEY": "test-key"}, recover_startup=False)
    with TestClient(app) as client:
        response = client.post("/api/runs", json={**CATALYST_BODY, "research_question": "  核验订单兑现  "})
        assert response.status_code == 410, response.text
        assert response.json()["detail"]["code"] == "research_profile_retired"
        run_id = manager.start(replace(request(), research_question="核验订单兑现")).run_id
        assert manager.wait(run_id, 10).status == "completed"
        before = (MissingSources.calls, ModelStub.calls)
        assert client.get(f"/api/runs/{run_id}/catalyst").json()["research_question"] == "核验订单兑现"
        view = client.get(f"/api/runs/{run_id}/view")
        assert view.status_code == 200, view.text
        artifact = next(e.payload["artifact_id"] for e in manager.store.read_events(run_id)
            if e.type == "artifact.written" and e.payload.get("locator") == "reports/complete_report.md")
        assert client.get(f"/api/runs/{run_id}/artifacts/{artifact}").status_code == 200
        assert (MissingSources.calls, ModelStub.calls) == before
        retried = client.post(f"/api/runs/{run_id}/retry")
        assert retried.status_code == 410
        assert retried.json()["detail"]["code"] == "research_profile_retired"
        assert (MissingSources.calls, ModelStub.calls) == before



@pytest.mark.parametrize("question", ["😀" * 400, "界" * 400, "   "])
def test_question_unicode_boundary(question):
    value = replace(request(), research_question=question)
    assert value.research_question == (question.strip() or None)
    from tests.test_research_profile_contract import CATALYST_BODY
    from tradingagents.web.schemas import RunCreateRequest
    assert RunCreateRequest.model_validate({**CATALYST_BODY, "research_question": question}).research_question == value.research_question


def test_invalid_question_rejected_before_dispatch():
    with pytest.raises(ValueError):
        replace(request(), research_question="😀" * 401)
    with pytest.raises(ValueError):
        replace(request(), research_profile="classic", catalyst_policy=None)


def test_checkpoint_failure_refuses_model_dispatch(tmp_path, monkeypatch):
    from tradingagents.execution.catalyst_runner import catalyst_identity
    from tradingagents.graph.catalyst_workflow import _invoke_budgeted
    manager = setup(tmp_path)
    started = manager.start(request())
    snapshot = manager.wait(started.run_id, 10)
    observer = DurableRunObserver(manager.store, snapshot.run_id, development_assertions=False)
    journal = CatalystJournal(observer, catalyst_identity(_request_from_snapshot(snapshot)))
    def fail(*args, **kwargs):
        raise OSError("injected persistence failure")
    monkeypatch.setattr(manager.store, "store_artifact", fail)
    calls = []
    with pytest.raises(OSError):
        _invoke_budgeted(ledger=journal.ledger, bucket=BudgetBucket.NETWORK_RETRY, stage="probe", logical_call_id="probe", run=lambda: calls.append(True))
    assert calls == []


def test_resume_rejects_corrupt_checkpoint_before_any_calls(tmp_path):
    manager = setup(tmp_path)
    started = manager.start(request())
    snapshot = manager.wait(started.run_id, 10)
    latest = next(e for e in reversed(manager.store.read_events(snapshot.run_id)) if e.payload.get("kind") == "catalyst-checkpoint")
    path = manager.store._run_dir(snapshot.run_id) / latest.payload["locator"]
    path.write_bytes(b"{}")
    before = (MissingSources.calls, ModelStub.calls)
    with pytest.raises(ValueError):
        validate_catalyst_resume(manager.store, snapshot.run_id, _request_from_snapshot(snapshot))
    assert (MissingSources.calls, ModelStub.calls) == before


@pytest.mark.parametrize("repair", [False, True])
def test_real_model_adapter_has_zero_sdk_retries_and_thread_context(tmp_path, monkeypatch, repair):
    from types import SimpleNamespace

    import tradingagents.execution.catalyst_runner as module
    from tests.test_catalyst_workflow import _draft
    from tradingagents.dataflows.config import get_config
    from tradingagents.observability.provenance import current_provenance_observer
    from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
    constructions, calls = [], []
    class Sources(MissingSources):
        def collect(self):
            draft = _draft()
            records = tuple({**dict(e), "run_id": self.run_id} for e in draft.evidence)
            draft = draft.model_copy(update={"run_id": self.run_id, "cutoff": self.request.analysis_date, "evidence": records})
            return draft, {e["evidence_id"]: {"verified": "fixture only"} for e in records}
    class Client:
        def get_llm(self):
            return self
        def invoke(self, prompt):
            calls.append((get_config()["llm_provider"], current_provenance_observer().run_id, prompt))
            if repair and "ROLE: operating_delivery" in prompt and "previous response failed" not in prompt:
                return SimpleNamespace(content="invalid json", usage_metadata={"input_tokens": 10, "output_tokens": 10})
            import json
            if "ROLE: independent_refutation" in prompt:
                value = {"challenges": []}
            elif "ROLE: synthesis" in prompt:
                value = {"judgement": "等待核验", "priority": "keep_watching", "key_question": "兑现时点", "next_check": "核验披露", "critical_limitations": [], "dispositions": []}
            else:
                value = {"findings": [{"kind": "unknown", "text": "尚待验证", "next_checks": ["核验原始披露"]}]}
            return SimpleNamespace(content=json.dumps(value), usage_metadata={"input_tokens": 10, "output_tokens": 10})
    def client(**kwargs):
        constructions.append(kwargs)
        return Client()
    monkeypatch.setattr(module, "create_llm_client", client)
    manager = setup(tmp_path, runner_hook=lambda runner: (setattr(runner, "sources_factory", Sources), setattr(runner, "caller_factory", module.ProductionModelCaller)))
    started = manager.start(request())
    snapshot = manager.wait(started.run_id, 10)
    assert snapshot.status == "completed", snapshot.error_message
    assert len(constructions) == (6 if repair else 5)
    assert all(v["max_retries"] == 0 and 0 < v["timeout"] <= 300 for v in constructions)
    assert [v["model"] for v in constructions].count("quick") == (5 if repair else 4)
    assert [v["model"] for v in constructions].count("deep") == 1
    assert all(provider == "openai" and run_id == snapshot.run_id for provider, run_id, _ in calls)
    assert all("核验订单兑现" in prompt for _, _, prompt in calls)
    state = load_checkpoint(manager.store, snapshot.run_id)
    assert len(state["results"]) == (6 if repair else 5)
    assert sum(r["bucket"] == "structured_repair" and r["dispatched_at"] is not None for r in state["records"]) == int(repair)


def test_transport_charges_each_http_dispatch_and_disables_sdk_retry(tmp_path, monkeypatch):
    import requests

    from tradingagents.dataflows.catalyst_transport import BudgetedSession
    from tradingagents.execution.budget import BudgetLedger
    ledger = BudgetLedger("run_transport")
    calls = []
    def send(adapter, prepared, **kwargs):
        calls.append(prepared.url)
        response = requests.Response()
        response.status_code, response._content, response.url = 200, b"{}", prepared.url
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with BudgetedSession(ledger, lambda: None, lambda: 10) as session:
        assert session.adapters["https://"].max_retries.total == 0
        session.get("https://example.test/a")
        session.get("https://example.test/b")
    assert len(calls) == ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 2


class SimulatedProcessExit(BaseException):
    """Bypass graceful error handling, as a process exit does."""


class CompleteCaller(ModelStub):
    calls_by_role = []

    def __call__(self, *, role, prompt):
        type(self).calls_by_role.append(role)
        if role in {"catalyst_events", "operating_delivery", "market_reaction"}:
            return {"findings": [{"kind": "unknown", "text": "仍待核验", "next_checks": ["检查原始来源"]}]}
        return super().__call__(role=role, prompt=prompt)


def direct_runner(tmp_path, *, sources=None, caller=CompleteCaller):
    from scripts.catalyst_e2e_server import FixtureSources
    manager = setup(tmp_path)
    snapshot = manager._create_run(request(), configured_keys={}, queued=False)
    observer = DurableRunObserver(manager.store, snapshot.run_id, development_assertions=False)
    return manager, snapshot, CatalystRunner(observer, sources_factory=sources or FixtureSources, caller_factory=caller)


@pytest.mark.parametrize("stage", ["evidence", "specialists", "refutation", "synthesis"])
def test_resume_each_durable_stage_reuses_all_completed_calls(tmp_path, monkeypatch, stage):
    from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
    CompleteCaller.calls_by_role = []
    manager, snapshot, runner = direct_runner(tmp_path)
    original = CatalystJournal.stage
    def crash(journal, name, status, **kwargs):
        original(journal, name, status, **kwargs)
        if name == stage and status == "completed":
            raise SimulatedProcessExit()
    with monkeypatch.context() as patch:
        patch.setattr(CatalystJournal, "stage", crash)
        with pytest.raises(SimulatedProcessExit):
            runner.run(request(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    state = load_checkpoint(manager.store, snapshot.run_id)
    cached_roles = set(CompleteCaller.calls_by_role)
    assert state["stages"][stage] == "completed"
    assert "candidate" not in state
    result = runner.run(request(), checkpoint_guard=CatalystResumeGuard(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    assert result.final_signal == "research_only"
    for role in cached_roles:
        assert CompleteCaller.calls_by_role.count(role) == 1
    assert len(CompleteCaller.calls_by_role) == 5
    assert load_checkpoint(manager.store, snapshot.run_id)["candidate"]["source_sequence"] > 0


def test_crash_after_publication_barrier_resumes_without_external_calls(tmp_path):
    CompleteCaller.calls_by_role = []
    manager, snapshot, runner = direct_runner(tmp_path)
    def authorize_and_exit(journal):
        journal.put("publication_authorized", True)
        raise SimulatedProcessExit()
    with pytest.raises(SimulatedProcessExit):
        runner.run(request(), publication_authorizer=authorize_and_exit)
    assert project_catalyst(manager.store, snapshot.run_id)["state"] == "unavailable"
    before = list(CompleteCaller.calls_by_role)
    runner.run(request(), checkpoint_guard=CatalystResumeGuard(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    assert CompleteCaller.calls_by_role == before
    assert project_catalyst(manager.store, snapshot.run_id)["state"] == "ready"


def test_resumed_unknown_main_dispatch_is_charged_as_network_retry(tmp_path):
    from tradingagents.execution.catalyst_runner import catalyst_identity
    from tradingagents.graph.catalyst_workflow import _invoke_budgeted
    manager, snapshot, runner = direct_runner(tmp_path)
    journal = CatalystJournal(runner.observer, catalyst_identity(request()))
    grant = journal.ledger.reserve_or_raise(BudgetBucket.MAIN_ANALYSIS, stage="refutation", logical_call_id="refutation")
    journal.ledger.mark_dispatched(grant)
    restored = CatalystJournal(runner.observer, catalyst_identity(request()), require_existing=True)
    calls = []
    value = _invoke_budgeted(ledger=restored.ledger, bucket=BudgetBucket.MAIN_ANALYSIS, stage="refutation", logical_call_id="refutation", run=lambda: (calls.append(True) or {"challenges": []}))
    assert value == {"challenges": []}
    assert len(calls) == 1
    assert restored.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert restored.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 1


def test_late_source_completion_after_timeout_never_publishes(tmp_path):
    import time
    class LateSources(MissingSources):
        def collect(self):
            time.sleep(0.03)
            return super().collect()
    manager, snapshot, runner = direct_runner(tmp_path, sources=LateSources)
    before = ModelStub.calls
    req = replace(request(), effective_config={**request().effective_config, "catalyst_timeout_seconds": 0.01})
    authorizations = []
    with pytest.raises(TimeoutError):
        runner.run(req, publication_authorizer=lambda journal: authorizations.append(True))
    assert ModelStub.calls == before
    assert authorizations == []
    assert project_catalyst(manager.store, snapshot.run_id)["state"] == "unavailable"


def test_durable_result_and_candidate_content_conflicts_are_rejected(tmp_path):
    from tradingagents.execution.catalyst_runner import catalyst_identity
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict
    manager, snapshot, runner = direct_runner(tmp_path)
    journal = CatalystJournal(runner.observer, catalyst_identity(request()))
    journal.ledger.record_result("refutation", {"challenges": []})
    with pytest.raises(CatalystCheckpointConflict):
        journal.ledger.record_result("refutation", {"challenges": [{"different": True}]})
    journal.put("candidate", {"one": True})
    with pytest.raises(CatalystCheckpointConflict):
        journal.put("candidate", {"different": True})


def test_source_admission_filters_future_filings_and_financial_rows(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import tradingagents.dataflows.catalyst_sources as module
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.research.evidence_freeze import (
        CAP_EVENT_COVERAGE,
        CAP_FUNDAMENTALS,
        CAP_PRICE,
        CapabilityStatus,
    )
    req = replace(request(), effective_config=DEFAULT_CONFIG)
    def announcements(ticker, start, end, *, session, records_sink):
        assert (start, end) == ("2026-07-02", "2026-09-30")
        assert session is transport
        records_sink([
            {"Published": day, "Title": "股份回购方案", "Announcement ID": day, "Detail URL": "https://www.cninfo.com.cn/"}
            for day in ["2026-09-20", "2026-09-21", "2026-10-01"]
        ])
        return SimpleNamespace(coverage=SimpleNamespace(model_dump=lambda **_: {
            "completeness": "complete", "pagination_exhausted": True, "degradations": []}))
    monkeypatch.setattr(module, "get_a_share_cninfo_announcements", announcements)
    transport = object()
    source = module.CatalystSources(req, "run_source_test", transport, lambda key, operation: operation())
    periods = ["20260630", "20260331", "20251231", "20250930", "20250630", "20250331", "20241231", "20240930"]
    def tushare(api, fields, **kwargs):
        if api == "stock_basic":
            return [{"ts_code": "600519.SH", "name": "当前名称不可充当历史名称", "list_date": "20010827"}]
        return [{"ts_code": "600519.SH", "ann_date": "20260920", "end_date": day, "report_type": "1"} for day in periods] + [
            {"ts_code": "600519.SH", "ann_date": "20261001", "end_date": "20260930", "report_type": "1"}]
    monkeypatch.setattr(source, "tushare", tushare)
    draft, context = source.collect()
    assert draft.capability(CAP_EVENT_COVERAGE).status == CapabilityStatus.QUALIFIED
    assert draft.capability(CAP_FUNDAMENTALS).status == CapabilityStatus.QUALIFIED
    assert draft.capability(CAP_PRICE).status == CapabilityStatus.UNAVAILABLE
    assert len(draft.events) == 2
    assert all(len(e.evidence_ids) == 1 for e in draft.events)
    assert draft.events[0].evidence_ids != draft.events[1].evidence_ids
    for evidence in draft.evidence:
        if evidence["capability"] == CAP_FUNDAMENTALS:
            assert all(len(rows) == 8 for rows in context[evidence["evidence_id"]].values())
            assert all(row["ann_date"] <= "20260930" for rows in context[evidence["evidence_id"]].values() for row in rows)


def test_source_adapter_never_substitutes_an_unselected_vendor(tmp_path):
    from tradingagents.dataflows.catalyst_sources import CatalystSources
    from tradingagents.research.evidence_freeze import CapabilityStatus
    req = replace(request(), effective_config={"data_vendors": {}, "tool_vendors": {}})
    calls = []
    draft, context = CatalystSources(req, "run_source_test", object(), lambda key, operation: calls.append(key)).collect()
    assert calls == []
    assert context == {}
    assert all(c.status == CapabilityStatus.UNAVAILABLE for c in draft.capabilities if c.required)


def test_conflicting_existing_public_case_refuses_republication(tmp_path):
    from dataclasses import asdict

    from tradingagents.agents.schemas import CatalystResearchCase
    from tradingagents.observability.events import RunEventDraft
    from tradingagents.runtime.catalyst_checkpoint import (
        CatalystCheckpointConflict,
        load_checkpoint,
    )
    manager, snapshot, runner = direct_runner(tmp_path)
    runner.run(request(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    state = load_checkpoint(manager.store, snapshot.run_id)
    different = CatalystResearchCase.model_validate(state["candidate"]).model_copy(update={"research_question": "different"})
    artifact = manager.store.store_artifact(snapshot.run_id, kind="catalyst-research-case-v1", value=different.model_dump(mode="json"))
    manager.store.append_event(RunEventDraft(snapshot.run_id, "artifact.written", {
        **asdict(artifact), "public_contract": "catalyst-research-case-v1", "committed_sequence": 99999,
    }, status="committed"))
    before = list(CompleteCaller.calls_by_role)
    with pytest.raises(CatalystCheckpointConflict):
        runner.run(request(), checkpoint_guard=CatalystResumeGuard(), publication_authorizer=lambda journal: journal.put("publication_authorized", True))
    assert CompleteCaller.calls_by_role == before


def test_resume_rejects_hash_valid_non_object_checkpoint_before_any_calls(tmp_path):
    from dataclasses import asdict

    from tradingagents.observability.events import RunEventDraft
    manager, snapshot, runner = direct_runner(tmp_path)
    artifact = manager.store.store_artifact(snapshot.run_id, kind="catalyst-checkpoint", value=[])
    manager.store.append_event(RunEventDraft(snapshot.run_id, "artifact.written", asdict(artifact), status="committed"))
    before = list(CompleteCaller.calls_by_role)
    with pytest.raises(ValueError):
        validate_catalyst_resume(manager.store, snapshot.run_id, request())
    assert CompleteCaller.calls_by_role == before
