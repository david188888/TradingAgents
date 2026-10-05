"""Pure valuation assembly from admitted frozen native evidence, without I/O."""
import hashlib
import json
import math
from datetime import date
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
from tradingagents.research.source_families import FINANCIAL_SOURCES
from tradingagents.research.valuation import (
    DailyMultipleV1,
    EarningsBaseV1,
    ValuationInputsV1,
    ValuationSnapshotInputV1,
    assess_valuation,
)
from tradingagents.research.verification_tools import _date, _financial_operand, _Unavailable

VALUATION_SOURCES = frozenset({"tencent.valuation_snapshot", "tushare.valuation_history"})


def _finite(value, *, positive=False, optional=False):
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("invalid valuation numeric input")


def valuation_content(payload, source_name, ticker, cutoff):
    """Validate structured fields again at the frozen-record admission boundary."""
    if not isinstance(payload, dict) or payload.get("ts_code") != ticker or payload.get("currency") != "CNY":
        raise ValueError("valuation source identity or currency mismatch")
    as_of = date.fromisoformat(payload["as_of"])
    if as_of > cutoff:
        raise ValueError("valuation source after cutoff")
    if source_name == "tencent.valuation_snapshot":
        from datetime import datetime
        quoted = datetime.fromisoformat(payload["quote_timestamp"])
        if quoted.tzinfo is None or quoted.astimezone(ZoneInfo("Asia/Shanghai")).date() != as_of:
            raise ValueError("valuation timestamp mismatch")
        for key in ("price", "total_market_cap_yi"):
            _finite(payload[key], positive=True)
        for key in ("pe_ttm", "pb"):
            _finite(payload[key], positive=True, optional=True)
        if payload["pe_ttm"] is None and payload["pb"] is None:
            raise ValueError("valuation multiples unavailable")
        ValuationSnapshotInputV1.model_validate({key: payload[key] for key in
            ("as_of", "price", "pe_ttm", "pb", "total_market_cap_yi")})
        return payload
    if payload.get("capture_scope") != "current_cutoff_retrospective_history":
        raise ValueError("valuation history vintage unknown")
    rows = payload["rows"]
    days = [date.fromisoformat(row["date"]) for row in rows]
    if not 1 <= len(rows) <= 1000 or len(set(days)) != len(days) or max(days) != as_of or any(day > cutoff for day in days):
        raise ValueError("valuation history date mismatch")
    for row in rows:
        for key in ("pe_ttm", "pb"):
            if row[key] is not None:
                _finite(row[key])
                DailyMultipleV1(day=date.fromisoformat(row["date"]), value=row[key])
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return {"ts_code": ticker, "as_of": payload["as_of"], "capture_scope": payload["capture_scope"],
        "sample_size": len(rows), "window_start": min(days).isoformat(),
        "rows_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "selected_rows": rows[-3:]}


def assemble_valuation(record, payloads):
    """No snapshot means no native valuation judgement. Missing anchors stay absent."""
    from tradingagents.agents.schemas._research_record import NativeValuationV1, canonical_sha256
    eligible = [s for s in record.evidence if s.availability == "available" and s.content is not None]
    snapshot_source = next((s for s in eligible if s.source_name == "tencent.valuation_snapshot"), None)
    if snapshot_source is None:
        return None
    snapshot = ValuationSnapshotInputV1.model_validate({key: payloads[snapshot_source.evidence_id][key]
        for key in ("as_of", "price", "pe_ttm", "pb", "total_market_cap_yi")})
    refs = [snapshot_source.evidence_id]
    history = next((s for s in eligible if s.source_name == "tushare.valuation_history"), None)
    rows = []
    if history is not None and payloads[history.evidence_id]["as_of"] == snapshot.as_of.isoformat():
        rows = payloads[history.evidence_id]["rows"]
        refs.append(history.evidence_id)
    annual = None
    candidates = []
    for source in eligible:
        if source.source_name not in FINANCIAL_SOURCES:
            continue
        payload = payloads.get(source.evidence_id, {})
        for row in payload.get("income", []):
            try:
                period = _date(row["end_date"])
                if period.month != 12 or period.day != 31:
                    continue
                value, _ = _financial_operand(record, FinancialOperandV1(evidence_id=source.evidence_id,
                    table="income", field="n_income_attr_p", report_period=period.isoformat()))
                candidates.append((period, source.evidence_id, value))
            except (_Unavailable, ValueError, KeyError):
                continue
    if candidates:
        period, source_id, value = max(candidates, key=lambda item: (item[0], item[1]))
        annual = EarningsBaseV1(metric_id="net_income", value_yi=float(value / 100000000), period=period.isoformat())
        refs.append(source_id)
    inputs = ValuationInputsV1(run_id=record.run_id, ticker=record.ticker, as_of=record.analysis_date,
        snapshot=snapshot, net_income_annual=annual,
        pe_history=tuple(DailyMultipleV1(day=date.fromisoformat(r["date"]), value=r["pe_ttm"]) for r in rows if r["pe_ttm"] is not None),
        pb_history=tuple(DailyMultipleV1(day=date.fromisoformat(r["date"]), value=r["pb"]) for r in rows if r["pb"] is not None))
    return NativeValuationV1(inputs=inputs, assessment=assess_valuation(inputs), input_evidence_ids=tuple(refs), input_sha256=canonical_sha256(inputs),
        limitations=("current_capture_history_is_not_archived_pit", "historical_multiple_band_is_assumption_not_intrinsic_value",
                      "market_cap_and_quote_rounding_affect_implied_share_count"))
