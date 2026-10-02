"""Pure, allowlisted checks on frozen public evidence; no provider or model calls."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from tradingagents.agents.schemas._research_record import ResearchRecordV1, SourceEvidenceV1
from tradingagents.agents.schemas._verification_plan import (
    FinancialConditionV1,
    FinancialOperandV1,
    VerificationTaskV1,
    predicate_matches,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class VerificationToolResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["supports", "contradicts", "inconclusive", "unavailable"]
    reason: Literal[
        "predicate_evaluated",
        "source_unqualified",
        "content_unusable",
        "invalid_fields",
        "period_unavailable",
        "disclosure_unqualified",
        "nonpositive_growth_base",
        "metric_unqualified",
        "tool_failed",
    ]
    value: str | None = None
    predicate_met: bool | None = None
    evidence_ids: tuple[str, ...] = ()
    # Only code-selected numeric lineage; never a provider envelope or exception.
    calculation: dict | None = None


class _Unavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason


def _qualified_source(record: ResearchRecordV1, evidence_id: str) -> SourceEvidenceV1:
    source = next((item for item in record.evidence if item.evidence_id == evidence_id), None)
    if source is None or evidence_id not in record.snapshots[0].evidence_ids:
        raise _Unavailable("source_unqualified")
    if source.availability != "available" or source.usable_as_of is None:
        raise _Unavailable("source_unqualified")
    if source.usable_as_of.astimezone(SHANGHAI).date() > record.analysis_date:
        raise _Unavailable("source_unqualified")
    if (
        source.published_at
        and source.published_at.astimezone(SHANGHAI).date() > record.analysis_date
    ):
        raise _Unavailable("source_unqualified")
    return source


def _number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise _Unavailable("invalid_fields")
    text = str(value)
    if len(text) > 64:
        raise _Unavailable("invalid_fields")
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise _Unavailable("invalid_fields") from None
    if (
        not result.is_finite()
        or abs(result) > Decimal("1e30")
        or (result and abs(result) < Decimal("1e-30"))
    ):
        raise _Unavailable("invalid_fields")
    return result


def _date(value) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", value):
        raise _Unavailable("disclosure_unqualified")
    try:
        return date.fromisoformat(
            value if "-" in value else f"{value[:4]}-{value[4:6]}-{value[6:]}"
        )
    except ValueError:
        raise _Unavailable("disclosure_unqualified") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Unavailable("invalid_fields")
        result[key] = value
    return result


def _invalid_constant(_):
    raise _Unavailable("invalid_fields")


def _financial_operand(
    record: ResearchRecordV1, operand: FinancialOperandV1
) -> tuple[Decimal, dict]:
    source = _qualified_source(record, operand.evidence_id)
    if (
        source.source_name != "tushare.financial_statements"
        or source.source_kind not in {"official", "vendor"}
        or not source.source_family_id
    ):
        raise _Unavailable("source_unqualified")
    content = source.content
    if content is None or content.kind != "source_fields" or content.truncated:
        raise _Unavailable("content_unusable")
    try:
        payload = json.loads(
            content.text,
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=_invalid_constant,
            object_pairs_hook=_unique_object,
        )
    except (ValueError, TypeError):
        raise _Unavailable("invalid_fields") from None
    rows = payload.get(operand.table) if isinstance(payload, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise _Unavailable("invalid_fields")
    period = date.fromisoformat(operand.report_period)
    if period > record.analysis_date:
        raise _Unavailable("period_unavailable")
    candidates = [row for row in rows if _date(row.get("end_date")) == period]
    if len(candidates) != 1:
        raise _Unavailable("period_unavailable")
    row = candidates[0]
    disclosures = [row[key] for key in ("ann_date", "f_ann_date") if row.get(key) is not None]
    if not disclosures or any(
        _date(value) > record.analysis_date or _date(value) < period for value in disclosures
    ):
        raise _Unavailable("disclosure_unqualified")
    value = _number(row.get(operand.field))
    return value, {
        **operand.model_dump(mode="json"),
        "value": str(value),
        "source_content_sha256": content.content_sha256,
    }


def evaluate_condition(
    record: ResearchRecordV1, task: VerificationTaskV1
) -> VerificationToolResultV1:
    """Evaluate exactly the saved predicate, never the economic hypothesis itself."""
    try:
        check = task.check
        if isinstance(check, FinancialConditionV1):
            current, current_input = _financial_operand(record, check.current)
            operands = [current_input]
            value = current
            if check.base is not None:
                base, base_input = _financial_operand(record, check.base)
                current_source = _qualified_source(record, check.current.evidence_id)
                base_source = _qualified_source(record, check.base.evidence_id)
                if current_source.source_family_id != base_source.source_family_id:
                    raise _Unavailable("source_unqualified")
                operands.append(base_input)
                with localcontext() as context:
                    context.prec = 50
                    value = current - base
                    if check.operation == "growth":
                        if base <= 0:
                            raise _Unavailable("nonpositive_growth_base")
                        value /= base
            evidence_ids = tuple(dict.fromkeys(item["evidence_id"] for item in operands))
            calculation = {"kind": "financial", "operation": check.operation, "operands": operands}
        else:
            metric = next(
                (item for item in record.metrics if item.metric_id == check.metric_id), None
            )
            if (
                metric is None
                or metric.availability != "available"
                or metric.sample_size is None
                or metric.sample_size < 1
            ):
                raise _Unavailable("metric_unqualified")
            if (
                metric.unit != check.predicate.unit
                or metric.window_end is None
                or metric.window_end > record.analysis_date
            ):
                raise _Unavailable("metric_unqualified")
            for evidence_id in metric.input_evidence_ids:
                _qualified_source(record, evidence_id)
            value = _number(metric.value)
            evidence_ids = metric.input_evidence_ids
            calculation = {
                "kind": "metric",
                "metric_id": metric.metric_id,
                "input_evidence_ids": list(evidence_ids),
                "input_sha256": metric.input_sha256,
                "calculation_version": metric.calculation_version,
                "limitation": "saved_metric_threshold_only_not_raw_recomputation",
            }
        met = predicate_matches(value, check.predicate)
        status = (
            ("supports" if met else "contradicts")
            if task.condition_role == "necessary"
            else ("contradicts" if met else "inconclusive")
        )
        calculation.update(
            value=str(value), predicate=check.predicate.model_dump(mode="json"), predicate_met=met
        )
        return VerificationToolResultV1(
            status=status,
            reason="predicate_evaluated",
            value=str(value),
            predicate_met=met,
            evidence_ids=evidence_ids,
            calculation=calculation,
        )
    except _Unavailable as exc:
        return VerificationToolResultV1(status="unavailable", reason=exc.reason)
