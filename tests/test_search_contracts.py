"""Search contracts preserve epistemic limits and immutable revision lineage."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.agents.test_research_record import native_payload
from tradingagents.agents.schemas._research_record import SourceEvidenceV1
from tradingagents.agents.schemas._research_record_v2 import (
    ResearchRecordV2,
    make_evidence_snapshot_v2,
)
from tradingagents.agents.schemas._search import EvidenceGapV1, QualifiedFieldV1
from tradingagents.research.record_codec import parse_research_record


def record_payload():
    payload = native_payload()
    payload['schema_version'] = 'research-record-v2'
    payload['workflow_version'] = 'evidence-production-v8'
    return payload


def test_v1_roundtrip_unchanged():
    from tradingagents.agents.schemas._research_record import ResearchRecordV1
    payload = native_payload()
    original = ResearchRecordV1.model_validate(payload)
    assert parse_research_record(original.model_dump(mode='json')).model_dump_json() == original.model_dump_json()
    with pytest.raises(ValueError):
        parse_research_record({**payload, 'schema_version': 'unknown'})


def test_v2_eight_snapshots_and_tamper_rejection():
    payload = record_payload()
    for version in range(1, 8):
        payload['evidence'].append({**payload['evidence'][0], 'evidence_id': f'e{version+1}'})
        snapshot = make_evidence_snapshot_v2(
            tuple(SourceEvidenceV1.model_validate(e) for e in payload['evidence']),
            version=version, parent_snapshot_id=payload['snapshots'][-1]['snapshot_id'])
        payload['snapshots'].append(snapshot.model_dump(mode='json'))
    record = ResearchRecordV2.model_validate(payload)
    assert len(record.snapshots) == 8
    assert parse_research_record(record.model_dump(mode='json')) == record
    for defect in ('hash', 'parent', 'deleted', 'ninth', 'dangling'):
        changed = deepcopy(payload)
        if defect == 'hash':
            changed['snapshots'][2]['content_sha256'] = 'a'*64
        elif defect == 'parent':
            changed['snapshots'][2]['parent_snapshot_id'] = 'wrong'
        elif defect == 'deleted':
            changed['snapshots'][2]['evidence_ids'] = []
        elif defect == 'ninth':
            changed['snapshots'].append(changed['snapshots'][-1])
        else:
            changed['claims'][0]['evidence_ids'] = ['missing']
        with pytest.raises(ValidationError):
            ResearchRecordV2.model_validate(changed)


def test_gap_rejects_executable_tool_args():
    gap = {'gap_id': 'g1', 'question': '成本下降是否已经传导？', 'capability': 'industry',
           'role': 'operating_quality', 'priority': 'material', 'cutoff': '2026-09-30',
           'evidence_needed': '可核对的采购价格', 'rationale': '可能影响利润解释'}
    assert EvidenceGapV1.model_validate(gap).gap_id == 'g1'
    with pytest.raises(ValidationError):
        EvidenceGapV1.model_validate({**gap, 'tool': 'execute_shell'})


@pytest.mark.parametrize('value', ['NaN', 'Infinity', True, None])
def test_qualified_field_requires_finite_value_and_lineage(value):
    with pytest.raises(ValidationError):
        QualifiedFieldV1(ticker='600519.SH', field='revenue', period='2025-12-31',
                         unit='CNY', basis='consolidated_actual', value=value)


def test_shared_factories_accept_overrides():
    from tests.search_fixtures import make_search_request
    assert make_search_request(provider='tavily').provider == 'tavily'


@pytest.mark.parametrize('url', ['https://user:password@example.com/a', 'https://example.com/a?api_key=secret'])
def test_search_hits_cannot_persist_credential_urls(url):
    from tradingagents.agents.schemas._search import SearchHitV1
    with pytest.raises(ValidationError):
        SearchHitV1(provider='deepseek', url=url, canonical_url=url)


def test_v2_retains_metric_and_assessment_reference_guards():
    from tests.search_fixtures import make_v2_record
    record = make_v2_record()
    payload = record.model_dump(mode='json')
    payload['metrics'] = [{'metric_id': 'bad', 'label': 'bad', 'availability': 'unavailable',
        'input_evidence_ids': ['missing'], 'unit': 'ratio', 'method': 'bounded',
        'calculation_version': 'test', 'input_sha256': 'a'*64, 'unavailable_reason': 'missing'}]
    with pytest.raises(ValidationError):
        ResearchRecordV2.model_validate(payload)


def test_v2_rejects_recovered_field_for_another_company():
    from datetime import date

    from tests.search_fixtures import make_v2_record
    from tests.test_search_recovery import recover, report
    from tradingagents.research.evidence_revisions import append_admission
    record = make_v2_record(ticker='000001', analysis_date=date.today())
    with pytest.raises(ValidationError):
        append_admission(record, recover(report()), round_id='1')


def test_review_proposal_requires_support_before_acceptance():
    from tradingagents.agents.schemas._search import SearchReviewProposalV1
    with pytest.raises(ValidationError, match='requires facts'):
        SearchReviewProposalV1(disposition='maintained', rationale='仍然成立')
