"""Arithmetic views over an already validated current evidence revision."""
def snapshot_view(record, snapshot_id):
    """A non-published arithmetic view over one already validated revision."""
    snapshot = next((s for s in record.snapshots if s.snapshot_id == snapshot_id), None)
    if snapshot is None:
        raise ValueError('research input snapshot missing')
    scope = set(snapshot.evidence_ids)
    changes = {'snapshots': (snapshot,),
        'evidence': tuple(s for s in record.evidence if s.evidence_id in scope),
        'claims': tuple(c for c in record.claims if set(c.evidence_ids) <= scope),
        'metrics': tuple(m for m in record.metrics if set(m.input_evidence_ids) <= scope)}
    from tradingagents.agents.schemas._evidence_record import qualification_key
    versions = {s.snapshot_id: s.version for s in record.snapshots}
    changes['evidence_checks'] = next((c for c in (*record.check_revisions, record.evidence_checks)
        if c is not None and c.input_snapshot_id == snapshot_id), None)
    changes['recovered_fields'] = tuple(f for f in record.recovered_fields if f.evidence_id in scope
        and versions.get(record.qualification_snapshots[qualification_key(f)],
            int(record.qualification_snapshots[qualification_key(f)].split('.', 1)[0][1:])) <= snapshot.version)
    changes['qualification_snapshots'] = {qualification_key(f): record.qualification_snapshots[qualification_key(f)]
        for f in changes['recovered_fields']}
    return record.model_copy(update=changes)
