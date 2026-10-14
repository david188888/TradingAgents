"""Pure numeric catalog construction and rendering over frozen public records.

Only code-owned source selectors are admitted. Prose, source titles and saved
financial checks do not supply a back door for creating quantities. This module
does not validate the record model again: its caller owns that boundary, and a
record validator may itself call ``validate_numeric_catalog``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from tradingagents.agents.schemas._numeric_narrative import (
    NUMERIC_CATALOG_LIMIT,
    NumericAnchorV1,
    NumericCatalogV1,
    NumericMetadataV1,
)
from tradingagents.agents.schemas._verification_plan import (
    FINANCIAL_FIELDS,
    FinancialOperandV1,
    canonical_sha256,
)
from tradingagents.research.company_basics import FINANCIAL_LABELS
from tradingagents.research.minimum_evidence import (
    FORECAST_SOURCES,
    NUMERIC_SOURCE,
    qualify_payload,
)
from tradingagents.research.source_families import (
    FINANCIAL_SOURCES,
    OPERATING_SOURCES,
    PRICE_SOURCES,
)
from tradingagents.research.verification_tools import (
    _financial_operand,
    _number,
    _qualified_source,
    _Unavailable,
)

CATALOG_VERSION = "numeric-catalog-v1"
OFFICIAL_ARITHMETIC_VERSION = "numeric-official-arithmetic-v1"
_BASIS_LABELS = {
    "actual_reported": "实际披露",
    "observed_quote": "行情观察",
    "institution_forecast": "机构预测，非已实现",
    "computed_statistic": "代码计算",
    "accounting_check": "会计核查，不证明经济因果",
    "valuation_reference": "假设参考，非内在价值",
}
_OFFICIAL_LABELS = {
    "parent_net_income": "归母净利润", "consolidated_net_income": "合并净利润",
    "cfo": "经营现金流净额", "revenue": "营业收入",
}
_QUOTE_FIELDS = {
    "price": ("股价", "CNY/share"), "pe_ttm": ("PE-TTM", "multiple"),
    "pb": ("PB", "multiple"), "total_market_cap_yi": ("总市值", "CNY_YI"),
}


class _CatalogLimit(Exception):
    pass


class _Builder:
    def __init__(self, record):
        self.record = record
        self.snapshot = record.snapshots[0].snapshot_id
        self.anchors = {}
        self.metadata = {}
        self.source_facts = defaultdict(list)
        self.facts = {}
        for fact in record.claims:
            if fact.kind == "fact":
                self.facts[fact.claim_id] = fact
                for eid in fact.evidence_ids:
                    self.source_facts[eid].append(fact)

    def _limit(self):
        if len(self.anchors) + len(self.metadata) > NUMERIC_CATALOG_LIMIT:
            raise _CatalogLimit

    def meta(self, kind, text, fact_ids=(), evidence_ids=()):
        identity = {"version": CATALOG_VERSION, "snapshot": self.snapshot, "kind": kind,
                    "text": text, "facts": sorted(fact_ids), "evidence": sorted(evidence_ids)}
        mid = "meta." + canonical_sha256(identity)
        self.metadata[mid] = NumericMetadataV1(meta_id=mid, kind=kind, text=text,
            required_fact_ids=tuple(sorted(set(fact_ids))), input_evidence_ids=tuple(sorted(set(evidence_ids))))
        self._limit()

    def add(self, *, definition, label, value, unit, facts, sources, lineage,
            metadata=None, basis="actual_reported", subject=None, limitations=()):
        if value is None or not facts or not sources:
            return None
        number = _number(value)
        identity = {"version": CATALOG_VERSION, "snapshot": self.snapshot,
                    "definition": definition, "subject": subject or self.record.ticker,
                    "basis": basis, "lineage": lineage}
        aid = "num." + canonical_sha256(identity)
        anchor = NumericAnchorV1(anchor_id=aid, definition_key=definition, label=label,
            subject=subject or self.record.ticker, basis=basis, value=str(number), unit=unit,
            required_fact_ids=tuple(sorted(set(facts))), input_evidence_ids=tuple(sorted(set(sources))),
            snapshot_id=self.snapshot, metadata=metadata or {}, lineage=lineage,
            limitations=tuple(sorted(set(limitations))))
        if aid in self.anchors and self.anchors[aid] != anchor:
            raise ValueError("numeric anchor identity collision")
        self.anchors[aid] = anchor
        self._limit()
        return anchor

    def matching(self, source_id, locator):
        return tuple(sorted(f.claim_id for f in self.source_facts[source_id]
                            if "source_field:" + locator in f.limitations))

    def all_facts(self, source_ids):
        return tuple(sorted({f.claim_id for sid in source_ids for f in self.source_facts[sid]}))


def _source_lineage(source, **selector):
    return {"kind": "source", "source_name": source.source_name,
            "source_family_id": source.source_family_id or source.evidence_id,
            "source_content_sha256": source.content.content_sha256,
            "source_selector": selector}


def _qualified_payload(record, source):
    _qualified_source(record, source.evidence_id)
    if source.content is None or source.content.truncated or source.content.kind != "source_fields":
        raise _Unavailable("content_unusable")
    payload = json.loads(source.content.text)
    if not isinstance(payload, dict):
        raise _Unavailable("content_unusable")
    return payload


def _financial(builder, source, payload):
    for table, fields in FINANCIAL_FIELDS.items():
        for row in payload.get(table, []):
            raw_period = row.get("end_date", "")
            period = raw_period if "-" in raw_period else raw_period[:4] + "-" + raw_period[4:6] + "-" + raw_period[6:]
            for field in sorted(fields & row.keys()):
                facts = builder.matching(source.evidence_id, f"{table}[end_date={period}].{field}")
                if not facts:
                    continue
                try:
                    value, operand = _financial_operand(builder.record, FinancialOperandV1(
                        evidence_id=source.evidence_id, table=table, field=field, report_period=period))
                except _Unavailable:
                    continue
                builder.add(definition=f"financial.{table}.{field}", label=FINANCIAL_LABELS[field],
                    value=value, unit="CNY", facts=facts, sources=[source.evidence_id],
                    metadata={"report_period": period, "source_basis": "合并报表，期间长度未另行认定"},
                    lineage=_source_lineage(source, table=table, field=field, report_period=period),
                    limitations=source.limitations)
                builder.meta("period", "报告期：" + operand["report_period"], facts, [source.evidence_id])


def _official(builder, source, payload):
    row = qualify_payload(source.source_name, payload, ticker=builder.record.ticker,
        cutoff=builder.record.analysis_date, published=source.published_at,
        captured=source.captured_at, public_url=source.public_url)
    locator = f"official.{row.kind}.{row.field}.{row.page}.{row.frequency}"
    facts = builder.matching(source.evidence_id, locator)
    if not facts:
        return
    common = {"frequency": row.frequency, "page": row.page, "raw_unit": row.raw_unit}
    for attribute, period in (("current", row.period), ("previous", row.prior_period)):
        builder.add(definition=f"official.{row.kind}.{row.field}.{attribute}", label=row.label,
            value=getattr(row, attribute), unit=row.unit, facts=facts, sources=[source.evidence_id],
            metadata={**common, "report_period": period.isoformat(), "observation_role": attribute},
            basis="accounting_check" if row.kind == "cash_bridge" else "actual_reported",
            lineage=_source_lineage(source, field=row.field, attribute=attribute,
                                    report_period=period.isoformat(), page=row.page), limitations=source.limitations)
        builder.meta("period", f"报告期：{period}（{row.frequency}，{'本期' if attribute == 'current' else '上年同期'}）",
                     facts, [source.evidence_id])
    # Only the explicitly comparable FY/H1 financial row supplies a derived
    # value. A saved check or a vendor end_date alone is never sufficient.
    if row.kind != "financial" or row.frequency not in {"FY", "H1"} or row.current is None or row.previous is None:
        return
    current, base = _number(row.current), _number(row.previous)
    for operation in ("difference", "growth"):
        if operation == "growth" and base <= 0:
            continue
        with localcontext() as context:
            context.prec = 50
            value = current - base
            if operation == "growth":
                value /= base
        selector = {"field": row.field, "attribute": operation, "report_period": row.period.isoformat()}
        builder.add(definition=f"official.{row.field}.{operation}",
            label=_OFFICIAL_LABELS.get(row.field, row.label) + ("同比变化" if operation == "difference" else "同比增速"),
            value=value, unit=row.unit if operation == "difference" else "ratio", facts=facts,
            sources=[source.evidence_id], basis="computed_statistic",
            metadata={**common, "report_period": row.period.isoformat(), "prior_period": row.prior_period.isoformat()},
            lineage={"kind": "calculation", "calculation_version": OFFICIAL_ARITHMETIC_VERSION,
                     "input_sha256": source.content.content_sha256, "source_family_id": source.source_family_id or source.evidence_id,
                     "source_selector": selector}, limitations=source.limitations)


def _operating(builder, source, payload):
    row = payload.get("row", {})
    locator = f"operating[{row['classification']}:{row['name']}].page[{row['page']}]"
    facts = builder.matching(source.evidence_id, locator)
    fields = {"revenue": ("营业收入", "CNY"), "prior_revenue": ("上年同期营业收入", "CNY"),
              "cost": ("营业成本", "CNY"), "gross_margin_percent": ("毛利率", "%"),
              "revenue_share_percent": ("营业收入占比", "%"), "prior_share_percent": ("上年营业收入占比", "%"),
              "revenue_change_percent": ("披露营业收入同比", "%"), "cost_change_percent": ("披露成本同比", "%")}
    for field, (label, unit) in fields.items():
        builder.add(definition="operating." + field, label=label, value=row.get(field), unit=unit,
            facts=facts, sources=[source.evidence_id], subject=builder.record.ticker + " · " + row["name"],
            metadata={"report_period": row["report_period"], "classification": row["classification"],
                      "segment": row["name"], "page": row["page"], "raw_unit": row["raw_unit"]},
            lineage=_source_lineage(source, field=field, classification=row["classification"], segment=row["name"], page=row["page"]),
            limitations=source.limitations)


def _quote(builder, source, payload, *, peer=False):
    locator = "peer_quote" if peer else "snapshot"
    facts = builder.matching(source.evidence_id, locator)
    meta = {key: payload[key] for key in ("as_of", "quote_timestamp", "quote_basis") if key in payload}
    if peer:
        qualify_payload(source.source_name, payload, ticker=builder.record.ticker,
            cutoff=builder.record.analysis_date, published=source.published_at,
            captured=source.captured_at, public_url=source.public_url)
    else:
        from tradingagents.dataflows.ticker_utils import to_tushare_symbol
        from tradingagents.research.native_valuation import valuation_content
        valuation_content(payload, source.source_name, to_tushare_symbol(builder.record.ticker), builder.record.analysis_date)
    for field, (label, unit) in _QUOTE_FIELDS.items():
        builder.add(definition=("peer." if peer else "snapshot.") + field, label=label,
            value=payload.get(field), unit=unit, facts=facts, sources=[source.evidence_id], basis="observed_quote",
            subject=payload["ts_code"] + (" · " + payload["name"] if peer else ""), metadata=meta,
            lineage=_source_lineage(source, field=field, as_of=payload["as_of"]), limitations=source.limitations)


def _forecast(builder, source, payload):
    row = qualify_payload(source.source_name, payload, ticker=builder.record.ticker,
        cutoff=builder.record.analysis_date, published=source.published_at,
        captured=source.captured_at, public_url=source.public_url)
    facts = builder.matching(source.evidence_id, "dated_forecast")
    builder.add(definition="forecast.eps", label="EPS", value=row.eps, unit="CNY/share", facts=facts,
        sources=[source.evidence_id], basis="institution_forecast", subject=row.ts_code + " · " + row.institution,
        metadata={"forecast_year": row.forecast_year, "published": row.published.isoformat(),
                  "institution": row.institution, "report_id": row.report_id},
        lineage=_source_lineage(source, field="eps", forecast_year=row.forecast_year, institution=row.institution, report_id=row.report_id),
        limitations=source.limitations)


def _prices(builder, source, payload):
    bars = payload.get("last_three_bars", [])
    if not bars:
        return
    bar = max(bars, key=lambda item: item["Date"])
    facts = builder.matching(source.evidence_id, f"bars[Date={bar['Date']}].Close")
    meta = {key: payload[key] for key in ("adjustment_anchor", "price_basis") if key in payload}
    if payload.get("price_unit") != "CNY/share" or bar["Date"] > builder.record.analysis_date.isoformat():
        return
    builder.add(definition="price.last_close", label="已保存收盘价", value=bar.get("Close"), unit="CNY/share",
        facts=facts, sources=[source.evidence_id], basis="observed_quote", metadata={**meta, "as_of": bar["Date"]},
        lineage=_source_lineage(source, table="last_three_bars", field="Close", as_of=bar["Date"]), limitations=source.limitations)


def _metrics(builder):
    allowed = {"annualized_volatility", "historical_var_95", "historical_es_95", "max_drawdown", "atr_14", "beta"}
    sources = {s.evidence_id: s for s in builder.record.evidence}
    for metric in builder.record.metrics:
        name = metric.metric_id.rsplit(".", 1)[-1]
        if (name not in allowed or metric.availability != "available" or metric.value is None
                or not metric.window_start or not metric.window_end or metric.window_end > builder.record.analysis_date
                or not metric.sample_size or not metric.input_evidence_ids):
            continue
        try:
            payloads = [_qualified_payload(builder.record, sources[eid]) for eid in metric.input_evidence_ids]
        except (KeyError, _Unavailable, ValueError):
            continue
        if any(sources[eid].source_name not in PRICE_SOURCES for eid in metric.input_evidence_ids):
            continue
        facts = tuple(sorted({fid for eid in metric.input_evidence_ids for fid in builder.matching(eid, "computed_statistics:" + metric.metric_id)}))
        meta = {"window_start": metric.window_start.isoformat(), "window_end": metric.window_end.isoformat(),
                "sample_size": metric.sample_size}
        if metric.tail_sample_size is not None:
            meta["tail_sample_size"] = metric.tail_sample_size
        for key in ("price_basis", "adjustment_anchor"):
            if key in payloads[0]:
                meta[key] = payloads[0][key]
        builder.add(definition="metric." + name, label=metric.label, value=metric.value, unit=metric.unit,
            facts=facts, sources=metric.input_evidence_ids, basis="computed_statistic", metadata=meta,
            lineage={"kind": "calculation", "calculation_version": metric.calculation_version,
                     "input_sha256": metric.input_sha256, "source_selector": {"metric_id": metric.metric_id}}, limitations=metric.limitations)


def _local_checks(builder):
    checks = builder.record.evidence_checks
    if checks is None:
        return
    # Rebuild the closed branches; never interpret model-provided method prose.
    from tradingagents.research.minimum_evidence import compute_checks
    computed = compute_checks(builder.record)
    if computed != checks:
        raise ValueError("numeric check input binding invalid")
    for check in computed.checks:
        for observation in check.observations:
            # Raw official operands already have richer catalog entries. A
            # conflict's observed values remain labelled conflict, not passed.
            if check.check_id == "operating_disclosures":
                continue
            sources = observation.evidence_ids
            facts = builder.all_facts(sources)
            meta = {"check_id": check.check_id, "check_status": check.status}
            if check.check_id == "cash_conversion":
                numeric_sources = [s for s in builder.record.evidence if s.evidence_id in sources and s.source_name == NUMERIC_SOURCE]
                if not numeric_sources:
                    continue
                row = json.loads(numeric_sources[0].content.text)["row"]
                if row.get("frequency") not in {"FY", "H1"}:
                    continue
                meta.update(report_period=row["period"], prior_period=row["prior_period"], frequency=row["frequency"])
            elif observation.key.startswith("forecast_eps"):
                forecast_rows = [json.loads(s.content.text) for s in builder.record.evidence if s.evidence_id in sources and s.source_name in FORECAST_SOURCES]
                years = {row["forecast_year"] for row in forecast_rows}
                if len(years) != 1:
                    continue
                meta["forecast_year"] = next(iter(years))
                meta["source_basis"] = "选取机构预测，非已实现，非完整一致预期"
            else:
                quotes = [json.loads(s.content.text) for s in builder.record.evidence if s.evidence_id in sources and s.source_name == "tencent.peer_valuation"]
                if not quotes or len({row["as_of"] for row in quotes}) != 1:
                    continue
                meta["as_of"] = quotes[0]["as_of"]
                meta["source_basis"] = "选取行业候选样本，不代表全行业或业务可比"
            builder.add(definition="check." + check.check_id + "." + observation.key, label=observation.label,
                value=observation.value, unit=observation.unit, facts=facts, sources=sources,
                basis="accounting_check" if check.check_id == "cash_conversion" else "institution_forecast" if observation.key.startswith("forecast_eps") else "computed_statistic",
                metadata=meta, lineage={"kind": "calculation", "calculation_version": checks.calculation_version,
                    "input_sha256": checks.input_sha256, "source_selector": {"check_id": check.check_id, "observation_key": observation.key}},
                limitations=(*check.limitations, *check.missing))


def _valuation(builder):
    value = builder.record.valuation
    if value is None:
        return
    from tradingagents.research.valuation import assess_valuation
    if value.input_sha256 != canonical_sha256(value.inputs) or value.assessment != assess_valuation(value.inputs):
        raise ValueError("numeric valuation input binding invalid")
    for eid in value.input_evidence_ids:
        _qualified_payload(builder.record, next(s for s in builder.record.evidence if s.evidence_id == eid))
    facts = builder.all_facts(value.input_evidence_ids)
    common = {"as_of": value.inputs.as_of.isoformat(), "source_basis": "历史倍数及已保存盈利假设，不证明合理价值"}
    lineage = {"kind": "calculation", "calculation_version": "valuation-assessment-v1", "input_sha256": value.input_sha256}
    for point in value.assessment.positions:
        kind = point.window_label.split("_", 1)[0]
        series = value.inputs.pe_history if kind == "pe" else value.inputs.pb_history
        if not series:
            continue
        end = max(item.day for item in series)
        from datetime import timedelta
        window = 365 if point.window_label.endswith("1y") else 1095
        start = end - timedelta(days=window)
        builder.add(definition="valuation.position." + point.window_label, label=point.window_label + "历史分位",
            value=point.percentile, unit="%", facts=facts, sources=value.input_evidence_ids,
            basis="computed_statistic", metadata={**common, "window_start": start.isoformat(), "window_end": end.isoformat(),
                "window_label": point.window_label, "sample_size": point.sample_size},
            lineage={**lineage, "source_selector": {"component": "positions", "window_label": point.window_label}}, limitations=value.limitations)
    synthesis = value.assessment.synthesis
    if synthesis.status != "unavailable":
        for field, label, unit in (("reference_low_yi", "假设参考区间下沿", "CNY_YI"),
                                   ("reference_high_yi", "假设参考区间上沿", "CNY_YI"),
                                   ("per_share_low", "假设每股参考下沿", "CNY/share"),
                                   ("per_share_high", "假设每股参考上沿", "CNY/share")):
            builder.add(definition="valuation.synthesis." + field, label=label, value=getattr(synthesis, field), unit=unit,
                facts=facts, sources=value.input_evidence_ids, basis="valuation_reference", metadata=common,
                lineage={**lineage, "source_selector": {"component": "synthesis", "field": field}}, limitations=value.limitations)


def build_numeric_catalog(record):
    """Build without I/O or re-validating the containing record model."""
    builder = _Builder(record)
    try:
        builder.meta("identity", "证券身份：" + record.ticker)
        if record.company_basics is not None and record.company_basics.company_name:
            builder.meta("identity", "公司名称：" + record.company_basics.company_name)
        for source in sorted(record.evidence, key=lambda item: item.evidence_id):
            try:
                payload = _qualified_payload(record, source)
            except (_Unavailable, ValueError, TypeError):
                continue
            facts = builder.all_facts([source.evidence_id])
            if isinstance(payload.get("title"), str) and facts:
                builder.meta("source_title", "来源标题：" + payload["title"], facts, [source.evidence_id])
            if source.source_name in FINANCIAL_SOURCES:
                _financial(builder, source, payload)
            elif source.source_name == NUMERIC_SOURCE:
                _official(builder, source, payload)
            elif source.source_name in OPERATING_SOURCES:
                _operating(builder, source, payload)
            elif source.source_name == "tencent.valuation_snapshot":
                _quote(builder, source, payload)
            elif source.source_name == "tencent.peer_valuation":
                _quote(builder, source, payload, peer=True)
            elif source.source_name in FORECAST_SOURCES:
                _forecast(builder, source, payload)
            elif source.source_name in PRICE_SOURCES:
                _prices(builder, source, payload)
        _metrics(builder)
        _local_checks(builder)
        _valuation(builder)
    except _CatalogLimit:
        return NumericCatalogV1(availability="unavailable", reason_code="numeric_catalog_limit").model_dump(mode="json")
    return NumericCatalogV1(anchors=tuple(builder.anchors[key] for key in sorted(builder.anchors)),
        metadata=tuple(builder.metadata[key] for key in sorted(builder.metadata))).model_dump(mode="json")


def project_numeric_catalog(catalog, allowed_fact_ids):
    allowed = set(allowed_fact_ids)
    value = NumericCatalogV1.model_validate(catalog)
    return value.model_copy(update={
        "anchors": tuple(a for a in value.anchors if set(a.required_fact_ids) <= allowed),
        "metadata": tuple(m for m in value.metadata if set(m.required_fact_ids) <= allowed),
    }).model_dump(mode="json")


def render_numeric_anchor(anchor):
    """Render a complete host-owned fragment with fixed HALF_EVEN presets."""
    anchor = NumericAnchorV1.model_validate(anchor)
    meta = anchor.metadata
    with localcontext() as context:
        context.prec = 100
        value = Decimal(anchor.value)
        if anchor.unit == "CNY":
            value, unit, digits = value / Decimal(100000000), "亿元", 2
        elif anchor.unit == "CNY_YI":
            unit, digits = "亿元", 2
        elif anchor.unit == "CNY/share":
            unit, digits = "元/股", 4
        elif anchor.unit in {"return_fraction", "signed_return_fraction", "ratio"}:
            value, unit, digits = value * 100, "%", 2
        elif anchor.unit in {"%", "percent"}:
            unit, digits = "%", 2
        elif anchor.unit in {"multiple", "倍", "dimensionless"}:
            unit, digits = "倍" if anchor.unit != "dimensionless" else "（无量纲）", 2
        else:
            unit, digits = anchor.unit, None
        number = str(value) if digits is None else format(value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_EVEN), f".{digits}f")
    context_parts = [anchor.subject]
    if "report_period" in meta:
        context_parts.append(meta["report_period"] + ("（" + meta["frequency"] + "）" if "frequency" in meta else "报告期"))
    if "prior_period" in meta:
        context_parts.append("对比上年同期 " + meta["prior_period"])
    if "observation_role" in meta:
        context_parts.append("本期" if meta["observation_role"] == "current" else "上年同期")
    if "forecast_year" in meta:
        context_parts.append(str(meta["forecast_year"]) + "年预测")
    if "published" in meta:
        context_parts.append("报告发布 " + meta["published"])
    if "as_of" in meta:
        context_parts.append(meta["as_of"])
    if "quote_timestamp" in meta:
        context_parts.append("报价时间 " + meta["quote_timestamp"])
    if meta.get("quote_basis") == "unsettled_session_snapshot":
        context_parts.append("尚未结算快照，非收盘价")
    if "window_start" in meta and "window_end" in meta:
        context_parts.append("历史窗口 " + meta["window_start"] + " 至 " + meta["window_end"])
    if "sample_size" in meta:
        context_parts.append("样本 " + str(meta["sample_size"]))
    if "tail_sample_size" in meta:
        context_parts.append("尾部样本 " + str(meta["tail_sample_size"]))
    for key, label in (("price_basis", "价格口径"), ("adjustment_anchor", "复权锚点"), ("source_basis", "口径")):
        if key in meta:
            context_parts.append(label + " " + meta[key])
    if "check_status" in meta:
        context_parts.append("检查状态 " + meta["check_status"])
    return " · ".join(context_parts) + " · " + anchor.label + " " + number + unit + "（" + _BASIS_LABELS[anchor.basis] + "）"


def validate_numeric_catalog(record, catalog):
    if NumericCatalogV1.model_validate(catalog).model_dump(mode="json") != build_numeric_catalog(record):
        raise ValueError("numeric_manifest_binding")
