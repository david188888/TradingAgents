"""Gap-directed search and one review per affected role in three shared rounds."""

import json
from datetime import date

from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
from tradingagents.agents.schemas._search import (
    SearchGapsV1,
    SearchReviewProposalV1,
    SearchReviewV1,
)
from tradingagents.execution.budget import BudgetBucket, BudgetExhausted, BudgetLimitHit
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.execution.search_admission import admit_saved_search
from tradingagents.execution.search_coordinator import compile_queries
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.research.evidence_revisions import (
    affected_roles,
    append_admission,
    recompute_revision,
)
from tradingagents.research.native_policy import fact_views
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict


def extract_stage_gaps(value, *, stage, context, ledger, persist=True):
    """Questions are saved separately from accepted narrative and numeric proof."""
    value = value.model_dump(mode='json') if hasattr(value, 'model_dump') else json.loads(value) if isinstance(value, str) else dict(value)
    key = 'native.search_gaps.'+stage
    if 'gaps' not in value and ledger.cached_result(key) is not None:
        return value
    raw = value.pop('gaps', [])
    gaps = SearchGapsV1.model_validate({'gaps': raw}).gaps
    cutoff = context.get('cutoff') or context.get('numeric_analysis_date') or context.get('record', {}).get('analysis_date')
    role = context.get('role') or (stage if stage in ('operating_quality', 'event_context', 'market_context') else stage.removeprefix('response_'))
    allowed = {x['hypothesis_id'] for x in context.get('hypotheses', context.get('record', {}).get('hypotheses', []))}
    allowed.update(x['challenge_id'] for x in context.get('challenges', context.get('record', {}).get('challenges', [])))
    for gap in gaps:
        if cutoff is None or gap.cutoff != date.fromisoformat(str(cutoff)):
            raise ValueError('gap cutoff changed')
        if role in ('operating_quality', 'event_context', 'market_context') and gap.role != role:
            raise ValueError('gap role changed')
        if not set(gap.target_ids) <= allowed:
            raise ValueError('gap target outside supplied scope')
    key = 'native.search_gaps.'+stage
    payload = {'gaps': [g.model_dump(mode='json') for g in gaps]}
    if not persist:
        return value
    prior = ledger.cached_result(key)
    if prior is not None and prior != payload:
        raise CatalystCheckpointConflict('saved stage gaps changed')
    ledger.record_result(key, payload)
    return value


def _save(record, **changes):
    return ResearchRecordV2.model_validate({**record.model_dump(mode='python'), **changes})


def run_search_reviews(record, gaps, *, coordinator, caller, ledger, cancelled):
    from tradingagents.graph.native_research import _call
    from tradingagents.research.numeric_integration import numeric_enabled
    from tradingagents.research.numeric_narrative import prepare_numeric_context

    if record.schema_version != 'research-record-v2' or ledger.run_id != record.run_id:
        raise ValueError('search reviews require this run V2 record')
    frontier = canonical_sha256({'record': record, 'gaps': gaps})
    saved = ledger.cached_result('search.reviews.output')
    if saved is not None:
        if saved['input'] != frontier:
            raise CatalystCheckpointConflict('search review input changed')
        return ResearchRecordV2.model_validate(saved['record'])
    current, pending = record, tuple(gaps)
    if ledger.journal.state['identity'].get('search_research_policy', {}).get('enabled') is False:
        current = _save(record, search_gaps=pending,
            search_stop_reasons=tuple(dict.fromkeys((*record.search_stop_reasons, 'search_disabled'))))
        ledger.record_result('search.reviews.output', {'input': frontier, 'record': current.model_dump(mode='json')})
        return current
    reasons = list(record.search_stop_reasons)
    for round_id in range(1, 4):
        if cancelled():
            raise AnalysisCancelled('search reviews cancelled')
        coordinator.budget.ensure_active()
        if not pending:
            reasons.append('no_eligible_gaps')
            break
        selected = tuple(sorted(pending, key=lambda g: ({'critical': 0, 'material': 1, 'minor': 2}[g.priority], g.gap_id))[:3])
        if any(g.cutoff != record.analysis_date for g in selected):
            raise ValueError('gap cutoff differs from record')
        logical = f'search.round.{round_id}'
        bound = canonical_sha256({'record': current, 'gaps': selected})
        cached = ledger.cached_result(logical)
        if cached is not None:
            if cached['input'] != bound:
                raise CatalystCheckpointConflict('search round input changed')
            current = ResearchRecordV2.model_validate(cached['record'])
            pending = tuple(SearchGapsV1.model_validate({'gaps': cached['gaps']}).gaps)
            continue
        prior = ledger.cached_result(logical+'.input')
        if prior is not None and prior['sha256'] != bound:
            raise CatalystCheckpointConflict('search round frontier changed')
        if prior is None:
            grant = ledger.reserve(BudgetBucket.SEARCH_ROUNDS, stage='search.round', logical_call_id=logical)
            if isinstance(grant, BudgetLimitHit):
                reasons.append('round_budget_exhausted')
                break
            ledger.mark_dispatched(grant)
            ledger.record_result(logical+'.input', {'sha256': bound})
            ledger.settle(grant, ok=True, usage_available=False)
        name = current.company_basics.company_name if current.company_basics else None
        requests = tuple(r for gap in selected for r in compile_queries(gap, ticker=record.ticker,
            company_name=name or record.ticker, round_id=round_id))
        try:
            batch = coordinator.collect(requests, input_snapshot_id=current.snapshots[-1].snapshot_id)
        except (BudgetExhausted, TimeoutError):
            coordinator.budget.ensure_active()
            reasons.append('search_budget_or_time_exhausted')
            break
        admitted = admit_saved_search(batch, ticker=record.ticker, cutoff=record.analysis_date, ledger=ledger,
            requirements=tuple(dict.fromkeys(f for r in requests for f in r.requirements)))
        before = current
        current = append_admission(current, admitted, round_id=str(round_id))
        current = _save(current, search_batches=(*current.search_batches, batch))
        if current.snapshots == before.snapshots:
            reasons.append('no_qualified_delta')
            break
        current = recompute_revision(current, journal=ledger.journal)
        next_gaps = list(pending[len(selected):]) if tuple(pending[:len(selected)]) == selected else [g for g in pending if g not in selected]
        for role in affected_roles(before, current):
            facts = fact_views(current, valuation=True)[role]
            role_gaps = tuple(g for g in selected if g.role == role)
            # Initial specialist gaps precede host-assigned hypothesis IDs.
            # A role review must still bind its original hypotheses, including
            # roles affected by shared evidence rather than their own gap.
            owned = tuple(o.hypothesis_id for o in current.dialogue.origins if o.role == role) if current.dialogue else ()
            targets = tuple(dict.fromkeys((*owned, *(t for g in role_gaps for t in g.target_ids))))
            stage = f'search_review.{round_id}.{role}.'+current.snapshots[-1].content_sha256
            context = {'role': role, 'round_id': round_id, 'cutoff': str(current.analysis_date),
                'input_snapshot_id': current.snapshots[-1].snapshot_id, 'target_ids': targets,
                'facts': [f.model_dump(mode='json') for f in facts],
                'hypotheses': [h.model_dump(mode='json') for h in current.hypotheses if h.hypothesis_id in targets],
                'challenges': [c.model_dump(mode='json') for c in current.challenges if c.challenge_id in targets],
                'new_evidence_ids': sorted(set(current.snapshots[-1].evidence_ids)-set(before.snapshots[-1].evidence_ids)),
                'instruction': '复核相关专项，明确维持、修正、撤回或无法回答。原假设与条件不可改写。仅引用给定事实；计算不证明经济因果。可提出下一轮的具体缺口。'}
            if numeric_enabled(ledger.journal.state['identity']):
                context = prepare_numeric_context(stage, context, current, identity=ledger.journal.state['identity'])
            saved_stage = ledger.cached_result('native.'+stage)
            reservation = None
            if saved_stage is None and not any(r.logical_call_id == 'native.'+stage and r.dispatched_at is not None for r in ledger.records()):
                try:
                    reservation = coordinator.budget.reserve_review(str(round_id), role, stage)
                except BudgetExhausted:
                    reasons.append('review_unavailable:'+role)
                    next_gaps.extend(role_gaps)
                    continue
            proposal = _call(stage, context, SearchReviewProposalV1, caller=caller, ledger=ledger,
                cancelled=cancelled, reservation=reservation)
            if proposal is None or not set(proposal.supporting_fact_ids) <= {f.claim_id for f in facts}:
                reasons.append('review_unavailable:'+role)
                next_gaps.extend(role_gaps)
                continue
            saved_gaps = ledger.cached_result('native.search_gaps.'+stage) or {'gaps': []}
            new_gaps = SearchGapsV1.model_validate(saved_gaps).gaps
            review = SearchReviewV1(review_id='review.'+canonical_sha256({'stage': stage, 'proposal': proposal}),
                round_id=round_id, role=role, input_snapshot_id=current.snapshots[-1].snapshot_id,
                target_ids=targets, gaps=new_gaps, **proposal.model_dump(mode='python'))
            current = _save(current, search_reviews=(*current.search_reviews, review))
            next_gaps.extend(new_gaps)
        pending = tuple(dict.fromkeys(next_gaps))
        ledger.record_result(logical, {'input': bound, 'record': current.model_dump(mode='json'),
            'gaps': [g.model_dump(mode='json') for g in pending]})
    if pending and ledger.consumed(BudgetBucket.SEARCH_ROUNDS) >= 3:
        reasons.append('round_limit_reached')
    current = _save(current, search_gaps=pending, search_stop_reasons=tuple(dict.fromkeys(reasons)))
    ledger.record_result('search.reviews.output', {'input': frontier, 'record': current.model_dump(mode='json')})
    return current
