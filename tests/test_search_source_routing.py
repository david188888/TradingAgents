"""Dedicated APIs precede field recovery; context always uses dual discovery."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.test_native_multisource import PROFILE, statement
from tradingagents.agents.schemas._search import SearchBatchV1, SearchHitV1, SearchOutcomeV1
from tradingagents.dataflows.minimum_sources import MinimumEvidenceSources
from tradingagents.dataflows.search_sources import SearchEvidenceSources
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
from tradingagents.research.native_versions import (
    REPORT_DELIVERY_POLICY,
)


class Coordinator:
    def __init__(self, text='行业新闻原文', *, control=None):
        self.calls, self.text, self.control = [], text, control

    def collect(self, requests, *, input_snapshot_id):
        if self.control:
            raise self.control
        self.calls.append(requests)
        hit = SearchHitV1(provider='deepseek', url='https://example.com/news', canonical_url='https://example.com/news',
            title='公司与行业信息', content=self.text, published_at=datetime.now(timezone.utc)-timedelta(days=1))
        return SearchBatchV1(batch_id='batch.'+str(len(self.calls)), input_snapshot_id=input_snapshot_id,
            requests=requests, outcomes=tuple(SearchOutcomeV1(task_id=r.task_id, provider=r.provider,
                status='ok', hits=(hit.model_copy(update={'provider': r.provider}),)) for r in requests), hits=(hit,))


def collector(monkeypatch, coordinator=None, *, identity=True, financial=True):
    request = SimpleNamespace(ticker='002130.SZ', analysis_date=date.today().isoformat(),
        mode='company_research', catalyst_policy=catalyst_evidence_policy_v1(),
        report_delivery_policy=REPORT_DELIVERY_POLICY, financial_detail_policy=None,
        effective_config={'evidence_source_vendors': {'identity': ['sina'] if identity else [],
            'financial': ['sina'] if financial else [], 'events': [], 'calendar': [], 'price': [],
            'valuation': [], 'forecasts': [], 'peers': []}})
    coordinator = coordinator or Coordinator()
    sources = SearchEvidenceSources(request, 'routing-run', None, lambda key, operation: operation(), coordinator)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if 'CorpInfo' in url:
            return PROFILE
        table = {'lrb': 'income', 'fzb': 'balancesheet', 'llb': 'cashflow'}[kwargs['params']['source']]
        return statement(table)
    monkeypatch.setattr(sources, '_get', get)
    return sources, coordinator, calls


def test_news_search_even_when_data_apis_succeed(monkeypatch):
    sources, search, _ = collector(monkeypatch)
    record, _ = sources.collect()
    initial = [r for batch in search.calls for r in batch if r.kind == 'initial']
    assert len(initial) == 6 and {r.provider for r in initial} == {'deepseek', 'tavily'}
    assert record.schema_version == 'research-record-v2' and len(record.snapshots) == 1
    assert any('行业新闻原文' in fact.statement for fact in record.claims)


def test_partial_field_success_only_searches_missing_field(monkeypatch):
    sources, search, _ = collector(monkeypatch)
    record, _ = sources.collect()
    requirements = [f for batch in search.calls for r in batch for f in r.requirements]
    assert not any(f.field in {'revenue', 'n_income', 'n_cashflow_act'} for f in requirements)
    assert all(f.field != 'name' for f in requirements)


def test_failed_chain_search_recovery_once(monkeypatch):
    text = '公司代码：002130\n2026年半年度报告\n合并利润表\n单位：元  币种：人民币\n项目  2026年半年度  2025年半年度\n营业收入  120.50  100.00\n'
    sources, search, _ = collector(monkeypatch, Coordinator(text), financial=False)
    record, _ = sources.collect()
    recovered = [f for f in record.recovered_fields if f.field == 'revenue']
    assert recovered and recovered[0].value == '120.50'
    recovery_batches = [b for b in search.calls if any(r.kind == 'recovery' and r.capability == 'financial' for r in b)]
    assert len(recovery_batches) == 1


def test_identity_recovery_unique_before_company_materials(monkeypatch):
    text = '公司代码：002130\n公司名称：沃尔核材\n上市日期：2007-04-20\n'
    sources, search, calls = collector(monkeypatch, Coordinator(text), identity=False)
    record, _ = sources.collect()
    assert search.calls[0][0].capability == 'identity'
    initial = [r for batch in search.calls for r in batch if r.kind == 'initial']
    assert initial and all(r.company_name == '沃尔核材' for r in initial)
    assert record.company_basics.company_name == '沃尔核材'
    assert 'security_identity_unqualified' not in record.limitations


def test_global_control_error_never_falls_back(monkeypatch):
    sources, search, _ = collector(monkeypatch, Coordinator(control=AnalysisCancelled()), identity=False)
    with pytest.raises(AnalysisCancelled):
        sources.collect()
    assert not search.calls


def test_default_current_collector_still_legacy():
    from tradingagents.research.native_versions import UNIFIED_WORKFLOW_VERSION
    assert UNIFIED_WORKFLOW_VERSION == 'evidence-production-v7'
    assert not hasattr(MinimumEvidenceSources, 'coordinator')


def test_exhausted_dedicated_pool_still_allows_search_recovery(monkeypatch):
    from tradingagents.execution.budget import BudgetBucket, BudgetExhausted, BudgetLimitHit
    text = ('公司代码：002130\n2026年半年度报告\n合并利润表\n单位：元  币种：人民币\n'
        '项目  2026年半年度  2025年半年度\n营业收入  120.50  100.00\n')
    sources, search, _ = collector(monkeypatch, Coordinator(text))
    previous = sources._attempt
    def exhausted(capability, *args):
        if capability == 'fundamentals':
            raise BudgetExhausted(BudgetLimitHit(BudgetBucket.DATA_CAPABILITY_CALLS, 'data', 24, 24, 'limit_reached'))
        return previous(capability, *args)
    monkeypatch.setattr(sources, '_attempt', exhausted)
    record, _ = sources.collect()
    assert any(f.field == 'revenue' and f.value == '120.50' for f in record.recovered_fields)


def test_missing_valuation_attempts_search_without_fabricating_snapshot(monkeypatch):
    sources, search, _ = collector(monkeypatch)
    record, _ = sources.collect()
    requests = [r for batch in search.calls for r in batch if r.capability == 'valuation']
    assert {r.provider for r in requests} == {'deepseek', 'tavily'}
    assert {f.field for r in requests for f in r.requirements} == {'dated_valuation_snapshot'}
    assert record.valuation is None
