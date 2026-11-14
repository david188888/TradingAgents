"""Saved Insight pipeline exercises real compilation with deterministic callers."""

from datetime import date

import pytest

from tests.test_insight_protocol import catalog, proposal
from tests.v9_fixtures import journal_setup as setup
from tradingagents.execution.insight_model import InsightUnavailable
from tradingagents.graph.insight_research import run_insight_research


def execute(journal, respond):
    return run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ',
        analysis_date=date(2026, 10, 28), catalogs={'operating_quality': catalog()},
        caller=respond, journal=journal, ensure_active=lambda: None)


def response(stage, context, *, phase='main'):
    if stage == 'operating_quality':
        return {'insights': [proposal()]}
    if stage == 'challenge':
        return {'reviews': [{'target': 'I1', 'concern': None, 'reasoning': '已审阅，未发现额外有效反证。', 'evidence_refs': []}]}
    if stage == 'synthesis':
        return {'judgement': '依据现有研究作有边界的判断。', 'stance': 'favorable',
            'insight_refs': ['I1'], 'reasoning': '客户依赖需要持续关注 [I1]。',
            'limitations': '尚缺少后续订单变化和完整估值材料。', 'next_check': '核查后续客户披露。'}
    raise AssertionError(stage)


def test_valid_pipeline_rates_without_legacy_valuation_anchor_and_replays(tmp_path):
    _, journal, _ = setup(tmp_path)
    report = execute(journal, response)
    assert report.schema_version == 'insight-research-v1'
    assert report.synthesis.stance == 'favorable'
    assert report.reviews[0].status == 'no_counterevidence'
    assert len(report.insights) == 1
    assert execute(journal, lambda *a, **k: (_ for _ in ()).throw(AssertionError('replay called model'))) == report


def test_only_failed_items_are_repaired_and_accepted_item_is_immutable(tmp_path):
    _, journal, _ = setup(tmp_path)
    seen = []

    def respond(stage, context, *, phase='main'):
        seen.append((stage, phase))
        if stage == 'operating_quality':
            if phase == 'main':
                return {'insights': [proposal(), proposal(claim='毛利率变化', evidence_refs=['E999']),
                    proposal(claim='现金流变化', evidence_refs=['E998'])]}
            tasks = context['repair_items']
            assert [t['proposal']['claim'] for t in tasks] == ['毛利率变化', '现金流变化']
            assert [t['issues'] for t in tasks] == [['reference_unknown'], ['reference_unknown']]
            return {'repairs': [{'target': 2, 'proposal': proposal(claim='现金流变化')},
                {'target': 1, 'proposal': proposal(claim='毛利率变化')}]}
        return response(stage, context, phase=phase)

    report = execute(journal, respond)
    assert [i.proposal.claim for i in report.insights] == [proposal()['claim'], '毛利率变化', '现金流变化']
    assert [i.index for i in report.insights] == [0, 1, 2]
    assert seen.count(('operating_quality', 'repair')) == 1


def test_repair_preserves_the_original_draft_even_if_it_lacks_a_required_field(tmp_path):
    _, journal, _ = setup(tmp_path)
    draft = {'claim': '毛利率下降', 'evidence_refs': ['E1'], 'reasoning': '依据 E1。'}

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            if phase == 'main':
                return {'insights': [draft]}
            assert context['repair_items'] == [{'target': 0, 'proposal': draft,
                'issues': ['insight_schema_invalid'], 'fields': ['limitations']}]
            return {'repairs': [{'target': 0, 'proposal': proposal(**draft)}]}
        return response(stage, context, phase=phase)

    report = execute(journal, respond)
    assert report.insights[0].status == 'accepted'
    assert report.insights[0].proposal.claim == '毛利率下降'


def test_ambiguous_alias_range_is_repaired_without_changing_other_findings(tmp_path):
    _, journal, _ = setup(tmp_path)

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            if phase == 'main':
                return {'insights': [proposal(reasoning='依据 E2-N1。'), proposal(reasoning='依据 E2-E3。')]}
            assert [item['target'] for item in context['repair_items']] == [0]
            return {'repairs': [{'target': 0, 'proposal': None}]}
        return response(stage, context, phase=phase)

    report = execute(journal, respond)
    assert [item.index for item in report.insights] == [1]
    assert report.insights[0].proposal.reasoning == '依据 [E2]、[E3]。'
    assert 'operating_quality_partial' in report.gaps


def test_invalid_synthesis_keeps_specialist_findings_without_default_rating(tmp_path):
    _, journal, _ = setup(tmp_path)

    def respond(stage, context, *, phase='main'):
        value = response(stage, context, phase=phase)
        if stage == 'synthesis':
            value['insight_refs'] = ['I999']
        return value

    report = execute(journal, respond)
    assert report.synthesis is None
    assert report.insights[0].status == 'accepted'
    assert 'synthesis_unavailable' in report.gaps


def test_withdrawn_insight_cannot_support_synthesis(tmp_path):
    _, journal, _ = setup(tmp_path)

    def respond(stage, context, *, phase='main'):
        if stage == 'challenge':
            return {'reviews': [{'target': 'I1', 'concern': '该推断也有其他解释。',
                'reasoning': '没有订单期限资料。', 'evidence_refs': []}]}
        if stage == 'response_operating_quality':
            return {'responses': [{'target': 'I1', 'action': 'withdraw', 'reasoning': '撤回该推断。',
                'evidence_refs': [], 'replacement': None}]}
        return response(stage, context, phase=phase)

    report = execute(journal, respond)
    assert report.insights[0].status == 'excluded'
    assert report.synthesis is None
    assert report.responses[0].action == 'withdraw'


def test_empty_review_is_unreviewed_not_no_counterevidence(tmp_path):
    _, journal, _ = setup(tmp_path)

    def respond(stage, context, *, phase='main'):
        return {'reviews': []} if stage == 'challenge' else response(stage, context, phase=phase)

    report = execute(journal, respond)
    assert report.reviews[0].status == 'unreviewed'
    assert 'unreviewed_insights' in report.gaps


@pytest.mark.parametrize('jev_enabled', [False, True])
def test_cross_specialist_aliases_and_review_targets_are_explicit(tmp_path, jev_enabled):
    _, journal, _ = setup(tmp_path)
    journal.state['identity']['jev_verification_enabled'] = jev_enabled
    base = catalog()
    second = base.model_copy(update={'evidence': (base.evidence[1].model_copy(update={'ref': 'E1'}),), 'numbers': ()})
    first = base.model_copy(update={'evidence': (base.evidence[0],), 'numbers': ()})
    jev_states = []

    def verify(_id, state, _questions):
        jev_states.append(state)
        return {'evidence_sufficient': 0.5, 'reasoning_sound': 0.5}, {}

    def respond(stage, context, *, phase='main'):
        if stage in {'operating_quality', 'event_context'}:
            return {'insights': [proposal(reasoning='依据 E1。')]}
        if stage == 'challenge':
            assert context['insights'][1]['reasoning'] == '依据 [E2]。'
            assert context['insights'][1]['evidence_refs'] == ['E2']
            return {'reviews': [{'target': 'I2', 'concern': '存在替代解释。', 'reasoning': '需要核实。', 'evidence_refs': []}]}
        if stage == 'response_event_context':
            target = context['insights'][1]
            assert context['reviews'][1]['target_id'] == target['insight_id']
            return {'responses': [{'target': 'I2', 'action': 'maintain', 'reasoning': '保留有边界的判断。', 'evidence_refs': [], 'replacement': None}]}
        assert context['insights'][1]['insight_id'] == context['responses'][0]['target_id']
        assert context['insights'][1]['reasoning'] == '依据 [E2]。'
        return response(stage, context, phase=phase)

    respond.call_jev_verification = verify
    run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': first, 'event_context': second}, caller=respond,
        journal=journal, ensure_active=lambda: None)
    if jev_enabled:
        assert jev_states[1]['insight']['reasoning'] == '依据 [E2]。'
        assert [card['ref'] for card in jev_states[1]['cited_evidence']] == ['E2']
    else:
        assert jev_states == []


def test_saved_synthesis_text_is_replayed_on_read_and_resume(tmp_path):
    import pytest

    from tradingagents.research.insight_report import parse_insight_report
    _, journal, _ = setup(tmp_path)
    value = execute(journal, response).model_dump(mode='json')
    value['synthesis']['reasoning'] = '利润999亿元 [I999]，因此有利。'
    with pytest.raises(ValueError):
        parse_insight_report(value)
    journal.put('insight.report', value)
    with pytest.raises(ValueError):
        execute(journal, response)


def test_search_requests_revise_affected_role_and_resume_without_resending(tmp_path):
    from tradingagents.research.insight_report import parse_insight_report
    _, journal, _ = setup(tmp_path)
    searched = []
    base = catalog()
    updated = base.model_copy(update={'snapshot_id': 'snapshot-b', 'numbers': (),
        'evidence': (*base.evidence, base.evidence[0].model_copy(update={'ref': 'E9', 'fact_id': 'new-fact'}))})
    updated = updated.model_copy(update={'evidence': tuple(
        e.model_copy(update={'ref': 'E2' if e.ref == 'E1' else 'E1' if e.ref == 'E2' else e.ref})
        for e in updated.evidence)})

    def supplement(requests, round_id):
        searched.append(requests)
        assert requests == {'operating_quality': ('客户订单是否变化',)}
        return {'catalogs': {'operating_quality': updated}, 'affected_roles': ['operating_quality'], 'gaps': []}

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            if phase == 'supplement_1':
                assert context['search_requests_allowed'] is True
                assert context['previous_findings'][0]['reasoning'] == '公司仍有客户依赖 [E2]。'
                return {'insights': [proposal(claim='补证后修正判断。', evidence_refs=['E9'], reasoning='新证据改变判断 [E9]。')],
                    'search_requests': []}
            return {'insights': [proposal()], 'search_requests': ['客户订单是否变化', ' 客户订单是否变化 ']}
        return response(stage, context, phase=phase)

    kwargs = {'run_id': journal.observer.run_id, 'ticker': '002130.SZ', 'analysis_date': date(2026, 10, 28),
        'catalogs': {'operating_quality': base}, 'caller': respond, 'journal': journal, 'ensure_active': lambda: None, 'supplement': supplement}
    report = run_insight_research(**kwargs)
    assert len(searched) == 1
    assert [i.status for i in report.insights] == ['excluded', 'accepted']
    assert report.synthesis.insight_ids == (report.insights[-1].insight_id,)
    assert parse_insight_report(report.model_dump(mode='json')) == report
    assert run_insight_research(**kwargs) == report
    assert len(searched) == 1


def test_capability_requests_run_without_web_search_and_resume_without_resending(tmp_path):
    from tradingagents.research.insight_report import parse_insight_report
    _, journal, _ = setup(tmp_path)
    called = []
    base = catalog()
    updated = base.model_copy(update={'snapshot_id': 'snapshot-cap', 'numbers': (),
        'evidence': (*base.evidence, base.evidence[0].model_copy(update={'ref': 'E9', 'fact_id': 'cap-fact'}))})
    cards = [{'id': 'shareholder_count', 'title': '股东户数', 'solves': '户数变化',
              'not_for': '定价', 'inputs': {'query': '留空'}, 'cost': 'low'}]

    def capability(requests, round_id):
        called.append((round_id, requests))
        assert list(requests) == ['operating_quality']
        assert requests['operating_quality'][0]['capability_id'] == 'shareholder_count'
        return {'catalogs': {'operating_quality': updated}, 'affected_roles': ['operating_quality'], 'gaps': []}

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            assert 'capability_catalog' in context
            assert context['capability_catalog'][0]['id'] == 'shareholder_count'
            if phase == 'supplement_1':
                assert context['search_requests_allowed'] is False
                return {'insights': [proposal(claim='按户数补证后修正。', evidence_refs=['E9'],
                    reasoning='新材料改变判断 [E9]。')], 'search_requests': [], 'capability_requests': []}
            return {'insights': [proposal()], 'search_requests': [],
                'capability_requests': [{'capability_id': 'shareholder_count', 'query': '',
                    'gap_reason': '缺近一年股东户数'}]}
        if stage == 'challenge':
            assert 'capability_catalog' not in context
        return response(stage, context, phase=phase)

    kwargs = {'run_id': journal.observer.run_id, 'ticker': '002130.SZ', 'analysis_date': date(2026, 10, 28),
        'catalogs': {'operating_quality': base}, 'caller': respond, 'journal': journal,
        'ensure_active': lambda: None, 'capability': capability,
        'capability_catalog': {'operating_quality': cards}}
    report = run_insight_research(**kwargs)
    assert len(called) == 1
    assert [i.status for i in report.insights] == ['excluded', 'accepted']
    assert report.synthesis.insight_ids == (report.insights[-1].insight_id,)
    assert parse_insight_report(report.model_dump(mode='json')) == report
    assert run_insight_research(**kwargs) == report
    assert len(called) == 1


def test_capability_runs_before_web_search_in_same_round(tmp_path):
    _, journal, _ = setup(tmp_path)
    order = []
    base = catalog()
    updated = base.model_copy(update={'snapshot_id': 'snapshot-both', 'numbers': ()})

    def capability(requests, round_id):
        order.append(('capability', round_id))
        return {'catalogs': {'operating_quality': updated}, 'affected_roles': ['operating_quality'], 'gaps': []}

    def supplement(requests, round_id):
        order.append(('search', round_id))
        return {'catalogs': {'operating_quality': updated}, 'affected_roles': ['operating_quality'], 'gaps': []}

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality' and phase == 'main':
            return {'insights': [proposal()], 'search_requests': ['客户订单是否变化'],
                'capability_requests': [{'capability_id': 'shareholder_count', 'query': '',
                    'gap_reason': '缺户数'}]}
        if stage == 'operating_quality':
            return {'insights': [proposal(claim='已更新')], 'search_requests': [], 'capability_requests': []}
        return response(stage, context, phase=phase)

    run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': base}, caller=respond, journal=journal, ensure_active=lambda: None,
        supplement=supplement, capability=capability,
        capability_catalog={'operating_quality': [{'id': 'shareholder_count'}]})
    assert order[:2] == [('capability', 1), ('search', 1)]


def test_prompt_keeps_all_facts_but_retrieves_bounded_original_passages():
    import hashlib

    from tradingagents.graph.insight_research import catalog_prompt
    base = catalog()
    text = '客户订单发生变化。' * 2000
    content = base.sources[0].content.model_copy(update={'text': text, 'content_sha256': hashlib.sha256(text.encode()).hexdigest()})
    base = base.model_copy(update={'sources': (base.sources[0].model_copy(update={'content': content}),)})
    value = catalog_prompt(base, query='客户订单')
    assert len(value['evidence']) == len(base.evidence)
    assert 'content' not in value['sources'][0]
    assert 0 < len(value['source_passages']) <= 8
    for passage in value['source_passages']:
        assert passage['text'] == text[passage['start']:passage['end']]
        assert len(passage['text']) <= 1200


def test_focus_runs_after_synthesis_without_changing_baseline(tmp_path):
    _, journal, _ = setup(tmp_path)
    order = []
    def respond(stage, context, *, phase='main'):
        order.append(stage)
        if stage == 'focus_response':
            assert context['question'] == '如何理解客户风险'
            return {'insights': [proposal(claim='针对客户风险的补充解释。')], 'search_requests': []}
        assert 'question' not in context
        return response(stage, context, phase=phase)
    report = run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': catalog()}, caller=respond, journal=journal, ensure_active=lambda: None,
        focus_question='如何理解客户风险')
    assert order[-2:] == ['synthesis', 'focus_response']
    assert report.focus_insights[0].role == 'focus_response'
    assert report.focus_insights[0].insight_id not in report.synthesis.insight_ids


def test_optional_explanation_targets_use_only_saved_insights(tmp_path):
    from tradingagents.research.report_explanation import (
        explanation_targets,
    )
    _, journal, _ = setup(tmp_path)
    report = execute(journal, response)
    targets, excluded = explanation_targets(report, batched=True)
    key = 'insight:' + report.insights[0].insight_id
    assert report.insights[0].rendered.reasoning in targets[key]['text']
    assert set(targets[key]['references']) == set(report.insights[0].source_ids)
    assert not excluded


def test_conflicting_duplicate_replies_do_not_choose_a_version(tmp_path):
    _, journal, _ = setup(tmp_path)
    def respond(stage, context, *, phase='main'):
        if stage == 'challenge':
            return {'reviews': [{'target': 'I1', 'concern': '存在替代解释。', 'reasoning': '需要核实。', 'evidence_refs': []}]}
        if stage == 'response_operating_quality':
            return {'responses': [{'target': 'I1', 'action': action, 'reasoning': '研究回应。', 'evidence_refs': [], 'replacement': None}
                                  for action in ('withdraw', 'maintain')]}
        return response(stage, context, phase=phase)
    report = execute(journal, respond)
    assert report.responses == ()
    assert report.insights[0].status == 'accepted'
    assert 'response_operating_quality_unresolved' in report.gaps


def test_saved_review_text_is_revalidated(tmp_path):
    import pytest

    from tradingagents.research.insight_report import parse_insight_report
    _, journal, _ = setup(tmp_path)
    value = execute(journal, response).model_dump(mode='json')
    value['reviews'][0]['reasoning'] = '收入999亿元。'
    with pytest.raises(ValueError):
        parse_insight_report(value)


def test_no_qualified_facts_preserves_empty_report_without_calling_focus(tmp_path):
    _, journal, _ = setup(tmp_path)
    empty = catalog().model_copy(update={'evidence': (), 'numbers': (), 'sources': ()})
    def forbidden(*args, **kwargs):
        raise AssertionError('No qualified input: model must not be called')
    result = run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': empty}, caller=forbidden, journal=journal, ensure_active=lambda: None,
        focus_question='核查客户风险')
    assert result.synthesis is None
    assert result.focus_insights == ()
    assert 'focus_unavailable' in result.gaps


def test_basic_company_facts_survive_when_all_agent_outputs_fail(tmp_path):
    from tradingagents.agents.schemas._company_basics import CompanyBasicFieldV1, CompanyBasicsV1
    _, journal, _ = setup(tmp_path)
    basics = CompanyBasicsV1(company_name='合成测试公司', introduction=(CompanyBasicFieldV1(label='主营业务', claim_id='fact-1'),))
    result = run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': catalog()}, caller=lambda *a, **k: {}, journal=journal, ensure_active=lambda: None,
        company_basics=basics, foundation_catalog=catalog())
    assert result.synthesis is None and not result.insights
    assert result.company_basics == basics
    assert any(e.fact_id == 'fact-1' for c in result.catalogs.values() for e in c.evidence)


def test_supplement_can_follow_new_gaps_but_stops_at_three_rounds(tmp_path):
    _, journal, _ = setup(tmp_path)
    rounds = []
    def supplement(requests, round_id):
        rounds.append(round_id)
        updated = catalog().model_copy(update={'snapshot_id': f'snapshot-{round_id}', 'numbers': ()})
        return {'catalogs': {'operating_quality': updated}, 'affected_roles': ['operating_quality'], 'gaps': []}
    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality':
            return {'insights': [proposal()], 'search_requests': ['新资料问题' + phase]}
        return response(stage, context, phase=phase)
    report = run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ', analysis_date=date(2026, 10, 28),
        catalogs={'operating_quality': catalog()}, caller=respond, journal=journal, ensure_active=lambda: None, supplement=supplement)
    assert rounds == [1, 2, 3]
    assert 'search_requests_remaining' in report.gaps
    assert len([i for i in report.insights if i.status == 'accepted']) == 1


def test_challenge_rejections_are_recorded_with_safe_reason_codes(tmp_path):
    _, journal, _ = setup(tmp_path)

    def respond(stage, context, *, phase='main'):
        if stage == 'operating_quality' and phase == 'main':
            return {'insights': [proposal(), proposal(claim='第二观点需要核查。', evidence_refs=['E1'])]}
        if stage == 'operating_quality':
            return {'insights': [proposal(claim='第二观点需要核查。', evidence_refs=['E1'])]}
        if stage == 'challenge' and phase == 'repair':
            return {'reviews': []}
        if stage == 'challenge':
            return {'reviews': [
                {'target': 'I1', 'concern': None, 'reasoning': '已审阅，未发现额外有效反证。', 'evidence_refs': []},
                {'target': 'I2', 'concern': None, 'reasoning': '收入增长 10% 需要关注。', 'evidence_refs': []},
                {'target': 'I9', 'concern': None, 'reasoning': '越界目标。', 'evidence_refs': []},
            ]}
        return response(stage, context, phase=phase)

    report = execute(journal, respond)
    diagnostics = journal.state['insight.diagnostics.challenge']
    codes = [item['code'] for item in diagnostics]
    assert 'numeric_literal_unbound' in codes
    assert 'target_unknown' in codes
    assert 'repair_unresolved' in codes
    assert [review.status for review in report.reviews] == ['no_counterevidence', 'unreviewed']
    assert 'unreviewed_insights' in report.gaps


def test_challenge_reviews_are_repaired_once_for_failed_targets(tmp_path):
    _, journal, _ = setup(tmp_path)
    seen = []

    def respond(stage, context, *, phase='main'):
        seen.append((stage, phase))
        if stage == 'operating_quality' and phase == 'main':
            return {'insights': [proposal(), proposal(claim='第二观点需要核查。', evidence_refs=['E1'])]}
        if stage == 'operating_quality':
            return {'insights': [proposal(claim='第二观点需要核查。', evidence_refs=['E1'])]}
        if stage == 'challenge' and phase == 'main':
            return {'reviews': [
                {'target': 'I1', 'concern': None, 'reasoning': '已审阅，未发现额外有效反证。', 'evidence_refs': []},
                {'target': 'I2', 'concern': None, 'reasoning': '收入增长 10% 需要关注。', 'evidence_refs': []},
            ]}
        if stage == 'challenge':
            assert context['repair_targets'] == ['I2']
            assert 'instruction' in context and 'Arabic digit' in context['instruction']
            assert any(item.get('code') == 'numeric_literal_unbound' for item in context['issues'])
            return {'reviews': [
                {'target': 'I2', 'concern': '客户集中度需要复核。', 'reasoning': '需要复核客户依赖是否改善 [E1]。', 'evidence_refs': ['E1']},
            ]}
        if stage.startswith('response_'):
            return {'responses': [{'target': 'I2', 'action': 'maintain', 'reasoning': '维持现有观点 [E1]。',
                                   'evidence_refs': ['E1'], 'replacement': None}]}
        return response(stage, context, phase=phase)

    report = execute(journal, respond)
    assert seen.count(('challenge', 'repair')) == 1
    assert [review.status for review in report.reviews] == ['no_counterevidence', 'challenged']
    assert report.stages['challenge'] == 'completed'
    assert 'unreviewed_insights' not in report.gaps
    diagnostics = journal.state['insight.diagnostics.challenge']
    assert any(item['target'] == 'I2' and item['code'] == 'numeric_literal_unbound' for item in diagnostics)
    assert not any(item.get('code') == 'repair_unresolved' for item in diagnostics)
    assert execute(journal, lambda *a, **k: (_ for _ in ()).throw(AssertionError('replay called model'))) == report


class JevCaller:
    """Stage caller that also answers the Jev verification stage."""

    def __init__(self, result):
        self.result, self.stages, self.jev_calls = result, [], []

    def __call__(self, stage, context, *, phase='main'):
        self.stages.append((stage, phase))
        return response(stage, context, phase=phase)

    def call_jev_verification(self, insight_id, insight_state, questions):
        self.jev_calls.append((insight_id, insight_state, questions))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result, {'id': 'gen-test', 'model': 'typesafe/jev-1.14',
            'provider': 'TypeSafe', 'usage': {'input_tokens': 100}}


def jev_report(journal, caller):
    return run_insight_research(run_id=journal.observer.run_id, ticker='002130.SZ',
        analysis_date=date(2026, 10, 28), catalogs={'operating_quality': catalog()},
        caller=caller, journal=journal, ensure_active=lambda: None)


def test_jev_verification_is_skipped_unless_enabled(tmp_path):
    _, journal, _ = setup(tmp_path)
    caller = JevCaller({'evidence_sufficient': 0.95, 'reasoning_sound': 0.95})
    report = jev_report(journal, caller)
    assert caller.jev_calls == []
    assert report.stages['jev_verify'] == 'skipped'
    assert [review.status for review in report.reviews] == ['no_counterevidence']
    assert ('challenge', 'main') in caller.stages


def test_clear_jev_scores_verify_the_insight_without_challenge(tmp_path):
    _, journal, _ = setup(tmp_path)
    journal.state['identity']['jev_verification_enabled'] = True
    caller = JevCaller({'evidence_sufficient': 0.93, 'reasoning_sound': 0.91})
    report = jev_report(journal, caller)
    assert report.stages['jev_verify'] == 'completed'
    assert ('challenge', 'main') not in caller.stages
    review, = report.reviews
    assert review.status == 'verified' and review.note is None
    assert review.jev_scores == {'evidence_sufficient': 0.93, 'reasoning_sound': 0.91}
    assert review.jev_meta is not None and review.jev_meta.model == 'typesafe/jev-1.14'
    insight_id, state, questions = caller.jev_calls[0]
    assert insight_id == review.target_id and state['insight']['claim'] == proposal()['claim']
    assert {'evidence_sufficient', 'reasoning_sound'} <= set(questions)


def test_failed_jev_verification_does_not_fall_back_to_challenge(tmp_path):
    _, journal, _ = setup(tmp_path)
    journal.state['identity']['jev_verification_enabled'] = True
    caller = JevCaller(InsightUnavailable('jev_unavailable'))
    report = jev_report(journal, caller)
    assert ('challenge', 'main') not in caller.stages
    review, = report.reviews
    assert review.status == 'failed' and review.jev_scores is None
    assert f'jev_failed:{review.target_id}' in report.gaps and 'unreviewed_insights' in report.gaps
    assert journal.state['insight.diagnostics.jev'] == [{'insight_id': review.target_id, 'error': 'jev_unavailable'}]
