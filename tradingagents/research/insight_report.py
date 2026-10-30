"""Publication/read integrity and Markdown for independent Insight records."""

from tradingagents.agents.schemas._insight import EvidenceCard, InsightCatalog, InsightReport
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.insights import compile_insights


def validate_insight_report(record):
    """Replay host compilation and effective versions, without model decisions."""
    if record.company_basics is not None:
        facts = {e.fact_id for c in record.catalogs.values() for e in c.evidence}
        if any(f.claim_id not in facts for f in (*record.company_basics.introduction,
                *record.company_basics.fundamentals, *record.company_basics.quantitative)):
            raise ValueError('insight_company_basics_reference')
    ids = {i.insight_id for i in record.insights}
    if len(ids) != len(record.insights):
        raise ValueError('insight_identity_duplicate')
    excluded = set(record.superseded_ids) | {r.target_id for r in record.responses if r.action in {'revise', 'withdraw'}}
    catalogs = {canonical_sha256(c.model_dump(mode='json')): c for c in record.catalogs.values()}
    for item in (*record.insights, *record.focus_insights):
        catalog = catalogs[item.catalog_id]
        replay = compile_insights({'insights': [item.proposal.model_dump(mode='json')]}, catalog=catalog,
            role=item.role, revision=item.revision, indices=[item.index]).items[0]
        if item.insight_id in excluded:
            replay = replay.model_copy(update={'status': 'excluded'})
        if replay != item:
            raise ValueError('insight_replay_mismatch')
    for note in (r.note for r in (*record.reviews, *record.responses) if r.note is not None):
        replay = compile_insights({'insights': [note.proposal.model_dump(mode='json')]},
            catalog=catalogs[note.catalog_id], role='review').items[0]
        if replay != note or set(replay.issues) - {'evidence_missing'}:
            raise ValueError('insight_note_replay_mismatch')
    for review in record.reviews:
        if review.status in {'challenged', 'no_counterevidence'} and (review.note is None
                or review.reasoning != review.note.rendered.reasoning or review.source_ids != review.note.source_ids
                or review.concern is not None and review.concern != review.note.rendered.claim):
            raise ValueError('insight_review_replay_mismatch')
        if review.target_id not in ids:
            raise ValueError('insight_review_target')
    for reply in record.responses:
        if reply.reasoning != reply.note.rendered.reasoning or reply.source_ids != reply.note.source_ids:
            raise ValueError('insight_response_replay_mismatch')
        if reply.target_id not in ids or reply.replacement_id is not None and reply.replacement_id not in ids:
            raise ValueError('insight_response_target')
    if record.synthesis is not None:
        validate_saved_synthesis(record.synthesis, record.insights, record.catalogs['review'])
    return record


def validate_saved_synthesis(value, insights, catalog):
    active = {i.insight_id: i for i in insights if i.status == 'accepted'}
    if not value.insight_ids or not set(value.reference_ids.values()) <= active.keys():
        raise ValueError('insight_synthesis_support')
    context = InsightCatalog(snapshot_id=catalog.snapshot_id, sources=catalog.sources,
        evidence=tuple(EvidenceCard(ref=ref, fact_id=identity, text=active[identity].rendered.claim,
            source_ids=active[identity].source_ids) for ref, identity in value.reference_ids.items()))
    replay = compile_insights({'insights': [{'claim': value.judgement,
        'evidence_refs': [ref for ref, identity in value.reference_ids.items() if identity in value.insight_ids],
        'reasoning': value.reasoning, 'limitations': value.limitations + '\n' + value.next_check}]},
        catalog=context, role='synthesis').items[0]
    if replay.status != 'accepted' or set(replay.fact_ids) != set(value.insight_ids):
        raise ValueError('insight_synthesis_replay_mismatch')
    return value


def parse_insight_report(value):
    return validate_insight_report(InsightReport.model_validate(value))


def insight_markdown(record):
    from tradingagents.runtime.reports import _markdown_text

    escaped = _markdown_text
    lines = [f'# {escaped(record.ticker)} 公司研究', '', f'资料截至：{record.analysis_date}', '', '## 综合判断', '']
    if record.synthesis is not None:
        value = record.synthesis
        stance = {'favorable': '有利', 'neutral': '中性', 'unfavorable': '不利', None: '暂不评级'}[value.stance]
        lines.extend([f'总体判断：{stance}', '', escaped(value.judgement), '', escaped(value.reasoning), '',
            '局限：' + escaped(value.limitations), '', '后续核查：' + escaped(value.next_check), ''])
        lines.extend(['引用观点：' + ', '.join(value.insight_ids), ''])
    else:
        lines.extend(['暂未形成通过引用与数值核验的总体判断；不设置默认评级。', ''])
    if record.company_basics is not None:
        facts = {e.fact_id: e for c in record.catalogs.values() for e in c.evidence}
        lines.extend(['## 公司基础资料', '', escaped(record.company_basics.company_name or record.ticker), ''])
        for field in (*record.company_basics.introduction, *record.company_basics.fundamentals, *record.company_basics.quantitative):
            lines.extend([escaped(field.label) + '：' + escaped(facts[field.claim_id].text), ''])
    lines.extend(['## 专项观点', ''])
    labels = {'accepted': '可追溯研究观点', 'pending': '待验证', 'excluded': '已撤回或修订'}
    for item in (*record.insights, *record.focus_insights):
        lines.extend([f'### {escaped(item.rendered.claim)}', '', f'{labels[item.status]} · {escaped(item.role)}', '',
            escaped(item.rendered.reasoning), '', '反证或局限：' + escaped(item.rendered.limitations), '',
            '观点标识：' + item.insight_id, '', '来源：' + ', '.join(item.source_ids), ''])
    lines.extend(['## 质疑与回应', ''])
    for review in record.reviews:
        lines.extend([f'- {review.target_id}：{escaped(review.concern or review.status)}',
            '  ' + escaped(review.reasoning)])
    for reply in record.responses:
        lines.extend([f'- 回应 {reply.target_id}：{reply.action}', '  ' + escaped(reply.reasoning)])
    lines.extend(['', '## 资料与流程限制', ''])
    lines.extend('- ' + escaped(gap) for gap in record.gaps)
    lines.extend(['', '## 保存的来源与片段', ''])
    sources = {s.evidence_id: s for c in record.catalogs.values() for s in c.sources}
    for sid, source in sources.items():
        lines.extend([f'### {escaped(source.source_name)}', '', '来源标识：' + escaped(sid), ''])
        if source.content:
            lines.extend(['定位：' + escaped(source.content.locator_label), '', escaped(source.content.text), ''])
        if source.public_url:
            lines.extend([source.public_url, ''])
    return '\n'.join(lines).rstrip() + '\n'
