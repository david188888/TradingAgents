"""Reader/process/focus/explanation are read-only for the new record contract."""

import pytest

from tests.search_pipeline_fixtures import saved_v2_run
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.runtime.reports import build_markdown_from_native_record
from tradingagents.web.focus_projection import project_reader_focus
from tradingagents.web.reader_process_projection import project_reader_agent, project_reader_process
from tradingagents.web.report_explanation import project_report_explanation


@pytest.mark.parametrize('with_search', [False, True])
def test_v2_process_and_export_preserve_qualified_saved_record(tmp_path, with_search):
    journal, record = saved_v2_run(tmp_path, with_search=with_search)
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put('publication_authorized', True))
    process = project_reader_process(journal.observer.store, record.run_id)
    assert process['workflow_version'] == 'evidence-production-v8'
    assert process['reason_code'] is None
    assert project_reader_agent(journal.observer.store, record.run_id, 'synthesis')['availability'] == 'available'
    text = build_markdown_from_native_record(record, workflow_version='evidence-production-v8')
    assert record.assessment.judgement in text


def test_read_focus_explanation_never_search_or_write(tmp_path, monkeypatch):
    journal, record = saved_v2_run(tmp_path)
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put('publication_authorized', True))
    def fail(*a, **kw):
        raise AssertionError('read side cannot dispatch or persist')
    monkeypatch.setattr(journal.observer.store, 'store_artifact', fail)
    monkeypatch.setattr('tradingagents.execution.search_coordinator.SearchCoordinator.collect', fail)
    assert project_reader_focus(journal.observer.store, record.run_id)['state'] == 'not_applicable'
    project_report_explanation(journal.observer.store, record.run_id)
    project_reader_process(journal.observer.store, record.run_id)


def test_sdk_totals_include_review_dispatches_without_inventing_budget_calls():
    from tradingagents.runtime.native_observation import NativeSDKObservationV1
    from tradingagents.web.reader_process_projection import native_counts
    cp = {'identity': {'workflow_version': 'evidence-production-v8'}, 'records': [],
        'native_sdk_observation': NativeSDKObservationV1(start_sequence=0,
            prior_main_authorizations=0, prior_repair_authorizations=0,
            prior_focus_authorizations=0).model_dump(),
        'native.model.search_review.1.operating_quality.hash.dispatched': True,
        'native.model.search_review.1.operating_quality.hash.main.retry.1.dispatched': True}
    assert native_counts(cp).sdk_total.value == 2
    assert native_counts(cp, role='operating_quality').sdk_total.value == 2
    assert native_counts(cp, role='market_context').sdk_total.value == 0
