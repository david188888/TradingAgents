"""Request boundary uses native formats, durable budgets and no lost-call resend."""

import hashlib
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from tests.v9_fixtures import journal_setup as setup
from tradingagents.execution.budget import AttemptOutcome
from tradingagents.execution.insight_model import InsightModelCaller, InsightUnavailable
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.runtime import research_checkpoint


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
    assert '\nSchema:\n' not in seen[0]['prompt']
    assert '{"evidence":[]}' in seen[0]['prompt']
    assert journal.state['insight.model_usage']['operating_quality.main']['input_tokens'] == 10
    assert len(journal.ledger.records()) == 1
    with pytest.raises(InsightUnavailable, match='response_unknown'):
        caller(journal)('operating_quality', {'evidence': []})
    assert len(seen) == 1


def test_malformed_response_keeps_reported_usage_without_raw_text(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    response = SimpleNamespace(content='private raw invalid text', response_metadata={'token_usage': {
        'prompt_tokens': 88, 'completion_tokens': 11, 'prompt_tokens_details': {'cached_tokens': 0},
        'completion_tokens_details': {'reasoning_tokens': 7},
    }})
    llm = SimpleNamespace(invoke=lambda _: response)
    monkeypatch.setattr('tradingagents.execution.insight_model.create_llm_client',
                        lambda **_: SimpleNamespace(get_llm=lambda: llm))
    delegate = caller(journal)
    with pytest.raises(InsightUnavailable, match='response_json_invalid'):
        delegate('operating_quality', {})
    assert 'private raw' not in str(journal.state)
    record, = journal.ledger.records()
    assert record.outcome is AttemptOutcome.FAILED
    assert record.usage_available is True
    assert (record.input_tokens, record.output_tokens, record.reasoning_tokens) == (88, 11, 7)
    assert record.cached_tokens == 0
    assert record.cache_creation_tokens is None
    with pytest.raises(InsightUnavailable, match='response_unknown'):
        delegate('operating_quality', {})


def test_checkpoint_without_token_details_still_resumes(tmp_path, monkeypatch):
    observer, journal, _ = setup(tmp_path)
    optional = {'cached_tokens', 'cache_creation_tokens', 'reasoning_tokens'}
    original = research_checkpoint._record_json

    def legacy_record_json(record):
        return {key: value for key, value in original(record).items() if key not in optional}

    def invoke(**kwargs):
        kwargs['dispatch']()
        kwargs['on_usage']({'input_tokens': 10, 'output_tokens': 20})
        return SimpleNamespace(content='{}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    with monkeypatch.context() as legacy:
        legacy.setattr(research_checkpoint, '_record_json', legacy_record_json)
        caller(journal)('operating_quality', {})
    saved = research_checkpoint.load_checkpoint(observer.store, observer.run_id)
    assert not optional.intersection(saved['records'][0])
    restored = research_checkpoint.ResearchJournal(observer, journal.state['identity'], require_existing=True)
    record, = restored.ledger.records()
    assert (record.input_tokens, record.output_tokens) == (10, 20)
    assert all(getattr(record, key) is None for key in optional)
    with pytest.raises(InsightUnavailable, match='response_unknown'):
        caller(restored)('operating_quality', {})


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
    observer, journal, _ = setup(tmp_path)
    monkeypatch.setenv("BAILIAN_API_KEY", "offline-bailian-key")
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "chatcmpl-fixture", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"insights": []}', "reasoning_content": "fixture reasoning",
            }}],
            "usage": {"prompt_tokens": 1100, "completion_tokens": 20, "total_tokens": 1120,
                      "prompt_tokens_details": {"cached_tokens": 0}, "cache_creation_input_tokens": 1024,
                      "completion_tokens_details": {"reasoning_tokens": 12}},
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
    system, user = payload["messages"]
    assert system["role"] == "system"
    frozen, task = user["content"]
    assert frozen["text"].endswith("{}")
    assert "\nSchema:\n" in task["text"]
    assert payload["max_completion_tokens"] == 10_240
    assert "cache_control" not in json.dumps(payload["messages"])
    assert not {"thinking", "reasoning_effort"} & payload.keys()
    saved = research_checkpoint.load_checkpoint(observer.store, observer.run_id)
    counters = {"input_tokens": 1100, "output_tokens": 20, "cached_tokens": 0,
                "cache_creation_tokens": 1024, "reasoning_tokens": 12}
    assert saved["insight.model_usage"]["operating_quality.main"] == {**counters, "total_tokens": 1120}
    assert {key: saved["records"][0][key] for key in counters} == counters


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


def test_decision_switches_model_after_rate_limit_and_reuses_saved_result(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    sent = []

    def post(_url, *, headers, json, timeout):
        sent.append(json['model'])
        if json['model'].startswith('perplexity/'):
            return SimpleNamespace(status_code=429, headers={'Retry-After': '120'}, text='quota')
        return SimpleNamespace(status_code=200, json=lambda: {
            'id': 'fallback-id', 'model': 'typesafe/jev-1.14', 'provider': 'TypeSafe',
            'usage': None, 'answers': {'check': {'type': 'noul', 'noul': 0.5}},
        })

    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-openrouter')
    monkeypatch.setattr('tradingagents.llm_clients.decisions_client.requests.post', post)
    monkeypatch.setattr('tradingagents.llm_clients.decisions_client.time.sleep', lambda _: None)
    delegate = caller(journal)
    delegate.config.update(jev_model='perplexity/pplx-decider-flash-v1.3:free',
                           jev_fallback_model='typesafe/jev-1.14')
    questions = {'check': {'type': 'noul'}}
    result = delegate.call_jev_verification('sample', {}, questions)
    assert result[0] == {'check': 0.5}
    assert result[1]['model'] == 'typesafe/jev-1.14'
    assert delegate.call_jev_verification('sample', {}, questions) == result
    assert sent == ['perplexity/pplx-decider-flash-v1.3:free', 'typesafe/jev-1.14']
    assert len(journal.ledger.records()) == 2


@pytest.mark.parametrize(('provider', 'model', 'mode', 'field', 'expected'), [
    ('deepseek', 'deepseek-v4-pro', 'disabled', 'thinking', {'type': 'disabled'}),
    ('bailian', 'kimi-k3.1-pro', 'enabled', 'enable_thinking', True),
    ('bailian', 'deepseek-v4.1-flash-1017', 'disabled', 'enable_thinking', False),
])
def test_stage_thinking_reaches_provider_payload(tmp_path, monkeypatch, provider, model, mode, field, expected):
    _, journal, _ = setup(tmp_path)
    monkeypatch.setenv('BAILIAN_API_KEY', 'offline-bailian')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'offline-deepseek')
    payloads = []

    def reply(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'fixture', 'model': model,
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': '{"responses": []}'}}],
        })

    with httpx.Client(transport=httpx.MockTransport(reply)) as http_client:
        monkeypatch.setattr('tradingagents.execution.insight_model.create_llm_client',
                            lambda **kwargs: create_llm_client(**kwargs, http_client=http_client))
        delegate = caller(journal)
        delegate.config['stage_models'] = {'operating_quality': {
            'provider': provider, 'model': model, 'thinking': mode}}
        assert delegate('response_operating_quality', {}) == {'responses': []}

    assert payloads[0][field] == expected


def test_v2_response_distinguishes_target_from_narrative_citations(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)

    def invoke(**kwargs):
        kwargs['dispatch']()
        prompt = kwargs['prompt'].split('\nSaved context:\n', 1)[0]
        assert 'Copy the assigned I identifier into target only' in prompt
        assert 'In narrative text, use only bracketed E and N references supplied for that target.' in prompt
        assert 'like [E1], [N1] and [I1]' not in prompt
        return SimpleNamespace(content='{"responses": []}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    assert caller(journal)('response_event_context', {'assigned': ['I1']}) == {'responses': []}


def test_saved_v1_prompt_digest_can_resume_without_resending(tmp_path, monkeypatch):
    observer, journal, _ = setup(tmp_path)
    identity = {**journal.state['identity'], 'insight_context_policy': 'insight-handoff-v1'}
    journal.put('identity', identity)
    key = 'insight.operating_quality.main.prompt'
    # Prompt digest captured from the pre-L2 implementation for this exact request.
    digest = '6f4f8e8f087cc4bdafd8ab0386a8abf5ffa9e5a56129f3fb92c99219cecba855'
    journal.put(key, digest)
    seen = []

    def invoke(**kwargs):
        seen.append(hashlib.sha256(kwargs['prompt'].encode()).hexdigest())
        kwargs['dispatch']()
        return SimpleNamespace(content='{}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    preserved = research_checkpoint.ResearchJournal(observer, identity, require_existing=True)
    delegate = caller(preserved)
    context = {'evidence': [], 'search_requests_allowed': True}
    assert delegate('operating_quality', context) == {}
    preserved = research_checkpoint.ResearchJournal(observer, identity, require_existing=True)
    with pytest.raises(InsightUnavailable, match='response_unknown'):
        caller(preserved)('operating_quality', context)
    assert seen == [digest]


def test_bailian_main_and_repair_share_only_the_frozen_catalog(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    sent = []

    def invoke(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(content='{}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    model = caller(journal)
    model.config.update(llm_provider='bailian', quick_think_llm='deepseek-v4.1-flash-1017')
    catalog = {'evidence': [{'ref': 'E1', 'text': 'saved evidence'}], 'sources': []}
    model('event_context', {**catalog, 'search_requests_allowed': True})
    model('event_context', {**catalog, 'repair_items': [{'target': 0}]}, phase='repair')
    main, repair = [call['prompt'] for call in sent]
    assert main[0] == repair[0]
    assert main[1]['content'][0] == repair[1]['content'][0]
    assert 'repair_items' not in main[1]['content'][0]['text']
    assert 'repair_items' in repair[1]['content'][1]['text']
    assert sent[1]['config']['bailian_thinking'] == 'disabled'
    assert sent[1]['config']['llm_max_tokens'] == 4096


def test_bailian_v2_keeps_single_string_and_old_route(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    journal.put('identity', {**journal.state['identity'], 'insight_context_policy': 'insight-handoff-v2'})

    def invoke(**kwargs):
        assert isinstance(kwargs['prompt'], str)
        assert 'llm_max_tokens' not in kwargs['config']
        return SimpleNamespace(content='{}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    model = caller(journal)
    model.config.update(llm_provider='bailian', quick_think_llm='deepseek-v4.1-flash-1017')
    model('event_context', {}, phase='repair')


def test_bailian_output_limit_is_a_failed_attempt_even_if_json_is_closed(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)

    def invoke(**kwargs):
        kwargs['dispatch']()
        kwargs['on_usage']({'input_tokens': 10, 'output_tokens': 100})
        return SimpleNamespace(content='{}', response_metadata={'finish_reason': 'length'})

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    with pytest.raises(InsightUnavailable, match='response_output_limit'):
        caller(journal)('operating_quality', {})
    record, = journal.ledger.records()
    assert record.outcome is AttemptOutcome.FAILED and record.output_tokens == 100


def test_columnar_experiment_uses_same_frozen_prefix_and_delta_schema(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)
    journal.put('identity', {**journal.state['identity'], 'insight_context_policy': 'insight-handoff-v4'})
    sent = []

    def invoke(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(content='{}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    model = caller(journal)
    model.config.update(llm_provider='bailian', quick_think_llm='deepseek-v4.1-flash-1017', insight_experiment='columnar')
    context = {'evidence': [{'ref': f'E{i}', 'text': 'result', 'source_ids': ['S1']} for i in range(1, 20)]}
    model('event_context', context)
    model('event_context', {**context, 'delta_catalog': {'evidence': []}}, phase='supplement_1')
    main, delta = [call['prompt'][1]['content'] for call in sent]
    assert main[0] == delta[0]
    assert '"columns"' in main[0]['text']
    assert '"keep_ids"' in delta[1]['text'] and 'delta_catalog' in delta[1]['text']
