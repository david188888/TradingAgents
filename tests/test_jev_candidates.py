import pytest

from tradingagents.agents.schemas._insight import EvidenceCard
from tradingagents.research.jev_candidates import select_jev_candidates


def _card(number: int, text: str = '') -> EvidenceCard:
    return EvidenceCard(ref=f'E{number}', fact_id=f'fact-{number}', text=text,
                        source_ids=(f'source-{number}',))


@pytest.mark.parametrize('limit', [20, 30])
def test_recalls_late_conflicts_beyond_the_old_input_caps(limit):
    cited = _card(150, '北辰智造曾发布业绩预告。')
    conflicts = (
        _card(151, '北辰智造：报告期 2025-09-30，归属于母公司股东的净利润同比下滑。'),
        _card(152, '北辰智造：报告期 2025-09-30，经营活动产生的现金流量净额转负。'),
    )
    distractors = tuple(_card(i, (
        '北辰智造 2025年半年报：归母净利润和经营性现金流上升。',
        '北辰智造 2025Q3：存货和应收账款下降。',
        '南河材料 2025Q3：归母净利润和经营性现金流持平。',
    )[i % 3]) for i in range(1, 150))
    evidence = (*distractors, cited, *conflicts)
    candidates, partial = select_jev_candidates(
        evidence, cited=[cited.ref], limit=limit,
        claim='北辰智造2025年前三季度归母净利润增长。',
        reasoning='同季度北辰智造经营性现金流持续改善。',
    )

    assert not set(conflicts).intersection(evidence[:126])
    assert len(candidates) == limit
    assert candidates[0] is cited
    assert set(conflicts) <= set(candidates)
    assert partial is True


@pytest.mark.parametrize(('limit', 'include_uncited', 'partial'), [
    (1, False, True), (2, False, True), (3, True, False), (10, True, False),
])
def test_cited_cards_are_never_dropped_even_over_limit(limit, include_uncited, partial):
    cited = (_card(2, '无相关线索'), _card(3, '另一事实'))
    other = _card(1, '恒远工业营收下降')
    expected = (*cited, other) if include_uncited else cited
    selected, is_partial = select_jev_candidates(
        (*cited, other), cited={card.ref for card in cited}, claim=other.text,
        reasoning='', limit=limit,
    )
    assert selected == expected
    assert is_partial is partial


def test_oversized_cited_only_catalog_is_complete():
    cards = (_card(1), _card(2))
    assert select_jev_candidates(cards, cited=('E1', 'E2'), claim='', reasoning='', limit=1) == (
        cards, False,
    )


def test_ranking_ties_are_stable_across_catalog_order_and_keep_card_identity():
    cards = tuple(_card(i, '恒远工业 2026Q1 营业收入与预告不符。') for i in (8, 2, 1, 9))
    args = {'cited': ['E9'], 'claim': '恒远工业 2026年第一季度营收符合预期。',
            'reasoning': '', 'limit': 3}
    selected, partial = select_jev_candidates(cards, **args)

    assert tuple(card.ref for card in selected) == ('E9', 'E1', 'E2')
    assert select_jev_candidates(reversed(cards), **args) == (selected, partial)
    assert partial is True
    expected = (cards[3], cards[2], cards[1])
    assert all(actual is original for actual, original in zip(selected, expected, strict=True))
