"""Dual discovery is merged once and uncertain paid dispatch is never replayed."""

import pytest

from tests.search_fixtures import make_gap, make_search_request
from tests.test_search_budget import Journal
from tests.test_search_providers import Session
from tradingagents.execution.search_budget import SearchBudget
from tradingagents.execution.search_coordinator import (
    SearchCoordinator,
    compile_queries,
    initial_requests,
)


def test_initial_topics_paired():
    requests = initial_requests(ticker='600519.SH', company_name='测试公司', cutoff='2026-09-30')
    assert len(requests) == 6
    assert [r.provider for r in requests].count('deepseek') == 3
    assert all(r.kind == 'initial' and 'before:' in r.query for r in requests)


def test_priority_top_three_and_query_cap():
    tasks = compile_queries(make_gap(), ticker='600519.SH', company_name='测试公司', round_id=1)
    assert len(tasks) <= 4
    assert all(t.round_id == 1 and t.kind == 'supplement' for t in tasks)


def test_completed_task_cached(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    j = Journal()
    s = Session(data={'results': [{'url': 'https://example.com/a', 'title': '行业', 'content': '正文', 'date': None}]})
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    req = make_search_request()
    first = c.collect((req,), input_snapshot_id='v0')
    second = c.collect((req,), input_snapshot_id='v0')
    assert first == second and len(s.calls) == 1


def test_unknown_dispatch_not_resent(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    j = Journal()
    s = Session()
    b = SearchBudget(j.ledger)
    c = SearchCoordinator(s, b, j)
    req = make_search_request()
    task = c.task_identity(req, 'v0')
    j.ledger.mark_dispatched(b.reserve_search('deepseek', task))
    result = c.collect((req,), input_snapshot_id='v0')
    assert not s.calls and 'dispatch_outcome_unknown' in result.stop_reasons


def test_same_url_tracking_and_summary_never_body(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    monkeypatch.setenv('TAVILY_API_KEY', 'not-real')
    j = Journal()
    s = Session(data={'results': [
        {'url': 'https://example.com/a?id=7&utm_source=x', 'summary': '摘要', 'content': '正文'},
        {'url': 'https://example.com/a?utm_source=y&id=7', 'summary': '摘要', 'content': '正文'}]})
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    result = c.collect((make_search_request(),), input_snapshot_id='v0')
    assert len(result.hits) == 1 and result.hits[0].canonical_url == 'https://example.com/a?id=7'


def test_document_ref_parameter_is_not_tracking():
    from tradingagents.execution.search_coordinator import canonical_url
    assert canonical_url('https://example.com/a?ref=report-1') != canonical_url('https://example.com/a?ref=report-2')


def test_transient_retry_once_counts_budget(monkeypatch):
    from tradingagents.execution.budget import BudgetBucket
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    j = Journal()
    class RateLimited(Session):
        def post(self, url, **kwargs):
            self.status = 429 if not self.calls else 200
            return super().post(url, **kwargs)
    s = RateLimited()
    c = SearchCoordinator(s, SearchBudget(j.ledger), j, sleeper=lambda _: None)
    result = c.collect((make_search_request(),), input_snapshot_id='v0')
    assert result.outcomes[0].status == 'empty' and len(s.calls) == 2
    assert j.ledger.consumed(BudgetBucket.DEEPSEEK_SEARCH) == 2
    c.collect((make_search_request(),), input_snapshot_id='v0')
    assert len(s.calls) == 2


def test_one_provider_unavailable_degrades(monkeypatch):
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    monkeypatch.delenv('TAVILY_API_KEYS', raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    j = Journal()
    s = Session(data={'results': [{'url': 'https://example.com/a', 'title': '新闻', 'content': '原文'}]})
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    result = c.collect((make_search_request(), make_search_request(provider='tavily', task_id='tavily')), input_snapshot_id='v0')
    assert len(result.hits) == 1 and len(s.calls) == 1
    assert result.outcomes[1].status == 'unavailable'


def test_summary_never_becomes_body(monkeypatch):
    from tradingagents.agents.schemas._search import SearchOutcomeV1
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    monkeypatch.setattr('tradingagents.execution.search_coordinator.fetch_page', lambda url, **kw:
        SearchOutcomeV1(task_id=kw['task_id'], provider=kw['provider'], status='unavailable', reason='fixture'))
    j = Journal()
    s = Session(data={'results': [{'url': 'https://example.com/a', 'summary': '不可冒充原文的摘要'}]})
    result = SearchCoordinator(s, SearchBudget(j.ledger), j).collect((make_search_request(),), input_snapshot_id='v0')
    assert result.hits[0].summary and not result.hits[0].content


def test_mixed_company_batch_rejected_before_dispatch():
    import pytest
    j = Journal()
    s = Session()
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    with pytest.raises(ValueError):
        c.collect((make_search_request(), make_search_request(ticker='000001.SZ')), input_snapshot_id='v0')
    assert not s.calls


def test_cancellation_propagates_and_never_searches():
    import pytest

    from tradingagents.execution.models import AnalysisCancelled
    j = Journal()
    s = Session()
    def active():
        raise AnalysisCancelled()
    c = SearchCoordinator(s, SearchBudget(j.ledger, ensure_active=active), j)
    with pytest.raises(AnalysisCancelled):
        c.collect((make_search_request(),), input_snapshot_id='v0')
    assert not s.calls


def test_recovery_pdf_gets_structured_pages_even_with_search_content(monkeypatch):
    from tests.test_search_recovery import demand
    from tradingagents.agents.schemas._search import SearchDocumentV1, SearchHitV1
    j = Journal()
    c = SearchCoordinator(Session(), SearchBudget(j.ledger), j)
    hit = SearchHitV1(provider='deepseek', url='https://static.cninfo.com.cn/finalpage/2026-04-01/123.PDF',
        canonical_url='https://static.cninfo.com.cn/finalpage/2026-04-01/123.PDF', title='2025年年度报告', content='已提取的部分正文')
    calls = []
    monkeypatch.setattr('tradingagents.execution.search_coordinator.download_public_document',
        lambda url, **kw: (calls.append(url) or b'pdf', url))
    doc = SearchDocumentV1(parser_version='official-pdf-v2', pdf_sha256='a'*64, security_id='600519.SH', title=hit.title,
        page_count=1, pages=({'page': 1, 'text': '原始财务表'},))
    monkeypatch.setattr('tradingagents.execution.search_coordinator.parse_search_document', lambda *a, **kw: doc)
    result = c._body(hit, make_search_request(kind='recovery', requirements=(demand(),)))
    assert result.document == doc and len(calls) == 1
    assert c._body(hit, make_search_request(kind='recovery', requirements=(demand(),))).document == doc
    assert len(calls) == 1


def test_long_gap_preserves_deepseek_query_limit_and_cutoff():
    tasks = compile_queries(make_gap(question='很长的明确研究问题'*30, evidence_needed='需要核对的原始证据'*30),
        ticker='600519.SH', company_name='贵州茅台', round_id=1)
    assert len(tasks) == 4
    assert all(len(r.query) <= (128 if r.provider == 'deepseek' else 400) for r in tasks)
    assert all(r.query.endswith('before:2026-10-01') for r in tasks)
    assert all('600519.SH' in r.query and '贵州茅台' in r.query for r in tasks)


@pytest.mark.parametrize('truncated', [False, True])
def test_post_fetch_reposts_share_family_with_role_scopes(monkeypatch, truncated):
    from datetime import date, datetime, timezone

    from tradingagents.agents.schemas._search import SearchOutcomeV1
    from tradingagents.research.search_admission import admit_search_batch
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    body = '公司行业原文信息，需核对来源。' * 40
    s = Session(data={'results': [{'url': 'https://example.com/'+str(i), 'title': '行业',
        'date': datetime.now(timezone.utc).isoformat()} for i in range(2)]})
    j = Journal()
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    def body_fetch(url, **kwargs):
        content = body[:250] if truncated and url.endswith('1') else body
        hit = {'provider': 'deepseek', 'url': url, 'canonical_url': url, 'content': content,
               'truncated': truncated and url.endswith('1')}
        return SearchOutcomeV1(task_id=kwargs['task_id'], provider='deepseek', status='ok', hits=(hit,))
    monkeypatch.setattr('tradingagents.execution.search_coordinator.fetch_page', body_fetch)
    requests = tuple(make_search_request(task_id='r'+str(i), cutoff=date.today(), role=role)
        for i, role in enumerate(('operating_quality', 'event_context')))
    batch = c.collect(requests, input_snapshot_id='v0')
    admitted = admit_search_batch(batch, ticker='600519.SH', cutoff=date.today())
    assert len({o.source.source_family_id for o in admitted.observations}) == 1
    assert {o.role for o in admitted.observations} == {'operating_quality', 'event_context'}


@pytest.mark.parametrize('error', [ConnectionResetError('offline'), OSError('offline')])
def test_optional_pdf_transport_failure_preserves_original_body(monkeypatch, error):
    s = Session(data={'results': [{'url': 'https://example.com/report.pdf', 'content': '已有原文'}]})
    j = Journal()
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    from tests.test_search_recovery import demand
    def fail(*a, **kw):
        raise error
    monkeypatch.setattr('tradingagents.execution.search_coordinator.download_public_document', fail)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    batch = c.collect((make_search_request(requirements=(demand(),)),), input_snapshot_id='v0')
    assert batch.hits[0].content == '已有原文'
    assert 'document_transport_unavailable' in batch.stop_reasons


def test_pdf_checkpoint_conflict_is_never_degraded(monkeypatch):
    from tests.test_search_recovery import demand
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    s = Session(data={'results': [{'url': 'https://example.com/report.pdf', 'content': '已有原文'}]})
    j = Journal()
    c = SearchCoordinator(s, SearchBudget(j.ledger), j)
    def fail(*a, **kw):
        raise CatalystCheckpointConflict('offline conflict')
    monkeypatch.setattr('tradingagents.execution.search_coordinator.download_public_document', fail)
    with pytest.raises(CatalystCheckpointConflict):
        c.collect((make_search_request(requirements=(demand(),)),), input_snapshot_id='v0')


@pytest.mark.parametrize('financial_first', [False, True])
@pytest.mark.parametrize('shared_url', [False, True])
def test_batch_pdf_recovery_uses_matching_demands(monkeypatch, financial_first, shared_url):
    from types import SimpleNamespace

    from tests.test_search_recovery import demand
    from tradingagents.agents.schemas._search import SearchDocumentV1
    from tradingagents.execution.budget import BudgetBucket

    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-real')
    financial_url = 'https://example.com/financial.pdf'
    background_url = financial_url if shared_url else 'https://example.com/background.pdf'
    class ByQuery(Session):
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            hit_url = financial_url if kwargs['json']['query'] == 'financial' else background_url
            return SimpleNamespace(status_code=200, json=lambda: {'results': [
                {'url': hit_url, 'title': '报告', 'content': '发现阶段已有部分原文'}]})
    journal = Journal()
    budget = SearchBudget(journal.ledger)
    coordinator = SearchCoordinator(ByQuery(), budget, journal)
    background = make_search_request(task_id='background', query='background', role='event_context')
    financial = make_search_request(task_id='financial', query='financial', role='operating_quality',
                                    requirements=(demand(),))
    requests = (financial, background) if financial_first else (background, financial)
    downloads = []
    def download(url, *, task_id, budget):
        reservation = budget.reserve_page(task_id)
        journal.ledger.mark_dispatched(reservation)
        journal.ledger.settle(reservation, ok=True)
        downloads.append(url)
        return b'pdf', url
    monkeypatch.setattr('tradingagents.execution.search_coordinator.download_public_document', download)
    document = SearchDocumentV1(parser_version='official-pdf-v2', pdf_sha256='a'*64,
        security_id='600519.SH', title='2025年年度报告', page_count=1,
        pages=({'page': 1, 'text': '原始财务表'},))
    monkeypatch.setattr('tradingagents.execution.search_coordinator.parse_search_document', lambda *a, **kw: document)
    batch = coordinator.collect(requests, input_snapshot_id='v0')
    hits = {hit.canonical_url: hit for hit in batch.hits}
    assert hits[financial_url].document == document
    assert downloads == [financial_url]
    assert {request.role for request in batch.requests} == {'event_context', 'operating_quality'}
    assert journal.ledger.consumed(BudgetBucket.DEEPSEEK_SEARCH) == 2
    assert journal.ledger.consumed(BudgetBucket.SEARCH_PAGE) == 1
    coordinator.collect(requests, input_snapshot_id='v0')
    assert downloads == [financial_url]
