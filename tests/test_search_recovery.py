"""Financial search recovery must satisfy the exact original field demand."""

from tests.test_search_admission import material
from tradingagents.agents.schemas._search import FieldRequirementV1
from tradingagents.research.search_admission import admit_search_batch
from tradingagents.research.search_recovery import recover_fields


def demand(**changes):
    value = {'ticker': '600519.SH', 'field': 'revenue', 'period': '2025-12-31',
             'unit': 'CNY', 'currency': 'CNY', 'basis': 'consolidated_actual'}
    return FieldRequirementV1.model_validate({**value, **changes})


def report():
    return '公司代码：600519\n2025年年度报告\n合并利润表\n单位：元  币种：人民币\n项目  2025年  2024年\n营业收入  120.50  100.00\n'


def recover(text, requirement=None):
    batch = material(text)
    admitted = admit_search_batch(batch, ticker='600519.SH', cutoff=batch.requests[0].cutoff)
    return recover_fields(admitted, requirements=(requirement or demand(),))


def test_official_report_recovers_missing_revenue():
    result = recover(report())
    assert len(result.fields) == 1 and result.fields[0].value == '120.50'
    assert result.fields[0].source_content_sha256 == result.observations[0].source.content.content_sha256


def test_wrong_company_period_unit_and_forecast_rejected():
    assert not recover(report().replace('600519', '000001')).fields
    assert not recover(report(), demand(period='2024-12-31')).fields
    assert not recover(report().replace('人民币', '美元')).fields
    assert not recover(report().replace('2025年年度报告', '2025年盈利预测')).fields


def test_missing_price_series_not_recovered_by_return_article():
    assert not recover('公司代码：600519\n近一年上涨20%。', demand(field='adjusted_daily', unit='CNY/share')).fields


def test_clipped_table_not_calculable():
    batch = material(report(), truncated=True)
    admitted = admit_search_batch(batch, ticker='600519.SH', cutoff=batch.requests[0].cutoff)
    assert not recover_fields(admitted, requirements=(demand(),)).fields


def test_conflicting_original_values_remain_separate_not_a_unified_value():
    first = material(report())
    second_hit = first.hits[0].model_copy(update={'url': 'https://example.com/second',
        'canonical_url': 'https://example.com/second', 'content': report().replace('120.50', '130.50')})
    batch = first.model_copy(update={'hits': (*first.hits, second_hit)})
    admitted = admit_search_batch(batch, ticker='600519.SH', cutoff=batch.requests[0].cutoff)
    result = recover_fields(admitted, requirements=(demand(),))
    assert 'field_conflict:revenue' in result.conflicts
    assert {f.value for f in result.fields} == {'120.50', '130.50'}
