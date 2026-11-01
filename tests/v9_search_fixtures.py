"""Offline supplemental-search fixtures for current Insight execution."""
from datetime import date, datetime, timedelta, timezone

from tests.test_insight_protocol import catalog
from tests.test_search_budget import Journal
from tradingagents.agents.schemas._evidence import RecordClaimV1
from tradingagents.agents.schemas._evidence_record import EvidenceRecord, make_evidence_snapshot
from tradingagents.agents.schemas._search import SearchBatchV1, SearchHitV1, SearchOutcomeV1
from tradingagents.execution.search_budget import SearchBudget


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
    source = catalog().sources[0]
    record = EvidenceRecord(run_id=journal.ledger.run_id, ticker="002130.SZ", analysis_date=date.today(),
        evidence=(source,), snapshots=(make_evidence_snapshot((source,)),), claims=(
            RecordClaimV1(claim_id="fact-1", kind="fact", statement="已保存原始资料。", evidence_ids=(source.evidence_id,)),))
    return journal, record, Coordinator(SearchBudget(journal.ledger), empty=empty), None
