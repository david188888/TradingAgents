"""Code-selected basic company facts, with explicit public claim bindings."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompanyBasicFieldV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str = Field(min_length=1, max_length=80)
    claim_id: str = Field(min_length=1, max_length=512)
    report_period: date | None = None


class CompanyBasicsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["company-basics-v1"] = "company-basics-v1"
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    introduction: tuple[CompanyBasicFieldV1, ...] = Field(default=(), max_length=4)
    fundamentals: tuple[CompanyBasicFieldV1, ...] = Field(default=(), max_length=12)
    quantitative: tuple[CompanyBasicFieldV1, ...] = Field(default=(), max_length=12)
    gaps: tuple[str, ...] = ()
