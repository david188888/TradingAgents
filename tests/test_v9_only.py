"""Current execution rejects retired task identities without opening providers."""

import pytest

from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity, validate_native_resume
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict, ResearchJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore


def test_request_defaults_to_current_company_research():
    request = AnalysisRequest('002130.SZ', '2026-10-28', effective_config={})
    assert request.research_profile == 'evidence_v1'
    assert native_identity(request)['workflow_version'] == 'evidence-production-v9'


def test_retired_checkpoint_cannot_resume(tmp_path):
    request = AnalysisRequest('002130.SZ', '2026-10-28', research_profile='evidence_v1')
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date)
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    journal = ResearchJournal(observer, native_identity(request))
    journal.state['identity']['workflow_version'] = 'evidence-production-v8'
    journal.persist()
    with pytest.raises(ResearchCheckpointConflict, match='unsupported|incompatible'):
        validate_native_resume(store, snapshot.run_id, request)
