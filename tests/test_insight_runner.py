"""Actual native runner collection, Insight graph, publication and recovery."""

from dataclasses import replace

from tests.test_dual_search_pipeline import setup
from tests.test_insight_protocol import proposal
from tradingagents.execution.native_runner import NativeResumeGuard, native_identity
from tradingagents.runtime.reports import ReportArtifactWriter
from tradingagents.web.research_record_projection import project_research_record


def test_new_version_omits_legacy_output_gates(tmp_path, monkeypatch):
    _, request, _, _, _, _ = setup(tmp_path, monkeypatch, enabled=False)
    value = native_identity(request, workflow_version='evidence-production-v9')
    assert value['insight_policy'] == 'insight-first-v1'
    assert 'model_binding_policy' not in value
    assert 'factual_premise_policy' not in value
    assert 'challenge_check_policy' not in value
    assert value['search_budget_policy']['limits']['search_rounds'] == 3


def test_actual_runner_publishes_and_resumes_insight_record(tmp_path, monkeypatch):
    runner, request, store, run_id, session, _ = setup(tmp_path, monkeypatch, enabled=False)
    monkeypatch.setattr('tradingagents.execution.native_runner.WORKFLOW_VERSION', 'evidence-production-v9')
    snapshot = store.read_snapshot(run_id)
    store.write_snapshot_atomic(replace(snapshot, metadata={**snapshot.metadata, 'native_workflow_version': 'evidence-production-v9'}))
    calls = []

    def delegate(stage, context, *, phase='main'):
        calls.append((stage, phase))
        if stage in {'operating_quality', 'event_context', 'market_context'}:
            assert 'proposal' not in context and 'factual_observations' not in context
            return {'insights': [proposal(evidence_refs=[context['evidence'][0]['ref']])]}
        if stage == 'challenge':
            from tradingagents.web.reader_process_projection import project_reader_agent
            stage_view = project_reader_agent(store, run_id, 'operating_quality')
            assert stage_view['availability'] == 'insight_stage_available'
            assert stage_view['insight_record']['synthesis'] is None
            return {'reviews': [{'target': i['ref'], 'concern': None, 'reasoning': '审阅后未发现有效反证。',
                'evidence_refs': []} for i in context['insights']]}
        if stage == 'synthesis':
            return {'judgement': '现有证据支持有边界的判断。', 'stance': 'favorable',
                'insight_refs': [context['insights'][0]['ref']], 'reasoning': '参考已保存专项观点。',
                'limitations': '部分资料仍缺失。', 'next_check': '关注后续披露。'}
        raise AssertionError(stage)

    runner.caller_factory = lambda **kwargs: delegate
    result = runner.run(request, publication_authorizer=lambda j: j.put('publication_authorized', True))
    assert result.final_state['native_research_record']['schema_version'] == 'insight-research-v1'
    projected = project_research_record(store, run_id)
    assert projected['state'] == 'insight_ready'
    from tradingagents.web.focus_projection import project_reader_focus
    assert project_reader_focus(store, run_id)['state'] == 'not_applicable'
    assert projected['record']['synthesis']['stance'] == 'favorable'
    published = ReportArtifactWriter(store).publish_final(run_id, result.final_state, ticker=request.ticker)
    assert published.complete_report.exists()
    count = len(calls), len(session.calls)
    runner.run(request, checkpoint_guard=NativeResumeGuard(), publication_authorizer=lambda j: j.put('publication_authorized', True))
    assert (len(calls), len(session.calls)) == count


def test_insight_process_and_stage_outputs_are_readable(tmp_path, monkeypatch):
    from tests.test_insight_research import response
    from tradingagents.web.reader_process_projection import (
        project_reader_agent,
        project_reader_process,
    )
    runner, request, store, run_id, _, _ = setup(tmp_path, monkeypatch, enabled=False)
    monkeypatch.setattr('tradingagents.execution.native_runner.WORKFLOW_VERSION', 'evidence-production-v9')
    snapshot = store.read_snapshot(run_id)
    store.write_snapshot_atomic(replace(snapshot, metadata={**snapshot.metadata, 'native_workflow_version': 'evidence-production-v9'}))
    def call(stage, context, *, phase='main'):
        if stage in {'operating_quality', 'event_context', 'market_context'}:
            return {'insights': [proposal()]}
        return response(stage, context, phase=phase)
    runner.caller_factory = lambda **kwargs: call
    runner.run(request, publication_authorizer=lambda j: j.put('publication_authorized', True))
    process = project_reader_process(store, run_id)
    assert process['workflow_version'] == 'evidence-production-v9'
    assert process['availability'] == 'ready'
    agent = project_reader_agent(store, run_id, 'operating_quality')
    assert agent['availability'] == 'available'
    assert agent['insight_record']['insights']


def test_new_research_defaults_to_insight_workflow():
    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.execution.native_runner import WORKFLOW_VERSION
    assert WORKFLOW_VERSION == 'evidence-production-v9'
    request = AnalysisRequest('002130.SZ', '2026-10-28', research_profile='evidence_v1', effective_config={})
    assert native_identity(request)['insight_policy'] == 'insight-first-v1'
