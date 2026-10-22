"""Versioned challenge propositions; model classification is not execution."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ._verification_plan import VerificationConditionV1

CHALLENGE_CHECK_POLICY = "hypothesis-directed-checks-v1"
Verifiability = Literal[
    "computable_now", "computable_unsupported", "needs_source",
    "future_observation", "not_testable",
]
UnsupportedReason = Literal[
    "field_not_supported", "metric_not_supported", "operation_not_supported",
    "input_domain_unsupported",
]
NotTestableReason = Literal["no_observable_counterevidence", "undefined_measurement"]


class _ChallengeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class FinancialRequirementV1(_ChallengeModel):
    kind: Literal["financial"] = "financial"
    table: Literal["income", "balancesheet", "cashflow"]
    # Requirements can name unsupported fields; executable operands cannot.
    field: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    report_period: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    basis: Literal["consolidated_cny"] = "consolidated_cny"

    @model_validator(mode="after")
    def valid_period(self):
        date.fromisoformat(self.report_period)
        return self


class MetricRequirementV1(_ChallengeModel):
    kind: Literal["metric"] = "metric"
    metric_id: str = Field(min_length=1, max_length=120)


class SourceRequirementV1(_ChallengeModel):
    kind: Literal["source"] = "source"
    description: str = Field(min_length=1, max_length=300)


ChallengeRequirementV1 = Annotated[
    FinancialRequirementV1 | MetricRequirementV1 | SourceRequirementV1,
    Field(discriminator="kind"),
]


class ChallengeTestV1(_ChallengeModel):
    verifiability: Verifiability | None = None
    supporting_fact_ids: tuple[str, ...] = Field(default=(), max_length=6)
    check: VerificationConditionV1 | None = None
    required_inputs: tuple[ChallengeRequirementV1, ...] = Field(default=(), max_length=8)
    required_operation: str = Field(default="value", pattern=r"^[a-z][a-z0-9_]{0,79}$")
    reason_code: UnsupportedReason | NotTestableReason | None = None
    observation_date: date | None = None

    @model_validator(mode="after")
    def closed_category(self):
        if len(set(self.supporting_fact_ids)) != len(self.supporting_fact_ids):
            raise ValueError("duplicate challenge fact")
        if len({r.model_dump_json() for r in self.required_inputs}) != len(self.required_inputs):
            raise ValueError("duplicate challenge requirement")
        category = self.verifiability
        if (category == "computable_now") != (self.check is not None):
            raise ValueError("only computable_now has an executable check")
        if category == "computable_now" and (not self.supporting_fact_ids or self.required_inputs):
            raise ValueError("computable_now binds facts and check, not missing inputs")
        if category in {"computable_unsupported", "needs_source"}:
            if not self.required_inputs:
                raise ValueError("classification requires typed inputs")
        elif self.required_inputs:
            raise ValueError("classification cannot claim missing inputs")
        reasons = {
            "computable_unsupported": {"field_not_supported", "metric_not_supported",
                                      "operation_not_supported", "input_domain_unsupported"},
            "not_testable": {"no_observable_counterevidence", "undefined_measurement"},
        }
        if category in reasons:
            if self.reason_code not in reasons[category]:
                raise ValueError("classification requires a matching reason")
        elif self.reason_code is not None:
            raise ValueError("classification cannot carry this reason")
        if (category == "future_observation") != (self.observation_date is not None):
            raise ValueError("only future_observation carries a future date")
        if self.required_operation != "value" and category not in {"computable_unsupported", "needs_source"}:
            raise ValueError("required operation belongs to input requirements")
        return self


class ChallengeInputAvailabilityV1(_ChallengeModel):
    input_index: int = Field(ge=0, le=7, strict=True)
    availability: Literal["available", "missing", "unqualified", "availability_unknown"]
    reason: str = Field(min_length=1, max_length=80)
    evidence_ids: tuple[str, ...] = ()


class ChallengeCheckOutcomeV1(_ChallengeModel):
    challenge_id: str = Field(min_length=1, max_length=512)
    state: Literal["not_generated", "completed", "budget_refused", "cancelled", "unknown"]
    reason: Verifiability | Literal["minor_unclassified"] | None = None
    task_id: str | None = Field(default=None, min_length=1, max_length=120)
    plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    inputs: tuple[ChallengeInputAvailabilityV1, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def no_fabricated_task(self):
        if self.state == "not_generated":
            if self.reason in {None, "computable_now"} or self.task_id or self.plan_sha256:
                raise ValueError("ungenerated check requires classification only")
        elif self.reason is not None or not self.task_id or not self.plan_sha256 or self.inputs:
            raise ValueError("generated check requires task and plan binding")
        return self
