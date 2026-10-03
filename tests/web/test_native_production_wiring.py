"""Actual public native lifecycle, using deterministic sources/models only."""

import copy
import threading
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from tests.test_native_pipeline import PipelineCaller
from tests.test_native_record import fixture
from tests.test_price_statistics_context import context as price_context
from tests.web.test_evidence_api import BODY, HOLDING
from tradingagents.execution.models import AnalysisRequest, HoldingContext
from tradingagents.execution.native_runner import (
    NativeRunner,
    validate_native_resume,
)
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.evidence_freeze import CAP_PRICE
from tradingagents.research.price_statistics import build_price_statistics
from tradingagents.runtime.catalyst_checkpoint import (
    CatalystCheckpointConflict,
    load_checkpoint,
)
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.manager import (
    RunNotActive,
    RunNotResumable,
    SingleRunManager,
    _complete_request,
    _default_runner_factory,
    _request_from_snapshot,
)
from tradingagents.web.research_record_projection import project_research_record


class ProcessStopped(BaseException):
    pass


class Sources:
    operations = []
    crash_before_seed = False
    wrong_ticker = False

    def __init__(self, request, run_id, session, fetch):
        self.request, self.run_id, self.fetch = request, run_id, fetch

    def collect(self):
        bars, provenance = price_context(30)
        provenance["input_sha256"] = "a" * 64
        prices = {
            "bars": bars,
            "provenance": provenance,
            "computed_statistics": build_price_statistics(bars, provenance),
        }
        draft, context = fixture(extra=((CAP_PRICE, "tushare.adjusted_daily", prices, None),))
        rebuilt = {}
        for key, value in context.items():

            def operation(key=key, value=value):
                type(self).operations.append((self.run_id, key))
                return copy.deepcopy(value)

            rebuilt[key] = self.fetch(key, operation)
        if type(self).crash_before_seed:
            type(self).crash_before_seed = False
            raise ProcessStopped()
        ticker = "000001" if type(self).wrong_ticker else self.request.ticker
        draft = draft.model_copy(
            update={
                "run_id": self.run_id,
                "ticker": ticker,
                "evidence": tuple(
                    {**item, "run_id": self.run_id, "ticker": ticker} for item in draft.evidence
                ),
            }
        )
        return draft, rebuilt


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    Sources.operations, Sources.crash_before_seed, Sources.wrong_ticker = [], False, False
    caller = PipelineCaller()

    def forbidden(*args, **kwargs):
        pytest.fail("public native acceptance must not dispatch real network or SDK calls")

    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    monkeypatch.setattr("tradingagents.execution.native_model.create_llm_client", forbidden)
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "true")
    monkeypatch.setattr(
        "tradingagents.execution.native_runner.NativeRunner",
        lambda observer: NativeRunner(
            observer, sources_factory=Sources, caller_factory=lambda **kwargs: caller
        ),
    )
    store = RunStore(tmp_path)
    return SingleRunManager(store), caller


def request(mode="company_research"):
    holding = (
        HoldingContext(
            "600519",
            100,
            1500,
            None,
            None,
            None,
            "2026-09-01",
            "经营现金流改善可能延续。",
            "user_provided",
        )
        if mode == "holding_review"
        else None
    )
    return AnalysisRequest(
        "600519",
        "2026-09-30",
        mode=mode,
        holding_context=holding,
        research_profile="evidence_v1",
        research_question="核对经营兑现",
        effective_config={
            "llm_provider": "openai",
            "quick_think_llm": "quick",
            "deep_think_llm": "deep",
            "checkpoint_enabled": False,
        },
    )


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_actual_http_manager_record_report_and_retry(runtime, mode):
    manager, caller = runtime
    body = {
        **BODY,
        "ticker": "600519",
        "analysis_date": "2026-09-30",
        "mode": mode,
        "research_question": "核对经营兑现",
    }
    if mode == "holding_review":
        body["holding"] = {**HOLDING, "ticker": "600519", "facts_as_of": "2026-09-30"}
    with TestClient(
        create_app(
            manager=manager,
            recover_startup=False,
            environment={"OPENAI_API_KEY": "offline-placeholder"},
            connectivity_check=lambda _: None,
        )
    ) as client:
        response = client.post("/api/runs", json=body)
        assert response.status_code == 201, response.text
        run_id = response.json()["run_id"]
        snapshot = manager.wait(run_id, 10)
        assert snapshot.status == "completed", snapshot.error_message
        restored = _request_from_snapshot(snapshot)
        assert restored.research_profile == "evidence_v1" and restored.mode == mode
        assert restored.profile_identity() == manager._requests[run_id].profile_identity()
        assert isinstance(
            _default_runner_factory(restored, DurableRunObserver(manager.store, run_id)),
            NativeRunner,
        )
        record = client.get(f"/api/runs/{run_id}/reader/record").json()
        assert record["state"] == "ready", record
        assert record["record"]["mode"] == mode and record["record"]["construction"] == "native"
        assert record["record"]["assessment"]["quality"] == "LOW_CONFIDENCE"
        assert record["record"]["assessment"]["completeness"] == (
            "complete" if mode == "catalyst_research" else "partial"
        )
        assert (record["record"]["assessment"]["forward_window_calendar_days"] == 84) == (
            mode == "catalyst_research"
        )
        events = manager.store.read_events(run_id)
        assert {e.actor_id for e in events if e.type == "role.status_changed"} == {
            "native." + key
            for key in (
                "evidence",
                "operating_quality",
                "event_context",
                "market_context",
                "challenge",
                "synthesis",
            )
        }
        assert not any(
            e.type == "model.started" and e.payload.get("purpose") == "debate_summary"
            for e in events
        )
        artifact = next(
            e.payload["artifact_id"]
            for e in events
            if e.type == "artifact.written"
            and e.payload.get("locator") == "reports/complete_report.md"
        )
        text = client.get(f"/api/runs/{run_id}/artifacts/{artifact}").text
        assert record["record"]["assessment"]["judgement"] in text
        assert "原文与来源回溯" in text
        before = (len(Sources.operations), len(caller.calls))
        for _ in range(2):
            assert client.get(f"/api/runs/{run_id}/reader/record").json() == record
            view = client.get(f"/api/runs/{run_id}/view").json()
            assert view["view"]["run"]["research_profile"] == "evidence_v1"
        assert (len(Sources.operations), len(caller.calls)) == before == (4, 5)
        retry = client.post(f"/api/runs/{run_id}/retry")
        assert retry.status_code == 201, retry.text
        retried = manager.wait(retry.json()["run_id"], 10)
        assert retried.status == "completed", retried.error_message
        assert retried.run_id != run_id and retried.retry_of == run_id
        assert _request_from_snapshot(retried).profile_identity() == restored.profile_identity()
        assert (len(Sources.operations), len(caller.calls)) == (8, 10)


@pytest.mark.parametrize("before_seed", [True, False])
def test_actual_startup_and_resume_reuse_saved_frontier(runtime, before_seed):
    manager, caller = runtime
    req = _complete_request(request())
    snapshot = manager._create_run(req, configured_keys={}, queued=False)
    observer = DurableRunObserver(manager.store, snapshot.run_id, development_assertions=False)
    runner = NativeRunner(observer, sources_factory=Sources, caller_factory=lambda **kwargs: caller)

    def stopped(journal):
        raise ProcessStopped()

    Sources.crash_before_seed = before_seed
    with pytest.raises(ProcessStopped):
        runner.run(req, publication_authorizer=stopped)
    before = (len(Sources.operations), len(caller.calls))
    state = load_checkpoint(manager.store, snapshot.run_id)
    assert ("native_seed" not in state) == before_seed
    recovered = SingleRunManager(RunStore(manager.store.root))
    assert recovered.recover_startup()[0].status == "interrupted"
    resumed = recovered.resume(snapshot.run_id)
    terminal = recovered.wait(resumed.run_id, 10)
    assert terminal.status == "completed", terminal.error_message
    assert (len(Sources.operations), len(caller.calls)) == (4, 5)
    assert before == ((4, 0) if before_seed else (4, 5))
    assert project_research_record(recovered.store, snapshot.run_id)["state"] == "ready"
    assert (
        sum(
            e.payload.get("public_contract") == "research-record-v1"
            for e in recovered.store.read_events(snapshot.run_id)
        )
        == 1
    )


@pytest.mark.parametrize("cancel_first", [True, False])
def test_cancellation_and_native_publication_share_lifecycle_lock(runtime, cancel_first):
    manager, _ = runtime
    reached, release = threading.Event(), threading.Event()
    original = manager._authorize_catalyst

    def authorize(run_id, token, journal):
        if not cancel_first:
            original(run_id, token, journal)
        reached.set()
        assert release.wait(5)
        if cancel_first:
            original(run_id, token, journal)

    manager._authorize_catalyst = authorize
    snapshot = manager.start(request())
    assert reached.wait(5)
    if cancel_first:
        manager.cancel(snapshot.run_id)
    else:
        with pytest.raises(RunNotActive):
            manager.cancel(snapshot.run_id)
    release.set()
    terminal = manager.wait(snapshot.run_id, 10)
    assert terminal.status == ("cancelled" if cancel_first else "completed")
    assert project_research_record(manager.store, snapshot.run_id)["state"] == (
        "unavailable" if cancel_first else "ready"
    )


def test_native_resume_rejects_changed_identity_and_missing_checkpoint(runtime):
    manager, _ = runtime
    snapshot = manager.start(request())
    terminal = manager.wait(snapshot.run_id, 10)
    assert terminal.status == "completed", terminal.error_message
    assert terminal.summary == "研究流程已完成；判断受证据限制。"
    req = _request_from_snapshot(terminal)
    validate_native_resume(manager.store, snapshot.run_id, req)
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(
            manager.store, snapshot.run_id, replace(req, research_question="changed")
        )
    missing = manager._create_run(_complete_request(request()), configured_keys={}, queued=False)
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(manager.store, missing.run_id, _request_from_snapshot(missing))
    altered = terminal.evolve(
        metadata={
            key: value for key, value in terminal.metadata.items() if key != "evidence_policy"
        }
    )
    with pytest.raises(RunNotResumable, match="evidence policy"):
        _request_from_snapshot(altered)


def test_cross_security_seed_rejected_before_any_model(runtime):
    manager, caller = runtime
    Sources.wrong_ticker = True
    snapshot = manager.start(request())
    terminal = manager.wait(snapshot.run_id, 10)
    assert terminal.status == "failed"
    assert caller.calls == []
    assert project_research_record(manager.store, snapshot.run_id)["state"] == "unavailable"


@pytest.mark.parametrize("cancel_first", [True, False])
def test_already_published_resume_reenters_lifecycle_arbitration(runtime, cancel_first):
    manager, caller = runtime
    req = _complete_request(request())
    snapshot = manager._create_run(req, configured_keys={}, queued=False)
    observer = DurableRunObserver(manager.store, snapshot.run_id, development_assertions=False)
    NativeRunner(observer, sources_factory=Sources, caller_factory=lambda **kwargs: caller).run(
        req, publication_authorizer=lambda journal: journal.put("publication_authorized", True)
    )
    assert project_research_record(manager.store, snapshot.run_id)["state"] == "ready"
    recovered = SingleRunManager(RunStore(manager.store.root))
    assert recovered.recover_startup()[0].status == "interrupted"
    entered, release = threading.Event(), threading.Event()
    original = recovered._authorize_catalyst

    def authorize(run_id, token, journal):
        if not cancel_first:
            original(run_id, token, journal)
        entered.set()
        assert release.wait(5)
        if cancel_first:
            original(run_id, token, journal)

    recovered._authorize_catalyst = authorize
    recovered.resume(snapshot.run_id)
    assert entered.wait(5), "cached record replay must still arbitrate the resumed lifecycle"
    if cancel_first:
        recovered.cancel(snapshot.run_id)
    else:
        with pytest.raises(RunNotActive):
            recovered.cancel(snapshot.run_id)
    release.set()
    terminal = recovered.wait(snapshot.run_id, 10)
    assert terminal.status == ("cancelled" if cancel_first else "completed")
    assert len(Sources.operations) == 4 and len(caller.calls) == 5
    assert (
        sum(
            e.payload.get("public_contract") == "research-record-v1"
            for e in recovered.store.read_events(snapshot.run_id)
        )
        == 1
    )


def test_missing_all_sources_completes_workflow_without_research_success(runtime, monkeypatch):
    from tradingagents.research.evidence_freeze import EvidenceFreezer, FreezeInputs

    manager, caller = runtime

    class MissingSources:
        def __init__(self, request, run_id, session, fetch):
            self.request, self.run_id = request, run_id

        def collect(self):
            return EvidenceFreezer(
                FreezeInputs(
                    self.run_id,
                    self.request.ticker,
                    self.request.analysis_date,
                    self.request.catalyst_policy,
                )
            ).close(), {}

    monkeypatch.setattr(
        "tradingagents.execution.native_runner.NativeRunner",
        lambda observer: NativeRunner(
            observer, sources_factory=MissingSources, caller_factory=lambda **kwargs: caller
        ),
    )
    snapshot = manager.start(request())
    terminal = manager.wait(snapshot.run_id, 10)
    assert terminal.status == "completed", terminal.error_message
    assert terminal.summary == "研究流程已完成；判断受证据限制。"
    record = project_research_record(manager.store, snapshot.run_id)["record"]
    assert (
        record["claims"]
        == record["hypotheses"]
        == record["challenges"]
        == record["verifications"]
        == []
    )
    assert record["assessment"]["quality"] == "LOW_CONFIDENCE"
    assert record["assessment"]["completeness"] == "partial"
    assert caller.calls == []
    assert (
        next(
            e.payload["summary"]
            for e in manager.store.read_events(snapshot.run_id)
            if e.type == "run.completed"
        )
        == terminal.summary
    )
