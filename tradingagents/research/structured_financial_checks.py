"""Finite comparisons from qualified cumulative consolidated statements. No I/O."""

import json
from datetime import date
from decimal import Decimal, localcontext

from tradingagents.agents.schemas._evidence_checks import CheckObservationV1, LocalEvidenceCheckV1
from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
from tradingagents.research.source_families import FINANCIAL_SOURCES
from tradingagents.research.verification_tools import (
    _date,
    _financial_operand,
    _invalid_constant,
    _qualified_source,
    _Unavailable,
    _unique_object,
)

QUESTIONS = {
    "financial_baseline": ("financial_baseline.structured_coverage", "同期间合并营业收入、归母净利润与经营现金流是否具有合格结构化字段？"),
    "cashflow_comparison": ("cashflow_comparison.same_period_endpoints", "同期间合并净利润与经营现金流的金额、差额和变化是否可核对？"),
}
FIELDS = {
    "revenue": ("income", "营业收入"),
    "n_income_attr_p": ("income", "归母净利润"),
    "n_income": ("income", "合并净利润"),
    "n_cashflow_act": ("cashflow", "经营现金流净额"),
}
LIMITS = ("structured_financial_comparison_not_reported_cash_bridge",
          "structured_financial_coverage_not_quantitative_operations", "two_periods_not_structural_persistence")


def observation_operands(key, period):
    """Exact saved cells required by a closed comparison observation."""
    prior = period.replace(year=period.year - 1)
    if key.startswith("cfo_minus_net_income_"):
        attribute = key.removeprefix("cfo_minus_net_income_")
        if attribute not in {"current", "previous"}:
            raise ValueError("unknown structured financial observation")
        day = period if attribute == "current" else prior
        return [(FIELDS[field][0], field, day.isoformat()) for field in ("n_cashflow_act", "n_income")]
    for field, (table, _) in FIELDS.items():
        if key.startswith(field + "_"):
            suffix = key[len(field) + 1:]
            if suffix not in {"current", "previous", "change", "yoy_percent"}:
                break
            days = (period, prior) if suffix in {"change", "yoy_percent"} else (period if suffix == "current" else prior,)
            return [(table, field, day.isoformat()) for day in days]
    raise ValueError("unknown structured financial observation")


def qualified_statements(record):
    result = []
    for source in record.evidence:
        if record.schema_version == 'research-record-v2':
            from tradingagents.research.search_recovery import recovered_statement
            recovered = recovered_statement(record, source)
            if recovered:
                _qualified_source(record, source.evidence_id)
                result.append((source, recovered))
        if source.source_name not in FINANCIAL_SOURCES:
            continue
        try:
            _qualified_source(record, source.evidence_id)
            if source.content is None or source.content.kind != "source_fields" or source.content.truncated:
                continue
            payload = json.loads(source.content.text, parse_int=Decimal, parse_float=Decimal,
                                 parse_constant=_invalid_constant, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                continue
        except (ValueError, TypeError):
            continue
        result.append((source, payload))
    return result


def target_period(record, statements=None):
    """Latest disclosed quarter in either required table, not latest complete pair."""
    periods = []
    for _, payload in qualified_statements(record) if statements is None else statements:
        for table in ("income", "cashflow"):
            for row in payload.get(table, []) if isinstance(payload.get(table), list) else []:
                try:
                    period = _date(row["end_date"])
                    disclosures = [_date(row[k]) for k in ("ann_date", "f_ann_date") if row.get(k) is not None]
                    if (period.strftime("%m-%d") in {"03-31", "06-30", "09-30", "12-31"}
                            and disclosures and period <= record.analysis_date
                            and all(period <= day <= record.analysis_date for day in disclosures)):
                        periods.append(period)
                except (ValueError, KeyError, TypeError):
                    continue
    return max(periods) if periods else None


def _observation(key, label, value, unit, method, ids):
    return CheckObservationV1(key=key, label=label, value=str(value), unit=unit, method=method,
                              evidence_ids=tuple(sorted(ids)))


def _compute(record, statements, rows, period, check_id):
    scope, question = QUESTIONS[check_id]
    fields = ("revenue", "n_income_attr_p", "n_cashflow_act") if check_id == "financial_baseline" else ("n_income", "n_cashflow_act")
    missing, satisfied, conflicts, observations, ids = [], [], [], [], set()
    limits = list(LIMITS)
    if period is None:
        missing.append("structured_current_period")
    else:
        prior = date(period.year - 1, period.month, period.day)
        complete = []
        # Partial suppliers remain visible but never donate cells to another
        # supplier's comparison. Report conflict even when only one is complete.
        operands = {field: {"current": [], "previous": []} for field in fields}
        for source, _ in statements:
            values, absent = {}, []
            for field in fields:
                for attribute, day in (("current", period), ("previous", prior)):
                    try:
                        value, _ = _financial_operand(record, FinancialOperandV1(evidence_id=source.evidence_id,
                            table=FIELDS[field][0], field=field, report_period=day.isoformat()))
                    except _Unavailable:
                        absent.append(field + ":" + attribute)
                    else:
                        values[(field, attribute)] = value
                        operands[field][attribute].append((source.evidence_id, value))
            if not absent:
                complete.append((source, values))
            else:
                limits.append("structured_supplier_incomplete:" + source.evidence_id)
        for field in fields:
            for attribute, entries in operands[field].items():
                ids.update(eid for eid, _ in entries)
                if len({value for _, value in entries}) > 1:
                    conflicts.append("structured_supplier_discrepancy:" + field + ":" + attribute)
        if not complete:
            missing.append("complete_same_supplier_structured_pair")
            missing.extend("structured_pair:" + field + ":" + attribute
                for field in fields for attribute, entries in operands[field].items() if not entries)
        if complete:
            complete.sort(key=lambda item: (item[0].source_name, item[0].evidence_id))
            selected, values = complete[0]
            source_ids = {selected.evidence_id}
            # Official crosschecks use the saved raw-cell precision, never
            # invent a tolerance for structured supplier disagreements.
            from tradingagents.research.minimum_evidence import _precision
            official_count = 0
            official_fields = {"revenue": "revenue", "n_income_attr_p": "parent_net_income",
                               "n_income": "consolidated_net_income", "n_cashflow_act": "cfo"}
            for source, _, row in rows:
                for field in fields:
                    if row.kind != "financial" or row.field != official_fields[field] or row.period != period or row.frequency == "Q2":
                        continue
                    for attribute, day in (("current", period), ("previous", prior)):
                        if getattr(row, attribute) is None or (row.period if attribute == "current" else row.prior_period) != day:
                            continue
                        official_count += 1
                        ids.add(source.evidence_id)
                        if abs(values[field, attribute] - Decimal(getattr(row, attribute))) > _precision(row, attribute) / 2:
                            conflicts.append("structured_official_discrepancy:" + field + ":" + attribute)
            satisfied.append("complete_same_supplier_structured_pair")
            if official_count:
                satisfied.append("available_official_cells_crosschecked")
                limits.append("official_crosscheck_covers_available_cells_only")
            else:
                limits.append("structured_without_official_table_crosscheck")
            limits.append("single_structured_supplier" if len({s.source_name for s, _ in complete}) == 1 else
                          "multiple_structured_suppliers_not_proven_independent")
            method = f"{period} 对 {prior}；同供应商、合并累计口径；金额 CNY；未证明经济原因或完整现金流桥。"
            for field in fields:
                label = FIELDS[field][1]
                for attribute, day in (("current", period), ("previous", prior)):
                    observations.append(_observation(field + "_" + attribute, str(day) + " " + label,
                        values[field, attribute], "CNY", method, source_ids))
                change = values[field, "current"] - values[field, "previous"]
                observations.append(_observation(field + "_change", label + "同比金额变化", change, "CNY", method, source_ids))
                if values[field, "previous"] > 0:
                    growth = (values[field, "current"] / values[field, "previous"] - 1) * 100
                    observations.append(_observation(field + "_yoy_percent", label + "同比变化", growth, "%", method, source_ids))
                else:
                    limits.append("structured_nonpositive_growth_base:" + field)
            if check_id == "cashflow_comparison":
                for attribute in ("current", "previous"):
                    gap = values["n_cashflow_act", attribute] - values["n_income", attribute]
                    observations.append(_observation("cfo_minus_net_income_" + attribute, "经营现金流减合并净利润（" + ("本期" if attribute == "current" else "上年同期") + "）",
                        gap, "CNY", method + "差额不是调节桥组件或因果归因。", source_ids))
    return LocalEvidenceCheckV1(check_id=check_id, question_scope=scope, question=question,
        status="conflict" if conflicts else "unavailable" if missing else "passed",
        satisfied=tuple(sorted(set(satisfied))), missing=tuple(sorted({*missing, *conflicts})),
        evidence_ids=tuple(sorted(ids)), observations=tuple(observations), limitations=tuple(dict.fromkeys(limits)))


def compute_structured_checks(record, rows, *, identity_qualified):
    if not identity_qualified:
        return tuple(LocalEvidenceCheckV1(check_id=key, question_scope=scope, question=question,
            status="unavailable", missing=("security_identity_unqualified",)) for key, (scope, question) in QUESTIONS.items())
    statements = qualified_statements(record)
    period = target_period(record, statements)
    with localcontext() as ctx:
        ctx.prec = 80
        return tuple(_compute(record, statements, rows, period, key) for key in QUESTIONS)
