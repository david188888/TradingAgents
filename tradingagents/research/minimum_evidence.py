"""Frozen source admission and repeatable minimum-evidence checks. No I/O."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas._evidence_checks import (
    ChallengeAssessmentV2,
    CheckObservationV1,
    DatedForecastV1,
    EvidenceChecksV1,
    LocalEvidenceCheckV1,
    OfficialNumericRowV1,
    PeerQuoteV1,
    PeerSelectionV1,
)
from tradingagents.agents.schemas._research_record import SourceContentV1, SourceEvidenceV1
from tradingagents.agents.schemas._verification_plan import FinancialOperandV1, canonical_sha256
from tradingagents.dataflows.disclosure_documents import pdf_url
from tradingagents.dataflows.disclosure_documents_v2 import NUMERIC_SOURCE, SCALES, title_info
from tradingagents.dataflows.supplemental_valuation import (
    CAP_FORECAST,
    CAP_PEERS,
    FORECAST_SOURCES,
    PEER_SOURCES,
)
from tradingagents.dataflows.ticker_utils import to_tushare_symbol
from tradingagents.research.evidence_freeze import CapabilityStatus
from tradingagents.research.source_families import FINANCIAL_SOURCES, IDENTITY_SOURCES
from tradingagents.research.verification_tools import _financial_operand, _Unavailable

NEW_SOURCES = frozenset({NUMERIC_SOURCE}) | FORECAST_SOURCES | PEER_SOURCES
SUPPLEMENTAL_VALUATION_SOURCES = FORECAST_SOURCES | PEER_SOURCES
QUESTIONS = {
    "operating_disclosures": ("operating_disclosures.current_period_coverage", "当前报告期的经营判断是否有正式财务与定量运营披露支撑？"),
    "cash_conversion": ("cash_conversion.reported_bridge", "当前及上年同期间的净利润到经营现金流桥是否完整、可核对？"),
    "valuation_context": ("valuation_context.supplementary_positioning", "当前估值定位是否有同日同行样本或带日期的机构预测作为补充？"),
}


def qualify_payload(name, payload, *, ticker, cutoff, published, captured, public_url=None):
    """Reused at collection admission and saved-record validation."""
    ts_code = to_tushare_symbol(ticker)
    if captured is None or captured.tzinfo is None or captured.astimezone(ZoneInfo("Asia/Shanghai")).date() != cutoff:
        raise ValueError("supplemental historical vintage unverified")
    if name == NUMERIC_SOURCE:
        info = title_info(payload["title"])
        numeric = OfficialNumericRowV1.model_validate(payload["row"])
        count = payload["page_count"]
        if (payload["ts_code"] != ts_code or payload["parser_version"] != "official-pdf-v2"
                or payload["body_coverage"] != "partial" or not info or info["period"] != payload["report_period"]
                or numeric.period.isoformat() != payload["report_period"] or numeric.period > cutoff
                or published is None or date.fromisoformat(payload["published"]) != published.date()
                or numeric.period > published.date() or isinstance(count, bool) or not isinstance(count, int)
                or not numeric.page <= count <= 500 or not re.fullmatch(r"[a-f0-9]{64}", payload["pdf_sha256"])):
            raise ValueError("official numeric row identity/metadata invalid")
        url = pdf_url({"PDF URL": payload["url"], "Announcement ID": payload["document_id"]})
        if public_url and public_url != url:
            raise ValueError("official numeric URL differs from attachment")
        return numeric
    if name in FORECAST_SOURCES:
        forecast = DatedForecastV1.model_validate(payload)
        if (forecast.ts_code != ts_code or not cutoff-timedelta(days=180) <= forecast.published <= cutoff
                or forecast.forecast_year not in range(cutoff.year, cutoff.year+3)
                or published is None or published.date() != forecast.published):
            raise ValueError("forecast identity/date/year invalid")
        return forecast
    if name == "eastmoney.peer_candidates":
        selection = PeerSelectionV1.model_validate(payload)
        if selection.target_ts_code != ts_code or any(c.financial_period and c.financial_period > cutoff for c in selection.candidates):
            raise ValueError("peer selection identity/date invalid")
        return selection
    if name == "tencent.peer_valuation":
        quote = PeerQuoteV1.model_validate(payload)
        if quote.target_ts_code != ts_code or quote.as_of > cutoff or published is None or quote.as_of != published.date():
            raise ValueError("peer quote identity/date invalid")
        return quote
    raise ValueError("unknown supplemental source")


def source_record(item, draft, payload):
    limitation = []
    capability_name = "operating_detail" if item.source_name == NUMERIC_SOURCE else CAP_FORECAST if item.source_name in FORECAST_SOURCES else CAP_PEERS
    capability = draft.capability(capability_name)
    availability, content, family = "available", None, item.source_family_id
    try:
        if item.capability != capability_name or capability is None or capability.status not in {CapabilityStatus.QUALIFIED, CapabilityStatus.PARTIAL}:
            raise ValueError("supplemental capability unqualified")
        cutoff = date.fromisoformat(draft.cutoff)
        if item.usable_as_of is None or item.usable_as_of.tzinfo is None or item.usable_as_of.astimezone(ZoneInfo("Asia/Shanghai")).date() > cutoff:
            raise ValueError("supplemental point in time invalid")
        parsed = qualify_payload(item.source_name, payload, ticker=draft.ticker, cutoff=cutoff,
            published=item.published_at, captured=item.captured_at, public_url=item.public_url)
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(text) > 4000:
            raise ValueError("supplemental public content exceeds limit")
        if item.source_name == NUMERIC_SOURCE:
            label = f"{payload['title'][:60]} · PDF 第 {parsed.page} 页 · {parsed.raw_unit} · SHA256 {payload['pdf_sha256']}"
            family = f"cninfo.disclosure:{payload['ts_code']}:{payload['report_period']}"
            limitation.extend(("company_disclosure_not_independent_delivery_verification", "selected_document_content_not_all_disclosures"))
        elif item.source_name in FORECAST_SOURCES:
            label = f"{parsed.institution} · {parsed.published} · {parsed.forecast_year}年 EPS预测"
            institution_key = re.sub(r"\s", "", parsed.institution)
            family = f"analyst:{institution_key}:{parsed.published}"
            limitation.extend(("institution_forecast_not_reported_earnings", "sample_not_complete_consensus"))
        else:
            label = "行业候选样本；财务期间不是报价时间" if item.source_name == "eastmoney.peer_candidates" else f"{parsed.name} · {parsed.quote_timestamp.isoformat()} · PE/PB"
            limitation.extend(("industry_candidates_not_business_equivalence", "selected_peers_not_full_industry_population"))
        content = SourceContentV1(kind="source_fields", text=text, locator_label=label[:200], content_sha256=hashlib.sha256(text.encode()).hexdigest())
    except (ValueError, KeyError, TypeError, AttributeError):
        availability = "unavailable"
        limitation.append("supplemental_fields_unqualified")
    return SourceEvidenceV1(evidence_id=item.evidence_id, source_name=item.source_name,
        source_kind="official" if item.source_name == NUMERIC_SOURCE else "vendor", source_family_id=family,
        availability=availability, content=content, public_url=item.public_url,
        published_at=item.published_at, usable_as_of=item.usable_as_of, captured_at=item.captured_at,
        limitations=tuple(dict.fromkeys(limitation)))


def fact_statement(name, payload):
    if name == NUMERIC_SOURCE:
        row = OfficialNumericRowV1.model_validate(payload["row"])
        return "operating_quality", f"official.{row.kind}.{row.field}.{row.page}.{row.frequency}", (
            f"公司披露 {row.period}（{row.frequency}）{row.label}：本期 {row.current if row.current is not None else '未披露'}，"
            f"上年同期间 {row.previous if row.previous is not None else '未披露'} {row.unit}；PDF 第 {row.page} 页，原表单位 {row.raw_unit}。")
    if name in FORECAST_SOURCES:
        row = DatedForecastV1.model_validate(payload)
        return "valuation", "dated_forecast", f"{row.institution} 于 {row.published} 预测 {row.forecast_year} 年 EPS {row.eps} 元/股；这是机构预测，不是已实现盈利。"
    if name == "tencent.peer_valuation":
        row = PeerQuoteV1.model_validate(payload)
        return "valuation", "peer_quote", f"行业候选 {row.name}（{row.ts_code}）{row.as_of} PE-TTM {row.pe_ttm} 倍、PB {row.pb} 倍；同日样本不保证业务可比性。"
    row = PeerSelectionV1.model_validate(payload)
    return "valuation", "peer_candidates", f"供应商返回 {len(row.candidates)} 家行业候选公司；报告的行业总体数量 {row.reported_population}，这是选取样本。"


def _frozen_sources(record):
    ids = set(record.snapshots[0].evidence_ids)
    return [e for e in record.evidence if e.evidence_id in ids]


def _identity_qualified(record):
    identities = [s for s in _frozen_sources(record) if s.source_name in IDENTITY_SOURCES and s.availability == "available" and s.content is not None]
    if len(identities) != 1 or "security_identity_unqualified" in record.limitations:
        return False
    try:
        payload = json.loads(identities[0].content.text)
        listed = str(payload["list_date"])
        listed = listed if "-" in listed else listed[:4]+"-"+listed[4:6]+"-"+listed[6:8]
        return payload["ts_code"] == to_tushare_symbol(record.ticker) and date.fromisoformat(listed) <= record.analysis_date
    except (ValueError, KeyError, TypeError):
        return False


def _rows(record):
    result = []
    for source in _frozen_sources(record):
        if source.source_name != NUMERIC_SOURCE or source.availability != "available" or source.content is None:
            continue
        payload = json.loads(source.content.text)
        row = qualify_payload(source.source_name, payload, ticker=record.ticker, cutoff=record.analysis_date,
            published=source.published_at, captured=source.captured_at, public_url=source.public_url)
        result.append((source, payload, row))
    return result


def _check(check_id, *, status, satisfied=(), missing=(), sources=(), observations=(), limitations=()):
    scope, question = QUESTIONS[check_id]
    return LocalEvidenceCheckV1(check_id=check_id, question_scope=scope, question=question, status=status,
        satisfied=tuple(sorted(set(satisfied))), missing=tuple(sorted(set(missing))),
        evidence_ids=tuple(sorted(set(sources))), observations=tuple(observations), limitations=tuple(dict.fromkeys(limitations)))


def _official_pairs(rows, period):
    pairs, conflicts = {}, []
    for source, payload, row in rows:
        if row.kind != "financial" or row.period != period or row.current is None or row.previous is None:
            continue
        if row.field in pairs and (pairs[row.field][2].current, pairs[row.field][2].previous) != (row.current, row.previous):
            conflicts.append("official_financial_conflict:"+row.field)
        pairs.setdefault(row.field, (source, payload, row))
    return pairs, conflicts


def _precision(row, attribute):
    raw = getattr(row, "raw_"+attribute)
    return SCALES[row.raw_unit] * Decimal(1).scaleb(Decimal(raw.replace(",", "")).as_tuple().exponent)


def _operating(record, rows, period):
    if period is None:
        return _check("operating_disclosures", status="unavailable", missing=("official_current_period",))
    pairs, conflicts = _official_pairs(rows, period)
    required = {"revenue", "parent_net_income", "cfo"}
    missing = ["official_pair:"+field for field in sorted(required-pairs.keys())]
    satisfied = ["official_pair:"+field for field in sorted(required & pairs.keys())]
    sources = [pairs[field][0].evidence_id for field in sorted(required & pairs.keys())]
    operating = [(s, r) for s, _, r in rows if r.kind == "operating" and r.frequency != "Q2" and r.period == period and r.current is not None]
    if operating:
        satisfied.append("quantitative_operating_disclosure")
        sources.extend(s.evidence_id for s, _ in operating)
    else:
        missing.append("quantitative_operating_disclosure")
    mapping = {"revenue": ("income", "revenue"), "parent_net_income": ("income", "n_income_attr_p"), "cfo": ("cashflow", "n_cashflow_act")}
    comparisons = 0
    for source in _frozen_sources(record):
        if source.source_name not in FINANCIAL_SOURCES or source.availability != "available":
            continue
        for field in required & pairs.keys():
            row = pairs[field][2]
            for attribute, day in (("current", row.period), ("previous", row.prior_period)):
                try:
                    value, _ = _financial_operand(record, FinancialOperandV1(evidence_id=source.evidence_id,
                        table=mapping[field][0], field=mapping[field][1], report_period=day.isoformat()))
                except _Unavailable:
                    continue
                comparisons += 1
                sources.append(source.evidence_id)
                if abs(value-Decimal(getattr(row, attribute))) > _precision(row, attribute)/2:
                    conflicts.append("supplier_financial_discrepancy:"+field+":"+day.isoformat())
    limits = ["selected_disclosure_coverage_not_complete_business_verification"]
    if comparisons:
        satisfied.append("supplier_same_period_crosscheck")
    else:
        limits.append("single_disclosure_family_no_supplier_crosscheck")
    observations = []
    for field in sorted(required & pairs.keys()):
        source, _, row = pairs[field]
        for attribute, day in (("current", row.period), ("previous", row.prior_period)):
            observations.append(_obs(field+"_"+attribute, str(day)+" "+row.label, Decimal(getattr(row, attribute)), row.unit,
                f"官方披露第{row.page}页；原表{row.raw_unit}，保留同期间口径。", [source.evidence_id]))
    for source, row in operating:
        for attribute, day in (("current", row.period), ("previous", row.prior_period)):
            if getattr(row, attribute) is not None:
                observations.append(_obs(row.field+"_"+attribute, str(day)+" "+row.label, Decimal(getattr(row, attribute)), row.unit,
                    f"官方运营公告第{row.page}页；半年累计，保留原表物理单位。", [source.evidence_id]))
    return _check("operating_disclosures", status="conflict" if conflicts else "unavailable" if missing else "passed",
        satisfied=satisfied, missing=(*missing, *conflicts), sources=sources, observations=observations, limitations=limits)


def _obs(key, label, value, unit, method, sources):
    return CheckObservationV1(key=key, label=label, value=str(value), unit=unit, method=method, evidence_ids=tuple(sorted(set(sources))))


def _cash(record, rows, period):
    if period is None:
        return _check("cash_conversion", status="unavailable", missing=("official_current_period",))
    pairs, conflicts = _official_pairs(rows, period)
    required = {"consolidated_net_income", "cfo"}
    missing = ["official_pair:"+field for field in sorted(required-pairs.keys())]
    groups = {}
    for source, payload, row in rows:
        if row.kind == "cash_bridge" and row.period == period:
            groups.setdefault(payload["document_id"], []).append((source, row))
    observations, ids, satisfied = [], [], []
    for document_id, items in sorted(groups.items()):
        fields = {r.field: (s, r) for s, r in items}
        needed = {"net_income", "cfo", "inventory", "operating_receivables", "operating_payables"}
        if len(fields) != len(items) or not needed <= fields.keys() or any(r.current is None or r.previous is None for _, r in (fields[k] for k in needed & fields.keys())):
            missing.append("cash_bridge_required_cells_or_duplicates:"+document_id)
            continue
        ids = [s.evidence_id for s, _ in items]
        residuals, tolerances = [], []
        for attribute in ("current", "previous"):
            components = [r for _, r in items if r.field != "cfo" and getattr(r, attribute) is not None]
            residual = sum((Decimal(getattr(r, attribute)) for r in components), Decimal(0))-Decimal(getattr(fields["cfo"][1], attribute))
            tolerance = min(_precision(r, attribute) for r in components)/2*(len(components)+1)
            residuals.append(residual)
            tolerances.append(tolerance)
            if abs(residual) > tolerance:
                conflicts.append("cash_bridge_reconciliation:"+attribute)
            for field, bridge_field in (("consolidated_net_income", "net_income"), ("cfo", "cfo")):
                if field in pairs:
                    official = pairs[field][2]
                    if abs(Decimal(getattr(official, attribute))-Decimal(getattr(fields[bridge_field][1], attribute))) > _precision(official, attribute)/2:
                        conflicts.append("cash_bridge_endpoint_discrepancy:"+field+":"+attribute)
        for index, attribute in enumerate(("current", "previous")):
            observations.append(_obs("bridge_residual_"+attribute, "现金流桥核对差额（"+("本期" if index == 0 else "上年同期")+"）", residuals[index], "CNY",
                f"已披露数字组件之和减CFO；允许舍入差额 {tolerances[index]} CNY，空白单元格保留未披露。", ids))
        changes = {r.field: Decimal(r.current)-Decimal(r.previous) for _, r in items if r.current is not None and r.previous is not None}
        for field, label in (("cfo", "经营现金流同比变化"), ("inventory", "存货调整同比贡献"), ("operating_receivables", "经营性应收调整同比贡献"), ("operating_payables", "经营性应付调整同比贡献"), ("investment_loss", "投资损益调整同比贡献"), ("fair_value_loss", "公允价值调整同比贡献")):
            if field in changes:
                observations.append(_obs(field+"_change", label, changes[field], "CNY", "本期披露的调整额减上年同期间调整额；会计桥贡献不等于经济因果。", ids))
        observations.append(_obs("working_capital_change", "三项营运资金调整同比贡献", sum(changes[k] for k in ("inventory", "operating_receivables", "operating_payables")), "CNY", "存货、经营性应收及经营性应付调整的同比变化之和。", ids))
        satisfied.append("complete_adjacent_page_reported_bridge")
        break
    if not satisfied:
        missing.append("complete_reconciled_cash_bridge")
    ids.extend(pairs[k][0].evidence_id for k in sorted(required & pairs.keys()))
    return _check("cash_conversion", status="conflict" if conflicts else "unavailable" if missing else "passed",
        satisfied=satisfied, missing=(*missing, *conflicts), sources=ids, observations=observations,
        limitations=("reported_accounting_bridge_not_economic_causation", "two_periods_not_structural_persistence", "blank_cells_remain_undisclosed"))


def _valuation(record):
    target, selection, forecasts, peers = None, None, [], []
    for source in _frozen_sources(record):
        if source.availability != "available" or source.content is None:
            continue
        if source.source_name == "tencent.valuation_snapshot":
            target = (source, json.loads(source.content.text))
        elif source.source_name in SUPPLEMENTAL_VALUATION_SOURCES:
            parsed = qualify_payload(source.source_name, json.loads(source.content.text), ticker=record.ticker,
                cutoff=record.analysis_date, published=source.published_at, captured=source.captured_at, public_url=source.public_url)
            if source.source_name in FORECAST_SOURCES:
                forecasts.append((source, parsed))
            elif source.source_name == "eastmoney.peer_candidates":
                selection = (source, parsed)
            else:
                peers.append((source, parsed))
    if target is None:
        return _check("valuation_context", status="unavailable", missing=("qualified_target_snapshot",), limitations=("historical_positioning_can_still_be_described",))
    sources, satisfied, missing = [target[0].evidence_id], ["qualified_target_snapshot"], []
    eligible = []
    if selection:
        codes = {c.ts_code for c in selection[1].candidates}
        names = {c.ts_code: c.name for c in selection[1].candidates}
        eligible = [(s, q) for s, q in peers if q.ts_code in codes and q.name == names[q.ts_code] and q.as_of.isoformat() == target[1]["as_of"] and q.pe_ttm is not None and q.pb is not None]
    # A duplicate wrapper/quote never increases sample size.
    unique_peers = {q.ts_code: (s, q) for s, q in eligible}
    observations = []
    if len(unique_peers) >= 3:
        satisfied.append("same_session_peers_at_least_three")
        sources.append(selection[0].evidence_id)
        sources.extend(s.evidence_id for s, _ in unique_peers.values())
        for key, label in (("pe_ttm", "行业候选 PE-TTM 中位数"), ("pb", "行业候选 PB 中位数")):
            values = sorted(Decimal(str(getattr(q, key))) for _, q in unique_peers.values())
            median = values[len(values)//2] if len(values)%2 else (values[len(values)//2-1]+values[len(values)//2])/2
            observations.append(_obs("peer_"+key+"_median", label, median, "倍", f"同日 {len(values)} 家选取样本的中位数；不代表全行业或业务可比性。", sources))
    else:
        missing.append("peers_fewer_than_three")
    latest = {}
    for source, row in sorted(forecasts, key=lambda pair: (pair[1].published, pair[1].report_id), reverse=True):
        latest.setdefault((re.sub(r"\s", "", row.institution), row.forecast_year), (source, row))
    if len({key[0] for key in latest}) > 8:
        raise ValueError("frozen forecast institution limit exceeded")
    if latest:
        satisfied.append("dated_institution_forecast")
        for year in sorted({row.forecast_year for _, row in latest.values()}):
            items = [(s, r) for s, r in latest.values() if r.forecast_year == year]
            refs = [s.evidence_id for s, _ in items]
            sources.extend(refs)
            eps = sorted(Decimal(row.eps) for _, row in items)
            if len(items) >= 3:
                observations.append(_obs("forecast_eps_mean_"+str(year), f"{year}年选取机构 EPS 均值", sum(eps)/len(eps), "CNY/share", f"{len(items)} 家去重机构，范围 {eps[0]}–{eps[-1]}；选取样本，不是完整一致预期。", refs))
            else:
                for source, row in items:
                    observations.append(_obs("forecast_eps_"+str(year)+"_"+row.report_id, f"{row.institution} {year}年 EPS 情景", row.eps, "CNY/share", f"个别机构预测，报告日期 {row.published}；不可标为一致预期。", [source.evidence_id]))
    else:
        missing.append("dated_institution_forecast_unavailable")
    passed = "dated_institution_forecast" in satisfied or "same_session_peers_at_least_three" in satisfied
    return _check("valuation_context", status="passed" if passed else "unavailable", satisfied=satisfied,
        missing=missing, sources=sources, observations=observations,
        limitations=("supplementary_positioning_not_fair_value_proof", "industry_candidates_not_business_equivalence", "sample_not_complete_population_or_consensus", *missing))


def compute_checks(record):
    rows = _rows(record)
    periods = [r.period for _, _, r in rows if r.frequency != "Q2" and r.period <= record.analysis_date]
    period = max(periods) if periods else None
    frozen = _frozen_sources(record)
    inputs = {"run_id": record.run_id, "ticker": record.ticker, "analysis_date": record.analysis_date.isoformat(),
              "snapshot": record.snapshots[0].snapshot_id, "sources": [s.model_dump(mode="json") for s in frozen]}
    checks = (_operating(record, rows, period), _cash(record, rows, period), _valuation(record)) if _identity_qualified(record) else tuple(
        _check(key, status="unavailable", missing=("security_identity_unqualified",)) for key in QUESTIONS)
    return EvidenceChecksV1(run_id=record.run_id, ticker=record.ticker, analysis_date=record.analysis_date,
        input_snapshot_id=record.snapshots[0].snapshot_id, input_evidence_ids=tuple(s.evidence_id for s in frozen), input_sha256=canonical_sha256(inputs),
        checks=checks)


def cfo_decline(record):
    if not _identity_qualified(record):
        return None
    rows = _rows(record)
    periods = [r.period for _, _, r in rows if r.kind == "financial" and r.field == "cfo" and r.frequency != "Q2"]
    if not periods:
        return None
    pairs, conflicts = _official_pairs(rows, max(periods))
    if conflicts or "cfo" not in pairs:
        return None
    source, _, row = pairs["cfo"]
    base = Decimal(row.previous)
    if base <= 0:
        return None
    growth = (Decimal(row.current)/base-1)*100
    return _obs("cfo_yoy_percent", "报告期经营现金流同比变化", growth, "%", f"{row.period}对{row.prior_period}：本期CFO÷正基期CFO−1。仅证明报告数值变化。", [source.evidence_id])


def challenge_assessments(record):
    checks = {check.check_id: check for check in record.evidence_checks.checks}
    risk = cfo_decline(record)
    output = []
    for binding in record.challenge_bindings or ():
        check = checks.get(binding.check_id)
        scope, question = QUESTIONS[binding.check_id] if binding.check_id else (None, None)
        observations = check.observations if check else ()
        evidence = check.evidence_ids if check else ()
        limits = (*check.limitations, *check.missing) if check else ("economic_question_exceeds_closed_check_scope",)
        outcome, rationale = "unresolved", "所需证据不足或问题超出已执行检查的范围；经济判断仍未解决。"
        if binding.observation_date and binding.observation_date > record.analysis_date:
            outcome, rationale = "future_observation", "该观察日期在研究截止日之后；保留后续观察，不替代当前证据核查。"
        elif binding.observed_risk:
            if risk is not None and Decimal(risk.value) < 0:
                outcome, rationale = "risk_supported", "已核对的同期间合并经营现金流同比下降；其原因及持续性仍未解决。"
                observations, evidence = (risk,), risk.evidence_ids
            else:
                rationale = "缺少合格正基期CFO，或数据不支持所选的经营现金流下降条件。"
        elif check and check.status == "passed":
            outcome, rationale = "evidence_sufficient", "此处仅回答代码定义的证据问题；不证明经济原因、持续性或整体假设。"
        output.append(ChallengeAssessmentV2(challenge_id=binding.challenge_id, outcome=outcome,
            question_scope=scope, answered_question=question, check_id=binding.check_id, rationale=rationale,
            evidence_ids=evidence, observed_risk=binding.observed_risk, observation_date=binding.observation_date,
            observations=observations, limitations=tuple(dict.fromkeys((*limits, "economic_parent_remains_unresolved")))))
    return tuple(output)
