"""Frozen operands and closed local questions for evidence-production-v5."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CheckId = Literal["operating_disclosures", "cash_conversion", "valuation_context"]
QuestionScope = Literal[
    "operating_disclosures.current_period_coverage",
    "cash_conversion.reported_bridge",
    "valuation_context.supplementary_positioning",
]
ObservedRisk = Literal["cash_conversion.cfo_yoy_decline"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class OfficialNumericRowV1(_Frozen):
    """One explicitly headed current/prior row; blanks remain undisclosed."""

    kind: Literal["financial", "cash_bridge", "operating"]
    field: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=180)
    period: date
    prior_period: date
    frequency: Literal["H1", "FY", "Q2"]
    unit: str = Field(min_length=1, max_length=40)
    raw_unit: str = Field(min_length=1, max_length=40)
    raw_current: str | None = Field(default=None, max_length=40)
    raw_previous: str | None = Field(default=None, max_length=40)
    current: str | None = Field(default=None, max_length=80)
    previous: str | None = Field(default=None, max_length=80)
    page: int = Field(ge=1, le=500)
    header_page: int = Field(ge=1, le=500)
    raw_header: str = Field(min_length=1, max_length=600)
    raw_row: str = Field(min_length=1, max_length=900)

    @model_validator(mode="after")
    def exact_units_and_periods(self):
        if (self.period.month, self.period.day) != (self.prior_period.month, self.prior_period.day) or self.period.year != self.prior_period.year + 1:
            raise ValueError("official row requires matching current/prior periods")
        expected = (12, 31) if self.frequency == "FY" else (6, 30)
        if (self.period.month, self.period.day) != expected or self.header_page > self.page:
            raise ValueError("official row period/header invalid")
        if self.kind == "cash_bridge" and self.page - self.header_page > 1:
            raise ValueError("cash bridge header must be on this or adjacent page")
        if self.kind != "operating" and (self.unit != "CNY" or self.raw_unit not in {"元", "万元", "百万元", "亿元"}):
            raise ValueError("financial row requires explicit CNY units")
        if self.kind == "operating" and self.unit != self.raw_unit:
            raise ValueError("operating row must preserve its physical unit")
        scale = {"元": 1, "万元": 10000, "百万元": 1000000, "亿元": 100000000}.get(self.raw_unit, 1) if self.unit == "CNY" else 1
        for raw, normalized in ((self.raw_current, self.current), (self.raw_previous, self.previous)):
            if raw is None:
                if normalized is not None:
                    raise ValueError("undisclosed cell cannot become a number")
                continue
            if not re.fullmatch(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", raw):
                raise ValueError("official numeric cell must be an explicit decimal")
            try:
                original, value = Decimal(raw.replace(",", "")), Decimal(normalized)
            except (InvalidOperation, TypeError):
                raise ValueError("invalid official numeric cell") from None
            if not original.is_finite() or not value.is_finite() or original * scale != value:
                raise ValueError("official row unit normalization changed")
        return self


class DatedForecastV1(_Frozen):
    ts_code: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    institution: str = Field(min_length=1, max_length=120)
    analyst: str | None = Field(default=None, max_length=120)
    report_id: str = Field(min_length=1, max_length=160)
    published: date
    forecast_year: int = Field(ge=2000, le=2100)
    eps: str = Field(min_length=1, max_length=80)
    unit: Literal["CNY/share"] = "CNY/share"
    year_basis: Literal["explicit_header", "response_currentYear"]

    @model_validator(mode="after")
    def positive_forecast(self):
        if not re.fullmatch(r"\d+(?:\.\d+)?", self.eps):
            raise ValueError("forecast EPS must be an explicit decimal")
        try:
            number = Decimal(self.eps)
        except InvalidOperation:
            raise ValueError("forecast EPS invalid") from None
        if not number.is_finite() or number <= 0:
            raise ValueError("forecast EPS must be positive")
        return self


class CheckObservationV1(_Frozen):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=80)
    method: str = Field(min_length=1, max_length=500)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class PeerCandidateV1(_Frozen):
    ts_code: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    name: str = Field(min_length=1, max_length=120)
    financial_period: date | None = None


class PeerSelectionV1(_Frozen):
    target_ts_code: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    candidates: tuple[PeerCandidateV1, ...] = Field(max_length=5)
    reported_population: int | None = Field(default=None, ge=1)
    selection_method: Literal["eastmoney_industry_candidates"] = "eastmoney_industry_candidates"

    @model_validator(mode="after")
    def unique_candidates(self):
        codes = [c.ts_code for c in self.candidates]
        if len(set(codes)) != len(codes) or self.target_ts_code in codes:
            raise ValueError("peer candidates duplicate or contain the target")
        return self


class PeerQuoteV1(_Frozen):
    target_ts_code: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    ts_code: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    name: str = Field(min_length=1, max_length=120)
    as_of: date
    quote_timestamp: datetime
    price: float = Field(gt=0, strict=True)
    total_market_cap_yi: float = Field(gt=0, strict=True)
    currency: Literal["CNY"] = "CNY"
    pe_ttm: float | None = Field(default=None, gt=0, strict=True)
    pb: float | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def quoted_session(self):
        if self.ts_code == self.target_ts_code or self.quote_timestamp.tzinfo is None or self.quote_timestamp.date() != self.as_of:
            raise ValueError("peer quote identity/session invalid")
        return self


class LocalEvidenceCheckV1(_Frozen):
    check_id: CheckId
    question_scope: QuestionScope
    question: str = Field(min_length=1, max_length=300)
    status: Literal["passed", "unavailable", "conflict"]
    satisfied: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    observations: tuple[CheckObservationV1, ...] = ()
    limitations: tuple[str, ...] = ()


class EvidenceChecksV1(_Frozen):
    schema_version: Literal["evidence-checks-v1"] = "evidence-checks-v1"
    calculation_version: Literal["minimum-evidence-v1"] = "minimum-evidence-v1"
    run_id: str
    ticker: str
    analysis_date: date
    input_snapshot_id: str
    input_evidence_ids: tuple[str, ...]
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    checks: tuple[LocalEvidenceCheckV1, ...] = Field(min_length=3, max_length=3)


class ChallengeCheckBindingV1(_Frozen):
    challenge_id: str = Field(min_length=1, max_length=512)
    check_id: CheckId | None = None
    observed_risk: ObservedRisk | None = None
    observation_date: date | None = None

    @model_validator(mode="after")
    def risk_scope(self):
        if self.observed_risk and self.check_id not in {None, "cash_conversion"}:
            raise ValueError("CFO risk cannot answer another check's question")
        return self


class ChallengeAssessmentV2(_Frozen):
    challenge_id: str = Field(min_length=1, max_length=512)
    outcome: Literal["evidence_sufficient", "risk_supported", "future_observation", "unresolved"]
    economic_outcome: Literal["unresolved"] = "unresolved"
    question_scope: QuestionScope | None = None
    answered_question: str | None = None
    check_id: CheckId | None = None
    rationale: str = Field(min_length=1, max_length=400)
    evidence_ids: tuple[str, ...] = ()
    observed_risk: ObservedRisk | None = None
    observation_date: date | None = None
    observations: tuple[CheckObservationV1, ...] = ()
    limitations: tuple[str, ...] = ()
