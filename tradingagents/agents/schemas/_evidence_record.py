"""Append-only research record; V1 keeps its original two-snapshot validators."""

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from ._company_basics import CompanyBasicsV1
from ._evidence import (
    NativeValuationV1,
    QuantitativeMetricV1,
    RecordClaimV1,
    SourceEvidenceV1,
    _RecordModel,
)
from ._evidence_checks import EvidenceChecksV1
from ._search import EvidenceGapV1, QualifiedFieldV1, SearchBatchV1


def qualification_key(field):
    raw = json.dumps(field.model_dump(mode='json'), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


class EvidenceSnapshot(_RecordModel):
    version: int = Field(ge=0, le=7)
    snapshot_id: str = Field(min_length=1, max_length=160)
    parent_snapshot_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class RevisionCalculationV1(_RecordModel):
    calculation_id: str
    input_snapshot_id: str
    inputs_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    field: str
    period: str
    prior_period: str | None = None
    operation: Literal['value', 'difference', 'growth']
    status: Literal['available', 'conflict', 'unavailable']
    value: str | None = None
    unit: str
    input_evidence_ids: tuple[str, ...]
    derived_evidence_id: str


def make_evidence_snapshot(evidence: tuple[SourceEvidenceV1, ...], *, version=0,
                              parent_snapshot_id=None) -> EvidenceSnapshot:
    text = json.dumps([s.model_dump(mode='json') for s in evidence], ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return EvidenceSnapshot(version=version, snapshot_id=f'v{version}.{digest}',
        parent_snapshot_id=parent_snapshot_id, evidence_ids=tuple(s.evidence_id for s in evidence),
        content_sha256=digest)


class EvidenceRecord(_RecordModel):
    schema_version: Literal['evidence-record-v1'] = 'evidence-record-v1'
    workflow_version: Literal['evidence-production-v9'] = 'evidence-production-v9'
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    analysis_date: date
    evidence: tuple[SourceEvidenceV1, ...] = ()
    claims: tuple[RecordClaimV1, ...] = ()
    metrics: tuple[QuantitativeMetricV1, ...] = ()
    valuation: NativeValuationV1 | None = None
    evidence_checks: EvidenceChecksV1 | None = None
    company_basics: CompanyBasicsV1 | None = None
    limitations: tuple[str, ...] = ()
    construction: Literal['native'] = 'native'
    mode: Literal['company_research'] = 'company_research'
    snapshots: tuple[EvidenceSnapshot, ...] = Field(min_length=1, max_length=8)
    search_batches: tuple[SearchBatchV1, ...] = ()
    search_gaps: tuple[EvidenceGapV1, ...] = ()
    search_stop_reasons: tuple[str, ...] = ()
    recovered_fields: tuple[QualifiedFieldV1, ...] = ()
    qualification_snapshots: dict[str, str] = Field(default_factory=dict)
    revision_calculations: tuple[RevisionCalculationV1, ...] = ()
    superseded_evidence: dict[str, str] = Field(default_factory=dict)
    check_revisions: tuple[EvidenceChecksV1, ...] = Field(default=(), max_length=7)

    @model_validator(mode='after')
    def revision_graph(self):
        def index(items, key):
            result = {getattr(item, key): item for item in items}
            if len(result) != len(items):
                raise ValueError('duplicate research identifier')
            return result

        def refs(ids, allowed):
            if len(set(ids)) != len(ids) or not set(ids) <= set(allowed):
                raise ValueError('duplicate or dangling research reference')

        sources = index(self.evidence, 'evidence_id')
        index(self.claims, 'claim_id')
        snapshots = index(self.snapshots, 'snapshot_id')
        index(self.metrics, 'metric_id')
        index(self.search_batches, 'batch_id')
        previous = None
        for version, snapshot in enumerate(self.snapshots):
            if snapshot.version != version or snapshot.parent_snapshot_id != (previous.snapshot_id if previous else None):
                raise ValueError('snapshot parent or version changed')
            refs(snapshot.evidence_ids, sources)
            expected = make_evidence_snapshot(tuple(sources[e] for e in snapshot.evidence_ids),
                version=version, parent_snapshot_id=snapshot.parent_snapshot_id)
            if snapshot != expected or previous and not set(previous.evidence_ids) <= set(snapshot.evidence_ids):
                raise ValueError('snapshot content changed or evidence removed')
            previous = snapshot
        if set(self.snapshots[-1].evidence_ids) != set(sources):
            raise ValueError('evidence outside final snapshot')
        for source in self.evidence:
            if any(t and t.date() > self.analysis_date for t in (source.published_at, source.usable_as_of)):
                raise ValueError('source is after cutoff')
        facts = {c.claim_id: c for c in self.claims if c.kind == 'fact'}
        for claim in self.claims:
            refs(claim.evidence_ids, sources)
            refs(claim.supporting_fact_ids, facts)
        from tradingagents.dataflows.ticker_utils import to_tushare_symbol
        if set(self.qualification_snapshots) != {qualification_key(f) for f in self.recovered_fields}:
            raise ValueError('field qualification version missing or dangling')
        for field in self.recovered_fields:
            introduction = snapshots.get(self.qualification_snapshots[qualification_key(field)])
            if introduction is None or field.evidence_id not in introduction.evidence_ids:
                raise ValueError('field qualification precedes its source')
            if to_tushare_symbol(field.ticker) != to_tushare_symbol(self.ticker):
                raise ValueError('recovered field company identity differs')
            source = sources.get(field.evidence_id)
            if source is None or source.content is None or source.content.truncated or source.content.content_sha256 != field.source_content_sha256:
                raise ValueError('recovered field lineage missing')
            from tradingagents.research.search_recovery import recover_fields

            from ._search import AdmissionBatchV1, AdmittedObservationV1, FieldRequirementV1
            candidate = next((f for f in facts.values() if f.evidence_ids == (source.evidence_id,)), None)
            if candidate is None:
                raise ValueError('recovered field requires a saved source observation')
            requirement = FieldRequirementV1.model_validate(field.model_dump(include=set(FieldRequirementV1.model_fields)))
            checked = recover_fields(AdmissionBatchV1(batch_id='validate', observations=(
                AdmittedObservationV1(source=source, fact=candidate, role='operating_quality', capability='financial'),)),
                requirements=(requirement,))
            if field not in checked.fields:
                raise ValueError('recovered value differs from original source')
        for old, new in self.superseded_evidence.items():
            if old == new or old not in sources or new not in sources:
                raise ValueError('invalid evidence replacement')
        if self.revision_calculations:
            from tradingagents.research.evidence_revisions import validate_revision_calculations
            validate_revision_calculations(self)
        if self.check_revisions:
            from tradingagents.research.minimum_evidence import compute_checks
            seen = set()
            for checks in self.check_revisions:
                snapshot = snapshots.get(checks.input_snapshot_id)
                if snapshot is None or snapshot.snapshot_id in seen:
                    raise ValueError('check revision input missing or duplicated')
                seen.add(snapshot.snapshot_id)
                from tradingagents.research.record_codec import snapshot_view
                view = snapshot_view(self, snapshot.snapshot_id)
                if compute_checks(view) != checks:
                    raise ValueError('saved check revision changed')
        for metric in self.metrics:
            refs(metric.input_evidence_ids, sources)
            if metric.window_end and metric.window_end > self.analysis_date:
                raise ValueError("metric window is after research cutoff")
            if metric.availability == "available" and any(sources[eid].availability != "available" for eid in metric.input_evidence_ids):
                raise ValueError("available metrics require qualified input evidence")
        if self.valuation is not None:
            value = self.valuation.inputs
            if (value.run_id, value.ticker, value.as_of) != (self.run_id, self.ticker, self.analysis_date):
                raise ValueError("valuation identity mismatch")
            refs(self.valuation.input_evidence_ids, sources)
            if value.snapshot is None or value.snapshot.as_of > self.analysis_date:
                raise ValueError("valuation snapshot missing or after cutoff")
            if any(item.day > self.analysis_date for item in (*value.pe_history, *value.pb_history)):
                raise ValueError("valuation history after cutoff")
        if self.company_basics is not None:
            from tradingagents.research.native_versions import REPORT_DELIVERY_POLICY
            if REPORT_DELIVERY_POLICY not in self.limitations:
                raise ValueError("company basics require the frozen delivery policy")
            for field in (*self.company_basics.introduction, *self.company_basics.fundamentals, *self.company_basics.quantitative):
                refs((field.claim_id,), facts)
                if field.report_period is not None and field.report_period > self.analysis_date:
                    raise ValueError("company basic period after cutoff")
                if any(sources[eid].availability != "available" or sources[eid].content is None or sources[eid].usable_as_of is None
                       for eid in facts[field.claim_id].evidence_ids):
                    raise ValueError("company basics require qualified saved facts")
        if self.evidence_checks is not None:
            from tradingagents.research.minimum_evidence import compute_checks
            if self.evidence_checks != compute_checks(self):
                raise ValueError("saved evidence checks changed")
        return self
