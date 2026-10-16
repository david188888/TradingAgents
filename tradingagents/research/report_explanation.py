"""Deterministic reading aids and scoped model targets over an unchanged record."""

import hashlib
import json
from decimal import Decimal, InvalidOperation

from tradingagents.agents.schemas._report_explanation import IndicatorExplanation


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def display_number(value, unit):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "暂不可用"
    if not number.is_finite():
        return "暂不可用"
    if number == 0:
        number = Decimal(0)
    suffix = {"CNY/share": " 元/股", "multiple": " 倍", "dimensionless": "", "ratio": ""}.get(unit, " " + unit)
    if unit in {"return_fraction", "signed_return_fraction"}:
        number *= 100
        suffix = "%"
    elif unit == "percent":
        suffix = "%"
    elif unit in {"CNY", "CNY_YI"}:
        number *= Decimal(100000000) if unit == "CNY_YI" else 1
        scale, suffix = (Decimal(100000000), " 亿元") if abs(number) >= 100000000 else (
            (Decimal(10000), " 万元") if abs(number) >= 10000 else (Decimal(1), " 元"))
        number /= scale
    rendered = f"{number:,.2f}"
    if number and (abs(number) <= Decimal("0.005") or abs(number) >= Decimal("1e15")):
        rendered = f"{number:.3g}"
    else:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered + suffix


# Definitions describe what is measured, not unsupported company-specific causes.
RULES = {
    "total_assets": ("总资产", "公司账面上拥有或控制的资源，包括现金、厂房、设备和存货等。", "反映资产规模；其中并非都是能立即使用的现金，规模大也不代表盈利好。"),
    "total_liab": ("总负债", "公司账面上需要承担的各类偿付义务，包括借款、应付货款等。", "不等于全部都是银行借款；需要结合资产质量、偿付期限和现金情况理解。"),
    "revenue": ("营业收入", "公司在对应报告期间销售商品、提供服务等确认的收入。", "收入不等于利润，也不代表这些钱已经全部收到。"),
    "n_income": ("净利润", "对应报告期间，收入扣除相关成本、费用和税费等后的会计结果。", "利润与现金流不同；单期数值不能说明盈利能否持续。"),
    "n_income_attr_p": ("归母净利润", "对应报告期间的净利润中，归属于母公司股东的部分。", "不同于整个集团的净利润，也不等于已收到或可分配的现金。"),
    "n_cashflow_act": ("经营现金流净额", "对应报告期间，经营活动收到的现金减去付出的现金。", "还需查看回款、存货和应付等变化，才能解释原因；它与会计利润不同。"),
    "annualized_volatility": ("年化波动率", "衡量历史日涨跌幅的分散程度，再换算为统一的年化尺度，方便比较价格波动。", "不是预计年收益率、未来涨跌区间，也不代表最大可能亏损。"),
    "historical_var_95": ("历史单日收益第 5 百分位", "把样本中的单日涨跌幅从差到好排列，这个数是约处于最差百分之五位置的分界值。", "描述历史样本，不能当作未来发生概率、最大亏损或合理股价；插值和重复值会影响分界下方的实际样本数。"),
    "historical_es_95": ("历史尾部平均收益（ES）", "在这段历史样本中，取单日收益不高于第 5 百分位门槛的交易日，计算其平均涨跌幅。", "反映过去较差交易日的平均表现，不是未来亏损上限。"),
    "max_drawdown": ("历史区间最大回撤", "沿这段已观察到的价格路径，寻找从此前高点到后续低点的最大跌幅。", "只描述已保存窗口的历史经历；未来可能出现更大跌幅，缺失行情也可能遗漏低点。"),
    "atr_14": ("平均真实波幅 ATR(14)", "结合每日最高价、最低价和前一日收盘价，概括近期价格波动的幅度。", "单位是元/股，不是百分比；不能用它确定价格方向或合理价值。"),
    "beta": ("相对基准敏感度 Beta", "描述这段历史里，股票收益与所选市场基准收益共同变化的统计关系。", "结果依赖基准和样本；不代表相关关系在未来保持不变，也不代表全部风险。"),
    "price": ("股价", "这是保存时点市场成交价格的观察值。", "市场成交价不等于公司合理价值，也不是目标价。"),
    "pe_ttm": ("市盈率 PE-TTM", "用股价与最近十二个月的每股盈利作比较，展示市场为这份盈利支付的倍数。", "倍数低不自动代表便宜；亏损、盈利波动和一次性收益都会影响解读。"),
    "pb": ("市净率 PB", "用股价与对应每股净资产作比较，展示市场价格相对账面净资产的倍数。", "需要结合资产质量和盈利能力；账面净资产不等于资产变卖后能拿到的现金。"),
    "total_market_cap_yi": ("总市值", "按保存时点股价和股本口径计算的公司整体市场价值。", "这是市场定价规模，不是公司账上的现金或资产。"),
}


def _reading(name, value, unit, professional):
    label, definition, caution = RULES[name]
    interpretation = ""
    if name == "n_cashflow_act":
        number = Decimal(str(value))
        interpretation = ("这段期间，经营活动付出的现金多于收到的现金，表现为净流出。" if number < 0 else
                          "这段期间，经营活动收到的现金多于付出的现金，表现为净流入。" if number > 0 else
                          "这段期间，经营活动的现金流入和流出净额为零。")
    return IndicatorExplanation(label=label, value=display_number(value, unit),
        definition=definition, interpretation=interpretation, caution=caution, professional=professional,
        raw_value=str(value), raw_unit=unit)


def indicator_presentations(record):
    result = {}
    claims = {c.claim_id: c for c in record.claims}
    for metric in record.metrics:
        name = metric.metric_id.rsplit(".", 1)[-1]
        if name not in RULES:
            continue
        item = (_reading(name, metric.value, metric.unit, f"{metric.label} = {metric.value} {metric.unit}；方法：{metric.method}")
                if metric.availability == "available" and metric.value is not None else
                IndicatorExplanation(label=RULES[name][0], value="暂不可用", definition=RULES[name][1],
                    caution="本次没有可用数值，不能估算或视为零。", professional=metric.unavailable_reason or "未取得"))
        item = item.model_copy(update={"scope": f"统计窗口 {metric.window_start or '未保存'} 至 {metric.window_end or '未保存'} · 有效样本 {metric.sample_size if metric.sample_size is not None else '未保存'}"})
        result["metric:" + metric.metric_id] = item
        for claim in record.claims:
            if (claim.kind == "fact" and "source_field:computed_statistics:" + metric.metric_id in claim.limitations
                    and set(claim.evidence_ids) == set(metric.input_evidence_ids)):
                result["claim:" + claim.claim_id] = item.model_copy(update={"professional": claim.statement})
    # The numeric catalog qualifies selectors, units, source identity and periods.
    from tradingagents.research.numeric_catalog import build_numeric_catalog
    catalog = build_numeric_catalog(record, source_only=True)
    grouped = {}
    aliases = {"parent_net_income": "n_income_attr_p", "consolidated_net_income": "n_income", "cfo": "n_cashflow_act", "last_close": "price"}
    for anchor in catalog["anchors"]:
        key = anchor["definition_key"]
        parts = key.split(".")
        if parts[0] not in {"financial", "official", "snapshot", "price"}:
            continue
        if parts[0] == "official" and (len(parts) != 4 or parts[-1] != "current" or parts[1] != "financial"):
            continue
        name = parts[-2] if parts[0] == "official" else parts[-1]
        name = aliases.get(name, name)
        if name not in RULES:
            continue
        for cid in anchor["required_fact_ids"]:
            if cid in claims:
                item = _reading(name, anchor["value"], anchor["unit"], claims[cid].statement)
                period = anchor["metadata"].get("report_period")
                as_of = anchor["metadata"].get("as_of") or anchor["metadata"].get("quote_timestamp")
                scope = f"报告期 {period} · 合并口径" if period else f"行情观察时点 {as_of}" if as_of else ""
                grouped.setdefault(cid, []).append(item.model_copy(update={"scope": scope}))
    for cid, items in grouped.items():
        quote_order = {RULES[k][0]: i for i, k in enumerate(("price", "pe_ttm", "pb", "total_market_cap_yi"))}
        items.sort(key=lambda item: quote_order.get(item.label, 10))
        first = items[0]
        if len(items) > 1:
            first = IndicatorExplanation(label="行情与估值快照", value="；".join(f"{i.label} {i.value}" for i in items),
                definition=" ".join(i.definition for i in items), caution=" ".join(i.caution for i in items), professional=claims[cid].statement, scope=items[0].scope)
        result["claim:" + cid] = first
    if record.evidence_checks:
        for check in record.evidence_checks.checks:
            for obs in check.observations:
                result[f"check:{check.check_id}:{obs.key}"] = IndicatorExplanation(label=obs.label,
                    value=display_number(obs.value, obs.unit), definition="此数值用于核对所列具体问题。",
                    caution="核对通过仍不能证明经营原因、增长持续性或合理价值。", professional=f"{obs.value} {obs.unit}；{obs.method}")
    return result


def explanation_targets(record, indicators, focus=None):
    """Stable, whole targets, with each target's own dependency closure."""
    targets = {}
    claim_states = {}
    if record.dialogue:
        for response in record.dialogue.responses:
            h = next((h for h in record.hypotheses if h.hypothesis_id == response.hypothesis_id), None)
            if h and response.disposition in {"withdrawn", "revised"}:
                claim_states[h.claim_id] = response.disposition
    claims = {c.claim_id: c for c in record.claims}

    def add(key, text, ids=(), evidence=()):
        if not text or key in indicators or key in targets:
            return
        dependencies, pending = {}, list(ids)
        while pending:
            cid = pending.pop()
            claim = claims.get(cid)
            if claim and cid not in dependencies:
                dependencies[cid] = {**claim.model_dump(mode="json"), "research_disposition": claim_states.get(cid, "original")}
                pending.extend(claim.supporting_fact_ids)
        refs = sorted(set(dependencies) | set(evidence) | {eid for c in dependencies.values() for eid in c["evidence_ids"]})
        targets[key] = {"target": key, "text": text, "text_sha256": text_hash(text),
                        "references": refs, "facts": list(dependencies.values())}

    a = record.assessment
    if a:
        add("assessment:judgement", a.judgement, a.key_claim_ids)
        for field in ("supporting_arguments", "opposing_arguments"):
            for i, item in enumerate(getattr(a, field, ())):
                add(f"assessment:{field}:{i}", item.rationale, item.claim_ids)
        for i, item in enumerate(getattr(a, "change_conditions", ())):
            h = next((h for h in record.hypotheses if h.hypothesis_id == item.hypothesis_id), None)
            add(f"assessment:change_conditions:{i}", item.text, (h.claim_id,) if h else ())
        for d in a.dimensions:
            add("dimension:" + d.dimension, d.judgement, d.claim_ids)
        add("assessment:next_check", a.next_check, a.key_claim_ids)
        for cid in a.key_claim_ids:
            if cid in claims:
                add("claim:" + cid, claims[cid].statement, (cid,))
    for challenge in record.challenges:
        add("challenge:" + challenge.challenge_id, challenge.statement, challenge.target_claim_ids)
        add("test:" + challenge.challenge_id, challenge.proposed_test, challenge.target_claim_ids)
    if record.dialogue:
        for r in record.dialogue.responses:
            add("reply:" + r.response_id, r.rationale, r.supporting_fact_ids)
        for item in getattr(a, "adjudications", ()):
            challenge = next((c for c in record.challenges if c.challenge_id == item.challenge_id), None)
            add("adjudication:" + item.response_id, item.rationale, challenge.target_claim_ids if challenge else ())
    if record.valuation:
        verdict = record.valuation.assessment.verdict
        add("valuation:reasoning", "\n".join((verdict.overall_label_zh, *verdict.fact_notes_zh)),
            evidence=record.valuation.input_evidence_ids)
    if focus and focus.proposal:
        add("focus:answer", focus.proposal.answer, focus.proposal.claim_ids, focus.proposal.evidence_ids)
    for c in record.claims:
        add("claim:" + c.claim_id, c.statement, (c.claim_id,))
    admitted, excluded, size = {}, {}, 0
    for key, target in targets.items():
        length = len(json.dumps(target, ensure_ascii=False))
        if len(admitted) >= 32 or size + length > 32000:
            excluded[key] = "capacity_limited"
        else:
            admitted[key] = target
            size += length
    return admitted, excluded


def validate_explanation_entry(entry, target):
    from tradingagents.research.numeric_narrative import _scan_literal
    if entry.target != target["target"] or not set(entry.references) <= set(target["references"]):
        raise ValueError("explanation reference invalid")
    _scan_literal(entry.explanation, "explanation")
    _scan_literal(entry.uncertainty, "uncertainty")
