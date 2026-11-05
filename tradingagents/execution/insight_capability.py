"""Admit gateway capability results into the saved evidence record, once per round."""

from tradingagents.agents.schemas._evidence_record import EvidenceRecord
from tradingagents.execution.capability_gateway import execute_capability_requests
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.research.evidence_revisions import affected_roles, append_admission
from tradingagents.research.insights import build_insight_catalog
from tradingagents.research.native_policy import fact_views
from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict


def collect_capability_supplement(record, requests, *, ledger, ensure_active, round_id,
                                  session=None, available_requirements=frozenset()):
    """requests: {role: (request dict, ...)}; returns (record, result) like the search supplement."""
    identity = canonical_sha256({'record': record, 'requests': requests})
    key = f'insight.capability.round.{round_id}'
    saved = ledger.cached_result(key)
    if saved is not None:
        if saved['input'] != identity:
            raise ResearchCheckpointConflict('insight capability input changed')
        current, gaps = EvidenceRecord.model_validate(saved['record']), saved['gaps']
    else:
        current, gaps = record, []
        for role, values in requests.items():
            result = execute_capability_requests(values, role=role, ticker=record.ticker,
                cutoff=record.analysis_date, ledger=ledger, ensure_active=ensure_active,
                session=session, available_requirements=available_requirements)
            gaps.extend(result.gaps)
            if result.admitted.observations:
                current = append_admission(current, result.admitted, round_id=f'capability.{round_id}.{role}')
        ledger.record_result(key, {'input': identity, 'record': current.model_dump(mode='json'), 'gaps': gaps})
    return current, {'catalogs': {role: build_insight_catalog(current, facts=facts)
        for role, facts in fact_views(current, valuation=True).items()},
        'affected_roles': list(affected_roles(record, current)), 'gaps': list(gaps)}
