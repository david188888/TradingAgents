"""Native HTTP request gates with no model/provider/background execution."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tradingagents.analysts import ANALYST_WIRE_KEYS
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.research.native_evidence_policy import NativeEvidencePolicyV1
from tradingagents.web.api import create_app
from tradingagents.web.schemas import RunCreateRequest
from tradingagents.web.store import RunStore

BODY = {
    "ticker": "600803.SS", "analysis_date": "2026-07-18", "asset_type": "stock",
    "research_profile": "evidence_v1", "llm_provider": "openai",
    "quick_think_llm": "gpt-5.4-mini", "deep_think_llm": "gpt-5.5", "output_language": "Chinese",
}
HOLDING = {"ticker": "600803.SS", "quantity": 100, "average_cost": 20,
    "facts_as_of": "2026-07-18", "original_thesis": "等待经营兑现。"}


class RecordingManager:
    """Only capture the validated neutral request, without simulating a run."""

    def __init__(self, store):
        self.store, self.requests = store, []

    def start(self, request, *, configured_keys):
        self.requests.append(request)
        return SimpleNamespace(as_dict=lambda: {"run_id": "mock-accepted", "mode": request.mode,
            "research_profile": request.research_profile})

    def start_batch(self, prepared, *, configured_keys, concurrency):
        self.requests.extend(request for request, _ in prepared)
        self.batch_items = [item for _, item in prepared]
        return SimpleNamespace(as_dict=lambda: {"batch_id": "mock-batch", "concurrency": concurrency})


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "true")
    monkeypatch.setenv("TRADINGAGENTS_CATALYST_PROFILE_ENABLED", "false")
    counter = 0

    def build(checkpoint_available=True, connectivity_check=lambda _: None):
        nonlocal counter
        counter += 1
        store = RunStore(tmp_path / str(counter))
        manager = RecordingManager(store)
        client = TestClient(create_app(manager=manager, store=store,
            environment={"OPENAI_API_KEY": "offline-placeholder"}, checkpoint_available=checkpoint_available,
            recover_startup=False, connectivity_check=connectivity_check))
        return client, manager

    return build


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_three_native_modes_forward_independent_policy_and_trimmed_question(factory, mode):
    client, manager = factory()
    payload = {**BODY, "mode": mode, "research_question": "  哪些证据会改变判断？  "}
    if mode == "holding_review":
        payload["holding"] = HOLDING
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201, response.text
    request = manager.requests[0]
    assert request.mode == mode and request.research_profile == "evidence_v1"
    assert request.research_question == "哪些证据会改变判断？"
    assert isinstance(request.evidence_policy, NativeEvidencePolicyV1)
    assert request.catalyst_policy is None
    assert request.evidence_policy.as_identity() == NativeEvidencePolicyV1().as_identity()
    assert "forward_window_max_calendar_days" not in request.profile_identity()["evidence_policy"]
    if mode == "holding_review":
        assert request.holding_context.original_thesis == HOLDING["original_thesis"]
        assert request.holding_context.cash is None and request.holding_context.total_account_value is None
    else:
        assert request.holding_context is None


@pytest.mark.parametrize("changes,code", [
    ({"mode": "holding_review"}, "holding_required"),
    ({"mode": "catalyst_research", "holding": HOLDING}, "holding_not_allowed"),
    ({"mode": "company_research", "holding": HOLDING}, "holding_not_allowed"),
    ({"ticker": "AAPL"}, "evidence_market_unsupported"),
    ({"ticker": "510300.SS"}, "evidence_market_unsupported"),
    ({"ticker": "000001.SS"}, "evidence_market_unsupported"),
    ({"horizon": "long"}, "evidence_horizon_not_supported"),
    ({"research_depth": 3}, "evidence_legacy_scheduling_params_not_applicable"),
    ({"selected_analysts": ["market"]}, "evidence_legacy_scheduling_params_not_applicable"),
    ({"research_question": "a" * 401}, "validation_error"),
    ({"evidence_policy": {"forward_window_max_calendar_days": 84}}, "validation_error"),
    ({"evidence_policy": {"price_history_trading_days": 200}}, "validation_error"),
    ({"mode": "holding_review", "holding": {**HOLDING, "ticker": "000001.SZ"}}, "holding_ticker_mismatch"),
])
def test_rejected_native_requests_never_enqueue(factory, changes, code):
    client, manager = factory()
    response = client.post("/api/runs", json={**BODY, **changes})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code
    assert manager.requests == [] and manager.store.list_runs() == []


@pytest.mark.parametrize("profile", ["classic", "catalyst_v1"])
def test_old_profiles_are_retired_for_creation(factory, profile, monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_CATALYST_PROFILE_ENABLED", "true")
    client, manager = factory()
    response = client.post("/api/runs", json={**BODY, "research_profile": profile, "mode": "catalyst_research"})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "research_profile_retired"
    assert manager.requests == []


@pytest.mark.parametrize("profile", ["classic", "catalyst_v1"])
def test_native_policy_cannot_be_used_by_old_profiles(factory, profile):
    client, manager = factory()
    response = client.post("/api/runs", json={**BODY, "research_profile": profile,
        "evidence_policy": NativeEvidencePolicyV1().as_identity()})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert manager.requests == []


def test_explicit_false_overrides_config(factory, monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_EVIDENCE_ENABLED")
    monkeypatch.setitem(DEFAULT_CONFIG, "evidence_profile_enabled", False)
    client, manager = factory()
    for _ in range(2):
        response = client.post("/api/runs", json=BODY)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "evidence_profile_unavailable"
        monkeypatch.setitem(DEFAULT_CONFIG, "evidence_profile_enabled", True)
        monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "false")
    assert manager.requests == []


def test_config_flag_accepts_native_without_enabling_old_catalyst(factory, monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_EVIDENCE_ENABLED")
    monkeypatch.setitem(DEFAULT_CONFIG, "evidence_profile_enabled", True)
    client, manager = factory()
    assert client.post("/api/runs", json=BODY).status_code == 201
    assert manager.requests[0].research_profile == "evidence_v1"
    payload = client.get("/api/config").json()
    assert payload["research_profiles"]["evidence_v1"]["supported"] is True
    assert payload["research_profiles"]["catalyst_v1"]["supported"] is False


def test_native_checkpoint_is_independent_of_classic_checkpointer(factory):
    client, manager = factory(checkpoint_available=False)
    response = client.post("/api/runs", json={**BODY, "checkpoint_enabled": True})
    assert response.status_code == 201, response.text
    assert manager.requests[0].effective_config["checkpoint_enabled"] is True
    config = client.get("/api/config").json()
    assert config["checkpoint_available"] is False
    assert config["research_profiles"]["evidence_v1"]["checkpoint_available"] is True
    response = client.post("/api/runs", json={**BODY, "research_profile": "classic", "checkpoint_enabled": True})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "research_profile_retired"


def test_default_native_params_and_inferred_holding_mode(factory):
    client, manager = factory()
    response = client.post("/api/runs", json={**BODY, "selected_analysts": list(ANALYST_WIRE_KEYS),
        "research_depth": 1, "horizon": "medium", "holding": HOLDING,
        "evidence_policy": NativeEvidencePolicyV1().as_identity()})
    assert response.status_code == 201, response.text
    assert manager.requests[0].mode == "holding_review"


def test_omitted_profile_uses_native_web_default(factory):
    client, manager = factory()
    body = {key: value for key, value in BODY.items() if key != "research_profile"}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 201, response.text
    request = manager.requests[0]
    assert request.research_profile == "evidence_v1" and request.evidence_policy is not None
    assert request.catalyst_policy is None
    assert RunCreateRequest.model_validate(body).research_profile == "evidence_v1"


def test_native_admission_precedes_connectivity_probe(factory, monkeypatch):
    probes = []
    client, manager = factory(connectivity_check=lambda ticker: probes.append(ticker))
    response = client.post("/api/runs", json={**BODY, "ticker": "AAPL"})
    assert response.status_code == 422
    assert probes == [] and manager.requests == []
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "false")
    assert client.post("/api/runs", json=BODY).status_code == 403
    assert probes == [] and manager.requests == []
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "true")
    assert client.post("/api/runs", json=BODY).status_code == 201
    assert probes == [manager.requests[0].ticker] == ["600803.SS"]


def test_batch_forwards_native_default_question_and_policy(factory, monkeypatch):
    import tradingagents.web.api as api

    resolved = []
    def resolve(raw, index):
        resolved.append(raw)
        return {"ticker": "600803.SS", "company_name": "新奥股份", "market": "china"}
    monkeypatch.setattr(api, "_resolve_batch_input", resolve)
    probes = []
    client, manager = factory(connectivity_check=probes.append)
    config = {key: value for key, value in BODY.items() if key not in {"ticker", "research_profile"}}
    config.update(research_question="  核验经营兑现😀  ", evidence_policy=NativeEvidencePolicyV1().as_identity())
    response = client.post("/api/batches", json={"entries": [{"input": "600803", "config": config}], "concurrency": 1})
    assert response.status_code == 201, response.text
    request = manager.requests[0]
    assert request.research_profile == "evidence_v1" and request.mode == "company_research"
    assert request.research_question == "核验经营兑现😀"
    assert request.evidence_policy == NativeEvidencePolicyV1()
    assert manager.batch_items[0].config["research_profile"] == "evidence_v1"
    assert resolved == ["600803"] and probes == ["600803.SS"]


@pytest.mark.parametrize("profile,disabled,status", [("classic", False, 410), ("catalyst_v1", False, 410), ("evidence_v1", True, 403)])
def test_batch_admission_precedes_resolution_probe_and_enqueue(factory, monkeypatch, profile, disabled, status):
    import tradingagents.web.api as api

    monkeypatch.setattr(api, "_resolve_batch_input", lambda *args: pytest.fail("rejected batch resolved a company"))
    probes = []
    client, manager = factory(connectivity_check=probes.append)
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "false" if disabled else "true")
    config = {key: value for key, value in BODY.items() if key != "ticker"}
    config["research_profile"] = profile
    response = client.post("/api/batches", json={"entries": [{"input": "600803", "config": config}]})
    assert response.status_code == status, response.text
    assert probes == [] and manager.requests == [] and manager.store.list_runs() == []


@pytest.mark.parametrize("thesis", ["x" * 4001, 12, True, [], {}])
def test_native_thesis_validation_precedes_probe_and_enqueue(factory, thesis):
    probes = []
    client, manager = factory(connectivity_check=lambda ticker: probes.append(ticker))
    response = client.post("/api/runs", json={**BODY, "mode": "holding_review",
        "holding": {**HOLDING, "original_thesis": thesis}})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "holding_original_thesis_invalid"
    assert detail["fields"] == ["holding.original_thesis"]
    assert probes == [] and manager.requests == [] and manager.store.list_runs() == []


@pytest.mark.parametrize("thesis", [None, "", "x" * 4000])
def test_native_thesis_missing_or_at_size_boundary_remains_accepted(factory, thesis):
    client, manager = factory()
    response = client.post("/api/runs", json={**BODY, "mode": "holding_review",
        "holding": {**HOLDING, "original_thesis": thesis}})
    assert response.status_code == 201, response.text
    assert manager.requests[0].holding_context.original_thesis == (thesis or None)


@pytest.mark.parametrize("thesis", ["x" * 4001, 12])
def test_retired_creation_is_rejected_before_thesis_normalization(factory, thesis):
    client, manager = factory()
    response = client.post("/api/runs", json={**BODY, "research_profile": "classic", "mode": "holding_review",
        "holding": {**HOLDING, "original_thesis": thesis}})
    assert response.status_code == 410, response.text
    assert response.json()["detail"]["code"] == "research_profile_retired"
    assert manager.requests == []
