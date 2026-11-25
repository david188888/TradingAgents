"""Publication/read integrity and Markdown for independent Insight records."""

import json
from urllib.parse import quote

from tradingagents.agents.schemas._insight import EvidenceCard, InsightCatalog, InsightReport
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.research.insights import _REFERENCE, compile_insights
from tradingagents.research.numeric_catalog import render_numeric_anchor


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
        if review.status == 'verified' and (review.note is not None
                or review.jev_scores is None):
            raise ValueError('insight_review_verified_mismatch')
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


class _NumberedCitations:
    """Resolve saved aliases locally; assign display numbers to source identities globally."""

    def __init__(self, record, escaped):
        self.escaped = escaped
        self.scopes = {}
        self.sources = {}
        self.cited = {}
        self.anchors = {}
        self.insights = {item.insight_id: item for item in record.insights}
        self.facts = {}
        for catalog in record.catalogs.values():
            cid = canonical_sha256(catalog.model_dump(mode='json'))
            sources = {source.evidence_id: source for source in catalog.sources}
            self.scopes[cid] = (sources, {card.ref: card for card in catalog.evidence},
                {number.ref: number.anchor for number in catalog.numbers})
            self.sources.update(sources)
            self.facts.update((card.fact_id, (sources, card)) for card in catalog.evidence)

    def source_marks(self, sources, source_ids, *, alias=None):
        marks = []
        unresolved = False
        for sid in dict.fromkeys(source_ids):
            source = sources.get(sid)
            if (source is None or source.availability != 'available'
                    or source.content is None or source.usable_as_of is None):
                marks.append(f'（来源未保存或不可用：{self.escaped(sid)}）')
                unresolved = True
                continue
            index, bound = self.cited.setdefault(sid, (len(self.cited) + 1, source))
            if source != bound:
                marks.append(f'（同一来源标识的保存内容冲突：{self.escaped(sid)}）')
                unresolved = True
                continue
            marks.append(f'[{index}](#source-{index})')
        if unresolved and alias is not None:
            marks.insert(0, self.escaped(f'[{alias}]'))
        return ' '.join(marks)

    def item_sources(self, item):
        return self.source_marks(self.scopes[item.catalog_id][0], item.source_ids)

    def company_fact_sources(self, fact_id):
        sources, card = self.facts[fact_id]
        return self.source_marks(sources, card.source_ids) or '（没有已绑定来源）'

    def render_alias(self, item, ref):
        sources, cards, numbers = self.scopes[item.catalog_id]
        card, anchor = cards.get(ref), numbers.get(ref)
        if card is not None and card.fact_id in item.fact_ids:
            marks = self.source_marks(sources, card.source_ids, alias=ref)
            if marks:
                return marks
        elif anchor is not None and anchor.anchor_id in item.numeric_ids:
            payload = anchor.model_dump(mode='json')
            self.anchors[canonical_sha256(payload)] = anchor
            marks = self.source_marks(sources, anchor.input_evidence_ids, alias=ref)
            return (self.escaped(render_numeric_anchor(payload))
                + self.escaped(f'（原值：{anchor.value} {anchor.unit}；数值标识：{anchor.anchor_id}）') + ' ' + marks)
        return self.escaped(f'[{ref}]') + '（未解析或无已保存绑定）'

    def render_text(self, value, render_alias):
        # Insert only host-generated markup, not interpolation of raw Markdown.
        # Escape ! as well so prose directly before a marker cannot turn it into an image.
        return ''.join(render_alias(part) if index % 2 else self.escaped(part).replace('!', r'\!')
            for index, part in enumerate(_REFERENCE.split(value)))

    def item_text(self, item, field):
        # The saved host rendering has already consumed numeric aliases; read the
        # replay-verified proposal to recover positions, never scan source text for aliases.
        return self.render_text(getattr(item.proposal, field), lambda ref: self.render_alias(item, ref))

    def explicit_refs(self, item, rendered_fields=('claim', 'reasoning', 'limitations')):
        proposal = item.proposal
        inline = {field: _REFERENCE.findall(getattr(proposal, field))
            for field in ('claim', 'reasoning', 'limitations')}
        shown = {ref for field in rendered_fields for ref in inline[field]}
        hidden_refs = (ref for field, refs in inline.items() if field not in rendered_fields for ref in refs)
        return '；'.join(self.render_alias(item, ref)
            for ref in dict.fromkeys((*proposal.evidence_refs, *hidden_refs)) if ref not in shown)

    def note_lines(self, note, rendered_fields):
        explicit, sources = self.explicit_refs(note, rendered_fields), self.item_sources(note)
        return [f'  {label}：{value}' for label, value in (('补充引用', explicit), ('来源', sources)) if value]

    def synthesis_text(self, value, references):
        def render(ref):
            identity = references.get(ref)
            if identity is None:
                return self.escaped(f'[{ref}]') + '（未解析观点）'
            marks = self.item_sources(self.insights[identity])
            return self.escaped(f'[{ref}]') + (' ' + marks if marks else '')

        return self.render_text(value, render)

    def numeric_lines(self):
        lines = []
        if self.anchors:
            lines.extend(['', '## 保存的数值绑定', ''])
        for anchor in self.anchors.values():
            lines.extend([
                f'### {self.escaped(anchor.label)}', '',
                self.escaped(f'数值标识：{anchor.anchor_id}；原值：{anchor.value} {anchor.unit}'), '',
                '事实标识：' + self.escaped(', '.join(anchor.required_fact_ids)), '',
                '输入来源标识：' + self.escaped(', '.join(anchor.input_evidence_ids)), '',
                '数据血缘：' + self.escaped(json.dumps(anchor.lineage, ensure_ascii=False, sort_keys=True)), '',
            ])
        return lines

    def source_lines(self):
        entries = [(index, source) for index, source in self.cited.values()]
        entries.extend((None, source) for sid, source in self.sources.items() if sid not in self.cited)
        lines = []
        for index, source in entries:
            title = self.escaped(source.source_name)
            if index is not None:
                lines.extend([f'<a id="source-{index}"></a>', '', f'### [{index}] {title}', ''])
            else:
                lines.extend([f'### {title}（未编号）', ''])
            lines.extend(['来源标识：' + self.escaped(source.evidence_id), ''])
            for label, timestamp in (('适用时间', source.usable_as_of), ('发布时间', source.published_at),
                    ('采集时间', source.captured_at)):
                if timestamp is not None:
                    lines.extend([f'{label}：{timestamp.isoformat()}', ''])
            if source.content:
                lines.extend(['定位：' + self.escaped(source.content.locator_label), '',
                    self.escaped(source.content.text), ''])
            if source.public_url:
                url = quote(source.public_url, safe=":/?#[]@!$&'()*+,;=%")
                lines.extend([f'<{url}>', ''])
            lines.extend('限制：' + self.escaped(value) for value in source.limitations)
            if source.limitations:
                lines.append('')
        return lines


def insight_markdown(record: InsightReport, *, numbered: bool = False) -> str:
    """Project a validated report without changing its canonical Markdown by default."""
    from tradingagents.runtime.reports import _markdown_text

    escaped = _markdown_text
    citations = _NumberedCitations(record, escaped) if numbered else None

    def item_text(item, field):
        return citations.item_text(item, field) if citations else escaped(getattr(item.rendered, field))

    lines = [f'# {escaped(record.ticker)} 公司研究', '', f'资料截至：{record.analysis_date}', '', '## 综合判断', '']
    if record.synthesis is not None:
        value = record.synthesis
        stance = {'favorable': '有利', 'neutral': '中性', 'unfavorable': '不利', None: '暂不评级'}[value.stance]
        def synthesis_text(text):
            return citations.synthesis_text(text, value.reference_ids) if citations else escaped(text)

        lines.extend([f'总体判断：{stance}', '', synthesis_text(value.judgement), '', synthesis_text(value.reasoning), '',
            '局限：' + synthesis_text(value.limitations), '', '后续核查：' + synthesis_text(value.next_check), ''])
        lines.extend(['引用观点：' + ', '.join(value.insight_ids), ''])
        if citations:
            for identity in value.insight_ids:
                marks = citations.item_sources(citations.insights[identity])
                lines.extend([f'观点 {identity} 的来源：{marks}', ''])
    else:
        lines.extend(['暂未形成通过引用与数值核验的总体判断；不设置默认评级。', ''])
    if record.company_basics is not None:
        facts = {e.fact_id: e for c in record.catalogs.values() for e in c.evidence}
        lines.extend(['## 公司基础资料', '', escaped(record.company_basics.company_name or record.ticker), ''])
        for field in (*record.company_basics.introduction, *record.company_basics.fundamentals, *record.company_basics.quantitative):
            text = escaped(field.label) + '：' + escaped(facts[field.claim_id].text)
            if citations:
                text += ' ' + citations.company_fact_sources(field.claim_id)
            lines.extend([text, ''])
    lines.extend(['## 专项观点', ''])
    labels = {'accepted': '可追溯研究观点', 'pending': '待验证', 'excluded': '已撤回或修订'}
    for item in (*record.insights, *record.focus_insights):
        lines.extend([f'### {item_text(item, "claim")}', '', f'{labels[item.status]} · {escaped(item.role)}', '',
            item_text(item, 'reasoning'), '', '反证或局限：' + item_text(item, 'limitations'), '',
            '观点标识：' + item.insight_id, ''])
        if citations:
            explicit = citations.explicit_refs(item)
            if explicit:
                lines.extend(['补充引用：' + explicit, ''])
        lines.extend(['来源：' + (citations.item_sources(item) if citations else ', '.join(item.source_ids)), ''])
    lines.extend(['## 质疑与回应', ''])
    for review in record.reviews:
        concern = escaped(review.concern or review.status)
        reasoning = escaped(review.reasoning)
        rendered_fields = []
        if citations and review.note:
            if review.concern == review.note.rendered.claim:
                concern = citations.item_text(review.note, 'claim')
                rendered_fields.append('claim')
            if review.reasoning == review.note.rendered.reasoning:
                reasoning = citations.item_text(review.note, 'reasoning')
                rendered_fields.append('reasoning')
        lines.extend([f'- {review.target_id}：{concern}', '  ' + reasoning])
        if citations and review.note:
            lines.extend(citations.note_lines(review.note, rendered_fields))
        elif citations and review.source_ids:
            lines.extend(['  来源：' + citations.source_marks({}, review.source_ids)])
    for reply in record.responses:
        reasoning = citations.item_text(reply.note, 'reasoning') if citations else escaped(reply.reasoning)
        lines.extend([f'- 回应 {reply.target_id}：{reply.action}', '  ' + reasoning])
        if citations:
            lines.extend(citations.note_lines(reply.note, ('reasoning',)))
    lines.extend(['', '## 资料与流程限制', ''])
    lines.extend('- ' + escaped(gap) for gap in record.gaps)
    if citations:
        lines.extend(citations.numeric_lines())
    lines.extend(['', '## 保存的来源与片段', ''])
    if citations:
        lines.extend(citations.source_lines())
        return '\n'.join(lines).rstrip() + '\n'
    sources = {s.evidence_id: s for c in record.catalogs.values() for s in c.sources}
    for sid, source in sources.items():
        lines.extend([f'### {escaped(source.source_name)}', '', '来源标识：' + escaped(sid), ''])
        if source.content:
            lines.extend(['定位：' + escaped(source.content.locator_label), '', escaped(source.content.text), ''])
        if source.public_url:
            lines.extend([source.public_url, ''])
    return '\n'.join(lines).rstrip() + '\n'
