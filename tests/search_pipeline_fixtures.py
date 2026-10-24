"""Real RunStore V8 fixtures; all company sources and model outputs are offline."""

from datetime import datetime, timezone

from tests.test_minimum_evidence import fixture
from tests.test_unified_research import UnifiedCaller
from tradingagents.agents.schemas._search import (
    AdmissionBatchV1,
    SearchBatchV1,
    SearchHitV1,
    SearchOutcomeV1,
)
from tradingagents.execution.search_budget import SEARCH_BUDGET_POLICY, SearchBudget
from tradingagents.graph.native_research import run_native_research
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.native_record import build_native_record
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore


def saved_v2_run(tmp_path, *, with_search=False):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker='600803', analysis_date='2026-10-05', metadata={
        'research_profile': 'evidence_v1', 'native_workflow_version': 'evidence-production-v8'})
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    identity = {'workflow_version': 'evidence-production-v8', 'search_budget_policy': SEARCH_BUDGET_POLICY,
        'ticker': snapshot.ticker, 'mode': 'company_research', 'cutoff': snapshot.analysis_date}
    journal = CatalystJournal(observer, identity)
    draft, context = fixture()
    payload = draft.model_dump(mode='json')
    payload['run_id'] = snapshot.run_id
    for evidence in payload['evidence']:
        evidence.update(run_id=snapshot.run_id, ticker=snapshot.ticker)
    seed = build_native_record(type(draft).model_validate(payload), context, mode='company_research',
        include_valuation=True, include_minimum=True, search_admission=AdmissionBatchV1(batch_id='empty'))
    from tests.search_fixtures import make_gap
    from tradingagents.execution.search_reviews import run_search_reviews
    base = UnifiedCaller()
    budget = SearchBudget(journal.ledger)
    class Coordinator:
        def __init__(self):
            self.budget, self.calls = budget, []
        def collect(self, requests, *, input_snapshot_id):
            self.calls.append(requests)
            url = f'https://static.cninfo.com.cn/finalpage/2026-10-01/{len(self.calls)}.PDF'
            hit = SearchHitV1(provider='deepseek', url=url, canonical_url=url, title='公司与行业材料',
                content=f'公司代码：600803。公司与行业的新增公开材料，批次标识 {len(self.calls)}；披露不证明经营原因。',
                published_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
            return SearchBatchV1(batch_id='fixture.'+str(len(self.calls)), input_snapshot_id=input_snapshot_id,
                requests=requests, hits=(hit,), outcomes=tuple(SearchOutcomeV1(task_id=r.task_id,
                    provider=r.provider, status='ok', hits=(hit.model_copy(update={'provider':r.provider}),)) for r in requests))
    coordinator = Coordinator()
    def caller(stage, context):
        if stage.startswith('search_review.'):
            return {'disposition':'maintained', 'rationale':'仍保留原有条件和经济不确定性。',
                'supporting_fact_ids':[context['facts'][-1]['claim_id']], 'new_risks':[],
                'gaps':[make_gap(gap_id='next.'+str(context['round_id']), cutoff=seed.analysis_date).model_dump(mode='json')]}
        value = base(stage, context)
        if with_search and stage == 'operating_quality':
            value['gaps'] = [make_gap(cutoff=seed.analysis_date).model_dump(mode='json')]
        return value
    def supplement(record, gaps):
        return run_search_reviews(record, gaps, coordinator=coordinator, caller=caller,
            ledger=journal.ledger, cancelled=lambda:False) if with_search else record
    record = run_native_research(seed, caller=caller, ledger=journal.ledger,
        minimum=True, valuation=True, scoped=True, independent=True, unified=True,
        supplement=supplement)
    return journal, record
