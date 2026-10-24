"""Real V8 runner, ledgers, publication and Reader with offline transports."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.test_native_multisource import PROFILE, statement
from tradingagents.dataflows.search_sources import SearchEvidenceSources
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import NativeResumeGuard, NativeRunner, native_identity
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.research_record_projection import project_research_record


class Session:
    def __init__(self, *, unavailable=False):
        self.calls, self.unavailable, self.closed = [], unavailable, False
    def close(self):
        self.closed = True
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs['json']))
        text = ('公司代码：002130\n2026年半年度报告\n公司简介：合成测试公司的业务介绍。\n'
            '主营业务：电气设备产品生产与销售，仅为离线测试合成数据。\n所属行业：电气设备行业\n'
            '合并利润表\n单位：元  币种：人民币\n项目  2026年半年度  2025年半年度\n'
            '归属于上市公司股东的净利润  120.50  100.00\n')
        hit = {'url': 'https://example.com/company-report', 'title': '公司公开材料',
            'date': (datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),
            'content': text, 'raw_content': text}
        return SimpleNamespace(status_code=401 if self.unavailable else 200,
            json=lambda: {'results':[hit]}, close=lambda:None)


class Sources(SearchEvidenceSources):
    def _get(self, url, **kwargs):
        if 'CorpInfo' in url:
            return PROFILE
        table = {'lrb':'income', 'fzb':'balancesheet', 'llb':'cashflow'}[kwargs['params']['source']]
        return statement(table)


class Caller:
    def __init__(self):
        self.calls=[]
    def __call__(self, stage, context):
        from tests.search_fixtures import make_gap
        self.calls.append(stage)
        gaps=[]
        if stage in {'operating_quality','event_context','market_context'}:
            fact=context['facts'][0]
            proposal={'hypotheses':[{'statement':'已有材料提供有限依据，持续性仍待核查。',
                'supporting_fact_ids':[fact['claim_id']],
                'conditions':[{'condition_role':'invalidation','text':'后续披露与当前解释不一致'}],
                'alternative_explanation':'其他因素可能共同影响经营。'}], 'unknowns':[]}
            if stage=='operating_quality':
                gaps=[make_gap(cutoff=context['numeric_analysis_date']).model_dump(mode='json')]
        elif stage=='challenge':
            proposal={'challenges':[]}
        elif stage.startswith('search_review.'):
            proposal={'disposition':'maintained','rationale':'新增材料仍需与经营结果对应核查。',
                'supporting_fact_ids':[context['facts'][-1]['claim_id']], 'new_risks':[]}
        elif stage=='synthesis':
            proposal={'judgement':'保留已有公司研究，整体判断仍需核查。', 'next_check':'核对后续经营披露。',
                'investment_stance':'insufficient_evidence',
                'dimensions':[{'dimension':name,'status':'conditional' if ids else 'unresolved',
                    'judgement':'保留资料覆盖限制。','claim_ids':ids[:1], 'limitations':['仍需核对经营含义。']}
                    for name,ids in context['dimension_claim_ids'].items()],
                'challenge_assessments':[], 'adjudications':[]}
        else:
            raise AssertionError(stage)
        envelope={'proposal':proposal,'plans':[],'structured_bindings':[]}
        if context.get('factual_premise_policy'):
            from tradingagents.research.factual_premises import premise_path
            from tradingagents.research.numeric_narrative import _field_scope, _fields
            envelope['premises']=[]
            for path,_ in _fields(proposal):
                if premise_path(path):
                    scope=_field_scope(stage,path,proposal,context)
                    observations=[o['observation_id'] for o in context['factual_observations'] if set(o['fact_ids'])<=scope]
                    envelope['premises'].append({'field_path':path,'observation_ids':observations[:1], 'pending_questions':[]})
        if stage!='synthesis':
            envelope['gaps']=gaps
        return envelope


def setup(tmp_path, monkeypatch, *, unavailable=False, enabled=True):
    monkeypatch.setenv('DEEPSEEK_API_KEY','offline-placeholder')
    monkeypatch.setenv('TAVILY_API_KEY','offline-placeholder')
    monkeypatch.delenv('TAVILY_API_KEYS',raising=False)
    config={'llm_provider':'deepseek','quick_think_llm':'offline','deep_think_llm':'offline',
        'evidence_search_enabled':enabled, 'evidence_source_vendors':{'identity':['sina'], 'financial':['sina'],
            'events':[], 'calendar':[], 'price':[], 'valuation':[], 'forecasts':[], 'peers':[]}}
    request=AnalysisRequest('002130.SZ',date.today().isoformat(),research_profile='evidence_v1',effective_config=config)
    store=RunStore(tmp_path)
    snapshot=RunSnapshot.create(ticker=request.ticker,analysis_date=request.analysis_date,
        metadata={'research_profile':'evidence_v1','native_workflow_version':'evidence-production-v8'})
    store.create_run(snapshot)
    observer=DurableRunObserver(store,snapshot.run_id,development_assertions=False)
    session,caller=Session(unavailable=unavailable),Caller()
    runner=NativeRunner(observer,sources_factory=Sources,caller_factory=lambda **kw:caller,
        search_session_factory=lambda:session)
    return runner,request,store,snapshot.run_id,session,caller


def test_new_workflow_identity_freezes_search_policy():
    request=AnalysisRequest('600803','2026-10-23',research_profile='evidence_v1',effective_config={})
    identity=native_identity(request)
    assert identity['workflow_version']=='evidence-production-v8'
    assert identity['search_budget_policy']['limits']['model_attempts']==21
    assert identity['search_research_policy']['endpoints']['deepseek_search'].endswith('/v1/tools/search')
    old=native_identity(request,workflow_version='evidence-production-v7')
    assert 'search_budget_policy' not in old and 'evidence_search_enabled' not in old['config']


@pytest.mark.parametrize('unavailable',[False,True])
def test_runner_publication_and_resume_never_duplicate_search(tmp_path,monkeypatch,unavailable):
    runner,request,store,run_id,session,caller=setup(tmp_path,monkeypatch,unavailable=unavailable)
    runner.run(request,publication_authorizer=lambda j:j.put('publication_authorized',True))
    projected=project_research_record(store,run_id)
    assert projected['state']=='ready'
    record=projected['record']
    assert record['schema_version']=='research-record-v2'
    assert len(record['snapshots'])<=8
    cp=load_checkpoint(store,run_id)
    def used(bucket):
        return sum(r['bucket']==bucket and r['dispatched_at'] is not None for r in cp['records'])
    assert 0<used('deepseek_search')<=50 and 0<used('tavily_search')<=50
    assert used('search_page')<=8 and used('search_review')<=9 and used('basic_model_attempts')<=12
    assert used('model_attempts')==0  # aggregate pools are derived, never dispatched themselves
    assert used('main_analysis')+used('search_review')<=21
    if unavailable:
        assert not record['recovered_fields']
        assert record['search_gaps'] and 'no_qualified_delta' in record['search_stop_reasons']
    else:
        assert any(f['field']=='n_income_attr_p' and f['value']=='120.50' for f in record['recovered_fields'])
        assert any(c['field']=='n_income_attr_p' and c['operation']=='growth' for c in record['revision_calculations'])
        assert record['search_reviews']
    before=len(session.calls),len(caller.calls)
    runner.run(request,checkpoint_guard=NativeResumeGuard(),publication_authorizer=lambda j:j.put('publication_authorized',True))
    assert (len(session.calls),len(caller.calls))==before and session.closed


def test_disabled_search_keeps_dedicated_research_without_spending(tmp_path,monkeypatch):
    runner,request,store,run_id,session,_=setup(tmp_path,monkeypatch,enabled=False)
    runner.run(request,publication_authorizer=lambda j:j.put('publication_authorized',True))
    assert not session.calls
    record=project_research_record(store,run_id)['record']
    assert 'search_disabled' in record['search_stop_reasons']
    assert any(s['source_name']=='sina.financial_statements' for s in record['evidence'])


def test_new_web_single_and_batch_select_v8_with_independent_ledgers(tmp_path, monkeypatch):
    from tradingagents.web.batch_models import BatchItem
    from tradingagents.web.manager import SingleRunManager
    _, request, _, _, _, _ = setup(tmp_path / 'setup', monkeypatch, enabled=False)
    sessions = []
    def factory(request, observer):
        session, caller = Session(), Caller()
        sessions.append(session)
        return NativeRunner(observer, sources_factory=Sources, caller_factory=lambda **kw: caller,
            search_session_factory=lambda: session)
    manager = SingleRunManager(RunStore(tmp_path / 'web'), runner_factory=factory)
    single = manager.start(request)
    assert manager.wait(single.run_id, 60).status == 'completed'
    items = tuple((request, BatchItem(request.ticker, '离线合成公司', request.ticker, 'china',
        RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date).run_id, i)) for i in range(2))
    batch = manager.start_batch(items, concurrency=1)
    ids = (single.run_id, *(item.run_id for item in batch.items))
    for run_id in ids:
        snapshot = manager.wait(run_id, 60)
        assert snapshot.status == 'completed', snapshot.error_message
        assert snapshot.metadata['native_workflow_version'] == 'evidence-production-v8'
        checkpoint = load_checkpoint(manager.store, run_id)
        assert checkpoint['identity']['workflow_version'] == 'evidence-production-v8'
        assert all(r['run_id'] == run_id for r in checkpoint['records'])
        assert project_research_record(manager.store, run_id)['record']['schema_version'] == 'research-record-v2'
    assert len(sessions) == 3 and all(not s.calls and s.closed for s in sessions)


def test_tavily_only_success_is_admitted_when_deepseek_unavailable(tmp_path, monkeypatch):
    runner, request, store, run_id, session, _ = setup(tmp_path, monkeypatch)
    post = session.post
    def tavily_only(url, **kwargs):
        response = post(url, **kwargs)
        if 'deepseek' in url:
            response.status_code = 401
        else:
            row = response.json()['results'][0]
            row.pop('date')
            row['published_date'] = (datetime.now(timezone.utc)-timedelta(days=1)).strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.json = lambda: {'results': [row]}
        return response
    session.post = tavily_only
    runner.run(request, publication_authorizer=lambda j: j.put('publication_authorized', True))
    record = project_research_record(store, run_id)['record']
    assert record['recovered_fields']
    assert any(s['source_name'].startswith('web.') for s in record['evidence'])
    assert all(b['outcomes'][0]['provider'] in {'deepseek', 'tavily'} for b in record['search_batches'])
