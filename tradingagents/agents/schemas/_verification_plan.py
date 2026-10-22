"""Code-owned numeric checks, bound to a frozen native research hypothesis.

Conditions are declarative data, never expressions, URLs or executable code.
Binding a condition's text does not establish that its numeric translation is
economically sufficient; the executor reports only the specified predicate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Baseline six fields: the frozen financial-statements evidence contract.
BASELINE_FIELD_REGISTRY = {
    "revenue": ("income", "营业收入", "BIZINCO"),
    "n_income": ("income", "净利润", "NETPROFIT"),
    "n_income_attr_p": ("income", "归母净利润", "PARENETP"),
    "total_assets": ("balancesheet", "总资产", "TOTASSET"),
    "total_liab": ("balancesheet", "总负债", "TOTLIAB"),
    "n_cashflow_act": ("cashflow", "经营现金流净额", "MANANETR"),
}
FINANCIAL_FIELDS = {
    table: frozenset(f for f, (t, _, _) in BASELINE_FIELD_REGISTRY.items() if t == table)
    for table in ("income", "balancesheet", "cashflow")
}
BASELINE_LABELS = {field: label for field, (_, label, _) in BASELINE_FIELD_REGISTRY.items()}

# financial-detail-fields-v1: one registry for collection, content, catalog and
# checks. field -> (table, label, Sina item code). Names follow Tushare.
DETAIL_FIELD_REGISTRY = {
    "oper_cost": ("income", "营业成本", "BIZCOST"),
    "sell_exp": ("income", "销售费用", "SALESEXPE"),
    "admin_exp": ("income", "管理费用", "MANAEXPE"),
    "rd_exp": ("income", "研发费用", "DEVEEXPE"),
    "fin_exp": ("income", "财务费用", "FINEXPE"),
    "accounts_receiv": ("balancesheet", "应收账款", "ACCORECE"),
    "accounts_receiv_bill": ("balancesheet", "应收票据及应收账款", "NOTESACCORECE"),
    "inventories": ("balancesheet", "存货", "INVE"),
    "acct_payable": ("balancesheet", "应付账款", "ACCOPAYA"),
    "accounts_pay": ("balancesheet", "应付票据及应付账款", "NOTESACCOPAYA"),
    "c_pay_acq_const_fiolta": ("cashflow", "购建长期资产支付的现金", "ACQUASSETCASH"),
}
DETAIL_FIELDS = {
    table: frozenset(f for f, (t, _, _) in DETAIL_FIELD_REGISTRY.items() if t == table)
    for table in FINANCIAL_FIELDS
}
DETAIL_LABELS = {field: label for field, (_, label, _) in DETAIL_FIELD_REGISTRY.items()}
VERIFIABLE_FIELDS = {table: FINANCIAL_FIELDS[table] | DETAIL_FIELDS[table] for table in FINANCIAL_FIELDS}
# Single Sina code map for both baseline and detail collection.
SINA_FIELDS = {
    table: {code: field for field, (t, _, code) in (*BASELINE_FIELD_REGISTRY.items(), *DETAIL_FIELD_REGISTRY.items()) if t == table}
    for table in ("income", "balancesheet", "cashflow")
}


class _PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class NumericPredicateV1(_PlanModel):
    operator: Literal["lt", "le", "eq", "ge", "gt"]
    # Strings retain exact decimal thresholds across JSON and binary floats.
    threshold: str = Field(pattern=r"^-?\d{1,18}(\.\d{1,12})?$", max_length=32)
    unit: str = Field(min_length=1, max_length=80)


class FinancialOperandV1(_PlanModel):
    evidence_id: str = Field(min_length=1, max_length=512)
    table: Literal["income", "balancesheet", "cashflow"]
    field: str = Field(min_length=1, max_length=80)
    report_period: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def allowlisted_field_and_date(self):
        if self.field not in VERIFIABLE_FIELDS[self.table]:
            raise ValueError("financial field is not allowlisted for table")
        date.fromisoformat(self.report_period)
        return self


class FinancialConditionV1(_PlanModel):
    kind: Literal["financial"] = "financial"
    operation: Literal["value", "difference", "growth"]
    current: FinancialOperandV1
    base: FinancialOperandV1 | None = None
    predicate: NumericPredicateV1

    @model_validator(mode="after")
    def comparable_operands(self):
        if (self.operation == "value") != (self.base is None):
            raise ValueError("comparison operations require exactly one base operand")
        if self.base is not None:
            if (self.base.table, self.base.field) != (self.current.table, self.current.field):
                raise ValueError("financial comparison requires the same field and table")
            if (
                self.base.report_period >= self.current.report_period
                or self.base.report_period[5:] != self.current.report_period[5:]
            ):
                raise ValueError("financial comparison requires earlier matching report periods")
        if self.predicate.unit != ("ratio" if self.operation == "growth" else "CNY"):
            raise ValueError("financial predicate unit does not match operation")
        return self


class MetricConditionV1(_PlanModel):
    kind: Literal["metric"] = "metric"
    metric_id: str = Field(min_length=1, max_length=120)
    predicate: NumericPredicateV1


VerificationConditionV1 = Annotated[
    FinancialConditionV1 | MetricConditionV1, Field(discriminator="kind")
]


class VerificationTaskV1(_PlanModel):
    task_id: str = Field(min_length=1, max_length=120)
    challenge_id: str = Field(min_length=1, max_length=512)
    hypothesis_id: str = Field(min_length=1, max_length=512)
    condition_role: Literal["necessary", "invalidation"]
    condition_text: str = Field(min_length=1, max_length=1200)
    check: VerificationConditionV1


class VerificationPlanV1(_PlanModel):
    schema_version: Literal["verification-plan-v1"] = "verification-plan-v1"
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    mode: Literal["company_research", "catalyst_research", "holding_review"]
    analysis_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    input_snapshot_id: str = Field(min_length=1, max_length=160)
    tasks: tuple[VerificationTaskV1, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def unique_tasks_and_date(self):
        date.fromisoformat(self.analysis_date)
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("duplicate verification task")
        # Multiple predicates must never masquerade as independent resolutions
        # of the same challenge in this bounded round.
        if len({task.challenge_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("one verification task per challenge")
        return self


class ChallengeVerificationTaskV1(_PlanModel):
    task_id: str = Field(min_length=1, max_length=120)
    challenge_id: str = Field(min_length=1, max_length=512)
    hypothesis_id: str = Field(min_length=1, max_length=512)
    proposition: str = Field(min_length=1, max_length=300)
    challenge_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    check: VerificationConditionV1


class VerificationPlanV2(VerificationPlanV1):
    schema_version: Literal["verification-plan-v2"] = "verification-plan-v2"
    tasks: tuple[ChallengeVerificationTaskV1, ...] = Field(default=(), max_length=3)


def parse_verification_plan(value):
    schema = VerificationPlanV2 if value.get("schema_version") == "verification-plan-v2" else VerificationPlanV1
    return schema.model_validate_json(json.dumps(value, allow_nan=False))


def canonical_sha256(value: BaseModel | dict) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def predicate_matches(value: Decimal, predicate: NumericPredicateV1) -> bool:
    threshold = Decimal(predicate.threshold)
    return {
        "lt": value < threshold,
        "le": value <= threshold,
        "eq": value == threshold,
        "ge": value >= threshold,
        "gt": value > threshold,
    }[predicate.operator]
