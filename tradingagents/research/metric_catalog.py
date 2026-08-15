"""Code-owned definitions for the first explainable metric basket."""

from __future__ import annotations

from types import MappingProxyType

from .metric_models import MetricDefinitionV1


def _definition(**values: object) -> MetricDefinitionV1:
    return MetricDefinitionV1.model_validate(values)


_METRICS = {
    "revenue_yoy": _definition(
        metric_id="revenue_yoy",
        label_zh="营业收入同比",
        label_en="Revenue YoY",
        plain_explanation="本期营业收入相对可比上期增长了多少。",
        formula_text="(本期收入 - 上期收入) / abs(上期收入)",
        unit="%",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("revenue_current", "revenue_prior"),
        validity_conditions=("两期必须采用同一币种和相同报告口径", "上期收入不能为零"),
        pitfalls=("不能把季度同比和年度同比混用", "负收入不应被当作正常增长率"),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "net_income_yoy": _definition(
        metric_id="net_income_yoy",
        label_zh="归母净利润同比",
        label_en="Net Income YoY",
        plain_explanation="本期归母净利润相对可比上期的变化。",
        formula_text="(本期净利润 - 上期净利润) / abs(上期净利润)",
        unit="%",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("net_income_current", "net_income_prior"),
        validity_conditions=("两期口径一致", "上期净利润不能为零"),
        pitfalls=("亏损转盈利应标注口径变化，不能只看百分比",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "operating_cash_flow_yoy": _definition(
        metric_id="operating_cash_flow_yoy",
        label_zh="经营现金流同比",
        label_en="Operating Cash Flow YoY",
        plain_explanation="经营活动产生的现金流相对可比上期的变化。",
        formula_text="(本期经营现金流 - 上期经营现金流) / abs(上期经营现金流)",
        unit="%",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("operating_cash_flow_current", "operating_cash_flow_prior"),
        validity_conditions=("两期口径一致", "上期经营现金流不能为零"),
        pitfalls=("现金流受季节性影响，不能替代多期趋势",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "gross_margin": _definition(
        metric_id="gross_margin",
        label_zh="毛利率",
        label_en="Gross Margin",
        plain_explanation="收入中扣除销售成本后剩余的比例。",
        formula_text="毛利 / 营业收入",
        unit="%",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("gross_profit", "revenue"),
        validity_conditions=("营业收入必须为正",),
        pitfalls=("不同会计准则或业务结构可能导致不可比",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "net_margin": _definition(
        metric_id="net_margin",
        label_zh="净利率",
        label_en="Net Margin",
        plain_explanation="每一元收入最终转化为净利润的比例。",
        formula_text="净利润 / 营业收入",
        unit="%",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("net_income", "revenue"),
        validity_conditions=("营业收入必须为正",),
        pitfalls=("一次性收益会扭曲当期净利率",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "roe": _definition(
        metric_id="roe",
        label_zh="净资产收益率",
        label_en="Return on Equity",
        plain_explanation="公司用股东投入资本创造净利润的效率。",
        formula_text="净利润 / 平均股东权益",
        unit="%",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("net_income", "equity_begin", "equity_end"),
        validity_conditions=("平均股东权益不能为零", "权益口径必须一致"),
        pitfalls=("高杠杆可能抬高 ROE，需结合负债率阅读",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "cash_conversion": _definition(
        metric_id="cash_conversion",
        label_zh="现金转换率",
        label_en="Cash Conversion",
        plain_explanation="净利润有多少被经营活动现金流覆盖。",
        formula_text="经营现金流 / 净利润",
        unit="x",
        interpretation_mode="higher_is_better",
        higher_is_better=True,
        required_inputs=("operating_cash_flow", "net_income"),
        validity_conditions=("净利润必须为正",),
        pitfalls=("亏损期间该比率不具有通常解释",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "debt_ratio": _definition(
        metric_id="debt_ratio",
        label_zh="资产负债率",
        label_en="Debt Ratio",
        plain_explanation="总资产中由负债提供资金的比例。",
        formula_text="总负债 / 总资产",
        unit="%",
        interpretation_mode="lower_is_better",
        higher_is_better=False,
        required_inputs=("total_liabilities", "total_assets"),
        validity_conditions=("总资产必须为正",),
        pitfalls=("行业资本结构差异很大，不能脱离同行比较",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual"),
    ),
    "pe": _definition(
        metric_id="pe",
        label_zh="市盈率",
        label_en="Price to Earnings",
        plain_explanation="市场愿意为一元可验证盈利支付多少价格。",
        formula_text="股权市值 / 可比净利润",
        unit="x",
        interpretation_mode="lower_is_better",
        higher_is_better=False,
        required_inputs=("equity_value", "net_income"),
        validity_conditions=("盈利必须为正", "市值与利润必须同一时点/口径"),
        pitfalls=("负盈利时 PE 不可用", "TTM、年度和预测利润不可混用"),
        source_capabilities=("verified_market_snapshot", "fundamentals_annual"),
    ),
    "pb": _definition(
        metric_id="pb",
        label_zh="市净率",
        label_en="Price to Book",
        plain_explanation="市场价格相对于每股账面净资产的倍数。",
        formula_text="股权市值 / 股东权益",
        unit="x",
        interpretation_mode="lower_is_better",
        higher_is_better=False,
        required_inputs=("equity_value", "equity"),
        validity_conditions=("股东权益必须为正",),
        pitfalls=("资产重估和会计口径会影响跨公司比较",),
        source_capabilities=("verified_market_snapshot", "fundamentals_annual"),
    ),
    "ps": _definition(
        metric_id="ps",
        label_zh="市销率",
        label_en="Price to Sales",
        plain_explanation="市场价格相对于营业收入的倍数。",
        formula_text="股权市值 / 营业收入",
        unit="x",
        interpretation_mode="lower_is_better",
        higher_is_better=False,
        required_inputs=("equity_value", "revenue"),
        validity_conditions=("营业收入必须为正",),
        pitfalls=("忽略利润率差异时容易误读",),
        source_capabilities=("verified_market_snapshot", "fundamentals_annual"),
    ),
}


_RAW_METRICS = {
    metric_id: _definition(
        metric_id=metric_id,
        label_zh=label_zh,
        label_en=label_en,
        plain_explanation=f"经验证来源披露的{label_zh}原始值。",
        formula_text="provider_observed",
        unit="provider_defined",
        interpretation_mode="descriptive",
        required_inputs=(),
        validity_conditions=("保留原始报告期、频率和单位",),
        pitfalls=("不得跨口径直接比较",),
        source_capabilities=("fundamentals_quarterly", "fundamentals_annual", "verified_market_snapshot"),
    )
    for metric_id, label_zh, label_en in (
        ("revenue", "营业收入", "Revenue"),
        ("revenue_current", "本期营业收入", "Current Revenue"),
        ("revenue_prior", "上期营业收入", "Prior Revenue"),
        ("net_income", "归母净利润", "Net Income"),
        ("net_income_current", "本期归母净利润", "Current Net Income"),
        ("net_income_prior", "上期归母净利润", "Prior Net Income"),
        ("operating_cash_flow", "经营现金流", "Operating Cash Flow"),
        ("operating_cash_flow_current", "本期经营现金流", "Current Operating Cash Flow"),
        ("operating_cash_flow_prior", "上期经营现金流", "Prior Operating Cash Flow"),
        ("gross_profit", "毛利", "Gross Profit"),
        ("equity_begin", "期初股东权益", "Beginning Equity"),
        ("equity_end", "期末股东权益", "Ending Equity"),
        ("equity", "股东权益", "Equity"),
        ("total_liabilities", "总负债", "Total Liabilities"),
        ("total_assets", "总资产", "Total Assets"),
        ("equity_value", "股权市值", "Equity Value"),
    )
}

METRIC_CATALOG = MappingProxyType({**_RAW_METRICS, **_METRICS})


def metric_definition(metric_id: str) -> MetricDefinitionV1:
    try:
        return METRIC_CATALOG[metric_id]
    except KeyError as exc:
        raise KeyError(f"unknown metric_id: {metric_id}") from exc


def all_metric_definitions() -> tuple[MetricDefinitionV1, ...]:
    return tuple(METRIC_CATALOG.values())
