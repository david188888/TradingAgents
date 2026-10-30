"""Independent Insight contracts: models propose, the host resolves provenance."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from ._company_basics import CompanyBasicsV1
from ._numeric_narrative import NumericAnchorV1
from ._research_record import SourceEvidenceV1


class _InsightModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class InsightProposal(_InsightModel):
    claim: str
    evidence_refs: tuple[str, ...]
    reasoning: str
    limitations: str

    @field_validator('claim', 'reasoning', 'limitations')
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip():
            raise ValueError('insight_text_empty')
        return value


class InsightSubmission(_InsightModel):
    insights: tuple[InsightProposal, ...]
    search_requests: tuple[str, ...] = ()


class EvidenceCard(_InsightModel):
    ref: str
    fact_id: str
    text: str
    source_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class NumericReference(_InsightModel):
    ref: str
    anchor: NumericAnchorV1


class InsightCatalog(_InsightModel):
    snapshot_id: str
    sources: tuple[SourceEvidenceV1, ...]
    evidence: tuple[EvidenceCard, ...]
    numbers: tuple[NumericReference, ...] = ()


class InsightText(_InsightModel):
    claim: str
    reasoning: str
    limitations: str


InsightIssue = Literal['evidence_missing', 'reference_unknown', 'source_unavailable',
    'numeric_literal_unbound', 'numeric_scope']


class SavedInsight(_InsightModel):
    insight_id: str
    role: str
    index: int
    revision: int
    snapshot_id: str
    catalog_id: str
    status: Literal['accepted', 'pending', 'excluded']
    proposal: InsightProposal
    rendered: InsightText
    fact_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    numeric_ids: tuple[str, ...]
    issues: tuple[InsightIssue, ...] = ()


class InsightRejection(_InsightModel):
    index: int
    code: Literal['insight_schema_invalid'] = 'insight_schema_invalid'
    fields: tuple[str, ...] = ()


class InsightBatch(_InsightModel):
    items: tuple[SavedInsight, ...] = ()
    rejected: tuple[InsightRejection, ...] = ()


class ReviewProposal(_InsightModel):
    target: str
    concern: str | None
    reasoning: str
    evidence_refs: tuple[str, ...]


class ReviewSubmission(_InsightModel):
    reviews: tuple[ReviewProposal, ...]


class ResponseProposal(_InsightModel):
    target: str
    action: Literal['maintain', 'revise', 'withdraw', 'uncertain']
    reasoning: str
    evidence_refs: tuple[str, ...]
    replacement: InsightProposal | None


class ResponseSubmission(_InsightModel):
    responses: tuple[ResponseProposal, ...]


class SynthesisProposal(_InsightModel):
    judgement: str
    stance: Literal['favorable', 'neutral', 'unfavorable'] | None
    insight_refs: tuple[str, ...]
    reasoning: str
    limitations: str
    next_check: str

    @field_validator('judgement', 'reasoning', 'limitations', 'next_check')
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip():
            raise ValueError('synthesis_text_empty')
        return value


class SavedReview(_InsightModel):
    note: SavedInsight | None = None
    target_id: str
    status: Literal['challenged', 'no_counterevidence', 'unreviewed', 'failed']
    concern: str | None = None
    reasoning: str = ''
    source_ids: tuple[str, ...] = ()


class SavedResponse(_InsightModel):
    note: SavedInsight
    target_id: str
    action: Literal['maintain', 'revise', 'withdraw', 'uncertain']
    reasoning: str
    source_ids: tuple[str, ...] = ()
    replacement_id: str | None = None


class SavedSynthesis(_InsightModel):
    judgement: str
    stance: Literal['favorable', 'neutral', 'unfavorable'] | None
    reasoning: str
    limitations: str
    next_check: str
    insight_ids: tuple[str, ...]
    reference_ids: dict[str, str]


class InsightReport(_InsightModel):
    schema_version: Literal['insight-research-v1'] = 'insight-research-v1'
    construction: Literal['native'] = 'native'
    run_id: str
    ticker: str
    mode: Literal['company_research'] = 'company_research'
    analysis_date: date
    catalogs: dict[str, InsightCatalog]
    insights: tuple[SavedInsight, ...]
    reviews: tuple[SavedReview, ...] = ()
    responses: tuple[SavedResponse, ...] = ()
    synthesis: SavedSynthesis | None = None
    gaps: tuple[str, ...] = ()
    stages: dict[str, str] = {}
    superseded_ids: tuple[str, ...] = ()
    search_requests: dict[str, tuple[str, ...]] = {}
    company_basics: CompanyBasicsV1 | None = None
    focus_question: str | None = None
    focus_insights: tuple[SavedInsight, ...] = ()
