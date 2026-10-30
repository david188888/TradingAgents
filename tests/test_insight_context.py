"""Prompt compaction preserves evidence, while synthesis stays on saved premises."""
from datetime import date

from tests.test_insight_protocol import catalog, proposal
from tests.test_insight_research import response
from tests.test_native_publication import setup
from tradingagents.agents.schemas._insight import EvidenceCard
from tradingagents.graph.insight_research import catalog_prompt, run_insight_research


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
    journal.state['identity']['insight_context_policy'] = 'compact-saved-evidence-v1'
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


def test_saved_v9_identity_without_compaction_resumes_unchanged(tmp_path):
    import pytest

    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.execution.native_runner import native_identity, validate_native_resume
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

    observer, journal, _ = setup(tmp_path)
    request = AnalysisRequest('600519', '2026-09-30', research_profile='evidence_v1', effective_config={})
    identity = native_identity(request, workflow_version='evidence-production-v9', insight_context_policy=False)
    journal.put('identity', identity)
    validate_native_resume(observer.store, observer.run_id, request)
    assert 'insight_context_policy' not in journal.state['identity']
    identity = native_identity(request, workflow_version='evidence-production-v9')
    journal.put('identity', identity)
    validate_native_resume(observer.store, observer.run_id, request)
    journal.put('identity', {**identity, 'insight_context_policy': 'unknown-policy'})
    with pytest.raises(CatalystCheckpointConflict):
        validate_native_resume(observer.store, observer.run_id, request)
