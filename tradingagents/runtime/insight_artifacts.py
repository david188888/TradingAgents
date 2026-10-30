"""Consumer-neutral reads of committed Insight publications."""

import hashlib
import json

from tradingagents.observability.canonical import canonical_sha256
from tradingagents.research.insight_report import parse_insight_report


def read_insight_publication(store, run_id, *, events=None, event=None):
    snapshot = store.read_snapshot(run_id)
    events = store.read_events(run_id) if events is None else events
    if event is None:
        event = max((e for e in events if e.type == 'artifact.written' and e.status == 'committed'
            and e.payload.get('public_contract') == 'insight-research-v1'), key=lambda e: e.sequence, default=None)
    if event is None:
        raise ValueError('insight_publication_missing')

    def read(item):
        raw = store.read_artifact(run_id, item.payload['artifact_id'])
        if hashlib.sha256(raw).hexdigest() != item.payload.get('content_sha256'):
            raise ValueError('insight_artifact_integrity')
        return json.loads(raw)

    record = parse_insight_report(read(event))
    if (record.run_id, record.ticker, record.analysis_date.isoformat(), record.mode) != (
            snapshot.run_id, snapshot.ticker, snapshot.analysis_date, snapshot.mode):
        raise ValueError('insight_publication_identity')
    barrier = next((e for e in events if e.event_id == event.parent_event_id), None)
    if (barrier is None or barrier.status != 'committed' or barrier.payload.get('kind') != 'catalyst-checkpoint'
            or barrier.sequence != event.payload.get('committed_sequence') or barrier.sequence >= event.sequence
            or event.payload.get('graph_task_id') != 'native.final'):
        raise ValueError('insight_publication_barrier')
    saved = read(barrier)
    value = record.model_dump(mode='json')
    if (saved.get('native_publication_candidate') != value or saved.get('insight.report') != value
            or saved.get('publication_authorized') is not True
            or saved.get('native_publication_authorized_candidate_sha256') != canonical_sha256(value)
            or saved.get('identity', {}).get('workflow_version') != 'evidence-production-v9'):
        raise ValueError('insight_publication_authorization')
    return record
