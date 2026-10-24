"""Append-only evidence and reproducible recovered-field calculations."""

import hashlib
import json
from decimal import Decimal, localcontext

from pydantic import TypeAdapter

from tradingagents.agents.schemas._research_record import (
    RecordClaimV1,
    SourceContentV1,
    SourceEvidenceV1,
)
from tradingagents.agents.schemas._research_record_v2 import (
    ResearchRecordV2,
    RevisionCalculationV1,
    make_evidence_snapshot_v2,
    qualification_key,
)
from tradingagents.observability.canonical import canonical_sha256


def _updated(record, **changes):
    changes = {key: TypeAdapter(ResearchRecordV2.model_fields[key].rebuild_annotation()).validate_python(value)
               for key, value in changes.items()}
    if 'snapshots' in changes and record.evidence_checks is not None:
        from tradingagents.research.minimum_evidence import compute_checks
        changes['check_revisions'] = (*record.check_revisions, record.evidence_checks)
        changes['evidence_checks'] = compute_checks(record.model_copy(update=changes))
    return ResearchRecordV2.model_validate({**record.model_dump(mode='python'), **changes})


def append_admission(record, admitted, *, round_id):
    sources = {s.evidence_id: s for s in record.evidence}
    claims = {c.claim_id: c for c in record.claims}
    for item in admitted.observations:
        existing = sources.get(item.source.evidence_id)
        if existing is not None and existing.model_dump(exclude={'captured_at'}) != item.source.model_dump(exclude={'captured_at'}):
            raise ValueError('saved source cannot be overwritten')
        sources[item.source.evidence_id] = existing or item.source
        if item.fact.claim_id in claims and claims[item.fact.claim_id] != item.fact:
            raise ValueError('saved fact cannot be overwritten')
        claims[item.fact.claim_id] = item.fact
    fields = tuple(dict.fromkeys((*record.recovered_fields, *admitted.fields)))
    if tuple(sources.values()) == record.evidence and tuple(claims.values()) == record.claims and fields == record.recovered_fields:
        return record
    snapshot = make_evidence_snapshot_v2(tuple(sources.values()), version=len(record.snapshots),
        parent_snapshot_id=record.snapshots[-1].snapshot_id)
    introductions = dict(record.qualification_snapshots)
    for field in fields:
        introductions.setdefault(qualification_key(field), snapshot.snapshot_id)
    return _updated(record, evidence=tuple(sources.values()), claims=tuple(claims.values()),
        snapshots=(*record.snapshots, snapshot), recovered_fields=fields, qualification_snapshots=introductions,
        limitations=tuple(dict.fromkeys((*record.limitations, *admitted.rejections, *admitted.conflicts))))


def affected_roles(before, after):
    previous = {c.claim_id for c in before.claims}
    markers = {limit.removeprefix('native_dimension:') for claim in after.claims
               if claim.claim_id not in previous for limit in claim.limitations
               if limit.startswith('native_dimension:')}
    new_sources = {f.evidence_id for f in after.recovered_fields if f not in before.recovered_fields}
    markers.update(limit.removeprefix('native_dimension:') for claim in after.claims
        if new_sources.intersection(claim.evidence_ids) for limit in claim.limitations
        if limit.startswith('native_dimension:'))
    return tuple(r for r in ('operating_quality', 'event_context', 'market_context') if r in markers)


def _groups(record, evidence_ids):
    from tradingagents.agents.schemas._search import QualifiedFieldV1
    from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
    from tradingagents.research.source_families import FINANCIAL_SOURCES
    from tradingagents.research.verification_tools import _financial_operand, _Unavailable

    groups = {}
    for field in record.recovered_fields:
        replacement = record.superseded_evidence.get(field.evidence_id)
        if field.evidence_id not in evidence_ids or replacement in evidence_ids or field.unit == 'text':
            continue
        key = (field.field, field.period.isoformat() if field.period else '', field.unit, field.basis)
        groups.setdefault(key, []).append(field)
    # Existing dedicated inputs retain priority and remain visible to conflict
    # detection; a later web result cannot silently replace an API value.
    for key, fields in groups.items():
        if not key[1] or key[2:] != ('CNY', 'consolidated_actual'):
            continue
        for source in record.evidence:
            if (source.evidence_id not in evidence_ids or source.source_name not in FINANCIAL_SOURCES
                    or record.superseded_evidence.get(source.evidence_id) in evidence_ids):
                continue
            operand = FinancialOperandV1(evidence_id=source.evidence_id,
                table='cashflow' if key[0] == 'n_cashflow_act' else 'income', field=key[0], report_period=key[1])
            try:
                value, _ = _financial_operand(record, operand)
            except _Unavailable:
                continue
            fields.append(QualifiedFieldV1(ticker=record.ticker, field=key[0], period=key[1],
                unit='CNY', currency='CNY', basis=key[3], value=str(value), evidence_id=source.evidence_id,
                locator=f'{operand.table}[end_date={key[1]}].{key[0]}',
                source_content_sha256=source.content.content_sha256))
    return groups


def _descriptions(record, key, fields, snapshot_id):
    from tradingagents.dataflows.disclosure_documents_v2 import financial_rows
    from tradingagents.research.search_recovery import FINANCIAL_FIELDS

    values = {Decimal(field.value) for field in fields}
    status = 'available' if len(values) == 1 else 'conflict'
    value = fields[0].value if status == 'available' else None
    sources = {s.evidence_id: s for s in record.evidence}
    comparisons = []
    for field in fields:
        source = sources[field.evidence_id]
        rows = financial_rows([{'page': 1, 'text': source.content.text}], key[1]) if key[1] else []
        comparisons.extend(r for r in rows if r['field'] == FINANCIAL_FIELDS.get(key[0])
            and r['frequency'] in {'FY', 'H1'} and r['unit'] == key[2]
            and r['current'] is not None and Decimal(r['current']) == Decimal(field.value)
            and r['previous'] is not None)
    inputs = canonical_sha256({'fields': [f.model_dump(mode='json') for f in fields], 'comparisons': comparisons})

    def build(operation, result, unit, prior=None, state=status):
        identity = canonical_sha256({'inputs': inputs, 'snapshot': snapshot_id, 'field': key[0],
                                    'period': key[1], 'operation': operation})
        return RevisionCalculationV1(calculation_id='calc.'+identity, input_snapshot_id=snapshot_id,
            inputs_sha256=inputs, field=key[0], period=key[1], prior_period=prior,
            operation=operation, status=state, value=result, unit=unit,
            input_evidence_ids=tuple(dict.fromkeys(f.evidence_id for f in fields)), derived_evidence_id='derived.'+identity)

    result = [build('value', value, key[2])]
    bases = {(r['prior_period'], Decimal(r['previous'])) for r in comparisons}
    if status == 'available' and len(bases) == 1:
        prior, base = next(iter(bases))
        with localcontext() as context:
            context.prec = 50
            difference = Decimal(value) - base
            result.append(build('difference', str(difference), key[2], prior))
            if base > 0:
                result.append(build('growth', str(difference / base), 'ratio', prior))
    return result


def recompute_revision(record, *, journal):
    cache_key = 'search.recompute.'+canonical_sha256(record)
    if journal is not None:
        cached = journal.ledger.cached_result(cache_key)
        if cached is not None:
            return ResearchRecordV2.model_validate(cached['record'])
    current = record.snapshots[-1]
    groups = _groups(record, set(current.evidence_ids))
    existing_inputs = {(c.field, c.period, c.operation, c.inputs_sha256) for c in record.revision_calculations}
    calculations = [c for key, fields in sorted(groups.items()) for c in _descriptions(record, key, fields, current.snapshot_id)]
    calculations = [c for c in calculations if (c.field, c.period, c.operation, c.inputs_sha256) not in existing_inputs]
    if not calculations:
        return record
    sources = list(record.evidence)
    claims = list(record.claims)
    by_id = {s.evidence_id: s for s in sources}
    for calculation in calculations:
        text = json.dumps(calculation.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)
        published = max(by_id[e].usable_as_of for e in calculation.input_evidence_ids)
        source = SourceEvidenceV1(evidence_id=calculation.derived_evidence_id, source_name='derived.web_fields.v1',
            source_kind='derived', source_family_id='derived:'+calculation.inputs_sha256,
            availability='available', published_at=published, usable_as_of=published,
            captured_at=max(by_id[e].captured_at or by_id[e].usable_as_of for e in calculation.input_evidence_ids), content=SourceContentV1(kind='source_fields', text=text,
                locator_label='已核对网页字段的确定性计算', content_sha256=hashlib.sha256(text.encode()).hexdigest()),
            limitations=('derived_not_an_independent_source', 'calculation_not_economic_causality'))
        sources.append(source)
        claims.append(RecordClaimV1(claim_id='fact.'+calculation.calculation_id, kind='fact',
            statement=f'{calculation.period} {calculation.field}：{calculation.value or "来源冲突"} {calculation.unit}',
            evidence_ids=(source.evidence_id,), limitations=('native_dimension:operating_quality', 'calculation_not_economic_causality')))
    snapshot = make_evidence_snapshot_v2(tuple(sources), version=len(record.snapshots), parent_snapshot_id=current.snapshot_id)
    result = _updated(record, evidence=tuple(sources), claims=tuple(claims), snapshots=(*record.snapshots, snapshot),
        revision_calculations=(*record.revision_calculations, *calculations))
    if journal is not None:
        journal.ledger.record_result(cache_key, {'record': result.model_dump(mode='json')})
    return result


def validate_revision_calculations(record):
    snapshots = {s.snapshot_id: s for s in record.snapshots}
    sources = {s.evidence_id: s for s in record.evidence}
    for calculation in record.revision_calculations:
        snapshot = snapshots.get(calculation.input_snapshot_id)
        if snapshot is None:
            raise ValueError('calculation input snapshot missing')
        from tradingagents.research.record_codec import snapshot_view
        view = snapshot_view(record, snapshot.snapshot_id)
        groups = _groups(view, set(snapshot.evidence_ids))
        matches = [key for key in groups if key[:2] == (calculation.field, calculation.period)]
        if len(matches) != 1 or calculation not in _descriptions(view, matches[0], groups[matches[0]], snapshot.snapshot_id):
            raise ValueError('calculation inputs or value changed')
        derived = sources.get(calculation.derived_evidence_id)
        if derived is None or derived.content is None or json.loads(derived.content.text) != calculation.model_dump(mode='json'):
            raise ValueError('calculation output lineage changed')
