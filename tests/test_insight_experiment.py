"""Offline checks for the opt-in V9 experiment, including a real saved-report replay."""

from datetime import date

import pytest

from tests.test_insight_protocol import catalog, proposal
from tests.test_insight_research import response
from tests.v9_fixtures import journal_setup as setup
from tradingagents.agents.schemas._insight import EvidenceCard
from tradingagents.graph.insight_research import run_insight_research
from tradingagents.research.insight_report import parse_insight_report
from tradingagents.research.native_versions import EXPERIMENTAL_INSIGHT_CONTEXT_POLICY
from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict

CUTOFF = date(2026, 10, 28)


def experiment(tmp_path):
    _, journal, _ = setup(tmp_path)
    journal.put('identity', {**journal.state['identity'], 'insight_context_policy': EXPERIMENTAL_INSIGHT_CONTEXT_POLICY})
    return journal


def run(journal, base, responder, **kwargs):
    return run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=CUTOFF,
        catalogs={'operating_quality': base}, caller=responder, journal=journal, ensure_active=lambda: None, **kwargs)


@pytest.mark.parametrize('all_keep', [False, True])
def test_material_delta_reuses_prefix_and_rejects_unresolved_all_keep(tmp_path, all_keep):
    journal = experiment(tmp_path)
    base = catalog()
    material = EvidenceCard(ref='E1', fact_id='fact-new', text='客户已经取消核心订单。',
                            source_ids=('source-a',), limitations=('conflict:order_direction',))
    updated = base.model_copy(update={'evidence': (material, *(
        card.model_copy(update={'ref': f'E{index}'}) for index, card in enumerate(base.evidence, 2)))})
    seen = {}

    def respond(stage, context, *, phase='main'):
        seen[stage, phase] = context
        if stage == 'operating_quality':
            if phase == 'main':
                return {'insights': [proposal(), proposal(claim='独立的产品线判断。', reasoning='另一产品线 [E2]。',
                                                         evidence_refs=['E2'])], 'search_requests': ['核查最新订单']}
            old, independent = [item['target'] for item in context['previous_findings']]
            assert context['evidence'] == seen[stage, 'main']['evidence']
            assert context['sources'] == seen[stage, 'main']['sources']
            assert [row['ref'] for row in context['delta_catalog']['evidence']] == ['E9']
            assert context['material_delta_refs'] == ['E9']
            return {'keep_ids': [old, independent] if all_keep else [independent], 'withdraw': [] if all_keep else [
                {'target': old, 'evidence_refs': ['E9']}], 'revise': [], 'add': [], 'delta_reviewed_refs': ['E9']}
        if stage == 'challenge':
            assert any(e['text'] == material.text for e in context['evidence'])
        return response(stage, context, phase=phase)

    report = run(journal, base, respond, supplement=lambda *_: {
        'catalogs': {'operating_quality': updated}, 'affected_roles': ['operating_quality'], 'gaps': []})
    assert parse_insight_report(report.model_dump(mode='json')) == report
    assert report.insights[0].status == 'excluded'
    assert report.insights[1].status == ('excluded' if all_keep else 'accepted')
    assert ('operating_quality_supplement_unresolved' in report.gaps) == all_keep
    assert report.catalogs['review'].evidence[-1].text == material.text


def test_supplement_replay_binds_saved_batch_to_exact_round_catalog(tmp_path):
    journal = experiment(tmp_path)
    base = catalog()
    new_card = base.evidence[-1].model_copy(update={'fact_id': 'new', 'text': '额外材料。'})
    updated = base.model_copy(update={'evidence': (*base.evidence, new_card)})
    supplement_calls = []

    def supplement(*_):
        changed = updated if not supplement_calls else base
        supplement_calls.append(changed)
        return {'catalogs': {'operating_quality': changed}, 'affected_roles': ['operating_quality'], 'gaps': []}

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            if phase == 'main':
                return {'insights': [proposal()], 'search_requests': ['核查披露']}
            return {'keep_ids': [context['previous_findings'][0]['target']], 'revise': [], 'add': [], 'withdraw': [],
                    'delta_reviewed_refs': ['E9']}
        raise RuntimeError('simulated interruption after durable supplement')

    with pytest.raises(RuntimeError, match='simulated interruption'):
        run(journal, base, respond, supplement=supplement)
    with pytest.raises(ResearchCheckpointConflict, match='supplement catalog changed'):
        run(journal, base, lambda *_args, **_kwargs: pytest.fail('must not dispatch'), supplement=supplement)


@pytest.mark.parametrize('count', [9, 39])
def test_jev_missing_or_truncated_checks_send_full_scope_to_challenge(tmp_path, count):
    journal = experiment(tmp_path)
    journal.put('identity', {**journal.state['identity'], 'jev_verification_enabled': True,
                           'config': {'insight_review_policy': 'targeted-v1'}})
    base = catalog()
    base = base.model_copy(update={'evidence': (*base.evidence, *(
        EvidenceCard(ref=f'E{i}', fact_id=f'other-{i}', text='不相关的独立信息。', source_ids=('source-a',))
        for i in range(9, count + 1)))})

    class Caller:
        def call_jev_verification(self, _target, state, questions):
            refs = {r.removeprefix('conflict_') for r in questions if r.startswith('conflict_')}
            assert len(refs) == min(30, count)
            assert 'E1' in refs
            assert refs == {row['ref'] for row in state['global_evidence']}
            return {key: (0 if key.startswith('conflict_') else 0.99) for key in questions if key != 'conflict_E1'}, {}

        def __call__(self, stage, context, *, phase='main'):
            if stage == 'challenge':
                assert context['insights'][0]['partial_conflict_coverage']
                assert len(context['evidence']) == count
            return response(stage, context, phase=phase)

    report = run(journal, base, Caller())
    assert report.reviews[0].status == 'no_counterevidence'  # From Challenge, not Jev auto-clear.


def test_supported_date_normalization_keeps_quantity_check_and_report_replay(tmp_path):
    journal = experiment(tmp_path)

    def respond(stage, context, *, phase='main'):
        if stage == 'challenge':
            return {'reviews': [{'target': 'I1', 'concern': None, 'evidence_refs': ['E1'],
                                'reasoning': '截至2026-10-28未见有效反证。'}]}
        return response(stage, context, phase=phase)

    report = run(journal, catalog(), respond)
    assert '二零二六年十月二十八日' in report.reviews[0].reasoning
    assert parse_insight_report(report.model_dump(mode='json')) == report
