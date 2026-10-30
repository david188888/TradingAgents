"""New Insight boundaries: isolated failures, host-owned references and numbers."""

import hashlib
from datetime import datetime, timezone

import pytest

from tradingagents.agents.schemas._insight import EvidenceCard, InsightCatalog, NumericReference
from tradingagents.agents.schemas._numeric_narrative import NumericAnchorV1
from tradingagents.agents.schemas._research_record import SourceContentV1, SourceEvidenceV1
from tradingagents.research.insights import compile_insights


def catalog():
    text = '已保存披露片段'
    source = SourceEvidenceV1(evidence_id='source-a', source_name='official', source_kind='official',
        availability='available', usable_as_of=datetime(2026, 10, 1, tzinfo=timezone.utc),
        content=SourceContentV1(kind='excerpt', text=text, locator_label='第十页',
            content_sha256=hashlib.sha256(text.encode()).hexdigest()))
    anchor = NumericAnchorV1(anchor_id='num.a', definition_key='financial.revenue', label='营业收入',
        subject='公司甲', basis='actual_reported', value='1000000000', unit='CNY',
        required_fact_ids=('fact-1',), input_evidence_ids=('source-a',), snapshot_id='snapshot-a',
        metadata={'report_period': '2026-06-30'}, lineage={'kind': 'source',
            'source_content_sha256': source.content.content_sha256})
    return InsightCatalog(snapshot_id='snapshot-a', sources=(source,),
        evidence=tuple(EvidenceCard(ref=f'E{i}', fact_id=f'fact-{i}', text=text,
            source_ids=('source-a',)) for i in range(1, 9)),
        numbers=(NumericReference(ref='N1', anchor=anchor),))


def proposal(**changes):
    return {'claim': '收入规模不能独自证明客户结构稳定。', 'evidence_refs': ['E1'],
        'reasoning': '公司仍有客户依赖 [E1]。', 'limitations': '尚缺少后续订单信息。', **changes}


def compile_one(**changes):
    return compile_insights({'insights': [proposal(**changes)]}, catalog=catalog(), role='operating_quality').items[0]


def test_four_field_protocol_preserves_long_insight_and_more_than_six_references():
    item = compile_one(claim='需要继续核查。' * 100, evidence_refs=[f'E{i}' for i in range(1, 9)])
    assert item.status == 'accepted'
    assert len(item.fact_ids) == 8
    assert len(item.proposal.claim) > 400
    assert set(item.proposal.model_dump()) == {'claim', 'evidence_refs', 'reasoning', 'limitations'}


def test_duplicate_and_inline_references_are_merged_by_host():
    item = compile_one(evidence_refs=['E1', 'E1'], reasoning='另一项披露值得关注 [E2]。')
    assert item.status == 'accepted'
    assert item.fact_ids == ('fact-1', 'fact-2')


def test_numeric_reference_brings_its_own_evidence_and_full_label():
    item = compile_one(evidence_refs=[], reasoning='已披露的数值是 [N1]。')
    assert item.status == 'accepted'
    assert item.fact_ids == ('fact-1',)
    assert item.numeric_ids == ('num.a',)
    assert all(value in item.rendered.reasoning for value in ('公司甲', '2026-06-30', '营业收入', '10.00亿元'))


@pytest.mark.parametrize('changes,code', [
    ({'evidence_refs': [], 'reasoning': '这是一个研究假设。'}, 'evidence_missing'),
    ({'evidence_refs': ['E999']}, 'reference_unknown'),
    ({'reasoning': '收入 [N999]。'}, 'reference_unknown'),
    ({'reasoning': '收入达10亿元 [E1]。'}, 'numeric_literal_unbound'),
    ({'reasoning': '增长２０％ [E1]。'}, 'numeric_literal_unbound'),
    ({'reasoning': '增长百分之二十 [E1]。'}, 'numeric_literal_unbound'),
])
def test_unsupported_items_are_pending_not_silently_admitted(changes, code):
    item = compile_one(**changes)
    assert item.status == 'pending'
    assert code in item.issues


def test_year_ticker_and_enumeration_do_not_become_unbound_financial_numbers():
    item = compile_one(reasoning='2026年，关注002130.SZ披露的两项变化：1.客户结构；2.订单期限 [E1]。')
    assert item.status == 'accepted'


def test_bad_sibling_does_not_discard_good_or_pending_items():
    result = compile_insights({'insights': [proposal(), {'claim': '缺字段'}, proposal(evidence_refs=['E99'])]},
        catalog=catalog(), role='operating_quality')
    assert [(i.index, i.status) for i in result.items] == [(0, 'accepted'), (2, 'pending')]
    assert [r.index for r in result.rejected] == [1]
    assert '缺字段' not in result.rejected[0].model_dump_json()


def test_numeric_dependency_cannot_escape_provided_evidence_scope():
    context = catalog()
    context = context.model_copy(update={'evidence': context.evidence[1:]})
    item = compile_insights({'insights': [proposal(reasoning='数值 [N1]。', evidence_refs=['E2'])]},
        catalog=context, role='operating_quality').items[0]
    assert item.status == 'pending'
    assert 'numeric_scope' in item.issues


def test_host_identity_is_stable_and_distinguishes_versions():
    payload = {'insights': [proposal()]}
    first = compile_insights(payload, catalog=catalog(), role='operating_quality')
    assert first == compile_insights(payload, catalog=catalog(), role='operating_quality')
    revised = compile_insights(payload, catalog=catalog(), role='operating_quality', revision=2)
    assert first.items[0].insight_id != revised.items[0].insight_id


def test_outer_shape_failure_is_explicit():
    with pytest.raises(ValueError, match='insight_batch_shape'):
        compile_insights({'insights': 'not an array'}, catalog=catalog(), role='operating_quality')


@pytest.mark.parametrize('text', ['收入10亿 [E1]。', '收入10 dollars [E1]。', '增长10 basis points [E1]。'])
def test_explicit_quantity_units_cannot_escape_numeric_binding(text):
    assert compile_one(reasoning=text).status == 'pending'
