"""Closed search proposals and admitted material, independent of model providers."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._research_record import RecordClaimV1, SourceEvidenceV1

Provider = Literal['deepseek', 'tavily']
Role = Literal['operating_quality', 'event_context', 'market_context']


class SearchModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)


class FieldRequirementV1(SearchModel):
    ticker: str = Field(min_length=1, max_length=32)
    field: str = Field(min_length=1, max_length=100)
    period: date | None = None
    window_start: date | None = None
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = None
    basis: str = Field(min_length=1, max_length=100)


class QualifiedFieldV1(FieldRequirementV1):
    value: str = Field(min_length=1, max_length=1000)
    evidence_id: str = Field(min_length=1, max_length=512)
    locator: str = Field(min_length=1, max_length=500)
    source_content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @field_validator('value', mode='before')
    @classmethod
    def explicit_value(cls, value):
        if isinstance(value, bool) or value is None:
            raise ValueError('field requires an explicit value')
        return str(value)

    @model_validator(mode='after')
    def numeric_value(self):
        if self.unit != 'text':
            try:
                number = Decimal(self.value)
            except InvalidOperation:
                raise ValueError('numeric field is not a number') from None
            if not number.is_finite():
                raise ValueError('numeric field must be finite')
        return self


class EvidenceGapV1(SearchModel):
    gap_id: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=400)
    capability: str = Field(min_length=1, max_length=100)
    role: Role
    priority: Literal['critical', 'material', 'minor']
    cutoff: date
    evidence_needed: str = Field(min_length=1, max_length=400)
    rationale: str = Field(min_length=1, max_length=400)
    target_ids: tuple[str, ...] = Field(default=(), max_length=6)
    requirements: tuple[FieldRequirementV1, ...] = Field(default=(), max_length=16)


class SearchGapsV1(SearchModel):
    gaps: tuple[EvidenceGapV1, ...] = Field(default=(), max_length=3)


class SearchReviewProposalV1(SearchModel):
    disposition: Literal['maintained', 'revised', 'withdrawn', 'unanswerable']
    rationale: str = Field(min_length=1, max_length=1200)
    supporting_fact_ids: tuple[str, ...] = Field(default=(), max_length=12)
    new_risks: tuple[str, ...] = Field(default=(), max_length=3)

    @model_validator(mode='after')
    def judgement_requires_facts(self):
        if self.disposition in ('maintained', 'revised') and not self.supporting_fact_ids:
            raise ValueError('review judgement requires facts')
        return self


class SearchRequestV1(SearchModel):
    task_id: str = Field(min_length=1, max_length=200)
    provider: Provider
    kind: Literal['initial', 'recovery', 'supplement']
    role: Role = 'event_context'
    capability: str = Field(default='context', min_length=1, max_length=100)
    ticker: str = Field(min_length=1, max_length=32)
    company_name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=400)
    cutoff: date
    start_date: date | None = None
    round_id: int = Field(default=0, ge=0, le=3)
    gap_id: str | None = None
    depth: Literal['basic', 'advanced'] = 'basic'
    requirements: tuple[FieldRequirementV1, ...] = Field(default=(), max_length=16)

    @model_validator(mode='after')
    def request_scope(self):
        if not self.query.strip() or self.start_date and self.start_date > self.cutoff:
            raise ValueError('invalid search query or date window')
        if (self.kind == 'supplement') != (self.round_id > 0):
            raise ValueError('supplement requires a bounded research round')
        return self


class SearchDocumentPageV1(SearchModel):
    page: int = Field(ge=1, le=500)
    text: str = Field(min_length=1, max_length=4000)
    truncated: bool = False


class SearchDocumentV1(SearchModel):
    pdf_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    parser_version: Literal['official-pdf-v2']
    security_id: str
    title: str = Field(max_length=2000)
    page_count: int = Field(ge=1, le=500)
    pages: tuple[SearchDocumentPageV1, ...] = Field(max_length=12)


class SearchHitV1(SearchModel):
    provider: Provider
    url: str = Field(min_length=1, max_length=8192)
    canonical_url: str = Field(min_length=1, max_length=8192)
    title: str = Field(default='', max_length=2000)
    summary: str = Field(default='', max_length=8000)
    content: str = Field(default='', max_length=200000)
    published_at: datetime | None = None
    published_precision: Literal['timestamp', 'day'] = 'timestamp'
    publisher: str | None = None
    score: float | None = None
    authority: int | None = Field(default=None, ge=-1, le=4)
    family_id: str | None = None
    truncated: bool = False
    document: SearchDocumentV1 | None = None

    @field_validator('url', 'canonical_url')
    @classmethod
    def public_link(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('unsafe search URL')
        if any(any(part in key.lower() for part in ('token', 'secret', 'key', 'signature', 'auth'))
               for key, _ in parse_qsl(parsed.query)):
            raise ValueError('credential-shaped search URL')
        return value

    @field_validator('published_at')
    @classmethod
    def aware_date(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('search date requires timezone')
        return value


class SearchOutcomeV1(SearchModel):
    task_id: str
    provider: Provider
    status: Literal['ok', 'empty', 'unavailable', 'failed', 'refused']
    hits: tuple[SearchHitV1, ...] = Field(default=(), max_length=16)
    reason: str | None = None
    retryable: bool = False
    usage: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def explicit_outcome(self):
        if (self.status == 'ok') != bool(self.hits):
            raise ValueError('only successful search has hits')
        if self.status not in ('ok', 'empty') and not self.reason:
            raise ValueError('failure requires an explicit reason')
        return self


class SearchBatchV1(SearchModel):
    batch_id: str
    input_snapshot_id: str
    requests: tuple[SearchRequestV1, ...] = Field(default=(), max_length=100)
    outcomes: tuple[SearchOutcomeV1, ...] = Field(default=(), max_length=200)
    hits: tuple[SearchHitV1, ...] = Field(default=(), max_length=800)
    stop_reasons: tuple[str, ...] = ()


class AdmittedObservationV1(SearchModel):
    source: SourceEvidenceV1
    fact: RecordClaimV1
    role: Role
    capability: str

    @model_validator(mode='after')
    def binds_source(self):
        if self.fact.kind != 'fact' or self.fact.evidence_ids != (self.source.evidence_id,):
            raise ValueError('observation requires its own saved source')
        return self


class AdmissionBatchV1(SearchModel):
    batch_id: str
    observations: tuple[AdmittedObservationV1, ...] = ()
    fields: tuple[QualifiedFieldV1, ...] = ()
    rejections: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


class SearchReviewV1(SearchModel):
    review_id: str
    round_id: int = Field(ge=1, le=3)
    role: Role
    input_snapshot_id: str
    target_ids: tuple[str, ...] = ()
    disposition: Literal['maintained', 'revised', 'withdrawn', 'unanswerable']
    rationale: str = Field(min_length=1, max_length=1200)
    supporting_fact_ids: tuple[str, ...] = Field(default=(), max_length=12)
    new_risks: tuple[str, ...] = Field(default=(), max_length=3)
    gaps: tuple[EvidenceGapV1, ...] = Field(default=(), max_length=3)

    @model_validator(mode='after')
    def bound_review(self):
        if self.disposition in ('maintained', 'revised') and not self.supporting_fact_ids:
            raise ValueError('review judgement requires facts')
        return self
