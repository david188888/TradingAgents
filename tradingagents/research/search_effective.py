"""Read-only applicability of supplemental reviews; history stays immutable."""


def unreviewed_roles(record):
    if record.schema_version != 'research-record-v2':
        return ()
    from tradingagents.research.native_policy import ROLE_ORDER, fact_views
    versions = {s.snapshot_id: s.version for s in record.snapshots}
    first = {}
    for snapshot in record.snapshots:
        for eid in snapshot.evidence_ids:
            first.setdefault(eid, snapshot.version)
    from tradingagents.agents.schemas._research_record_v2 import qualification_key
    qualified = {}
    for field in record.recovered_fields:
        introduced = versions[record.qualification_snapshots[qualification_key(field)]]
        qualified[field.evidence_id] = max(qualified.get(field.evidence_id, 0), introduced)
    baseline = versions[record.dialogue.input_snapshot_id] if record.dialogue else 0
    views = fact_views(record, valuation=True)
    result = []
    for role in ROLE_ORDER:
        changed = max((max(first[eid], qualified.get(eid, 0)) for fact in views[role] for eid in fact.evidence_ids), default=baseline)
        reviewed = max((versions[r.input_snapshot_id] for r in record.search_reviews if r.role == role), default=baseline)
        if changed > reviewed:
            result.append(role)
    return tuple(result)


def excluded_search_claims(record):
    if record.schema_version != 'research-record-v2':
        return set()
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    challenges = {c.challenge_id: c for c in record.challenges}
    latest = {}
    for review in record.search_reviews:
        for target in review.target_ids:
            latest[target] = review
    excluded = set()
    for target, review in latest.items():
        if review.disposition in {'revised', 'withdrawn', 'unanswerable'}:
            if target in hypotheses:
                excluded.add(hypotheses[target].claim_id)
            elif target in challenges:
                excluded.update(challenges[target].target_claim_ids)
    if record.dialogue is not None:
        pending = set(unreviewed_roles(record))
        excluded.update(hypotheses[o.hypothesis_id].claim_id for o in record.dialogue.origins if o.role in pending)
    superseded = {old for old, new in record.superseded_evidence.items() if new in record.snapshots[-1].evidence_ids}
    excluded.update(c.claim_id for c in record.claims if superseded.intersection(c.evidence_ids))
    return excluded
