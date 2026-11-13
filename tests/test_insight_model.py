"""Request boundary uses native formats, durable budgets and no lost-call resend."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from tests.v9_fixtures import journal_setup as setup
from tradingagents.execution.insight_model import InsightModelCaller, InsightUnavailable
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.llm_clients.factory import create_llm_client


def caller(journal, **kwargs):
    return InsightModelCaller(effective_config={'llm_provider': 'openai',
        'quick_think_llm': 'gpt-4o', 'deep_think_llm': 'gpt-4o'}, run_id=journal.observer.run_id,
        ledger=journal.ledger, cancelled=kwargs.get('cancelled', lambda: False),
        deadline=lambda: time.monotonic() + 60)


def test_fixed_schema_dispatch_and_usage_are_durable(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    seen = []

    def invoke(**kwargs):
        seen.append(kwargs)
        kwargs['dispatch']()
        kwargs['on_usage']({'input_tokens': 10, 'output_tokens': 20})
        return SimpleNamespace(content='{"insights": []}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    assert caller(journal)('operating_quality', {'evidence': []}) == {'insights': []}
    shape = seen[0]['response_format']['json_schema']['schema']
    assert set(shape['properties']) == {'insights', 'search_requests', 'capability_requests'}
    request = shape['$defs']['CapabilityRequest']
    assert request['required'] == ['capability_id', 'query', 'gap_reason']
    assert request['additionalProperties'] is False
    assert 'field_path' not in str(shape)
    assert journal.state['insight.model_usage']['operating_quality.main']['input_tokens'] == 10
    assert len(journal.ledger.records()) == 1
    with pytest.raises(InsightUnavailable, match='response_unknown'):
        caller(journal)('operating_quality', {'evidence': []})
    assert len(seen) == 1


def test_malformed_response_is_safe_and_no_automatic_retry(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)

    def invoke(**kwargs):
        kwargs['dispatch']()
        return SimpleNamespace(content='private raw invalid text')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    with pytest.raises(InsightUnavailable, match='response_json_invalid'):
        caller(journal)('operating_quality', {})
    assert 'private raw' not in str(journal.state)
    assert len(journal.ledger.records()) == 1


def test_cancel_before_dispatch_consumes_no_model_attempt(tmp_path):
    _, journal, _ = setup(tmp_path)
    with pytest.raises(AnalysisCancelled):
        caller(journal, cancelled=lambda: True)('operating_quality', {})
    assert len(journal.ledger.records()) == 0


def test_each_stage_dispatches_its_configured_provider_and_model(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    seen = []

    def invoke(**kwargs):
        seen.append((kwargs['config']['llm_provider'], kwargs['model']))
        kwargs['dispatch']()
        return SimpleNamespace(content='{"insights": []}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    delegate = InsightModelCaller(effective_config={'llm_provider': 'openai', 'quick_think_llm': 'gpt-4o',
        'deep_think_llm': 'gpt-4o', 'stage_models': {'challenge': {'provider': 'deepseek', 'model': 'deepseek-v4-pro'}}},
        run_id=journal.observer.run_id, ledger=journal.ledger, cancelled=lambda: False,
        deadline=lambda: time.monotonic() + 60)
    delegate('operating_quality', {})
    delegate('challenge', {})
    assert seen == [('openai', 'gpt-4o'), ('deepseek', 'deepseek-v4-pro')]
    assert journal.state['insight.challenge.main.structured']['method'] == 'json_mode'
    assert journal.state['insight.challenge.main.structured']['model'] == 'deepseek-v4-pro'


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash-1017", "kimi-k3.1-pro"])
def test_bailian_stage_sends_json_mode_to_beijing(tmp_path, monkeypatch, model):
    _, journal, _ = setup(tmp_path)
    monkeypatch.setenv("BAILIAN_API_KEY", "offline-bailian-key")
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "chatcmpl-fixture", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"insights": []}', "reasoning_content": "fixture reasoning",
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })

    with httpx.Client(transport=httpx.MockTransport(reply)) as http_client:
        monkeypatch.setattr("tradingagents.execution.insight_model.create_llm_client",
                            lambda **kwargs: create_llm_client(**kwargs, http_client=http_client))
        delegate = InsightModelCaller(effective_config={
            "llm_provider": "deepseek", "quick_think_llm": "deepseek-flash", "deep_think_llm": "deepseek-flash",
            "backend_url": "https://other-provider.example/v1", "deepseek_reasoning_effort": "high",
            "stage_models": {"operating_quality": {"provider": "bailian", "model": model}},
        }, run_id=journal.observer.run_id, ledger=journal.ledger, cancelled=lambda: False,
            deadline=lambda: time.monotonic() + 60)
        assert delegate("operating_quality", {}) == {"insights": []}

    request, = requests
    assert request.method == "POST"
    assert str(request.url) == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer offline-bailian-key"
    payload = json.loads(request.content)
    assert payload["model"] == model
    assert payload["response_format"] == {"type": "json_object"}
    assert "JSON" in payload["messages"][0]["content"]
    assert not {"thinking", "reasoning_effort"} & payload.keys()


def test_prompt_identity_cannot_change_after_dispatch(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)

    def invoke(**kwargs):
        kwargs['dispatch']()
        return SimpleNamespace(content='{"insights": []}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    delegate = caller(journal)
    delegate('operating_quality', {'evidence': ['E1']})
    from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict
    with pytest.raises(ResearchCheckpointConflict, match='prompt'):
        delegate('operating_quality', {'evidence': ['E2']})


def test_saved_deepseek_effort_reaches_model_request(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    efforts = []

    def client_factory(**kwargs):
        efforts.append(kwargs.get("reasoning_effort"))
        llm = SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content="{}"))
        return SimpleNamespace(get_llm=lambda: llm)

    monkeypatch.setattr("tradingagents.execution.insight_model.create_llm_client", client_factory)
    delegate = InsightModelCaller(
        effective_config={
            "llm_provider": "deepseek",
            "quick_think_llm": "deepseek-v4-flash",
            "deep_think_llm": "deepseek-v4-pro",
            "deepseek_reasoning_effort": "high",
            "deepseek_task_efforts": {"native.challenge": "max", "native.operating_quality": "low"},
        },
        run_id=journal.observer.run_id,
        ledger=journal.ledger,
        cancelled=lambda: False,
        deadline=lambda: time.monotonic() + 60,
    )
    delegate("challenge", {})
    delegate("response_operating_quality", {})
    assert efforts == ["max", "low"]
