"""Real durable budget boundaries with mocked SDKs; no provider requests."""

import json
import time
from types import SimpleNamespace

import pytest

from tradingagents.execution import native_model as adapter
from tradingagents.execution.budget import AttemptOutcome, BudgetBucket, BudgetExhausted
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict, CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

SECRET = "test-private-provider-key"
CONFIG = {"llm_provider": "deepseek", "quick_think_llm": "quick", "deep_think_llm": "deep",
          "backend_url": "https://mock.invalid", "llm_max_retries": 5,
          "deepseek_api_key": SECRET, "output_language": "Chinese"}


@pytest.fixture
def journal(tmp_path):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(
        ticker="600519", analysis_date="2026-09-30", llm_provider="deepseek",
        quick_think_llm="quick", deep_think_llm="deep", runtime_semantics_hash="a" * 64,
        metadata={"effective_config_artifact_id": "data:" + "b" * 64},
    )
    store.create_run(snapshot)
    return CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False),
                           {"test": "native-model"})


def main(journal, stage="operating_quality"):
    token = journal.ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="native." + stage,
                                  logical_call_id="native." + stage)
    journal.ledger.mark_dispatched(token)
    return token


def caller(journal, **overrides):
    defaults = {"effective_config": CONFIG, "run_id": journal.ledger.run_id,
                "ledger": journal.ledger, "cancelled": lambda: False,
                "deadline": lambda: time.monotonic() + 30}
    return adapter.NativeModelCaller(**{**defaults, **overrides})


def valid(stage):
    if stage == "challenge":
        return {"challenges": []}
    if stage == "synthesis":
        return {"judgement": "资料有限", "dimensions": [{"dimension": "valuation", "status": "unresolved",
                    "judgement": "估值资料缺失", "limitations": ["估值资料缺失"]}],
                "next_check": "补齐估值资料"}
    return {"hypotheses": [], "unknowns": ["经营分项资料有限"]}


class Slots:
    def __init__(self):
        self.acquires, self.releases = [], 0

    def acquire(self, *, timeout):
        self.acquires.append(timeout)
        return True

    def release(self):
        self.releases += 1


class SDK:
    def __init__(self, responses):
        self.responses = list(responses)
        self.factories, self.prompts = [], []

    def factory(self, **kwargs):
        self.factories.append(kwargs)
        return SimpleNamespace(get_llm=lambda: self)

    def invoke(self, prompt):
        self.prompts.append(prompt)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value()
        if isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        return SimpleNamespace(content=value, usage_metadata={"input_tokens": 10, "output_tokens": 20})


def sdk(monkeypatch, responses):
    stub, slots = SDK(responses), Slots()
    monkeypatch.setattr(adapter, "create_llm_client", stub.factory)
    monkeypatch.setattr(adapter, "global_model_slots", lambda: slots)
    return stub, slots


@pytest.mark.parametrize("stage", tuple(adapter.STAGE_SCHEMAS))
def test_each_stage_uses_one_global_slot_correct_model_and_no_sdk_retries(journal, monkeypatch, stage):
    main(journal, stage)
    stub, slots = sdk(monkeypatch, [valid(stage)])
    result = caller(journal)(stage, {"facts": [], "mode": "company_research"})
    assert adapter.STAGE_SCHEMAS[stage].model_validate(result)
    assert len(stub.prompts) == len(slots.acquires) == slots.releases == 1
    assert stub.factories[0]["model"] == ("deep" if stage == "synthesis" else "quick")
    assert stub.factories[0]["max_retries"] == 0
    assert 0 < stub.factories[0]["timeout"] <= 30
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0
    assert journal.ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 0
    assert SECRET not in stub.prompts[0]
    assert SECRET not in json.dumps(journal.state)
    assert journal.state["native.prompt." + stage]


def test_single_repair_is_durable_measured_and_does_not_echo_invalid_response(journal, monkeypatch):
    main(journal)
    stub, slots = sdk(monkeypatch, ["not JSON " + SECRET, valid("operating_quality")])
    result = caller(journal)("operating_quality", {"facts": []})
    assert result["unknowns"] == ["经营分项资料有限"]
    assert len(stub.prompts) == len(slots.acquires) == slots.releases == 2
    assert SECRET not in stub.prompts[1]
    assert SECRET not in json.dumps(journal.state)
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS) == 2
    repair = next(item for item in journal.ledger.records() if item.bucket == BudgetBucket.STRUCTURED_REPAIR)
    assert repair.input_tokens == 10 and repair.output_tokens == 20 and repair.usage_available
    assert journal.ledger.cached_result("native.operating_quality.repair")["proposal"] == result


def test_second_invalid_output_stops_without_another_repair_or_network_retry(journal, monkeypatch):
    main(journal)
    stub, slots = sdk(monkeypatch, [{"facts": []}, {"unknowns": [SECRET], "unapproved": True}])
    model = caller(journal)
    with pytest.raises(adapter.NativeModelUnavailable, match="response invalid") as failed:
        model("operating_quality", {"facts": []})
    assert SECRET not in str(failed.value)
    with pytest.raises(adapter.NativeModelUnavailable, match="cannot be repeated"):
        model("operating_quality", {"facts": []})
    assert len(stub.prompts) == slots.releases == 2
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0


def test_budget_refused_repair_does_not_call_sdk(journal, monkeypatch):
    main(journal)
    journal.ledger._limits[BudgetBucket.STRUCTURED_REPAIR] = 0
    stub, slots = sdk(monkeypatch, ["malformed"])
    with pytest.raises(BudgetExhausted):
        caller(journal)("operating_quality", {})
    assert len(stub.prompts) == slots.releases == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0


def test_unknown_dispatched_repair_is_consumed_and_never_retried(journal, monkeypatch):
    main(journal)
    token = journal.ledger.reserve(BudgetBucket.STRUCTURED_REPAIR, stage="native.operating_quality",
                                  logical_call_id="native.operating_quality.repair")
    journal.ledger.mark_dispatched(token)
    stub, slots = sdk(monkeypatch, ["malformed"])
    with pytest.raises(adapter.NativeModelUnavailable, match="repair unavailable"):
        caller(journal)("operating_quality", {})
    assert len(stub.prompts) == slots.releases == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1


def test_requires_dispatched_main_without_reserving_main_itself(journal, monkeypatch):
    stub, _ = sdk(monkeypatch, [])
    with pytest.raises(adapter.NativeModelUnavailable, match="MAIN reservation"):
        caller(journal)("operating_quality", {})
    assert stub.factories == []
    assert journal.ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0


def test_network_exception_is_sanitized_no_repair_and_no_repeat(journal, monkeypatch):
    main(journal)
    stub, slots = sdk(monkeypatch, [RuntimeError("authorization failed " + SECRET)])
    model = caller(journal)
    with pytest.raises(adapter.NativeModelUnavailable, match="request failed") as failed:
        model("operating_quality", {})
    assert SECRET not in str(failed.value)
    assert failed.value.__suppress_context__
    with pytest.raises(adapter.NativeModelUnavailable, match="cannot be repeated"):
        model("operating_quality", {})
    assert len(stub.prompts) == slots.releases == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0
    assert SECRET not in json.dumps(journal.state)


def test_prompt_digest_is_immutable_and_key_order_does_not_change_it(journal, monkeypatch):
    main(journal)
    stub, _ = sdk(monkeypatch, [valid("operating_quality")])
    model = caller(journal)
    first = model("operating_quality", {"facts": [], "mode": "company_research"})
    assert model("operating_quality", {"mode": "company_research", "facts": []}) == first
    with pytest.raises(CatalystCheckpointConflict, match="prompt or dispatch changed"):
        model("operating_quality", {"facts": [], "mode": "holding_review"})
    assert len(stub.prompts) == 1


def test_cached_repair_survives_interruption_before_adapter_final_cache(journal, monkeypatch):
    main(journal)
    stub, _ = sdk(monkeypatch, ["malformed", valid("operating_quality")])
    model = caller(journal)
    expected = model("operating_quality", {})
    journal.state["results"].pop("native.adapter.operating_quality")
    journal.persist()
    assert model("operating_quality", {}) == expected
    assert len(stub.prompts) == 2


@pytest.mark.parametrize("repair_only", [False, True])
def test_readonly_recovery_accepts_unknown_main_under_cancellation_and_expired_deadline(journal, monkeypatch, repair_only):
    main(journal)
    responses = ["malformed", valid("operating_quality")] if repair_only else [valid("operating_quality")]
    stub, _ = sdk(monkeypatch, responses)
    expected = caller(journal)("operating_quality", {"facts": []})
    if repair_only:
        journal.state["results"].pop("native.adapter.operating_quality")
        journal.persist()
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert restored.ledger.records()[0].outcome == AttemptOutcome.UNKNOWN
    model = caller(restored, cancelled=lambda: True, deadline=lambda: -1)
    before_state = json.dumps(restored.state, sort_keys=True)
    before_events = len(restored.observer.store.read_events(restored.ledger.run_id))
    assert model.recover_cached("operating_quality", {"facts": []}) == expected
    assert json.dumps(restored.state, sort_keys=True) == before_state
    assert len(restored.observer.store.read_events(restored.ledger.run_id)) == before_events
    assert len(stub.prompts) == len(responses)
    assert restored.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0
    with pytest.raises(adapter.NativeModelCancelled):
        model("operating_quality", {"facts": []})


def test_readonly_recovery_missing_cache_is_noop_and_changed_prompt_is_rejected(journal, monkeypatch):
    stub, _ = sdk(monkeypatch, [])
    inactive = caller(journal, cancelled=lambda: True, deadline=lambda: -1)
    before_state = json.dumps(journal.state, sort_keys=True)
    assert inactive.recover_cached("operating_quality", {}) is None
    assert json.dumps(journal.state, sort_keys=True) == before_state
    assert stub.factories == []
    main(journal)
    stub.responses.append(valid("operating_quality"))
    caller(journal)("operating_quality", {})
    with pytest.raises(CatalystCheckpointConflict, match="cached prompt mismatch"):
        inactive.recover_cached("operating_quality", {"facts": []})
    assert len(stub.prompts) == 1


def test_cancelled_before_dispatch_does_not_create_sdk(journal, monkeypatch):
    main(journal)
    stub, _ = sdk(monkeypatch, [])
    with pytest.raises(adapter.NativeModelCancelled):
        caller(journal, cancelled=lambda: True)("operating_quality", {})
    assert stub.factories == []


def test_cancellation_while_waiting_for_slot_does_not_release_unacquired_slot(journal, monkeypatch):
    main(journal)
    stub, slots = sdk(monkeypatch, [])
    stopped = [False]
    def acquire(**kwargs):
        stopped[0] = True
        return False
    monkeypatch.setattr(slots, "acquire", acquire)
    with pytest.raises(adapter.NativeModelCancelled):
        caller(journal, cancelled=lambda: stopped[0])("operating_quality", {})
    assert stub.factories == [] and slots.releases == 0


def test_cancellation_after_response_keeps_dispatch_but_no_invalid_public_result(journal, monkeypatch):
    main(journal)
    stopped = [False]
    def response():
        stopped[0] = True
        return valid("operating_quality")
    stub, slots = sdk(monkeypatch, [response])
    model = caller(journal, cancelled=lambda: stopped[0])
    with pytest.raises(adapter.NativeModelCancelled):
        model("operating_quality", {})
    stopped[0] = False
    with pytest.raises(adapter.NativeModelUnavailable, match="cannot be repeated"):
        model("operating_quality", {})
    assert len(stub.prompts) == slots.releases == 1
    assert journal.ledger.cached_result("native.adapter.operating_quality") is None


@pytest.mark.parametrize("deadline", [99, float("nan"), float("inf"), True])
def test_invalid_or_elapsed_deadline_blocks_sdk(journal, monkeypatch, deadline):
    main(journal)
    stub, _ = sdk(monkeypatch, [])
    monkeypatch.setattr(adapter.time, "monotonic", lambda: 100)
    with pytest.raises((TimeoutError, adapter.NativeModelUnavailable)):
        caller(journal, deadline=lambda: deadline)("operating_quality", {})
    assert stub.factories == []


def test_elapsed_deadline_after_acquiring_slot_releases_it(journal, monkeypatch):
    main(journal)
    now = [100]
    stub, slots = sdk(monkeypatch, [])
    monkeypatch.setattr(adapter.time, "monotonic", lambda: now[0])
    def acquire(**kwargs):
        now[0] = 102
        return True
    monkeypatch.setattr(slots, "acquire", acquire)
    with pytest.raises(TimeoutError):
        caller(journal, deadline=lambda: 101)("operating_quality", {})
    assert slots.releases == 1 and stub.factories == []


def test_checkpoint_failure_at_dispatch_prevents_invoke(journal, monkeypatch):
    main(journal)
    stub, slots = sdk(monkeypatch, [])
    original = journal.put
    def put(key, value):
        if key.endswith(".dispatched"):
            raise CatalystCheckpointConflict("persistence failed")
        original(key, value)
    monkeypatch.setattr(journal, "put", put)
    with pytest.raises(CatalystCheckpointConflict, match="persistence failed"):
        caller(journal)("operating_quality", {})
    assert stub.prompts == [] and slots.releases == 1


def test_duplicate_json_keys_trigger_the_one_structural_repair(journal, monkeypatch):
    main(journal)
    stub, _ = sdk(monkeypatch, ['{"hypotheses":[],"hypotheses":[],"unknowns":[]}', valid("operating_quality")])
    caller(journal)("operating_quality", {})
    assert len(stub.prompts) == 2


def test_reasoning_blocks_are_not_used_as_structured_output(journal, monkeypatch):
    main(journal)
    text = json.dumps(valid("operating_quality"))
    stub, _ = sdk(monkeypatch, [[{"type": "reasoning", "text": SECRET}, {"type": "text", "text": text}]])
    result = caller(journal)("operating_quality", {})
    assert result["hypotheses"] == []
    assert SECRET not in json.dumps(journal.state)
    assert len(stub.prompts) == 1
