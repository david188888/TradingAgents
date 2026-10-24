"""Three shared gap-directed rounds, affected roles only and durable replay."""

from datetime import date, datetime, timedelta, timezone

import pytest

from tests.search_fixtures import make_gap, make_v2_record
from tests.test_search_budget import Journal
from tradingagents.agents.schemas._search import SearchBatchV1, SearchHitV1, SearchOutcomeV1
from tradingagents.execution.budget import BudgetBucket as B
from tradingagents.execution.search_budget import SearchBudget
from tradingagents.execution.search_reviews import run_search_reviews


class Coordinator:
    def __init__(self, budget, *, empty=False):
        self.budget, self.calls, self.empty = budget, [], empty

    def collect(self, requests, *, input_snapshot_id):
        self.calls.append(requests)
        hit = SearchHitV1(provider='deepseek', url=f'https://example.com/round{len(self.calls)}',
            canonical_url=f'https://example.com/round{len(self.calls)}', title='成本信息',
            content='公司与行业的新增原文信息', published_at=datetime.now(timezone.utc)-timedelta(days=1))
        return SearchBatchV1(batch_id='batch.'+str(len(self.calls)), input_snapshot_id=input_snapshot_id,
            requests=requests, hits=() if self.empty else (hit,), outcomes=tuple(
                SearchOutcomeV1(task_id=r.task_id, provider=r.provider, status='empty' if self.empty else 'ok',
                    hits=() if self.empty else (hit.model_copy(update={'provider': r.provider}),)) for r in requests))


def harness(*, empty=False):
    journal = Journal()
    record = make_v2_record(run_id=journal.ledger.run_id, analysis_date=date.today())
    coordinator = Coordinator(SearchBudget(journal.ledger), empty=empty)
    gap = make_gap(cutoff=date.today(), target_ids=(record.hypotheses[0].hypothesis_id,))
    return journal, record, coordinator, gap


def caller(calls, *, more=False):
    def invoke(stage, context):
        calls.append((stage, context))
        return {'disposition': 'maintained', 'rationale': '新增原文仍不足以消除原有经济不确定性。',
            'supporting_fact_ids': [context['facts'][-1]['claim_id']], 'new_risks': [],
            'gaps': [make_gap(gap_id='next.'+str(len(calls)), cutoff=date.today()).model_dump(mode='json')] if more else []}
    return invoke


def run(journal, record, coordinator, gaps, invoke):
    return run_search_reviews(record, gaps, coordinator=coordinator, caller=invoke,
        ledger=journal.ledger, cancelled=lambda: False)


def test_three_rounds_then_no_fourth():
    j, record, c, gap = harness()
    calls = []
    result = run(j, record, c, (gap,), caller(calls, more=True))
    assert len(c.calls) == len(result.search_reviews) == 3
    assert j.ledger.consumed(B.SEARCH_ROUNDS) == 3
    assert len(result.snapshots) <= 8
    assert 'round_limit_reached' in result.search_stop_reasons
    assert run(j, record, c, (gap,), caller(calls, more=True)) == result
    assert len(calls) == 3


def test_no_qualified_delta_no_review():
    j, record, c, gap = harness(empty=True)
    calls = []
    result = run(j, record, c, (gap,), caller(calls))
    assert not calls and len(c.calls) == 1
    assert len(result.snapshots) == 1
    assert 'no_qualified_delta' in result.search_stop_reasons


def test_only_affected_roles_review():
    j, record, c, gap = harness()
    calls = []
    result = run(j, record, c, (gap,), caller(calls))
    assert [r.role for r in result.search_reviews] == ['operating_quality']
    assert len(calls) == 1
    assert result.hypotheses == record.hypotheses


def test_retry_uses_third_slot_and_skips_unreviewed_role():
    j, record, c, gap = harness()
    calls = []
    def invoke(stage, context):
        calls.append(stage)
        for n in range(2):
            grant = c.budget.reserve_review('1', context['role'], stage+'.retry.'+str(n))
            j.ledger.mark_dispatched(grant)
            j.ledger.settle(grant, ok=False, usage_available=False)
        return caller([])(stage, context)
    result = run(j, record, c, (gap,), invoke)
    assert len(calls) == 1
    assert j.ledger.consumed(B.SEARCH_REVIEW) == 3
    assert len(result.search_reviews) == 1


def test_review_cannot_rewrite_original_condition():
    j, record, c, gap = harness()
    def invalid(stage, context):
        return {**caller([])(stage, context), 'assumptions': ['改写原条件']}
    result = run(j, record, c, (gap,), invalid)
    assert not result.search_reviews and result.hypotheses == record.hypotheses
    assert any('review_unavailable' in reason for reason in result.search_stop_reasons)


def test_repeated_material_stops_instead_of_spending_three_rounds():
    j, record, c, gap = harness()
    original = c.collect
    first = []
    def repeated(requests, **kwargs):
        batch = original(requests, **kwargs)
        if not first:
            first.extend(batch.hits)
        return batch.model_copy(update={'hits': tuple(first), 'outcomes': tuple(
            o.model_copy(update={'hits': tuple(first)}) for o in batch.outcomes)})
    c.collect = repeated
    calls = []
    result = run(j, record, c, (gap,), caller(calls, more=True))
    assert len(c.calls) == 2 and len(calls) == 1
    assert 'no_qualified_delta' in result.search_stop_reasons


def test_new_evidence_without_review_blocks_old_affirmative_support():
    from tradingagents.agents.schemas._research_dialogue import excluded_support
    from tradingagents.execution.search_coordinator import compile_queries
    from tradingagents.research.evidence_revisions import append_admission
    from tradingagents.research.search_admission import admit_search_batch
    j, record, c, gap = harness()
    batch = c.collect(compile_queries(gap, ticker=record.ticker, company_name='测试公司', round_id=1),
        input_snapshot_id=record.snapshots[-1].snapshot_id)
    changed = append_admission(record, admit_search_batch(batch, ticker=record.ticker, cutoff=record.analysis_date), round_id='1')
    assert changed.snapshots != record.snapshots
    # No dialogue fixture: the targeted review itself must still exclude a withdrawal.
    calls = []
    def withdrawn(stage, context):
        return {**caller(calls)(stage, context), 'disposition': 'withdrawn'}
    result = run(j, record, c, (gap,), withdrawn)
    assert record.hypotheses[0].claim_id in excluded_support(result)


@pytest.mark.parametrize('numeric', [False, True])
def test_v2_kernel_searches_between_replies_and_single_synthesis(tmp_path, numeric):
    from tests.test_unified_research import UnifiedCaller, setup
    from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
    from tradingagents.graph.native_research import run_native_research
    from tradingagents.research.minimum_evidence import compute_checks
    _, old = setup(tmp_path)
    j = Journal(run_id=old.run_id)
    payload = old.model_dump(mode='python')
    payload.update(schema_version='research-record-v2', workflow_version='evidence-production-v8',
        run_id=j.ledger.run_id, evidence_checks=None)
    record = ResearchRecordV2.model_validate(payload)
    record = ResearchRecordV2.model_validate({**record.model_dump(mode='python'), 'evidence_checks': compute_checks(record)})
    if numeric:
        from tradingagents.research.numeric_integration import attach_numeric_attribution
        j.state['identity']['numeric_narrative_policy'] = 'anchored-narrative-v1'
        record = attach_numeric_attribution(record, j)
    c = Coordinator(SearchBudget(j.ledger))
    initial_collect = c.collect
    def historical(requests, **kw):
        batch = initial_collect(requests, **kw)
        hit = batch.hits[0].model_copy(update={'url': 'https://static.cninfo.com.cn/finalpage/2026-10-01/123.PDF',
            'published_at': datetime(2026, 10, 1, tzinfo=timezone.utc)})
        return batch.model_copy(update={'hits': (hit,), 'outcomes': tuple(
            o.model_copy(update={'hits': (hit,)}) for o in batch.outcomes)})
    c.collect = historical
    base = UnifiedCaller()
    calls = []
    def invoke(stage, context):
        calls.append(stage)
        if stage.startswith('search_review.'):
            assert context['target_ids'] and context['hypotheses']
            value = {'disposition': 'maintained', 'rationale': '保留原判断的条件和不确定性。',
                'supporting_fact_ids': [context['facts'][-1]['claim_id']], 'new_risks': [], 'gaps': []}
        else:
            value = base(stage, context)
        if stage == 'operating_quality':
            value['gaps'] = [make_gap(cutoff=record.analysis_date).model_dump(mode='json')]
        if numeric:
            gaps = value.pop('gaps', [])
            return {'proposal': value, 'plans': [], 'structured_bindings': [], **({'gaps': gaps} if stage != 'synthesis' else {})}
        return value
    def supplement(current, gaps):
        return run(j, current, c, gaps, invoke)
    output = run_native_research(record, caller=invoke, ledger=j.ledger, minimum=True,
        valuation=True, scoped=True, independent=True, unified=True, supplement=supplement)
    assert output.assessment and len(output.search_reviews) == 1
    review_index = next(i for i, s in enumerate(calls) if s.startswith('search_review.'))
    assert review_index > next(i for i, s in enumerate(calls) if s.startswith('response_'))
    assert calls.count('synthesis') == 1 and review_index < calls.index('synthesis')
    assert output.dialogue.input_snapshot_id != output.snapshots[-1].snapshot_id


def test_unknown_review_dispatch_is_not_reopened_on_resume():
    j, record, c, gap = harness()
    first = c.collect
    batches = []
    def capture(requests, **kwargs):
        batch = first(requests, **kwargs)
        batches.append(batch)
        return batch
    c.collect = capture
    def crash(stage, context):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run(j, record, c, (gap,), crash)
    restored = Journal(j.state)
    resumed = Coordinator(SearchBudget(restored.ledger))
    replayed = []
    def resume_batch(requests, **kw):
        replayed.append(True)
        if len(replayed) == 1:
            return batches[0]
        return SearchBatchV1(batch_id='empty-next', input_snapshot_id=kw['input_snapshot_id'], requests=requests)
    resumed.collect = resume_batch
    calls = []
    result = run(restored, record, resumed, (gap,), caller(calls))
    assert not calls and not result.search_reviews
    assert any('review_unavailable' in reason for reason in result.search_stop_reasons)


def test_three_affected_roles_retry_uses_last_slot_and_marks_unreviewed(tmp_path):
    from tests.test_unified_research import setup
    from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
    _, old = setup(tmp_path)
    j = Journal(run_id=old.run_id)
    record = ResearchRecordV2.model_validate({**old.model_dump(mode='python'),
        'schema_version': 'research-record-v2', 'workflow_version': 'evidence-production-v8',
        'analysis_date': date.today(), 'evidence_checks': None, 'valuation': None})
    c = Coordinator(SearchBudget(j.ledger))
    gaps = tuple(make_gap(gap_id='g'+str(i), role=role, cutoff=date.today())
        for i, role in enumerate(('operating_quality', 'event_context', 'market_context')))
    calls = []
    def invoke(stage, context):
        calls.append(context['role'])
        if context['role'] == 'operating_quality':
            c.empty = True
            # Actual retry reservation consumes the third shared attempt.
            token = c.budget.reserve_review('1', context['role'], stage+'.main.retry.1')
            j.ledger.mark_dispatched(token)
            j.ledger.settle(token, ok=True, usage_available=False)
        return {'disposition': 'maintained', 'rationale': '仍待核对。',
            'supporting_fact_ids': [context['facts'][-1]['claim_id']]}
    result = run(j, record, c, gaps, invoke)
    assert calls[:2] == ['operating_quality', 'event_context']
    assert 'market_context' not in calls
    assert j.ledger.consumed(B.SEARCH_REVIEW, 'search.review.round.1') == 3
    assert 'review_unavailable:market_context' in result.search_stop_reasons
    from tradingagents.research.search_effective import unreviewed_roles
    assert 'market_context' in unreviewed_roles(result)
