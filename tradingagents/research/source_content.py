"""Qualified source excerpts and deterministic historical price metrics."""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from tradingagents.agents.schemas._evidence import QuantitativeMetricV1, SourceContentV1

_FINANCIAL_FIELDS = frozenset({"revenue", "n_income", "total_assets", "total_liab", "n_cashflow_act", "total_revenue", "n_income_attr_p", "gross_profit", "net_income", "operating_cash_flow", "total_liabilities"})
_DATE_FIELDS = frozenset({"ann_date", "f_ann_date", "end_date"})

def _content(value: Any, label: str) -> SourceContentV1 | None:
    if value in ({}, [], None):
        return None
    full = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    text = full[:4000]
    return SourceContentV1(kind="source_fields", text=text, locator_label=label,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), truncated=len(full) > len(text))

def _financial_row(row: dict) -> dict:
    selected = {}
    for key in sorted(row):
        value = row[key]
        if key in _DATE_FIELDS and isinstance(value, str) and len(value) == 8 and value.isdigit():
            selected[key] = value
        elif key in _FINANCIAL_FIELDS and not isinstance(value, bool):
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if isfinite(number):
                selected[key] = number
    return selected

def source_content(source: str, payload: Any) -> SourceContentV1 | None:
    if not isinstance(payload, dict):
        return None
    if source == "cninfo":
        selected = {key: payload[key] for key in ("Title", "Published", "Announcement ID")
            if key in payload and isinstance(payload[key], str)}
        return _content(selected, "公告列表原始字段；不代表公告正文或已实施")
    if source == "tushare.stock_basic":
        return _content({key: payload[key] for key in ("ts_code", "list_date") if key in payload}, "证券身份字段")
    if source == "tushare.financial_statements":
        selected = {key: [_financial_row(row) for row in rows[:2] if isinstance(row, dict)]
            for key, rows in payload.items() if key in {"income", "balancesheet", "cashflow"} and isinstance(rows, list)}
        return _content(selected, "已保存合并报表字段；金额 CNY，日期为披露/报告日期")
    if source == "tushare.adjusted_daily":
        provenance = payload.get("provenance", {})
        selected = {key: provenance[key] for key in ("actual_start", "actual_end", "adjustment_anchor", "price_basis", "price_unit") if key in provenance}
        bars = payload.get("bars", [])
        selected["last_three_bars"] = [{key: row[key] for key in ("Date", "Open", "High", "Low", "Close") if key in row} for row in bars[-3:]]
        return _content(selected, "已保存日行情字段与复权锚点；不代表价值区间")
    return None

def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if any(any(part in key.lower() for part in ("token", "secret", "key", "signature", "auth")) for key, _ in parse_qsl(parsed.query)):
            return None
    except ValueError:
        return None
    return value

def _price_metrics(evidence_id: str, payload: Any) -> tuple[QuantitativeMetricV1, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("computed_statistics"), dict):
        return ()
    stats = payload["computed_statistics"]
    provenance = payload.get("provenance", {})
    if provenance.get("pit_status") != "verified" or not provenance.get("window_covered") or stats.get("input_sha256") != provenance.get("input_sha256"):
        return ()
    definitions = (
        ("annualized_volatility", "年化波动率", "return_statistics", "return_fraction", "sample std(ddof=1) * sqrt(252)"),
        ("historical_var_95", "单日历史 5% 分位", "return_statistics", "signed_return_fraction", stats["var_method"]),
        ("historical_es_95", "历史尾部均值 ES", "return_statistics", "signed_return_fraction", stats["es_method"]),
        ("max_drawdown", "区间最大回撤", "return_statistics", "signed_return_fraction", "observed close / running maximum - 1; initial close included"),
        ("atr_14", "ATR(14)", "atr", "CNY/share", stats["atr_method"]),
        ("beta", "Beta", "benchmark_statistics", "dimensionless", "sample covariance(asset,benchmark) / sample variance(benchmark)"),
    )
    result = []
    for name, label, group, unit, method in definitions:
        values = stats.get(group, {})
        available = values.get("status") == "available"
        result.append(QuantitativeMetricV1(
            metric_id=f"{evidence_id}.{name}", label=label,
            availability="available" if available else "unavailable",
            value=values.get("value" if group == "atr" else name) if available else None,
            unit=unit, method=method, calculation_version=values.get("calculation_version", "not_calculated"),
            input_evidence_ids=(evidence_id,), input_sha256=stats["input_sha256"],
            window_start=values.get("window_start"), window_end=values.get("window_end"),
            sample_size=values.get("observation_count"),
            tail_sample_size=values.get("tail_observation_count") if name in {"historical_var_95", "historical_es_95"} else None,
            unavailable_reason=None if available else values.get("reason", "metric_not_calculated"),
            limitations=tuple(stats.get("limitations", ())),
        ))
    return tuple(result)
