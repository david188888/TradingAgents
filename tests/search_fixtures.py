"""Offline factories shared by search contract and integration tests."""

from types import SimpleNamespace

from tests.test_search_contracts import record_payload
from tradingagents.agents.schemas._research_record_v2 import ResearchRecordV2
from tradingagents.agents.schemas._search import EvidenceGapV1, SearchRequestV1


def make_v2_record(**changes):
    return ResearchRecordV2.model_validate({**record_payload(), **changes})


def make_search_request(**changes):
    value = {'task_id': 'task1', 'provider': 'deepseek',
        'kind': 'initial', 'ticker': '600519.SH', 'company_name': '测试公司', 'query': '测试公司 行业',
        'cutoff': '2026-09-30'}
    return SearchRequestV1.model_validate({**value, **changes})


def make_gap(**changes):
    value = {'gap_id': 'gap1', 'question': '原料成本是否下降？', 'capability': 'industry',
        'role': 'operating_quality', 'priority': 'material', 'cutoff': '2026-09-30',
        'evidence_needed': '带日期的价格原文', 'rationale': '核对成本解释'}
    return EvidenceGapV1.model_validate({**value, **changes})


def make_search_harness(**changes):
    return SimpleNamespace(**({"record": make_v2_record(), "requests": [], "responses": []} | changes))
