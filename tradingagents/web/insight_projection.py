"""Read the independent Insight contract only through its publication barrier."""

from tradingagents.runtime.insight_artifacts import read_insight_publication


def project_insight_record(store, snapshot, events, event):
    try:
        record = read_insight_publication(store, snapshot.run_id, events=events, event=event)
        return {'state': 'insight_ready', 'schema_version': 1, 'run_id': snapshot.run_id, 'record': record.model_dump(mode='json')}
    except (ValueError, KeyError, OSError, TypeError):
        return {'state': 'unavailable', 'schema_version': 1, 'run_id': snapshot.run_id, 'reason_code': 'corrupt'}
