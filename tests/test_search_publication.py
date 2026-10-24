"""V2 public bytes and historical records use explicit contract dispatch."""

from tests.search_pipeline_fixtures import saved_v2_run
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.research.record_codec import parse_research_record
from tradingagents.web.research_record_projection import project_research_record


def test_v2_publish_restore_project_export_same_record(tmp_path):
    journal, record = saved_v2_run(tmp_path)
    artifact = publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put('publication_authorized', True))
    store, run_id = journal.observer.store, record.run_id
    import json
    restored = parse_research_record(json.loads(store.read_artifact(run_id, artifact)))
    assert restored == record
    projected = project_research_record(store, run_id)
    assert projected['state'] == 'ready'
    assert projected['record'] == record.model_dump(mode='json')
    assert any(e.payload.get('public_contract') == 'research-record-v2' for e in store.read_events(run_id))
