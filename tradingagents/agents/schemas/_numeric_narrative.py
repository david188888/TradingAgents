"""Closed, host-owned numeric anchors; model text cannot create their values."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NUMERIC_CATALOG_LIMIT = 512
NUMERIC_METADATA_KEYS = frozenset({
    "report_period", "prior_period", "period", "frequency", "observation_role",
    "as_of", "quote_timestamp", "quote_basis", "adjustment_anchor", "price_basis",
    "window_start", "window_end", "sample_size", "tail_sample_size", "forecast_year",
    "published", "institution", "report_id", "classification", "segment", "page",
    "raw_unit", "check_id", "check_status", "source_basis", "window_label",
})
NUMERIC_SELECTOR_KEYS = frozenset({
    "table", "field", "report_period", "attribute", "metric_id", "check_id",
    "observation_key", "component", "window_label", "anchor_id", "classification",
    "segment", "page", "forecast_year", "report_id", "institution", "as_of",
})
NUMERIC_LINEAGE_KEYS = frozenset({
    "kind", "source_name", "source_family_id", "source_content_sha256",
    "source_selector", "calculation_version", "input_sha256", "operands",
})


class _NumericModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class NumericAnchorV1(_NumericModel):
    anchor_id: str = Field(min_length=1, max_length=160)
    definition_key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=300)
    basis: Literal["actual_reported", "observed_quote", "institution_forecast",
                   "computed_statistic", "accounting_check", "valuation_reference"]
    value: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=80)
    required_fact_ids: tuple[str, ...] = Field(min_length=1)
    input_evidence_ids: tuple[str, ...] = Field(min_length=1)
    snapshot_id: str = Field(min_length=1, max_length=200)
    metadata: dict[str, str | int] = Field(default_factory=dict)
    lineage: dict[str, Any]
    limitations: tuple[str, ...] = ()

    @field_validator("value")
    @classmethod
    def finite_decimal(cls, value):
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError("numeric anchor value invalid") from None
        if not number.is_finite():
            raise ValueError("numeric anchor value invalid")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def closed_metadata(cls, value):
        if (not isinstance(value, dict) or not value.keys() <= NUMERIC_METADATA_KEYS
                or any(type(item) not in (str, int) for item in value.values())):
            raise ValueError("numeric anchor metadata invalid")
        return value

    @field_validator("lineage")
    @classmethod
    def closed_lineage(cls, value):
        if not value.keys() <= NUMERIC_LINEAGE_KEYS or value.get("kind") not in {"source", "calculation"}:
            raise ValueError("numeric anchor lineage invalid")
        selector = value.get("source_selector", {})
        if (not isinstance(selector, dict) or not selector.keys() <= NUMERIC_SELECTOR_KEYS
                or any(type(item) not in (str, int) for item in selector.values())):
            raise ValueError("numeric anchor selector invalid")
        for key in ("source_content_sha256", "input_sha256"):
            digest = value.get(key)
            if digest is not None and (not isinstance(digest, str) or len(digest) != 64
                                       or any(c not in "0123456789abcdef" for c in digest)):
                raise ValueError("numeric anchor digest invalid")
        if value["kind"] == "source" and not value.get("source_content_sha256"):
            raise ValueError("numeric anchor source digest missing")
        if value["kind"] == "calculation" and not all(value.get(k) for k in ("calculation_version", "input_sha256")):
            raise ValueError("numeric anchor calculation lineage missing")
        # Operands are other stable source/anchor identities, never expressions.
        if "operands" in value and (not isinstance(value["operands"], list)
                                    or any(not isinstance(item, str) for item in value["operands"])):
            raise ValueError("numeric anchor operands invalid")
        return value


class NumericMetadataV1(_NumericModel):
    meta_id: str = Field(min_length=1, max_length=160)
    kind: Literal["identity", "period", "source_title"]
    text: str = Field(min_length=1, max_length=1200)
    required_fact_ids: tuple[str, ...] = ()
    input_evidence_ids: tuple[str, ...] = ()


class NumericCatalogV1(_NumericModel):
    schema_version: Literal["numeric-catalog-v1"] = "numeric-catalog-v1"
    anchors: tuple[NumericAnchorV1, ...] = ()
    metadata: tuple[NumericMetadataV1, ...] = ()
    availability: Literal["available", "unavailable"] = "available"
    reason_code: Literal["numeric_catalog_limit"] | None = None

    @model_validator(mode="after")
    def closed_availability(self):
        if len(self.anchors) + len(self.metadata) > NUMERIC_CATALOG_LIMIT:
            raise ValueError("numeric_catalog_limit")
        if len({a.anchor_id for a in self.anchors}) != len(self.anchors):
            raise ValueError("numeric anchor identity duplicate")
        if len({m.meta_id for m in self.metadata}) != len(self.metadata):
            raise ValueError("numeric metadata identity duplicate")
        if self.availability == "unavailable":
            if self.reason_code != "numeric_catalog_limit" or self.anchors or self.metadata:
                raise ValueError("numeric catalog unavailable shape invalid")
        elif self.reason_code is not None:
            raise ValueError("numeric catalog available reason invalid")
        return self
