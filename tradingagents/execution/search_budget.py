"""Durable search reservations and activity time; no provider dependencies."""

import time
from contextlib import contextmanager

from tradingagents.execution.budget import (
    BudgetBucket as B,
    BudgetExhausted,
    BudgetLimitHit,
    Reservation,
)

SEARCH_BUDGET_POLICY = {
    'version': 'dual-search-budget-v1',
    'limits': {'main_analysis': 8, 'focus_response': 1, 'basic_model_attempts': 12,
               'model_attempts': 21, 'search_review': 9, 'search_rounds': 3,
               'deepseek_search': 50, 'tavily_search': 50, 'search_page': 8,
               'data_capability_calls': 24, 'data_http_attempts': 64,
               'all_http_attempts': 172},
    'activity_seconds': 90,
    'round_attempts': 3,
}


class SearchBudget:
    def __init__(self, ledger, policy=None, clock=time.monotonic, *,
                 ensure_active=lambda: None, run_remaining=lambda: float('inf')):
        self.ledger = ledger
        self.journal = ledger.journal
        self.policy = policy or SEARCH_BUDGET_POLICY
        if self.policy != SEARCH_BUDGET_POLICY:
            raise ValueError('unsupported search budget policy')
        self.clock = clock
        self.ensure_active = ensure_active
        self.run_remaining = run_remaining
        self._depth = 0
        self._started = None
        with self.journal.lock:
            if getattr(ledger, '_search_budget_owner', None) is not None:
                raise ValueError('one activity clock owner per run ledger')
            ledger._search_budget_owner = self
            state = self.journal.state.setdefault('search_activity', {'spent': 0.0, 'pending': None})
            if state['pending'] is not None:
                state['spent'] = min(90.0, state['spent'] + state['pending'])
                state['pending'] = None
                self.journal.persist()

    def reserve_search(self, provider: str, task_id: str) -> Reservation:
        self.ensure_active()
        bucket = {'deepseek': B.DEEPSEEK_SEARCH, 'tavily': B.TAVILY_SEARCH}[provider]
        return self.ledger.reserve_or_raise(bucket, stage='search', logical_call_id=f'search.{provider}.{task_id}')

    def reserve_page(self, task_id: str) -> Reservation:
        self.ensure_active()
        return self.ledger.reserve_or_raise(B.SEARCH_PAGE, stage='search.page', logical_call_id='search.page.' + task_id)

    def reserve_review(self, round_id: str, role: str, attempt_id: str) -> Reservation:
        self.ensure_active()
        if round_id not in ('1', '2', '3'):
            raise ValueError('review requires round 1..3')
        stage = 'search.review.round.' + round_id
        with self.journal.lock:
            used = self.ledger.consumed(B.SEARCH_REVIEW, stage)
            if used >= 3:
                raise BudgetExhausted(BudgetLimitHit(B.SEARCH_REVIEW, stage, 3, used, 'round_limit_reached'))
            return self.ledger.reserve_or_raise(B.SEARCH_REVIEW, stage=stage,
                logical_call_id='native.'+attempt_id)

    def remaining_seconds(self) -> float:
        with self.journal.lock:
            spent = self.journal.state['search_activity']['spent']
            active = max(0.0, self.clock() - self._started) if self._started is not None else 0.0
            return max(0.0, min(90.0 - spent - active, self.run_remaining()))

    def ensure_search_active(self):
        self.ensure_active()
        if self.remaining_seconds() <= 0:
            raise TimeoutError('search activity budget exhausted')

    @contextmanager
    def activity_batch(self, batch_id: str):
        self.ensure_active()
        with self.journal.lock:
            remaining = self.remaining_seconds()
            if remaining <= 0:
                raise TimeoutError('search activity budget exhausted')
            if self._depth == 0:
                self._started = self.clock()
                self.journal.state['search_activity']['pending'] = remaining
                self.journal.persist()
            self._depth += 1
        try:
            yield
        finally:
            with self.journal.lock:
                self._depth -= 1
                if self._depth == 0:
                    state = self.journal.state['search_activity']
                    state['spent'] = min(90.0, state['spent'] + max(0.0, self.clock() - self._started))
                    state['pending'] = None
                    self._started = None
                    self.journal.persist()
