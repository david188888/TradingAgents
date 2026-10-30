"""The Insight contract must pass the same durable publication boundary."""

from dataclasses import replace

import pytest

from tests.test_insight_research import execute, response
from tests.test_native_publication import setup
from tradingagents.execution.native_publication import NativePublicationError, publish_native_record
from tradingagents.runtime.reports import build_markdown_from_native_record
from tradingagents.web.research_record_projection import project_research_record


def test_insight_publication_projects_and_replays_without_legacy_assessment(tmp_path):
    observer, journal, _ = setup(tmp_path)
    report = execute(journal, response)
    snapshot = observer.store.read_snapshot(report.run_id)
    observer.store.write_snapshot_atomic(replace(snapshot, ticker=report.ticker,
        analysis_date=report.analysis_date.isoformat(), metadata={'research_profile': 'evidence_v1',
        'native_workflow_version': 'evidence-production-v9'}))
    journal.state['identity'].update(workflow_version='evidence-production-v9')
    journal.persist()
    aid = publish_native_record(observer, record=report, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put('publication_authorized', True))
    assert aid.startswith('insight-research-v1:')
    projected = project_research_record(observer.store, report.run_id)
    assert projected['state'] == 'insight_ready'
    assert projected['record'] == report.model_dump(mode='json')
    assert publish_native_record(observer, record=report, ledger=journal.ledger,
        publication_authorizer=lambda _: pytest.fail('replay authorized')) == aid
    text = build_markdown_from_native_record(report)
    assert report.synthesis.judgement in text
    assert report.insights[0].rendered.claim in text
    assert '第十页' in text


def test_tampered_insight_numeric_render_cannot_publish(tmp_path):
    observer, journal, _ = setup(tmp_path)
    report = execute(journal, response)
    item = report.insights[0]
    changed = item.model_copy(update={'rendered': item.rendered.model_copy(update={'reasoning': '伪造数值10亿元'})})
    report = report.model_copy(update={'insights': (changed,)})
    with pytest.raises(NativePublicationError):
        publish_native_record(observer, record=report, ledger=journal.ledger,
            publication_authorizer=lambda _: pytest.fail('invalid report authorized'))
