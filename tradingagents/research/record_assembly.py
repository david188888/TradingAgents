"""Compatibility producers of the shared research record, without I/O/LLMs.

Old case semantics are retained. Model challenge dispositions never become
executed verifications. Source content is selected through narrow allowlists;
reports, arbitrary provider envelopes and prompts are not source excerpts.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from math import isfinite
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from tradingagents.agents.schemas._catalyst_research import CatalystResearchCase
from tradingagents.agents.schemas._research_case import ResearchCaseV2
from tradingagents.agents.schemas._research_record import (
    EvidenceSnapshotV1,
    QuantitativeMetricV1,
    RecordClaimV1,
    ResearchChallengeV1,
    ResearchHypothesisV1,
    ResearchRecordV1,
    SourceContentV1,
    SourceEvidenceV1,
    make_evidence_snapshot,
)

COMPATIBILITY_LIMIT = "converted_inference_not_an_executed_hypothesis_test"
_FINANCIAL_FIELDS = frozenset({
    "revenue", "n_income", "total_assets", "total_liab", "n_cashflow_act",
    "total_revenue", "n_income_attr_p", "gross_profit", "net_income",
    "operating_cash_flow", "total_liabilities",
})
_DATE_FIELDS = frozenset({"ann_date", "f_ann_date", "end_date"})


def case_content_sha256(case) -> str:
    return hashlib.sha256(json.dumps(case.model_dump(mode="json"), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


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


def _catalyst_content(source: str, payload: Any) -> SourceContentV1 | None:
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


def _snapshot(evidence) -> EvidenceSnapshotV1:
    return make_evidence_snapshot(evidence)


def _hypotheses(claims, snapshot) -> tuple[ResearchHypothesisV1, ...]:
    return tuple(ResearchHypothesisV1(
        hypothesis_id=f"h.{item.claim_id}", claim_id=item.claim_id,
        input_snapshot_id=snapshot.snapshot_id, origin="adapted_inference",
        limitations=(COMPATIBILITY_LIMIT, "explicit_falsification_condition_not_recorded"),
    ) for item in claims if item.kind == "inference")


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


def record_from_catalyst(case: CatalystResearchCase, context: dict[str, Any]) -> ResearchRecordV1:
    evidence = tuple(SourceEvidenceV1(
        evidence_id=item.evidence_id, source_name=item.source_name, source_kind=item.source_tier,
        source_family_id=item.source_family_id, availability=item.availability,
        public_url=_safe_url(item.public_url), published_at=item.published_at,
        usable_as_of=item.usable_as_of, captured_at=item.captured_at,
        content=_catalyst_content(item.source_name, context.get(item.evidence_id)),
        limitations=("source_fields_are_not_full_document_text",)
            if _catalyst_content(item.source_name, context.get(item.evidence_id)) else ("source_content_not_saved_or_not_admitted",),
    ) for item in case.evidence)
    claims = tuple(RecordClaimV1(
        claim_id=item.finding_id, kind=item.kind, statement=item.text,
        evidence_ids=item.evidence_ids, supporting_fact_ids=item.supporting_finding_ids,
        limitations=item.limitations if item.kind != "unknown" else (*item.limitations, *item.next_checks),
    ) for item in case.findings)
    snapshot = _snapshot(evidence)
    dispositions = {item.challenge_id: item.outcome for item in case.dispositions}
    challenges = tuple(ResearchChallengeV1(
        challenge_id=item.challenge_id, target_claim_ids=item.target_finding_ids,
        statement=item.statement, severity=item.severity, risk_type="unclassified",
        evidence_ids=item.evidence_ids, proposed_test=item.test_method,
        reported_disposition=dispositions.get(item.challenge_id),
    ) for item in case.challenges)
    metrics = tuple(metric for item in case.evidence if item.source_name == "tushare.adjusted_daily"
        for metric in _price_metrics(item.evidence_id, context.get(item.evidence_id)))
    return ResearchRecordV1(run_id=case.run_id, ticker=case.ticker,
        mode="catalyst_research", analysis_date=case.as_of.date(), construction="adapted_case",
        source_case_contract="catalyst-research-case-v1", source_case_sha256=case_content_sha256(case),
        snapshots=(snapshot,), evidence=evidence, claims=claims,
        hypotheses=_hypotheses(claims, snapshot), challenges=challenges, metrics=metrics,
        limitations=("independent_tool_verification_not_executed", "compatibility_record_preserves_source_case_semantics"))


def _classic_financial_content(bundle: dict | None, ref_id: str) -> SourceContentV1 | None:
    if bundle is None:
        return None
    digest = hashlib.sha256(json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != ref_id:
        return None
    selected = {}
    for capability in bundle.get("results", []):
        if not isinstance(capability, dict):
            continue
        for item in capability.get("statements", []):
            if not isinstance(item, dict) or item.get("status") != "ok" or not isinstance(item.get("data"), str) or item.get("statement") not in {"income_statement", "balance_sheet", "cash_flow"}:
                continue
            # Public CSV numeric/date fields only, never arbitrary report text,
            # response headers, endpoint URLs or provider diagnostic strings.
            lines = [line for line in item["data"].splitlines() if line and not line.startswith("#")]
            rows = [_financial_row(row) for row in csv.DictReader(io.StringIO("\n".join(lines)))]
            rows = [row for row in rows if any(key in _FINANCIAL_FIELDS for key in row)][:2]
            if rows:
                selected[item["statement"]] = rows
    return _content(selected, "已保存财报数据字段；不代表公告全文")


def record_from_classic(case: ResearchCaseV2, *, mode: str, analysis_date: str,
                        fundamentals_bundle: dict | None = None) -> ResearchRecordV1:
    evidence = tuple(SourceEvidenceV1(
        evidence_id=ref.ref_id, source_name=ref.artifact_id.split(":", 1)[0],
        source_kind="analysis_report" if ref.media_type in {"text/markdown", "text/plain"} else "unknown",
        availability="available" if ref.resolution_status == "available" else "unavailable",
        captured_at=ref.captured_at,
        content=_classic_financial_content(fundamentals_bundle, ref.ref_id),
        limitations=("source_family_and_original_document_not_available_in_legacy_reference",),
    ) for ref in case.evidence_refs)
    claims = tuple(RecordClaimV1(
        claim_id=item.claim_key, kind=item.claim_type, statement=item.text,
        evidence_ids=item.evidence_ref_ids, supporting_fact_ids=item.supporting_claim_keys,
        limitations=item.required_evidence if item.claim_type == "unknown" else (),
    ) for item in case.claims)
    snapshot = _snapshot(evidence)
    return ResearchRecordV1(run_id=case.run_id, ticker=case.ticker,
        mode=mode, analysis_date=date.fromisoformat(analysis_date), construction="adapted_case",
        source_case_contract="research-case-v2", source_case_sha256=case_content_sha256(case),
        snapshots=(snapshot,), evidence=evidence, claims=claims, hypotheses=_hypotheses(claims, snapshot),
        limitations=("independent_tool_verification_not_executed", "legacy_debate_not_converted_into_executed_challenges", "local_risk_metrics_not_published_for_classic"))
