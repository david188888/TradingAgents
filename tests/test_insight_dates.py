import unicodedata
from datetime import date

import pytest

from tradingagents.research.insight_dates import normalize_supported_dates
from tradingagents.research.insights import _QUANTITY
from tradingagents.research.quantity_tokens import _CN_QUANTITY, _EN_QUANTITY, _scan_literal

_CUTOFF = date(2024, 3, 5)


@pytest.mark.parametrize(('draft', 'citation'), [
    ('公告日期：2024-02-29。', '公司于2024年2月29日披露。'),
    ('公告日期：2024年02月29日。', 'Date: 2024-02-29.'),
    ('公告日期：二〇二四年二月二十九日。', '公司于2024-02-29披露。'),
    ('公告日期：2024-02-29。', '二〇二四年二月二十九日披露。'),
])
def test_attested_date_is_normalized_and_passes_quantity_checks(draft, citation):
    rendered = normalize_supported_dates(draft, (citation,), analysis_date=_CUTOFF)
    assert rendered == '公告日期：二零二四年二月二十九日。'
    normalized = unicodedata.normalize('NFKC', rendered)
    assert not any(regex.search(normalized) for regex in (_QUANTITY, _CN_QUANTITY, _EN_QUANTITY))
    _scan_literal(rendered, 'claim')


def test_analysis_date_needs_no_citation_and_other_unsupported_dates_stay_unchanged():
    text = '截至2024年3月5日股东会未开；2024-03-04及2024年3月6日另议。'
    assert normalize_supported_dates(text, ('2024-03-06有安排。',), analysis_date=_CUTOFF) == (
        '截至二零二四年三月五日股东会未开；2024-03-04及2024年3月6日另议。'
    )


@pytest.mark.parametrize('text', [
    '2023-02-29', '2024-04-31', '2024-00-29', '0000年2月29日',
    '2024-2-29', '2024/02/29', '2024年2月029日', '2024年2月29号',
    '二零二四年二月廿九日', '２０２４-０２-２９', '2024-02-29T12:00:00',
    '2024Q1', '2024年报', '2024年2月', '2月29日',
    'X2024-02-29', '12024年2月29日', '2024年2月29日5',
])
def test_only_strict_standalone_real_full_dates_are_eligible(text):
    assert normalize_supported_dates(text, (text,), analysis_date=_CUTOFF) == text


@pytest.mark.parametrize('citation', [
    '证券代码为X2024-02-29。', '只披露2024年2月。',
    '二零二四年二月三十日', '2024年2月与29日另见两则公告。',
])
def test_non_date_evidence_does_not_support_a_date(citation):
    text = '2024-02-29有披露'
    assert normalize_supported_dates(text, (citation,), analysis_date=_CUTOFF) == text


@pytest.mark.parametrize('text', [
    '2024-02-29-2024-03-05', '2024-02-29 ～ 2024-03-05',
    '（2024年2月29日）至（2024年3月5日）', '2024年2月29日至五日',
    '5 至 2024-02-29', '1.2024-02-29', '2024-02-29.5',
    '$ 2024-02-29', 'RMB 2024-02-29', '2024-02-29万元',
    '2024-02-29 ％', '2024-02-29 ｍｉｌｌｉｏｎ',
    '2024-02-29[E1]万元', 'USD [E1]2024-02-29', '2024-02-29[E1]～2024-03-05',
])
def test_quantity_and_range_syntax_is_not_a_date_exemption(text):
    citations = ('公司公告于2024-02-29。', '公司公告于2024-03-05。')
    assert normalize_supported_dates(text, citations, analysis_date=_CUTOFF) == text


def test_mixed_text_only_changes_supported_dates_and_retains_numeric_errors():
    text = '2024-02-29披露，2024年3月5日更新，增长5%，估值三倍。[E1]'
    rendered = normalize_supported_dates(text, ('公司于2024年2月29日发布公告。',), analysis_date=_CUTOFF)
    assert rendered == '二零二四年二月二十九日披露，二零二四年三月五日更新，增长5%，估值三倍。[E1]'
    normalized = unicodedata.normalize('NFKC', rendered.removesuffix('[E1]'))
    assert _QUANTITY.search(normalized).group() == '5%'
    assert _CN_QUANTITY.search(normalized).group() == '三倍'
    with pytest.raises(ValueError, match='numeric_literal_unbound'):
        _scan_literal(normalized, 'claim')
