"""Offline tests for the opt-in, publication-neutral Markdown projection."""

import hashlib
from datetime import date, datetime, timezone

from tradingagents.agents.schemas._company_basics import CompanyBasicsV1
from tradingagents.agents.schemas._evidence import SourceContentV1, SourceEvidenceV1
from tradingagents.agents.schemas._insight import (
    EvidenceCard,
    InsightCatalog,
    InsightReport,
    NumericReference,
    SavedResponse,
    SavedReview,
    SavedSynthesis,
)
from tradingagents.agents.schemas._numeric_narrative import NumericAnchorV1
from tradingagents.research.insight_report import insight_markdown, validate_insight_report
from tradingagents.research.insights import compile_insights

AS_OF = datetime(2026, 11, 20, tzinfo=timezone.utc)


def source(sid, text='摘录'):
    return SourceEvidenceV1(evidence_id=sid, source_name=f'报告 {sid}', source_kind='official',
        availability='available', public_url='https://example.com/report?x=1&y=2',
        usable_as_of=AS_OF, published_at=AS_OF, captured_at=AS_OF,
        content=SourceContentV1(kind='excerpt', text=text, locator_label='第十页',
            content_sha256=hashlib.sha256(text.encode()).hexdigest()))


def card(ref, *sources):
    return EvidenceCard(ref=ref, fact_id=f'fact.{sources[0]}', text='公司已披露经营数据', source_ids=sources)


def catalog(*, sources=(), cards=(), numbers=()):
    return InsightCatalog(snapshot_id='snapshot', sources=sources, evidence=cards, numbers=numbers)


def compiled(scope, *, role='operating', claim='研究观点', refs=(), reasoning='经营解释', limitations='仍待核查'):
    return compile_insights({'insights': [{'claim': claim, 'evidence_refs': refs, 'reasoning': reasoning,
        'limitations': limitations}]}, catalog=scope, role=role).items[0]


def report(*, catalogs=None, **kwargs):
    return validate_insight_report(InsightReport(run_id='run', ticker='002130', analysis_date=date(2026, 11, 21),
        catalogs=catalogs or {}, **({'insights': ()} | kwargs)))


def test_default_markdown_unchanged():
    record = report(gaps=('<gap> [E1]',))
    expected = (
        '# 002130 公司研究\n\n资料截至：2026-11-21\n\n## 综合判断\n\n'
        '暂未形成通过引用与数值核验的总体判断；不设置默认评级。\n\n'
        '## 专项观点\n\n## 质疑与回应\n\n\n## 资料与流程限制\n\n'
        '- &lt;gap&gt; \\[E1\\]\n\n## 保存的来源与片段\n'
    )
    assert insight_markdown(record).encode() == insight_markdown(record, numbered=False).encode() == expected.encode()


def test_scoped_aliases_first_display_order_and_source_deduplication():
    a, b, c, d = (source(sid) for sid in ('a', 'b', 'c', 'd'))
    left = catalog(sources=(a, b, d), cards=(card('E1', 'a'), card('E2', 'b')))
    right = catalog(sources=(a, c), cards=(card('E1', 'c'), card('E2', 'a')))
    first = compiled(left, claim='正文先见 [E2]', reasoning='后见 [E1]', refs=('E1', 'E2'))
    second = compiled(right, role='event', claim='另一本地 [E1]', reasoning='同一来源 [E2]')
    record = report(catalogs={'event': right, 'operating': left}, insights=(first, second))

    markdown = insight_markdown(record, numbered=True)

    assert '正文先见 [1](#source-1)' in markdown
    assert '后见 [2](#source-2)' in markdown
    assert '另一本地 [3](#source-3)' in markdown
    assert '同一来源 [2](#source-2)' in markdown
    assert markdown.index('### [1] 报告 b') < markdown.index('### [2] 报告 a') < markdown.index('### [3] 报告 c')
    assert markdown.count('id="source-2"') == 1
    assert '### 报告 d（未编号）' in markdown
    assert '适用时间：2026-11-20T00:00:00+00:00' in markdown
    assert '定位：第十页' in markdown
    assert '<https://example.com/report?x=1&y=2>' in markdown
    assert insight_markdown(record, numbered=True) == markdown


def test_synthesis_review_response_and_basic_facts_use_the_actual_bound_catalog():
    a, b, c, d = (source(sid) for sid in ('a', 'b', 'c', 'd'))
    own = catalog(sources=(a,), cards=(card('E1', 'a'),))
    review_scope = catalog(sources=(a, b), cards=(card('E1', 'b'),))
    reply_scope = catalog(sources=(c,), cards=(card('E1', 'c'),))
    basic_scope = catalog(sources=(d,), cards=(card('E1', 'd'),))
    item = compiled(own, claim='专项 [E1]')
    note = compiled(review_scope, role='review', claim='质疑 [E1]')
    reply = compiled(reply_scope, role='review', reasoning='回复 [E1]')
    record = report(catalogs={'operating': own, 'review': review_scope, 'response': reply_scope, 'basic': basic_scope},
        insights=(item,), company_basics=CompanyBasicsV1(introduction=({'label': '主营', 'claim_id': 'fact.d'},)),
        synthesis=SavedSynthesis(stance=None, judgement='综合 [I1]', reasoning='解释', limitations='局限', next_check='核查',
            insight_ids=(item.insight_id,), reference_ids={'I1': item.insight_id}),
        reviews=(SavedReview(note=note, target_id=item.insight_id, status='challenged', concern=note.rendered.claim,
            reasoning=note.rendered.reasoning, source_ids=note.source_ids),),
        responses=(SavedResponse(note=reply, target_id=item.insight_id, action='maintain',
            reasoning=reply.rendered.reasoning, source_ids=reply.source_ids),))

    markdown = insight_markdown(record, numbered=True)

    assert r'综合 \[I1\] [1](#source-1)' in markdown
    assert f'引用观点：{item.insight_id}' in markdown
    assert '主营：公司已披露经营数据 [2](#source-2)' in markdown
    assert '专项 [1](#source-1)' in markdown
    assert '质疑 [3](#source-3)' in markdown
    assert '回复 [4](#source-4)' in markdown
    assert len([line for line in markdown.splitlines() if line.startswith('<a id=')]) == 4


def test_numeric_binding_retains_exact_value_unit_and_input_lineage():
    a, b = source('a'), source('b')
    def anchor(src, amount):
        return NumericReference(ref='N1', anchor=NumericAnchorV1(anchor_id=f'num.{src.evidence_id}',
            definition_key='reported', subject='公司', label='营收', basis='actual_reported', value=amount, unit='CNY',
            required_fact_ids=(f'fact.{src.evidence_id}',), input_evidence_ids=(src.evidence_id,), snapshot_id='snapshot',
            lineage={'kind': 'source', 'source_content_sha256': src.content.content_sha256,
                'source_selector': {'table': 'income', 'field': 'revenue'}}))
    first = catalog(sources=(a,), cards=(card('E1', 'a'),), numbers=(anchor(a, '123456789.012345'),))
    second = catalog(sources=(b,), cards=(card('E1', 'b'),), numbers=(anchor(b, '987654321.098765'),))
    inline = compiled(first, claim='收入 [N1]')
    listed = compiled(second, role='market', refs=('N1',))
    invalid = compiled(first.model_copy(update={'snapshot_id': 'other'}), role='focus_response', reasoning='无法绑定 [N1]')
    record = report(catalogs={'first': first, 'second': second, 'invalid': first.model_copy(update={'snapshot_id': 'other'})},
        insights=(inline, listed), focus_insights=(invalid,))

    markdown = insight_markdown(record, numbered=True)

    assert '1.23亿元' in markdown
    assert '原值：123456789.012345 CNY；数值标识：num.a） [1](#source-1)' in markdown
    assert '补充引用：' in markdown
    assert '原值：987654321.098765 CNY；数值标识：num.b） [2](#source-2)' in markdown
    assert '输入来源标识：a' in markdown and '输入来源标识：b' in markdown
    assert a.content.content_sha256 in markdown and '"field": "revenue"' in markdown
    assert r'无法绑定 \[N1\]（未解析或无已保存绑定）' in markdown


def test_pending_references_remain_visible_and_external_prose_is_inert():
    a = source('a', '[E1] [1](#source-77) <a id="source-1">fake</a>')
    left = catalog(sources=(a,), cards=(card('E1', 'a'), card('E2', 'absent', 'a')))
    right = catalog(sources=(source('absent'),), cards=(card('E2', 'absent'),))
    item = compiled(left, claim='![E1]', refs=('E9',), reasoning='不完整 [E2]；原文 [77](#source-77)')
    record = report(catalogs={'left': left, 'right': right}, insights=(item,))

    markdown = insight_markdown(record, numbered=True)

    assert r'\![1](#source-1)' in markdown
    assert r'不完整 \[E2\] （来源未保存或不可用：absent） [1](#source-1)' in markdown
    assert r'补充引用：\[E9\]（未解析或无已保存绑定）' in markdown
    assert r'\[77\](#source-77)' not in markdown  # the destination # is escaped too
    assert r'\[77\](\#source-77)' in markdown
    assert r'\[E1\] \[1\](\#source-77) &lt;a id="source-1"&gt;fake&lt;/a&gt;' in markdown
    assert '### 报告 absent（未编号）' in markdown
    assert markdown.count('<a id="source-1">') == 1 and '(#source-2)' not in markdown
