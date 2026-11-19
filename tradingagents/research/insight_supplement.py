"""Keep model aliases stable over append-only specialist evidence revisions."""

from tradingagents.agents.schemas._insight import InsightBatch, InsightSupplementSubmission
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.insights import compile_insights


def _number_key(anchor):
    # Anchor IDs include the snapshot; the same receipt can survive a later snapshot.
    return canonical_sha256(anchor.model_dump(mode='json', exclude={'anchor_id', 'snapshot_id'}))


def rebase_catalog(catalog, aliases):
    """Keep retired alias slots reserved; never bind an old ref to different data."""
    def alias(prefix, key):
        table = aliases[prefix]
        return table.setdefault(key, f'{prefix}{len(table) + 1}')

    for source in catalog.sources:
        alias('S', source.evidence_id)
    return catalog.model_copy(update={
        'evidence': tuple(card.model_copy(update={'ref': alias('E', card.fact_id)}) for card in catalog.evidence),
        'numbers': tuple(row.model_copy(update={'ref': alias('N', _number_key(row.anchor))}) for row in catalog.numbers),
    })


def compile_delta(raw, *, previous, catalog, history, delta_refs, critical_refs, role, revision, analysis_date):
    submission = InsightSupplementSubmission.model_validate(raw)
    keep = submission.keep_ids
    revise, withdraw = submission.revise, submission.withdraw
    targets = (*keep, *(item.target for item in revise), *(item.target for item in withdraw))
    if len(targets) != len(set(targets)) or set(targets) != previous.keys():
        raise ValueError('supplement_target_coverage')
    reviewed = set(submission.delta_reviewed_refs)
    if reviewed != delta_refs:
        raise ValueError('supplement_delta_coverage')

    usable = supported_prior(previous, catalog, history)
    if not set(keep) <= usable:
        raise ValueError('supplement_keep_stale')
    proposals = [*(item.proposal for item in revise), *submission.add]
    batch = compile_insights({'insights': proposals}, catalog=catalog, role=role,
                              revision=revision, normalize_refs=True, analysis_date=analysis_date)
    if batch.rejected or any(item.status != 'accepted' for item in batch.items):
        raise ValueError('supplement_proposal_invalid')
    fact_refs = {card.fact_id: card.ref for card in catalog.evidence}
    numeric_refs = {row.anchor.anchor_id: row.ref for row in catalog.numbers}
    acted_refs = set()
    for item in batch.items:
        refs = ({fact_refs[key] for key in item.fact_ids} | {numeric_refs[key] for key in item.numeric_ids}) & delta_refs
        if not refs:
            raise ValueError('supplement_proposal_missing_delta')
        acted_refs.update(refs)
    for item in withdraw:
        if not item.evidence_refs or not set(item.evidence_refs) <= delta_refs:
            raise ValueError('supplement_withdraw_missing_delta')
        acted_refs.update(item.evidence_refs)
    if not critical_refs <= acted_refs or critical_refs and previous and not (revise or withdraw):
        raise ValueError('supplement_material_delta_unresolved')
    return InsightBatch(items=batch.items), [target for target in previous if target not in keep]


def supported_prior(previous, catalog, history):
    facts = {e.fact_id for e in catalog.evidence}
    sources = {s.evidence_id for s in catalog.sources}
    numbers = {_number_key(n.anchor) for n in catalog.numbers}
    usable = set()
    for key, item in previous.items():
        origin = history[item.catalog_id]
        receipts = {_number_key(n.anchor) for n in origin.numbers if n.anchor.anchor_id in item.numeric_ids}
        if set(item.fact_ids) <= facts and set(item.source_ids) <= sources and receipts <= numbers:
            usable.add(key)
    return usable
