"""Host-assigned search scope, shared budget and recovery without model gates."""

from tests.test_search_reviews import harness
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.insight_search import collect_insight_supplement


def test_supplement_uses_host_scope_and_replays_saved_results():
    journal, record, coordinator, _ = harness()
    requests = {'operating_quality': ('客户是否变化',)}
    kwargs = {'coordinator': coordinator, 'ledger': journal.ledger, 'round_id': 1}
    current, result = collect_insight_supplement(record, requests, **kwargs)
    assert result['affected_roles'] == ['operating_quality']
    assert current.snapshots != record.snapshots
    assert len(coordinator.calls) == 1
    assert all(r.ticker == record.ticker and r.cutoff == record.analysis_date for r in coordinator.calls[0])
    assert {r.provider for r in coordinator.calls[0]} == {'deepseek', 'tavily'}
    assert journal.ledger.consumed(BudgetBucket.SEARCH_ROUNDS) == 1
    assert collect_insight_supplement(record, requests, **kwargs)[0] == current
    assert len(coordinator.calls) == 1


def test_no_delta_does_not_require_specialist_rerun():
    journal, record, coordinator, _ = harness(empty=True)
    current, result = collect_insight_supplement(record, {'operating_quality': ('客户是否变化',)},
        coordinator=coordinator, ledger=journal.ledger, round_id=1)
    assert result['affected_roles'] == []
    assert current.snapshots == record.snapshots
