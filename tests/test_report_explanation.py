"""Offline acceptance of reading semantics, publication isolation and dispatch bounds."""

import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.agents.schemas._report_explanation import EXPLANATION_POLICY, ExplanationEntry
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.execution.report_explanation import ExplanationService
from tradingagents.llm_clients.chatgpt_errors import ChatGPTError
from tradingagents.research.report_explanation import (
    display_number,
    explanation_targets,
    indicator_presentations,
    validate_explanation_entry,
)
from tradingagents.runtime.report_explanation import read_explanation_job, save_explanation_job
from tradingagents.web.api import create_app
from tradingagents.web.report_explanation import load_explanation_record, project_report_explanation

pytestmark = pytest.mark.unit


@pytest.fixture
def published(tmp_path):
    journal, seed = setup(tmp_path, full=True, delivery=True)
    record = run(journal, seed, UnifiedCaller())
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    store = journal.observer.store
    snapshot = store.read_snapshot(record.run_id)
    config = {"llm_provider": "openai", "quick_think_llm": "stub", "deep_think_llm": "stub", "backend_url": None}
    store.write_snapshot_atomic(snapshot.evolve(status="completed", quick_think_llm="stub", output_language="Chinese",
        metadata={**snapshot.metadata, "effective_config": config, "report_explanation_policy": EXPLANATION_POLICY}))
    return store, record, journal


class FakeProvider:
    def __init__(self, responses=()):
        self.calls = []
        self.responses = iter(responses)
        self.factories = []

    def factory(self, **kwargs):
        self.factories.append(kwargs)
        return SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=self.invoke))

    def invoke(self, prompt):
        self.calls.append(prompt)
        response = next(self.responses, None)
        if isinstance(response, Exception):
            raise response
        if response is None:
            targets = json.loads(prompt.split("\nDATA:\n")[1].split("\nRepair:")[0])
            response = json.dumps({"entries": [{"target": t["target"],
                "explanation": "这段分析保留有条件的判断，需要结合对应资料继续核查。",
                "uncertainty": "现有资料不能证明未来结果。", "references": t["references"][:1]} for t in targets]}, ensure_ascii=False)
        return SimpleNamespace(content=response, usage_metadata={"input_tokens": 30, "output_tokens": 20})


def wait_job(service, store, run_id):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        job = read_explanation_job(store, run_id)
        if job.state != "generating" and not service.active(run_id, job.job_id):
            return job
        time.sleep(0.01)
    pytest.fail("explanation job did not settle")


@pytest.mark.parametrize("value,unit,expected", [
    (-0.04471005588515259, "signed_return_fraction", "-4.47%"),
    (0.49966672015334296, "return_fraction", "49.97%"),
    (0.025, "signed_return_fraction", "2.5%"), (49.97, "percent", "49.97%"),
    (-5288000000, "CNY", "-52.88 亿元"), (211000, "CNY", "21.1 万元"),
    (21.1, "CNY/share", "21.1 元/股"), (0, "return_fraction", "0%"),
    (-0.0, "CNY", "0 元"), (0.00000001, "return_fraction", "0.00000100%"),
    (0.005, "ratio", "0.005"), ("NaN", "CNY", "暂不可用"), (None, "ratio", "暂不可用"),
])
def test_unit_aware_formatting_preserves_sign_small_values_and_missing(value, unit, expected):
    assert display_number(value, unit) == expected


def test_rules_use_saved_financial_and_metric_bindings(published):
    store, record, _ = published
    before = canonical_sha256(record)
    indicators = indicator_presentations(record)
    assert any(i.label == "营业收入" and "利润" in i.caution for i in indicators.values())
    var = next(m for m in record.metrics if m.metric_id.endswith(".historical_var_95"))
    item = indicators["metric:" + var.metric_id]
    assert "未来发生概率" in item.caution
    assert item.value.endswith("%") and "有效样本" in item.scope
    claim = next(c for c in record.claims if "source_field:computed_statistics:" + var.metric_id in c.limitations)
    assert indicators["claim:" + claim.claim_id].value == item.value
    assert indicators["claim:" + claim.claim_id].professional == claim.statement
    assert canonical_sha256(record) == before
    assert store.read_snapshot(record.run_id).status == "completed"


def test_saved_explanation_deduplicates_and_never_changes_research(published, monkeypatch):
    store, record, journal = published
    provider = FakeProvider()
    service = ExplanationService(store, lambda r: load_explanation_record(store, r), client_factory=provider.factory)
    before = (canonical_sha256(record), store.read_events(record.run_id), journal.state.copy(), store.read_snapshot(record.run_id))
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    assert job.state in {"available", "partial"}
    service.start(record.run_id, retry=True)
    assert len(provider.calls) == 1
    assert provider.factories[0]["max_retries"] == 0
    assert job.attempts[0].input_tokens == 30 and job.attempts[0].outcome == "received"
    assert job.result_artifact_id
    monkeypatch.setattr(store, "write_fixed_json", lambda *a, **k: pytest.fail("GET wrote state"))
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("GET wrote an artifact"))
    for _ in range(2):
        view = project_report_explanation(store, record.run_id, service=service)
        assert view["entries"] and view["state"] in {"available", "partial"}
    assert (canonical_sha256(record), store.read_events(record.run_id), journal.state, store.read_snapshot(record.run_id)) == before
    service.close()


@pytest.mark.parametrize("responses,count,state", [
    (["not json"], 2, "available"), (["not json", "not json"], 2, "failed"),
    ([ChatGPTError("subscription_sharing_usage_limit_exceeded")], 1, "failed"),
    ([RuntimeError("PRIVATE_SENTINEL")], 1, "failed"),
])
def test_bounded_repair_and_no_quota_network_retry(published, responses, count, state):
    store, record, _ = published
    provider = FakeProvider(responses)
    service = ExplanationService(store, lambda r: load_explanation_record(store, r), client_factory=provider.factory)
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    assert len(provider.calls) == count
    assert job.state == state or state == "available" and job.state == "partial"
    assert "PRIVATE_SENTINEL" not in job.model_dump_json()
    service.close()


@pytest.mark.parametrize("marked", [False, True])
def test_chatgpt_explanation_retry_keeps_originating_request_policy(published, marked):
    from tradingagents.llm_clients.chatgpt_policy import CHATGPT_REQUEST_POLICY

    store, record, journal = published
    identity = dict(journal.state["identity"])
    if marked:
        identity["chatgpt_request_policy"] = CHATGPT_REQUEST_POLICY
    journal.put("identity", identity)
    snapshot = store.read_snapshot(record.run_id)
    config = {**snapshot.metadata["effective_config"], "llm_provider": "chatgpt",
              "chatgpt_account_ref": "cg_" + "a" * 32, "openai_reasoning_effort": "high"}
    store.write_snapshot_atomic(snapshot.evolve(metadata={**snapshot.metadata, "effective_config": config}))
    provider = FakeProvider([RuntimeError("temporary fixture failure")])
    service = ExplanationService(store, lambda r: load_explanation_record(store, r),
                                 client_factory=provider.factory, chatgpt_auth=object())
    try:
        service.start(record.run_id)
        first = wait_job(service, store, record.run_id)
        assert first.state == "failed"
        service.start(record.run_id, retry=True)
        second = wait_job(service, store, record.run_id)
        assert second.state in {"available", "partial"}
        assert first.config_sha256 == second.config_sha256 == canonical_sha256(config)
        assert [item.get("reasoning_effort") for item in provider.factories] == (["high", "high"] if marked else [None, None])
        assert store.read_snapshot(record.run_id).metadata["effective_config"] == config
    finally:
        service.close()


def test_historical_reports_cannot_start_model_jobs(published):
    store, record, _ = published
    snap = store.read_snapshot(record.run_id)
    store.write_snapshot_atomic(snap.evolve(metadata={k: v for k, v in snap.metadata.items() if k != "report_explanation_policy"}))
    provider = FakeProvider()
    service = ExplanationService(store, lambda r: load_explanation_record(store, r), client_factory=provider.factory)
    with pytest.raises(ValueError, match="not_eligible"):
        service.start(record.run_id, retry=True)
    view = project_report_explanation(store, record.run_id, service=service)
    assert view["indicators"] and not view["eligible"] and view["state"] == "not_generated"
    assert not provider.calls
    service.close()


def test_unknown_outcome_is_interrupted_on_read_and_requires_explicit_retry(published):
    store, record, _ = published
    provider = FakeProvider()
    service = ExplanationService(store, lambda r: load_explanation_record(store, r), client_factory=provider.factory)
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    saved = job.model_copy(update={"state": "generating"})
    save_explanation_job(store, saved)
    view = project_report_explanation(store, record.run_id)
    assert view["state"] == "interrupted" and len(provider.calls) == 1
    assert not view["entries"]  # A pending/failed manifest cannot bypass result-artifact validation.
    service.start(record.run_id)
    assert len(provider.calls) == 1
    service.start(record.run_id, retry=True)
    assert wait_job(service, store, record.run_id).state in {"available", "partial"}
    assert len(provider.calls) == 2
    service.close()


def test_scope_numbers_duplicates_and_tampered_result_are_rejected(published):
    store, record, _ = published
    indicators = indicator_presentations(record)
    targets, _ = explanation_targets(record, indicators)
    key, target = next(iter(targets.items()))
    for entry in (
        ExplanationEntry(target=key, explanation="预计上涨 30%。"),
        ExplanationEntry(target=key, explanation="确定增长。", references=("outside",)),
    ):
        with pytest.raises(ValueError):
            validate_explanation_entry(entry, target)
    provider = FakeProvider()
    service = ExplanationService(store, lambda r: load_explanation_record(store, r), client_factory=provider.factory)
    service.start(record.run_id)
    job = wait_job(service, store, record.run_id)
    entry = job.entries[key].model_copy(update={"explanation": "被修改的解释。"})
    save_explanation_job(store, job.model_copy(update={"entries": {**job.entries, key: entry}}))
    view = project_report_explanation(store, record.run_id)
    assert view["state"] == "corrupt" and not view["entries"] and view["indicators"]
    service.close()


def test_get_endpoint_never_generates_and_historical_post_is_rejected(published):
    store, record, _ = published
    snap = store.read_snapshot(record.run_id)
    store.write_snapshot_atomic(snap.evolve(metadata={k: v for k, v in snap.metadata.items() if k != "report_explanation_policy"}))
    before = store.read_events(record.run_id)
    app = create_app(store=store, recover_startup=False)
    with TestClient(app) as client:
        response = client.get(f"/api/runs/{record.run_id}/reader/explanations")
        assert response.status_code == 200 and response.json()["indicators"]
        assert client.post(f"/api/runs/{record.run_id}/reader/explanations").status_code == 409
    assert store.read_events(record.run_id) == before


def test_duplicate_submission_during_dispatch_uses_one_job(published):
    store, record, _ = published
    started, release = threading.Event(), threading.Event()
    provider = FakeProvider()
    original = provider.invoke

    def blocking(prompt):
        started.set()
        assert release.wait(3)
        return original(prompt)

    provider.invoke = blocking
    service = ExplanationService(store, lambda r: load_explanation_record(store, r), client_factory=provider.factory)
    first = service.start(record.run_id)
    assert started.wait(3)
    assert service.start(record.run_id, retry=True).job_id == first.job_id
    release.set()
    wait_job(service, store, record.run_id)
    assert len(provider.calls) == 1
    service.close()
