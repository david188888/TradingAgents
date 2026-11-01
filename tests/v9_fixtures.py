"""Current runner, ledgers, publication and Reader with offline transports."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from tradingagents.dataflows.search_sources import SearchEvidenceSources
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import NativeRunner
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

PROFILE = '<title>沃尔核材(002130)公司资料_新浪财经_新浪网</title><table id="comInfo1"><tr><td>上市市场：</td><td>深圳证券交易所</td><td>上市日期：</td><td><a>2007-04-20</a></td></tr></table>'
FIELDS = {"income": ("BIZINCO", "NETPROFIT"), "balancesheet": ("TOTASSET", "TOTLIAB"), "cashflow": ("MANANETR",)}


def statement(table):
    return {"result": {"status": {"code": 0}, "data": {"report_list": {
        "20260630": {"rType": "合并期末", "rCurrency": "CNY", "publish_date": "20260825",
            "data": [{"item_field": field, "item_value": "4653091807.210000"} for field in FIELDS[table]]}}}}}


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
        metadata={'research_profile':'evidence_v1','native_workflow_version':'evidence-production-v9'})
    store.create_run(snapshot)
    observer=DurableRunObserver(store,snapshot.run_id,development_assertions=False)
    session,caller=Session(unavailable=unavailable),None
    runner=NativeRunner(observer,sources_factory=Sources,caller_factory=lambda **kw:caller,
        search_session_factory=lambda:session)
    return runner,request,store,snapshot.run_id,session,caller




def journal_setup(tmp_path):
    from tradingagents.execution.native_runner import native_identity
    from tradingagents.runtime.research_checkpoint import ResearchJournal
    request = AnalysisRequest("002130.SZ", "2026-10-28")
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date,
        metadata={"research_profile": "evidence_v1", "native_workflow_version": "evidence-production-v9"})
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    journal = ResearchJournal(observer, native_identity(request))
    return observer, journal, None
