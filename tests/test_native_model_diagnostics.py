"""Failure categories and secret exclusion with durable, offline SDK doubles."""

import json
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas._native_stage import SpecialistProposalV1
from tradingagents.execution import native_model as adapter
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.native_model_diagnostics import safe_model_diagnostic
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

SECRET = "private-invalid-value-and-field-name"


def test_schema_diagnostic_excludes_input_context_message_and_unknown_field_names():
    with pytest.raises(ValidationError) as caught:
        SpecialistProposalV1.model_validate({"unknowns": [SECRET * 30], SECRET: SECRET})
    diagnostic = safe_model_diagnostic("operating_quality", "main", "response_invalid",
        caught.value, schema=SpecialistProposalV1)
    assert diagnostic["category"] == "schema_validation"
    assert {issue["code"] for issue in diagnostic["issues"]} == {"string_too_long", "extra_forbidden"}
    assert diagnostic["issues"][0]["path"] == ["unknowns", 0]
    assert diagnostic["issues"][1]["path"] == ["<undeclared>"]
    assert SECRET not in json.dumps(diagnostic)


def test_http_diagnostic_keeps_numeric_status_and_only_known_codes():
    exc = RuntimeError(SECRET)
    exc.status_code, exc.code = 400, SECRET
    result = safe_model_diagnostic("synthesis", "main", "request_failed", exc)
    assert result["upstream_status"] == 400
    assert "upstream_code" not in result
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("error,category,code", [
    (ValueError("synthesis dimension references outside allowed claims"), "reference_validation", "dimension_claim_reference"),
    (ValueError("duplicate JSON key"), "invalid_json", "duplicate_json_key"),
    (TimeoutError(SECRET), "request_timeout", None),
])
def test_host_binding_and_timeout_errors_use_fixed_labels(error, category, code):
    result = safe_model_diagnostic("synthesis", "main", "request_failed", error)
    assert result["category"] == category
    assert result.get("detail_code") == code
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("request_error", [False, True])
def test_durable_failures_distinguish_main_json_repair_schema_and_request(tmp_path, monkeypatch, request_error):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker="600418.SS", analysis_date="2026-10-10",
        llm_provider="deepseek", quick_think_llm="quick", deep_think_llm="deep",
        runtime_semantics_hash="a" * 64, metadata={"effective_config_artifact_id": "data:" + "b" * 64})
    store.create_run(snapshot)
    journal = CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False),
        {"test": "safe-native-diagnostics"})
    token = journal.ledger.reserve(BudgetBucket.MAIN_ANALYSIS,
        stage="native.operating_quality", logical_call_id="native.operating_quality")
    journal.ledger.mark_dispatched(token)
    responses = iter(["not JSON " + SECRET, json.dumps({"unknowns": [SECRET * 30]})])
    def invoke(prompt):
        if request_error:
            error = RuntimeError(SECRET)
            error.status_code = 429
            raise error
        return SimpleNamespace(content=next(responses), response_metadata={"finish_reason": "stop"})
    monkeypatch.setattr(adapter, "create_llm_client", lambda **kwargs: SimpleNamespace(
        get_llm=lambda: SimpleNamespace(invoke=invoke)))
    model = adapter.NativeModelCaller(effective_config={"llm_provider": "deepseek",
        "quick_think_llm": "quick", "deep_think_llm": "deep"}, run_id=snapshot.run_id,
        ledger=journal.ledger, cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)
    with pytest.raises(adapter.NativeModelUnavailable):
        model("operating_quality", {"facts": []})
    failures = journal.state["native.model_diagnostics"]
    if request_error:
        assert failures["operating_quality.main"]["category"] == "request_failed"
        assert failures["operating_quality.main"]["upstream_status"] == 429
        assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0
    else:
        assert failures["operating_quality.main"]["category"] == "invalid_json"
        assert failures["operating_quality.repair"]["category"] == "schema_validation"
        assert failures["operating_quality.repair"]["issues"][0]["path"] == ["unknowns", 0]
        assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert SECRET not in json.dumps(journal.state)
