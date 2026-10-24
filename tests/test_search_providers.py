"""Provider requests are explicit, finite, and independent of chat clients."""

from types import SimpleNamespace

import pytest
import requests

from tests.search_fixtures import make_search_request
from tests.test_search_budget import Journal
from tradingagents.dataflows import deepseek_search, tavily_search
from tradingagents.execution.budget import BudgetBucket as B
from tradingagents.execution.search_budget import SearchBudget


class Session:
    def __init__(self, status=200, data=None):
        self.calls = []
        self.status = status
        self.data = data if data is not None else {'results': []}

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return SimpleNamespace(status_code=self.status, json=lambda: self.data)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-not-a-real-key')
    monkeypatch.setenv('TAVILY_API_KEY', 'test-not-a-real-key')
    monkeypatch.delenv('TAVILY_API_KEYS', raising=False)


def test_deepseek_query_unicode_128_and_nullable_date():
    session = Session(data={'results': [{'url': 'https://example.com/a', 'title': '报告',
        'summary': '摘要', 'content': '正文', 'date': None, 'rerank_score': 2.4, 'authority': 3}]})
    j = Journal()
    budget = SearchBudget(j.ledger)
    outcome = deepseek_search.search(make_search_request(query='中'*128), session=session, budget=budget)
    assert outcome.status == 'ok' and outcome.hits[0].published_at is None
    assert session.calls[0][1]['json']['count'] == 8
    assert session.calls[0][1]['json']['need_content'] is True
    assert 'model' not in session.calls[0][1]['json']
    rejected = deepseek_search.search(make_search_request(query='中'*129), session=session, budget=budget)
    assert rejected.status == 'refused' and len(session.calls) == 1
    assert j.ledger.consumed(B.DEEPSEEK_SEARCH) == 1


def test_tavily_basic_no_auto_upgrade():
    session = Session()
    outcome = tavily_search.search(make_search_request(provider='tavily'), session=session,
                                   budget=SearchBudget(Journal().ledger))
    assert outcome.status == 'empty'
    body = session.calls[0][1]['json']
    assert body['search_depth'] == 'basic' and body['auto_parameters'] is False
    assert body['include_answer'] is False


@pytest.mark.parametrize('status,retryable', [(401, False), (402, False), (400, False), (429, True), (500, True)])
@pytest.mark.parametrize('provider', ['deepseek', 'tavily'])
def test_provider_http_classification(status, retryable, provider):
    session = Session(status=status)
    module = deepseek_search if provider == 'deepseek' else tavily_search
    outcome = module.search(make_search_request(provider=provider), session=session,
                            budget=SearchBudget(Journal().ledger))
    assert outcome.status == 'failed' and outcome.retryable == retryable
    assert len(session.calls) == 1
    assert 'test-not-a-real-key' not in outcome.model_dump_json()


def test_no_credentials_no_dispatch(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    j = Journal()
    session = Session()
    result = deepseek_search.search(make_search_request(), session=session, budget=SearchBudget(j.ledger))
    assert result.status == 'unavailable' and session.calls == [] and j.ledger.records() == ()


def test_malformed_200_is_one_failed_attempt():
    j = Journal()
    session = Session(data=['invalid'])
    outcome = deepseek_search.search(make_search_request(), session=session, budget=SearchBudget(j.ledger))
    assert outcome.status == 'failed'
    assert len(j.ledger.records()) == 1
    assert j.ledger.records()[0].outcome.value == 'failed'


def test_tavily_rotation_keeps_one_shared_quota(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEYS', 'key-first,key-second')
    j = Journal()
    budget = SearchBudget(j.ledger)
    session = Session(status=401)
    tavily_search.search(make_search_request(provider='tavily'), session=session, budget=budget)
    session.status = 200
    tavily_search.search(make_search_request(provider='tavily', task_id='other'), session=session, budget=budget)
    assert session.calls[0][1]['headers']['Authorization'] == 'Bearer key-first'
    assert session.calls[1][1]['headers']['Authorization'] == 'Bearer key-second'
    assert j.ledger.consumed(B.TAVILY_SEARCH) == 2


def test_transport_timeout_is_retryable_but_never_retried_in_adapter():
    class TimeoutSession:
        calls = 0
        def post(self, *args, **kwargs):
            self.calls += 1
            raise requests.Timeout('safe synthetic timeout')
    session = TimeoutSession()
    result = deepseek_search.search(make_search_request(), session=session,
                                   budget=SearchBudget(Journal().ledger))
    assert result.retryable and session.calls == 1


def test_cancellation_propagates_before_dispatch():
    from tradingagents.execution.models import AnalysisCancelled
    def cancelled():
        raise AnalysisCancelled('cancelled')
    j = Journal()
    budget = SearchBudget(j.ledger, ensure_active=cancelled)
    with pytest.raises(AnalysisCancelled):
        deepseek_search.search(make_search_request(), session=Session(), budget=budget)
    assert not j.ledger.records()


@pytest.mark.parametrize('published', ['Tue, 11 Mar 2025 17:00:00 GMT', '2025-03-11'])
def test_tavily_dates_requested_and_parsed_for_admission(published):
    session = Session(data={'results': [{'url': 'https://example.com/a', 'title': '正文',
        'raw_content': '完整原文', 'published_date': published}]})
    result = tavily_search.search(make_search_request(provider='tavily'), session=session,
        budget=SearchBudget(Journal().ledger))
    assert session.calls[0][1]['json']['include_published_date'] is True
    assert result.hits[0].published_at is not None
    assert result.hits[0].published_at.date().isoformat() == '2025-03-11'
