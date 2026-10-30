"""Request boundary uses native formats, durable budgets and no lost-call resend."""

import time
from types import SimpleNamespace

import pytest

from tests.test_native_publication import setup
from tradingagents.execution.insight_model import InsightModelCaller, InsightUnavailable
from tradingagents.execution.models import AnalysisCancelled


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
    assert set(shape['properties']) == {'insights', 'search_requests'}
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


def test_prompt_identity_cannot_change_after_dispatch(tmp_path, monkeypatch):
    _, journal, _ = setup(tmp_path)

    def invoke(**kwargs):
        kwargs['dispatch']()
        return SimpleNamespace(content='{"insights": []}')

    monkeypatch.setattr('tradingagents.execution.insight_model.invoke_model_request', invoke)
    delegate = caller(journal)
    delegate('operating_quality', {'evidence': ['E1']})
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict
    with pytest.raises(CatalystCheckpointConflict, match='prompt'):
        delegate('operating_quality', {'evidence': ['E2']})
