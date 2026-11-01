"""Current Insight explanation targets and validation."""
import hashlib
import json


def indicator_presentations(record):
    return {}

def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def explanation_targets(record, indicators, focus=None, *, batched=False):
    targets, excluded, size = {}, {}, 0
    for item in (*record.insights, *record.focus_insights):
        key = 'insight:' + item.insight_id
        text = '\n'.join((item.rendered.claim, item.rendered.reasoning, item.rendered.limitations))
        target = {'target': key, 'text': text, 'text_sha256': text_hash(text),
            'references': list(item.source_ids), 'facts': [], 'research_disposition': item.status}
        length = len(json.dumps(target, ensure_ascii=False))
        if length + 2 > 32000 or not batched and (len(targets) >= 32 or size + length > 32000):
            excluded[key] = 'target_too_large' if batched else 'capacity_limited'
        else:
            targets[key] = target
            size += length
    return targets, excluded


def validate_explanation_entry(entry, target):
    from tradingagents.research.quantity_tokens import _scan_literal
    if entry.target != target["target"] or not set(entry.references) <= set(target["references"]):
        raise ValueError("explanation reference invalid")
    _scan_literal(entry.explanation, "explanation")
    _scan_literal(entry.uncertainty, "uncertainty")
