"""Resolve a shallow Insight submission without the legacy proposal envelopes."""

import re
import unicodedata

from pydantic import ValidationError

from tradingagents.agents.schemas._insight import (
    EvidenceCard,
    InsightBatch,
    InsightCatalog,
    InsightProposal,
    InsightRejection,
    InsightText,
    NumericReference,
    SavedInsight,
)
from tradingagents.agents.schemas._numeric_narrative import NumericCatalogV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.numeric_catalog import build_numeric_catalog, render_numeric_anchor
from tradingagents.research.numeric_narrative import _CN_QUANTITY, _EN_QUANTITY

_REFERENCE = re.compile(r'\[([ENI][0-9]+)\]')
_QUANTITY = re.compile(
    r'(?:[+-]?\d[\d,]*(?:\.\d+)?)\s*(?:%|％|亿元|万元|亿|万|元|美元|人民币|倍|股|吨|辆|个百分点|基点|percent|basis\s+points?|dollars?|yuan|shares?|times|million|billion)'
    r'|(?:CNY|RMB|USD|\$|￥|¥)\s*[+-]?\d', re.I)
_TEXT_FIELDS = ('claim', 'reasoning', 'limitations')


def build_insight_catalog(record, *, facts=None):
    """Freeze aliases over a supplied source-qualified view, in canonical order."""
    sources = {s.evidence_id: s for s in record.evidence}
    qualified = sorted((f for f in (record.claims if facts is None else facts)
        if f.kind == 'fact' and f.evidence_ids and all(
            sources[e].availability == 'available' and sources[e].content is not None
            and sources[e].usable_as_of is not None
            and sources[e].usable_as_of.date() <= record.analysis_date for e in f.evidence_ids)),
        key=lambda f: f.claim_id)
    cards = tuple(EvidenceCard(ref=f'E{i}', fact_id=f.claim_id, text=f.statement,
        source_ids=f.evidence_ids, limitations=f.limitations) for i, f in enumerate(qualified, 1))
    fact_ids = {f.claim_id for f in qualified}
    numeric = NumericCatalogV1.model_validate(build_numeric_catalog(record))
    anchors = sorted((a for a in numeric.anchors if set(a.required_fact_ids) <= fact_ids), key=lambda a: a.anchor_id)
    source_ids = {s for card in cards for s in card.source_ids}
    return InsightCatalog(snapshot_id=record.snapshots[-1].snapshot_id,
        sources=tuple(sources[s] for s in sorted(source_ids)), evidence=cards,
        numbers=tuple(NumericReference(ref=f'N{i}', anchor=a) for i, a in enumerate(anchors, 1)))


def compile_insights(payload, *, catalog: InsightCatalog, role: str, revision: int = 1, indices=None):
    """Validate each external item once; retain valid siblings and safe diagnostics."""
    if not isinstance(payload, dict) or not {'insights'} <= set(payload) <= {'insights', 'search_requests'} or not isinstance(payload['insights'], list):
        raise ValueError('insight_batch_shape')
    if revision < 1:
        raise ValueError('insight_revision_invalid')
    if indices is not None and len(indices) != len(payload['insights']):
        raise ValueError('insight_repair_count')
    cards = {e.ref: e for e in catalog.evidence}
    facts = {e.fact_id: e for e in catalog.evidence}
    numbers = {n.ref: n.anchor for n in catalog.numbers}
    sources = {s.evidence_id: s for s in catalog.sources}
    items, rejected = [], []
    for position, raw in enumerate(payload['insights']):
        index = position if indices is None else indices[position]
        try:
            proposal = InsightProposal.model_validate(raw)
        except ValidationError as exc:
            fields = tuple(dict.fromkeys(str(e['loc'][0]) if e['loc'] and e['loc'][0] in InsightProposal.model_fields
                else '<undeclared>' for e in exc.errors(include_input=False, include_context=False)))
            rejected.append(InsightRejection(index=index, fields=fields))
            continue
        texts = {name: getattr(proposal, name) for name in _TEXT_FIELDS}
        references = list(dict.fromkeys([*proposal.evidence_refs,
            *(ref for text in texts.values() for ref in _REFERENCE.findall(text))]))
        issues, fact_ids, source_ids, numeric_ids = [], [], [], []
        replacements = {}
        for ref in references:
            if ref in cards:
                card = cards[ref]
                fact_ids.append(card.fact_id)
                source_ids.extend(card.source_ids)
            elif ref in numbers:
                anchor = numbers[ref]
                if (not set(anchor.required_fact_ids) <= facts.keys()
                        or not set(anchor.input_evidence_ids) <= sources.keys()
                        or anchor.snapshot_id != catalog.snapshot_id):
                    issues.append('numeric_scope')
                    continue
                numeric_ids.append(anchor.anchor_id)
                fact_ids.extend(anchor.required_fact_ids)
                source_ids.extend(anchor.input_evidence_ids)
                replacements[ref] = render_numeric_anchor(anchor.model_dump(mode='json'))
            else:
                issues.append('reference_unknown')
        if not fact_ids:
            issues.append('evidence_missing')
        if any(sid not in sources or sources[sid].availability != 'available'
               or sources[sid].content is None or sources[sid].usable_as_of is None for sid in source_ids):
            issues.append('source_unavailable')
        for text in texts.values():
            normalized = unicodedata.normalize('NFKC', _REFERENCE.sub('', text))
            if (_QUANTITY.search(normalized) or _CN_QUANTITY.search(normalized)
                    or _EN_QUANTITY.search(normalized) or '{{' in normalized or '}}' in normalized):
                issues.append('numeric_literal_unbound')
        rendered = InsightText(**{name: _REFERENCE.sub(
            lambda m, values=replacements: values.get(m[1], m[0]), text) for name, text in texts.items()})
        identity = {'snapshot': catalog.snapshot_id, 'role': role, 'index': index,
                    'revision': revision, 'proposal': proposal.model_dump(mode='json')}
        items.append(SavedInsight(insight_id='insight.' + canonical_sha256(identity), role=role,
            index=index, revision=revision, snapshot_id=catalog.snapshot_id, catalog_id=canonical_sha256(catalog.model_dump(mode='json')),
            status='pending' if issues else 'accepted', proposal=proposal, rendered=rendered,
            fact_ids=tuple(dict.fromkeys(fact_ids)), source_ids=tuple(dict.fromkeys(source_ids)),
            numeric_ids=tuple(dict.fromkeys(numeric_ids)), issues=tuple(dict.fromkeys(issues))))
    return InsightBatch(items=tuple(items), rejected=tuple(rejected))
