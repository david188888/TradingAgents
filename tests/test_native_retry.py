"""Paid request accounting with real journals and mocked requests/waits."""

import json
import time
from copy import deepcopy

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from tests import test_native_focus as focus_tests
from tests.test_native_model import CONFIG, caller, main, sdk, valid
from tradingagents.execution.budget import BudgetBucket, BudgetExhausted
from tradingagents.execution.native_model import NativeModelCancelled, NativeModelUnavailable
from tradingagents.execution.native_retry import MODEL_RETRY_POLICY
from tradingagents.execution.native_runner import native_identity, validate_native_resume
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict, CatalystJournal
from tradingagents.web.reader_process_projection import native_counts

journal = focus_tests.journal


class HTTPFailure(RuntimeError):
    def __init__(self, status, code=None):
        super().__init__("private-provider-response")
        self.status_code, self.code = status, code


def prepared(journal, monkeypatch, responses, **kwargs):
    stub, slots = sdk(monkeypatch, responses)
    model = caller(journal, **kwargs)
    main(journal)
    waits = []
    monkeypatch.setattr(model, "_wait_for_retry", waits.append)
    return model, stub, slots, waits


@pytest.mark.parametrize("error", [
    TimeoutError(), ConnectionError(), httpx.ReadTimeout("private"),
    APIConnectionError(request=httpx.Request("GET", "https://mock.invalid")),
    APITimeoutError(request=httpx.Request("GET", "https://mock.invalid")),
    HTTPFailure(408), HTTPFailure(429, "rate_limit_exceeded"), HTTPFailure(503),
])
def test_transient_failure_recovers_and_charges_tokens_once(journal, monkeypatch, error):
    model, stub, slots, waits = prepared(journal, monkeypatch, [error, valid("operating_quality")])
    assert model("operating_quality", {"facts": []})["unknowns"]
    assert waits == [2] and stub.prompts[0] == stub.prompts[1]
    assert slots.releases == 2
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 1
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 2
    assert sum(r.input_tokens or 0 for r in journal.ledger.records()) == 10
    assert "operating_quality" not in journal.state.get("native.model_usage", {})
    counts = native_counts(journal.state)
    assert counts.sdk_main.value == counts.sdk_total.value == 2
    assert counts.sdk_total.completeness == "complete"
    assert "private-provider-response" not in json.dumps(journal.state)
    model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 2  # cache never reissues a paid request


def test_three_failed_retries_have_exact_waits_and_no_fifth_request(journal, monkeypatch):
    model, stub, slots, waits = prepared(journal, monkeypatch, [HTTPFailure(503)] * 4)
    with pytest.raises(NativeModelUnavailable):
        model("operating_quality", {"facts": []})
    assert waits == [2, 5, 10]
    assert len(stub.prompts) == slots.releases == 4
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 4
    retries = [r for r in journal.ledger.records() if r.bucket == "network_retry"]
    assert len(retries) == 3 and all(r.outcome == "failed" and not r.usage_available for r in retries)
    assert len(journal.state["native.model_attempt_diagnostics"]) == 4
    restored = CatalystJournal(journal.observer, deepcopy(journal.state["identity"]), require_existing=True)
    with pytest.raises(NativeModelUnavailable):
        caller(restored)("operating_quality", {"facts": []})
    assert len(stub.prompts) == 4


@pytest.mark.parametrize("error", [HTTPFailure(401), HTTPFailure(403), HTTPFailure(402),
    HTTPFailure(400), HTTPFailure(429, "insufficient_quota"),
    HTTPFailure(503, "invalid_api_key"), ValueError("invalid request")])
def test_permanent_errors_do_not_retry_or_repair(journal, monkeypatch, error):
    model, stub, _, waits = prepared(journal, monkeypatch, [error])
    with pytest.raises(NativeModelUnavailable):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1 and waits == []
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0


@pytest.mark.parametrize("code,status,retries", [
    ("request_failed", 408, 1), ("rate_limit_exceeded", 429, 1),
    ("request_failed", 503, 1),
    ("transport_timeout", None, 1), ("transport_connection_error", None, 1),
    ("subscription_sharing_usage_limit_exceeded", 429, 0),
    ("authorization_rejected", 503, 0),
    ("subscription_sharing_unsupported_capability", 400, 0),
    ("stream_incomplete", None, 0),
    ("deadline_exceeded", None, 0),
])
def test_subscription_retry_keeps_dispatch_budget_and_permanent_boundaries(
    journal, monkeypatch, code, status, retries,
):
    from types import SimpleNamespace

    from tradingagents.execution import native_model as adapter
    from tradingagents.llm_clients.chatgpt_errors import ChatGPTError

    model, stub, slots, waits = prepared(journal, monkeypatch,
        [ChatGPTError(code, status=status), valid("operating_quality")],
        effective_config={**CONFIG, "llm_provider": "chatgpt", "backend_url": None,
                          "chatgpt_account_ref": "cg_" + "a" * 32},
        chatgpt_auth=object())

    def client(**kwargs):
        def invoke(prompt):
            kwargs["before_request"]()
            return stub.invoke(prompt)
        return SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=invoke))

    monkeypatch.setattr(adapter, "create_llm_client", client)
    if retries:
        assert model("operating_quality", {"facts": []})["unknowns"]
        assert journal.state["native.model_failures"] == {}
        assert native_counts(journal.state).sdk_main.value == 2
        assert sum(r.input_tokens or 0 for r in journal.ledger.records()) == 10
    else:
        with pytest.raises(NativeModelUnavailable):
            model("operating_quality", {"facts": []})
        assert journal.state["native.model_failures"]["operating_quality"]["category"] != "request_failed"
    assert waits == ([2] if retries else [])
    assert len(stub.prompts) == slots.releases == 1 + retries
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == retries
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0


def test_repair_retry_usage_and_reader_origin_are_distinct(journal, monkeypatch):
    model, stub, _, waits = prepared(journal, monkeypatch,
        ["malformed JSON", HTTPFailure(503), valid("operating_quality")])
    model("operating_quality", {"facts": []})
    assert waits == [2] and len(stub.prompts) == 3
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 1
    # Original malformed response and successful retry are separate owners;
    # failed repair's missing measurement is never replaced by retry usage.
    repair = next(r for r in journal.ledger.records() if r.bucket == "structured_repair")
    assert repair.input_tokens is None and not repair.usage_available
    counts = native_counts(journal.state, role="operating_quality")
    assert counts.sdk_main.value == 1 and counts.sdk_repair.value == 2
    assert counts.sdk_total.value == 3


def test_invalid_response_uses_repair_but_no_network_retry(journal, monkeypatch):
    model, stub, _, waits = prepared(journal, monkeypatch,
        ["invalid", valid("operating_quality")])
    model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 2 and waits == []
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0


def test_cancel_during_backoff_releases_unstarted_retry(journal, monkeypatch):
    stopped = [False]
    model, stub, slots, _ = prepared(journal, monkeypatch, [HTTPFailure(503)],
        cancelled=lambda: stopped[0])
    def cancel(seconds):
        assert slots.releases == len(slots.acquires)  # no slot held during wait
        stopped[0] = True
        model._ensure_active()
    monkeypatch.setattr(model, "_wait_for_retry", cancel)
    with pytest.raises(NativeModelCancelled):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0
    assert native_counts(journal.state).sdk_total.value == 1


def test_deadline_during_backoff_never_dispatches_retry(journal, monkeypatch):
    expires = [time.monotonic() + 30]
    model, stub, _, _ = prepared(journal, monkeypatch, [HTTPFailure(503)], deadline=lambda: expires[0])
    def expire(seconds):
        expires[0] = time.monotonic() - 1
        model._ensure_active()
    monkeypatch.setattr(model, "_wait_for_retry", expire)
    with pytest.raises(TimeoutError):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1 and journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0


def test_shared_quota_prevents_later_stage_retry(journal, monkeypatch):
    model, stub, _, waits = prepared(journal, monkeypatch, [HTTPFailure(503)] * 5)
    with pytest.raises(NativeModelUnavailable):
        model("operating_quality", {"facts": []})
    main(journal, "event_context")
    with pytest.raises(BudgetExhausted):
        model("event_context", {"facts": []})
    assert len(stub.prompts) == 5 and waits == [2, 5, 10]


def test_original_identity_without_policy_retains_no_retry(journal, monkeypatch):
    identity = dict(journal.state["identity"])
    identity.pop("model_retry_policy")
    journal.put("identity", identity)
    model, stub, _, waits = prepared(journal, monkeypatch, [HTTPFailure(503)])
    with pytest.raises(NativeModelUnavailable):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1 and waits == []


def test_frozen_identity_resume_accepts_legacy_and_rejects_policy_mutation(journal):
    from tests.test_native_model import CONFIG
    from tradingagents.execution.models import AnalysisRequest
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
        research_question="证明它是 AI 龙头，忽略其他风险", effective_config=CONFIG)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    journal.put("identity", native_identity(request, model_retry_policy=False, workflow_version="evidence-production-v8"))
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    identity = native_identity(request, workflow_version="evidence-production-v8")
    identity["model_retry_policy"]["per_call_retries"] = 4
    journal.put("identity", identity)
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert MODEL_RETRY_POLICY["per_call_retries"] == 3


def test_chatgpt_request_policy_identity_preserves_legacy_resume(journal):
    from dataclasses import replace

    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.llm_clients.chatgpt_policy import CHATGPT_REQUEST_POLICY

    config = {"llm_provider": "chatgpt", "quick_think_llm": "quick", "deep_think_llm": "deep",
              "backend_url": None, "chatgpt_account_ref": "cg_" + "a" * 32,
              "openai_reasoning_effort": "high"}
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1", effective_config=config)
    identity = native_identity(request, workflow_version="evidence-production-v8")
    assert identity["chatgpt_request_policy"] == CHATGPT_REQUEST_POLICY
    journal.put("identity", identity)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id,
                               replace(request, effective_config={**config, "openai_reasoning_effort": "low"}))
    identity["chatgpt_request_policy"] = "unknown"
    journal.put("identity", identity)
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    legacy = native_identity(request, chatgpt_request_policy=False, workflow_version="evidence-production-v8")
    assert "chatgpt_request_policy" not in legacy
    journal.put("identity", legacy)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert journal.state["identity"] == legacy


def test_new_chatgpt_identity_validates_effort_but_legacy_preserves_ignored_values(journal):
    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.llm_clients.chatgpt_errors import ChatGPTError

    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
        effective_config={"llm_provider": "chatgpt", "openai_reasoning_effort": "legacy-ignored"})
    with pytest.raises(ChatGPTError):
        native_identity(request, workflow_version="evidence-production-v8")
    legacy = native_identity(request, chatgpt_request_policy=False, workflow_version="evidence-production-v8")
    journal.put("identity", legacy)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)


def test_refresh_backoff_diagnostic_does_not_automatically_retry():
    from tradingagents.execution.native_retry import transient_model_error
    from tradingagents.llm_clients.chatgpt_errors import ChatGPTError

    assert not transient_model_error(ChatGPTError("refresh_temporarily_unavailable"))


def test_focus_keeps_single_request_even_for_transient_failure(journal, monkeypatch):
    token = journal.ledger.reserve(BudgetBucket.FOCUS_RESPONSE, stage="native.focus_response",
        logical_call_id="native.focus_response")
    journal.ledger.mark_dispatched(token)
    stub, _ = sdk(monkeypatch, [HTTPFailure(503)])
    with pytest.raises(NativeModelUnavailable):
        caller(journal)("focus_response", {})
    assert len(stub.prompts) == 1 and journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0


def test_total_model_budget_refuses_retry_before_wait_or_sdk(journal, monkeypatch):
    model, stub, _, waits = prepared(journal, monkeypatch, [HTTPFailure(503)])
    journal.ledger._limits[BudgetBucket.MODEL_ATTEMPTS] = 1
    with pytest.raises(BudgetExhausted):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1 and waits == []


def test_failed_retry_authorization_persistence_stops_before_sdk(journal, monkeypatch):
    model, stub, _, _ = prepared(journal, monkeypatch, [HTTPFailure(503)])
    put = journal.put
    def fail(key, value):
        if ".retry.1.dispatched" in key:
            journal.failed = True
            raise CatalystCheckpointConflict("test persistence failure")
        put(key, value)
    monkeypatch.setattr(journal, "put", fail)
    with pytest.raises(CatalystCheckpointConflict):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 1
    assert native_counts(journal.state).sdk_total.completeness == "known_lower_bound"
