"""Prompt compaction preserves evidence, while synthesis stays on saved premises."""
import json
from datetime import date

from tests.test_insight_protocol import catalog, proposal
from tests.test_insight_research import response
from tests.v9_fixtures import journal_setup as setup
from tradingagents.agents.schemas._insight import EvidenceCard
from tradingagents.graph.insight_research import catalog_prompt, run_insight_research
from tradingagents.research.evidence_retrieval import retrieve_evidence


def test_coalesced_passages_keep_exact_boundaries_and_do_not_merge_sources():
    text = '收入' * 500 + '跨窗口风险提示' + '收入' * 600
    context = {
        'facts': [{'evidence_ids': ['a', 'b']}],
        'sources': [{'evidence_id': sid, 'content': {'text': text}} for sid in ('a', 'b')],
    }
    original = retrieve_evidence(context, '收入 风险提示', limit=6)
    merged = retrieve_evidence(context, '收入 风险提示', limit=6, coalesce=True)
    assert len(merged) < len(original)
    for sid in ('a', 'b'):
        spans = [p for p in merged if p['evidence_id'] == sid]
        assert all(p['text'] == text[p['start']:p['end']] for p in spans)
        assert any('跨窗口风险提示' in p['text'] for p in spans)
        assert {i for p in spans for i in range(p['start'], p['end'])} == {
            i for p in original if p['evidence_id'] == sid for i in range(p['start'], p['end'])
        }


def test_compact_catalog_keeps_all_facts_limits_and_exact_source_passages():
    c = catalog()
    value = catalog_prompt(c, compact=True)
    assert len(value['evidence']) == len(c.evidence)
    for item, fact in zip(value['evidence'], c.evidence, strict=True):
        assert (item['ref'], item['text'], item['limitations']) == (fact.ref, fact.text, list(fact.limitations))
        assert 'fact_id' not in item
        assert item['source_ids'] == ['S1']
    assert value['sources'][0]['evidence_id'] == 'S1'
    assert value['sources'][0]['locator'] == c.sources[0].content.locator_label
    for passage in value['source_passages']:
        assert passage['evidence_id'] == 'S1'
        assert passage['text'] == c.sources[0].content.text[passage['start']:passage['end']]
    assert value['numbers'] == catalog_prompt(c)['numbers']
    assert catalog_prompt(c)['evidence'][0]['fact_id'] == c.evidence[0].fact_id


def test_compact_synthesis_keeps_saved_support_but_not_unrelated_new_facts(tmp_path):
    _, journal, _ = setup(tmp_path)
    c = catalog()
    c = c.model_copy(update={'evidence': (*c.evidence, EvidenceCard(ref='E99', fact_id='unused',
        text='未被任何观点或审阅采用的材料。', source_ids=c.evidence[0].source_ids))})
    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            assert any(e['ref'] == 'E99' for e in context['evidence'])
            return {'insights': [proposal(evidence_refs=['E1'])]}
        if stage == 'challenge':
            assert any(e['text'] == '未被任何观点或审阅采用的材料。' for e in context['evidence'])
        if stage == 'synthesis':
            assert all(e['text'] != '未被任何观点或审阅采用的材料。' for e in context['sources']['evidence'])
            assert context['sources']['evidence']
            assert not context['sources']['numbers']
            assert 'source_passages' not in context['sources']
            assert all('note' not in r for r in context['reviews'])
        return response(stage, context, phase=phase)
    report = run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': c}, caller=respond, journal=journal, ensure_active=lambda: None)
    assert report.synthesis is not None


def test_invalid_response_preserves_safe_reason_without_rejected_prose(tmp_path):
    _, journal, _ = setup(tmp_path)
    def respond(stage, context, *, phase='main'):
        if stage == 'challenge':
            return {'reviews': [{'target': 'I1', 'concern': '需要核查。', 'reasoning': '存在替代解释。', 'evidence_refs': []}]}
        if stage == 'response_operating_quality':
            return {'responses': [{'target': 'I1', 'action': 'maintain', 'reasoning': 'PRIVATE_REPLY 10亿元',
                'evidence_refs': [], 'replacement': None}]}
        return response(stage, context, phase=phase)
    run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': catalog()}, caller=respond, journal=journal, ensure_active=lambda: None)
    diagnostics = journal.state['insight.diagnostics.response_operating_quality']
    assert diagnostics == [{'index': 0, 'target': 'I1', 'code': 'numeric_literal_unbound'}]
    assert 'PRIVATE_REPLY' not in str(journal.state)


def test_saved_v9_identity_requires_current_context_policy(tmp_path):
    import pytest

    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.execution.native_runner import native_identity, validate_native_resume
    from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict
    observer, journal, _ = setup(tmp_path)
    request = AnalysisRequest('002130.SZ', '2026-10-28')
    identity = native_identity(request)
    journal.put('identity', identity)
    validate_native_resume(observer.store, observer.run_id, request)
    legacy = {**identity, 'insight_context_policy': 'insight-handoff-v1'}
    journal.put('identity', legacy)
    assert validate_native_resume(observer.store, observer.run_id, request) == legacy
    journal.put('identity', {**legacy, 'insight_context_policy': 'compact-saved-evidence-v1'})
    with pytest.raises(ResearchCheckpointConflict):
        validate_native_resume(observer.store, observer.run_id, request)


def test_v2_scopes_review_repair_and_reply_without_changing_saved_result(tmp_path):
    base = catalog()
    first = base.model_copy(update={'evidence': base.evidence[:1]})
    second_card = base.evidence[1].model_copy(update={'ref': 'E1', 'text': '独立材料，提及柑橘。'})
    second = base.model_copy(update={'evidence': (second_card,), 'numbers': ()})
    def execute(policy):
        _, journal, _ = setup(tmp_path / policy)
        identity = journal.state['identity']
        identity['insight_context_policy'] = policy
        identity['config']['insight_review_policy'] = 'targeted-v1'
        prompts = {}
        def respond(stage, context, *, phase='main'):
            prompts[stage, phase] = context
            if stage == 'operating_quality':
                return {'insights': [proposal(claim='首个判断。', reasoning='第一项理由。')]}
            if stage == 'event_context':
                return {'insights': [proposal(claim='另一判断。', reasoning='第二项理由。')]}
            if stage == 'challenge':
                ref, evidence = ('I1', 'E1') if phase == 'main' else ('I2', 'E2')
                return {'reviews': [{'target': ref, 'concern': '证据边界仍需澄清。',
                                    'reasoning': '需要核实。', 'evidence_refs': [evidence]}]}
            if stage.startswith('response_'):
                ref, evidence = ('I1', 'E1') if stage.endswith('operating_quality') else ('I2', 'E2')
                return {'responses': [{'target': ref, 'action': 'maintain', 'reasoning': '维持现有判断。',
                                       'evidence_refs': [evidence], 'replacement': None}]}
            return response(stage, context, phase=phase)
        report = run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ',
            analysis_date=date(2026, 10, 28), catalogs={'operating_quality': first, 'event_context': second},
            caller=respond, journal=journal, ensure_active=lambda: None)
        return prompts, report.model_dump(exclude={'run_id'})

    before, old_report = execute('insight-handoff-v1')
    after, new_report = execute('insight-handoff-v2')
    assert new_report == old_report
    for stage, phase, target, evidence, numbers in (
        ('challenge', 'repair', 'I2', 'E2', []),
        ('response_event_context', 'main', 'I2', 'E2', []),
        ('response_operating_quality', 'main', 'I1', 'E1', ['N1']),
    ):
        scoped = after[stage, phase]
        assert [item['ref'] for item in scoped['insights']] == [target]
        assert [item['ref'] for item in scoped['evidence']] == [evidence]
        assert [item['ref'] for item in scoped['numbers']] == numbers
        if stage.startswith('response_'):
            reply, = scoped['reviews']
            assert reply['evidence_refs'] == [evidence]
            assert 'note' not in reply
    synthesis = after['synthesis', 'main']
    assert 'source_passages' not in synthesis['sources']
    assert [r['evidence_refs'] for r in synthesis['responses']] == [['E1'], ['E2']]
    assert [r['evidence_refs'] for r in synthesis['reviews']] == [['E1'], ['E2']]
    keys = before.keys() & after.keys()
    old_bytes = sum(len(json.dumps(before[key], ensure_ascii=False).encode()) for key in keys)
    new_bytes = sum(len(json.dumps(after[key], ensure_ascii=False, separators=(',', ':')).encode()) for key in keys)
    assert new_bytes < old_bytes
    print(f'L2 fixture context bytes: {old_bytes} -> {new_bytes} ({1-new_bytes/old_bytes:.1%} reduction)')
