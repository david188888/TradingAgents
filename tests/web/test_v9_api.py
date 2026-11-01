"""Current HTTP admission, durable publication, cancellation and historical rejection."""
import json
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from scripts.e2e_server import InsightFixtureCaller, InsightFixtureSources
from tradingagents.execution.native_runner import NativeRunner
from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuth
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.manager import SingleRunManager

BODY = {"ticker": "002130.SZ", "analysis_date": "2026-10-28", "llm_provider": "deepseek",
    "quick_think_llm": "deepseek-v4-flash", "deep_think_llm": "deepseek-v4-pro", "output_language": "Chinese"}


@contextmanager
def workbench(tmp_path, *, caller=None):
    store = RunStore(tmp_path / "runs")
    calls = []

    def factory(request, observer):
        def invoke(stage, context, *, phase="main"):
            calls.append(stage)
            return (caller or InsightFixtureCaller())(stage, context, phase=phase)
        return NativeRunner(observer, sources_factory=InsightFixtureSources,
            caller_factory=lambda **kwargs: invoke)

    manager = SingleRunManager(store, runner_factory=factory)
    manager.explanations.start = lambda run_id: None
    app = create_app(manager=manager, environment={"DEEPSEEK_API_KEY": "offline-key"},
        chatgpt_auth=ChatGPTAuth(tmp_path / "auth"))
    with TestClient(app) as client:
        yield client, manager, store, calls


def test_current_http_flow_publishes_exact_insight_and_stage_views(tmp_path):
    with workbench(tmp_path) as (client, manager, store, calls):
        response = client.post("/api/runs", json=BODY)
        assert response.status_code == 201, response.text
        run_id = response.json()["run_id"]
        completed = manager.wait(run_id, timeout=5)
        assert completed.status == "completed", completed.error_message
        assert calls == ["operating_quality", "challenge", "synthesis"]
        report = client.get(f"/api/runs/{run_id}/reader/record").json()
        assert report["state"] == "insight_ready"
        assert report["record"]["schema_version"] == "insight-research-v1"
        assert report["record"]["synthesis"]["stance"] == "neutral"
        assert client.get(f"/api/runs/{run_id}/reader/process").json()["availability"] == "ready"
        assert client.get(f"/api/runs/{run_id}/reader/agents/operating_quality").json()["insight_record"] == report["record"]
        assert client.get(f"/api/runs/{run_id}/audit").status_code == 200
        assert (store.root / run_id / "reports/complete_report.md").is_file()
        assert "offline-key" not in json.dumps(completed.as_dict())
        snapshot = client.get(f"/api/runs/{run_id}").json()
        assert not {"selected_analysts", "max_debate_rounds", "horizon", "holding_context"} & snapshot.keys()
        assert len(client.get("/api/runs").json()) == 1
        for endpoint in ("view", "reader", "reader/package", "catalyst"):
            assert client.get(f"/api/runs/{run_id}/{endpoint}").status_code == 404


@pytest.mark.parametrize("field,value", [("research_profile", "classic"), ("research_profile", "catalyst_v1"),
    ("ticker", "AAPL"), ("mode", "holding_review"), ("selected_analysts", ["market"]), ("research_depth", 2)])
def test_retired_or_non_a_share_requests_reject_before_worker(tmp_path, field, value):
    with workbench(tmp_path) as (client, _manager, store, calls):
        assert client.post("/api/runs", json={**BODY, field: value}).status_code == 422
        assert calls == [] and store.list_runs() == []


def test_retired_runs_are_skipped_and_return_explicit_unsupported_response(tmp_path):
    with workbench(tmp_path) as (client, _manager, store, calls):
        snapshot = RunSnapshot.create(ticker="002130.SZ", analysis_date="2026-10-28")
        store.create_run(snapshot)
        path = store.root / snapshot.run_id / "run.json"
        payload = json.loads(path.read_text())
        payload["metadata"]["native_workflow_version"] = "evidence-production-v8"
        path.write_text(json.dumps(payload))
        assert client.get("/api/runs").json() == []
        for suffix, method in [("", client.get), ("/resume", client.post), ("/retry", client.post), ("/reader/record", client.get)]:
            response = method(f"/api/runs/{snapshot.run_id}{suffix}")
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "unsupported_research_version"
        assert json.loads(path.read_text()) == payload and calls == []


def test_cancellation_during_specialist_work_prevents_publication(tmp_path):
    started, release = threading.Event(), threading.Event()

    def caller(stage, context, *, phase="main"):
        started.set()
        assert release.wait(5)
        return InsightFixtureCaller()(stage, context, phase=phase)

    with workbench(tmp_path, caller=caller) as (client, manager, store, _calls):
        response = client.post("/api/runs", json=BODY)
        run_id = response.json()["run_id"]
        assert started.wait(5)
        try:
            assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
        finally:
            release.set()
        assert manager.wait(run_id, timeout=5).status == "cancelled"
        assert not (store.root / run_id / "reports").exists()
        assert not any(e.payload.get("public_contract") == "insight-research-v1" for e in store.read_events(run_id))


@pytest.mark.parametrize("ticker", ["AAPL", "0700.HK"])
def test_batch_validation_and_creation_reject_non_a_share_before_worker(tmp_path, monkeypatch, ticker):
    monkeypatch.setattr("tradingagents.web.api.resolve_input_candidates", lambda value: [("Foreign company", ticker)])
    with workbench(tmp_path) as (client, _manager, store, calls):
        assert client.post("/api/batches/validate", json={"inputs": [ticker]}).status_code == 422
        config = {key: value for key, value in BODY.items() if key != "ticker"}
        assert client.post("/api/batches", json={"entries": [{"input": ticker, "config": config}]}).status_code == 422
        assert calls == [] and store.list_runs() == []


def test_current_v9_snapshot_discards_retired_unused_fields_without_rewrite(tmp_path):
    with workbench(tmp_path) as (client, _manager, store, _calls):
        snapshot = RunSnapshot.create(ticker="002130.SZ", analysis_date="2026-10-28")
        store.create_run(snapshot)
        path = store.root / snapshot.run_id / "run.json"
        payload = json.loads(path.read_text())
        payload.update(selected_analysts=["market"], max_debate_rounds=1, max_risk_discuss_rounds=1,
            horizon="medium", holding_context=None, resume_fingerprint=None, runtime_semantics_hash=None,
            agent_state_schema_sha256=None)
        path.write_text(json.dumps(payload))
        assert client.get(f"/api/runs/{snapshot.run_id}").status_code == 200
        assert len(client.get("/api/runs").json()) == 1
        assert client.post(f"/api/runs/{snapshot.run_id}/resume").status_code == 409
        assert json.loads(path.read_text()) == payload


def test_old_batch_history_and_scheduler_do_not_admit_retired_children(tmp_path):
    from tradingagents.runtime.batch_models import BatchItem, BatchSnapshot
    with workbench(tmp_path) as (client, manager, store, calls):
        snapshot = RunSnapshot.create(ticker="002130.SZ", analysis_date="2026-10-28")
        store.create_run(snapshot)
        batch = BatchSnapshot.create(items=(BatchItem(input_value="002130.SZ", company_name="Synthetic company",
            ticker=snapshot.ticker, market="A-share", run_id=snapshot.run_id, ordinal=0),))
        store.create_batch(batch)
        path = store.root / snapshot.run_id / "run.json"
        payload = json.loads(path.read_text())
        payload["metadata"]["native_workflow_version"] = "evidence-production-v8"
        payload["metadata"]["batch_id"] = batch.batch_id
        path.write_text(json.dumps(payload))
        manifest = store.root / "batches" / (batch.batch_id + ".json")
        before = manifest.read_bytes()
        assert client.get("/api/batches").json() == []
        assert manager.recover_startup() == ()
        manager.scheduler.queue_run(snapshot.run_id)
        manager.scheduler.drain()
        assert calls == [] and manager.active_run_ids == ()
        assert manifest.read_bytes() == before and json.loads(path.read_text()) == payload
