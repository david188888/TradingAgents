"""Persist admission once so crash replay preserves captured source bytes."""

from tradingagents.agents.schemas._search import AdmissionBatchV1
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.research.search_admission import admit_search_batch
from tradingagents.research.search_recovery import recover_fields
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict


def admit_saved_search(batch, *, ticker, cutoff, requirements, ledger):
    identity = canonical_sha256({'batch': batch, 'ticker': ticker, 'cutoff': str(cutoff), 'requirements': requirements})
    key = 'search.admission.'+batch.batch_id
    cached = ledger.cached_result(key)
    if cached is not None:
        if cached['input'] != identity:
            raise CatalystCheckpointConflict('search admission input changed')
        return AdmissionBatchV1.model_validate(cached['admitted'])
    admitted = recover_fields(admit_search_batch(batch, ticker=ticker, cutoff=cutoff), requirements=requirements)
    ledger.record_result(key, {'input': identity, 'admitted': admitted.model_dump(mode='json')})
    return admitted
