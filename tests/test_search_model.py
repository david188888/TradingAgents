"""Actual SDK attempts, including repair/retry, stay in the shared review pool."""

import time

from tests.test_native_model import CONFIG, sdk
from tests.test_search_budget import Journal
from tradingagents.agents.schemas._search import SearchReviewProposalV1
from tradingagents.execution.budget import BudgetBucket as B
from tradingagents.execution.native_model import NativeModelCaller
from tradingagents.execution.search_budget import SearchBudget
from tradingagents.graph.native_research import _call


def test_sdk_review_repair_uses_review_pool_and_keeps_base_budget(monkeypatch):
    journal = Journal()
    budget = SearchBudget(journal.ledger)
    stage = 'search_review.1.operating_quality.'+'a'*64
    context = {'role': 'operating_quality', 'round_id': 1, 'cutoff': '2026-09-30', 'facts': []}
    valid = {'disposition': 'unanswerable', 'rationale': '没有足够证据，保留待查。',
        'supporting_fact_ids': [], 'new_risks': [], 'gaps': []}
    stub, _ = sdk(monkeypatch, ['bad json', valid])
    caller = NativeModelCaller(effective_config=CONFIG, run_id=journal.ledger.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic()+30)
    reservation = budget.reserve_review('1', 'operating_quality', stage)
    output = _call(stage, context, SearchReviewProposalV1, caller=caller, ledger=journal.ledger,
        cancelled=lambda: False, reservation=reservation)
    assert output is not None and len(stub.prompts) == 2
    assert journal.ledger.consumed(B.SEARCH_REVIEW) == 2
    assert journal.ledger.consumed(B.BASIC_MODEL_ATTEMPTS) == 0
    assert journal.ledger.consumed(B.STRUCTURED_REPAIR) == 0
    assert caller.recover_cached(stage, context) == output.model_dump(mode='json')


def test_sdk_review_transient_retry_is_not_a_base_retry(monkeypatch):
    from tests.test_native_retry import HTTPFailure
    from tradingagents.execution.native_retry import MODEL_RETRY_POLICY
    journal = Journal()
    journal.state['identity']['model_retry_policy'] = MODEL_RETRY_POLICY
    budget = SearchBudget(journal.ledger)
    stage = 'search_review.1.operating_quality.'+'b'*64
    context = {'role': 'operating_quality', 'round_id': 1, 'cutoff': '2026-09-30', 'facts': []}
    valid = {'disposition': 'unanswerable', 'rationale': '证据不足，继续保留问题。',
        'supporting_fact_ids': [], 'new_risks': [], 'gaps': []}
    stub, _ = sdk(monkeypatch, [HTTPFailure(503), valid])
    caller = NativeModelCaller(effective_config=CONFIG, run_id=journal.ledger.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic()+30)
    monkeypatch.setattr(caller, '_wait_for_retry', lambda _: None)
    output = _call(stage, context, SearchReviewProposalV1, caller=caller, ledger=journal.ledger,
        cancelled=lambda: False, reservation=budget.reserve_review('1', 'operating_quality', stage))
    assert output is not None and len(stub.prompts) == 2
    assert journal.ledger.consumed(B.SEARCH_REVIEW) == 2
    assert journal.ledger.consumed(B.NETWORK_RETRY) == 0
