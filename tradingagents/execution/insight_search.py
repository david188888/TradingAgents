"""Bounded supplementary evidence collection for plain Insight questions."""

from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
from tradingagents.agents.schemas._search import EvidenceGapV1
from tradingagents.execution.budget import BudgetBucket, BudgetExhausted, BudgetLimitHit
from tradingagents.execution.search_admission import admit_saved_search
from tradingagents.execution.search_coordinator import compile_queries
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.research.evidence_revisions import (
    affected_roles,
    append_admission,
    recompute_revision,
)
from tradingagents.research.insights import build_insight_catalog
from tradingagents.research.native_policy import fact_views
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict


def collect_insight_supplement(record, questions, *, coordinator, ledger, round_id):
    if round_id not in (1, 2, 3) or sum(map(len, questions.values())) > 3:
        raise ValueError('insight_search_round_scope')
    identity = canonical_sha256({'record': record, 'questions': questions})
    key = f'insight.search.round.{round_id}'
    saved = ledger.cached_result(key)
    if saved is not None:
        if saved['input'] != identity:
            raise CatalystCheckpointConflict('insight search input changed')
        current = ResearchRecordV2.model_validate(saved['record'])
        gaps = saved['gaps']
    else:
        coordinator.budget.ensure_active()
        current, gaps = record, []
        prior = ledger.cached_result(key + '.input')
        if prior is not None and prior['sha256'] != identity:
            raise CatalystCheckpointConflict('insight search frontier changed')
        if prior is None:
            token = ledger.reserve(BudgetBucket.SEARCH_ROUNDS, stage='search.round', logical_call_id=key)
            if isinstance(token, BudgetLimitHit):
                gaps.append('search_round_budget_exhausted')
            else:
                ledger.mark_dispatched(token)
                ledger.record_result(key + '.input', {'sha256': identity})
                ledger.settle(token, ok=True, usage_available=False)
        if not gaps:
            company = record.company_basics.company_name if record.company_basics else record.ticker
            requests = []
            for role, values in questions.items():
                for question in values:
                    gap = EvidenceGapV1(gap_id='insight-gap.' + canonical_sha256({'role': role, 'question': question}),
                        question=question, evidence_needed=question, capability='context', role=role,
                        priority='material', cutoff=record.analysis_date, rationale='研究 Agent 明确请求补证。')
                    requests.extend(compile_queries(gap, ticker=record.ticker, company_name=company, round_id=round_id))
            try:
                batch = coordinator.collect(tuple(requests), input_snapshot_id=record.snapshots[-1].snapshot_id)
                admitted = admit_saved_search(batch, ticker=record.ticker, cutoff=record.analysis_date, ledger=ledger, requirements=())
                current = append_admission(record, admitted, round_id=str(round_id))
                current = current.model_copy(update={'search_batches': (*current.search_batches, batch)})
                current = recompute_revision(current, journal=ledger.journal)
                gaps.extend(batch.stop_reasons)
                gaps.extend(admitted.rejections)
                gaps.extend(admitted.conflicts)
            except (BudgetExhausted, TimeoutError):
                coordinator.budget.ensure_active()
                gaps.append('search_budget_or_time_exhausted')
        ledger.record_result(key, {'input': identity, 'record': current.model_dump(mode='json'), 'gaps': gaps})
    return current, {'catalogs': {role: build_insight_catalog(current, facts=facts)
        for role, facts in fact_views(current, valuation=True).items()},
        'affected_roles': list(affected_roles(record, current)), 'gaps': gaps}
