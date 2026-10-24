"""Physical dispatch, persistence and overlapping activity obey hard ceilings."""

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tradingagents.execution.budget import BudgetBucket as B, BudgetExhausted
from tradingagents.execution.search_budget import SEARCH_BUDGET_POLICY, SearchBudget
from tradingagents.runtime.catalyst_checkpoint import DurableBudgetLedger, _record_json


class Journal:
    def __init__(self, state=None, *, run_id="budget-test"):
        self.state = copy.deepcopy(state) if state else {'identity': {
            'workflow_version': 'evidence-production-v8',
            'search_budget_policy': SEARCH_BUDGET_POLICY}, 'records': [], 'results': {}}
        self.observer = SimpleNamespace(run_id=run_id)
        self.last_event = SimpleNamespace(sequence=0)
        self.lock = threading.RLock()
        self.failed = False
        self.ledger = DurableBudgetLedger(self)

    def put(self, key, value):
        self.state[key] = value
        self.persist()

    def persist(self):
        self.state['records'] = [_record_json(r) for r in self.ledger.records()]


def spent(ledger, reservation):
    ledger.mark_dispatched(reservation)
    ledger.settle(reservation, ok=False)


@pytest.mark.parametrize('provider', ['deepseek', 'tavily'])
def test_search_50_then_51_refused(provider):
    journal = Journal()
    budget = SearchBudget(journal.ledger)
    for i in range(50):
        spent(journal.ledger, budget.reserve_search(provider, f'query-{i}'))
    with pytest.raises(BudgetExhausted):
        budget.reserve_search(provider, 'query-51')
    assert len(journal.ledger.records()) == 50


def test_pages_8_then_9_refused():
    j = Journal()
    budget = SearchBudget(j.ledger)
    for i in range(8):
        spent(j.ledger, budget.reserve_page(str(i)))
    with pytest.raises(BudgetExhausted):
        budget.reserve_page('nine')


def test_model_pools_12_9_21():
    j = Journal()
    for bucket, count in ((B.MAIN_ANALYSIS, 8), (B.FOCUS_RESPONSE, 1), (B.NETWORK_RETRY, 3)):
        for i in range(count):
            spent(j.ledger, j.ledger.reserve_or_raise(bucket, stage=f'base-{bucket}-{i}'))
    with pytest.raises(BudgetExhausted):
        j.ledger.reserve_or_raise(B.STRUCTURED_REPAIR, stage='base-overflow')
    budget = SearchBudget(j.ledger)
    for r in range(1, 4):
        for i in range(3):
            spent(j.ledger, budget.reserve_review(str(r), 'operating_quality', str(i)))
    assert j.ledger.consumed(B.MODEL_ATTEMPTS) == 21
    with pytest.raises(BudgetExhausted):
        budget.reserve_review('3', 'market_context', 'overflow')


def test_http_total_172_and_dedicated_64():
    j = Journal()
    b = SearchBudget(j.ledger)
    for i in range(64):
        spent(j.ledger, j.ledger.reserve_or_raise(B.DATA_HTTP_ATTEMPTS, stage='source', logical_call_id=f'data-{i}'))
    with pytest.raises(BudgetExhausted):
        j.ledger.reserve_or_raise(B.DATA_HTTP_ATTEMPTS, stage='source-overflow')
    for provider in ('deepseek', 'tavily'):
        for i in range(50):
            spent(j.ledger, b.reserve_search(provider, str(i)))
    for i in range(8):
        spent(j.ledger, b.reserve_page(str(i)))
    assert j.ledger.consumed(B.ALL_HTTP_ATTEMPTS) == 172


def test_concurrent_last_slot_atomic():
    j = Journal()
    b = SearchBudget(j.ledger)
    for i in range(49):
        spent(j.ledger, b.reserve_search('deepseek', str(i)))
    def reserve(i):
        try:
            return b.reserve_search('deepseek', f'last-{i}')
        except BudgetExhausted:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(reserve, range(8)))
    assert sum(v is not None for v in values) == 1


def test_resume_unknown_dispatch_consumed():
    j = Journal()
    b = SearchBudget(j.ledger)
    for i in range(50):
        j.ledger.mark_dispatched(b.reserve_search('tavily', str(i)))
    resumed = Journal(j.state)
    with pytest.raises(BudgetExhausted):
        SearchBudget(resumed.ledger).reserve_search('tavily', 'retry-after-crash')


def test_parallel_activity_union_and_model_pause():
    j = Journal()
    now = [0.0]
    b = SearchBudget(j.ledger, clock=lambda: now[0])
    with b.activity_batch('a'):
        now[0] = 10
        with b.activity_batch('b'):
            now[0] = 20
        now[0] = 30
    assert b.remaining_seconds() == 60
    now[0] = 1000  # Model time is not search activity.
    assert b.remaining_seconds() == 60
    with b.activity_batch('c'):
        now[0] += 5
    assert b.remaining_seconds() == 55
    resumed = SearchBudget(Journal(j.state).ledger, clock=lambda: now[0])
    assert resumed.remaining_seconds() == 55


def test_review_round_retries_consume_three_slots():
    j = Journal()
    b = SearchBudget(j.ledger)
    for attempt in range(3):
        spent(j.ledger, b.reserve_review('1', 'operating_quality', str(attempt)))
    with pytest.raises(BudgetExhausted):
        b.reserve_review('1', 'event_context', 'fourth')
    assert j.ledger.consumed(B.SEARCH_REVIEW) == 3


def test_crash_pending_time_not_refunded():
    j = Journal()
    b = SearchBudget(j.ledger, clock=lambda: 0.0)
    context = b.activity_batch('pending')
    context.__enter__()
    try:
        resumed = SearchBudget(Journal(j.state).ledger, clock=lambda: 0.0)
        assert resumed.remaining_seconds() == 0
    finally:
        context.__exit__(None, None, None)


def test_legacy_custom_limits_are_not_narrowed_by_new_parent_pools():
    from tradingagents.execution.budget import BudgetLedger
    ledger = BudgetLedger('legacy', limits={B.MODEL_ATTEMPTS:16, B.MAIN_ANALYSIS:16, B.DATA_HTTP_ATTEMPTS:80})
    for index in range(16):
        spent(ledger, ledger.reserve_or_raise(B.MAIN_ANALYSIS, stage=str(index)))
    for index in range(80):
        spent(ledger, ledger.reserve_or_raise(B.DATA_HTTP_ATTEMPTS, stage=str(index)))
