"""Restricted model envelopes and replayable numeric compilation receipts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from ._factual_premise import PremiseBindingV1, PremiseReceiptV1

NUMERIC_NARRATIVE_POLICY = "anchored-narrative-v1"
NUMERIC_LEXER_VERSION = "quantity-lexer-v1"


class _NumericModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NumericPlanV1(_NumericModel):
    alias: str = Field(pattern=r"^p_[a-zA-Z0-9_]{1,48}$")
    field_path: str = Field(min_length=1, max_length=200)
    kind: Literal["quantity", "date"]
    threshold: str | None = Field(default=None, pattern=r"^-?\d{1,18}(\.\d{1,12})?$")
    unit: Literal["CNY", "CNY/share", "ratio", "percent", "multiple", "count"] | None = None
    operator: Literal["lt", "le", "eq", "ge", "gt"] | None = None
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def closed_parameters(self):
        if self.kind == "quantity":
            if self.threshold is None or self.unit is None or self.operator is None or self.date is not None:
                raise ValueError("numeric quantity plan parameters invalid")
        elif self.date is None or any(v is not None for v in (self.threshold, self.unit, self.operator)):
            raise ValueError("numeric date plan parameters invalid")
        return self


class NumericStructuredBindingV1(_NumericModel):
    field_path: str = Field(min_length=1, max_length=200)
    kind: Literal["num", "plan"]
    alias: str = Field(pattern=r"^[np]_[a-zA-Z0-9_]{1,48}$")


class NumericStageEnvelopeV1(_NumericModel):
    proposal: dict
    plans: tuple[NumericPlanV1, ...] = Field(default=(), max_length=64)
    structured_bindings: tuple[NumericStructuredBindingV1, ...] = Field(default=(), max_length=64)
    premises: tuple[PremiseBindingV1, ...] | None = Field(default=None, max_length=64)

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler):
        value = handler(self)
        if self.premises is None:
            value.pop("premises", None)
        return value


class NumericSegmentV1(_NumericModel):
    kind: Literal["literal", "num", "meta", "plan", "inherited"]
    text: str
    alias: str | None = None
    anchor_id: str | None = None
    parameters: dict | None = None


class NumericFieldProofV1(_NumericModel):
    path: str
    segments: tuple[NumericSegmentV1, ...]
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    lexer_version: Literal["quantity-lexer-v1"] = NUMERIC_LEXER_VERSION
    premise: PremiseReceiptV1 | None = None

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler):
        value = handler(self)
        if self.premise is None:
            value.pop("premise", None)
        return value


class NumericRejectionV1(_NumericModel):
    index: int = Field(ge=0, le=2, strict=True)
    code: Literal[
        "specialist_fact_reference", "condition_evidence_reference", "condition_metric_reference",
        "numeric_literal_unbound", "numeric_anchor_unknown", "numeric_anchor_scope",
        "numeric_basis_mismatch", "numeric_plan_mismatch", "numeric_render_limit",
        "premise_binding_invalid", "premise_binding_missing", "premise_observation_unknown",
        "premise_observation_scope", "premise_support_missing", "numeric_manifest_binding", "numeric_catalog_limit",
        "numeric_proposal_schema", "numeric_envelope_schema", "numeric_catalog_invalid",
        "numeric_cutoff_invalid", "numeric_condition_reference", "numeric_receipt_invalid",
        "challenge_schema_invalid", "challenge_fact_reference", "challenge_check_scope",
        "challenge_future_date", "challenge_check_unavailable", "challenge_requirement_invalid",
        "challenge_target_reference", "challenge_condition_reference",
    ]


class NumericStageProofV1(_NumericModel):
    policy: Literal["anchored-narrative-v1"] = NUMERIC_NARRATIVE_POLICY
    stage: str
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    proposal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    catalog_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    envelope: NumericStageEnvelopeV1
    fields: tuple[NumericFieldProofV1, ...]
    indices: tuple[int, ...] = ()
    rejections: tuple[NumericRejectionV1, ...] = ()
