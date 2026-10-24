"""Append-only research record; V1 keeps its original two-snapshot validators."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from ._evidence_checks import EvidenceChecksV1
from ._numeric_attribution import NumericAttributionV2
from ._research_record import ResearchRecordFields, SourceEvidenceV1, _RecordModel
from ._search import EvidenceGapV1, QualifiedFieldV1, SearchBatchV1, SearchReviewV1


def qualification_key(field):
    raw = json.dumps(field.model_dump(mode='json'), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


class EvidenceSnapshotV2(_RecordModel):
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


def make_evidence_snapshot_v2(evidence: tuple[SourceEvidenceV1, ...], *, version=0,
                              parent_snapshot_id=None) -> EvidenceSnapshotV2:
    text = json.dumps([s.model_dump(mode='json') for s in evidence], ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = hashlib.sha256(text.encode()).hexdigest()
    return EvidenceSnapshotV2(version=version, snapshot_id=f'v{version}.{digest}',
        parent_snapshot_id=parent_snapshot_id, evidence_ids=tuple(s.evidence_id for s in evidence),
        content_sha256=digest)


class ResearchRecordV2(ResearchRecordFields):
    schema_version: Literal['research-record-v2'] = 'research-record-v2'
    workflow_version: Literal['evidence-production-v8'] = 'evidence-production-v8'
    construction: Literal['native'] = 'native'
    mode: Literal['company_research'] = 'company_research'
    snapshots: tuple[EvidenceSnapshotV2, ...] = Field(min_length=1, max_length=8)
    numeric_attribution: NumericAttributionV2 | None = None
    search_batches: tuple[SearchBatchV1, ...] = ()
    search_reviews: tuple[SearchReviewV1, ...] = Field(default=(), max_length=9)
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
        claims = index(self.claims, 'claim_id')
        hypotheses = index(self.hypotheses, 'hypothesis_id')
        challenges = index(self.challenges, 'challenge_id')
        snapshots = index(self.snapshots, 'snapshot_id')
        index(self.verifications, 'verification_id')
        index(self.metrics, 'metric_id')
        index(self.search_reviews, 'review_id')
        index(self.search_batches, 'batch_id')
        previous = None
        for version, snapshot in enumerate(self.snapshots):
            if snapshot.version != version or snapshot.parent_snapshot_id != (previous.snapshot_id if previous else None):
                raise ValueError('snapshot parent or version changed')
            refs(snapshot.evidence_ids, sources)
            expected = make_evidence_snapshot_v2(tuple(sources[e] for e in snapshot.evidence_ids),
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
        for hypothesis in self.hypotheses:
            claim = claims.get(hypothesis.claim_id)
            if claim is None or claim.kind != 'inference' or hypothesis.input_snapshot_id not in snapshots:
                raise ValueError('hypothesis input or inference missing')
            scope = snapshots[hypothesis.input_snapshot_id].evidence_ids
            refs(claim.evidence_ids, scope)
            for fid in claim.supporting_fact_ids:
                refs(facts[fid].evidence_ids, scope)
        for challenge in self.challenges:
            refs(challenge.target_claim_ids, claims)
            refs(challenge.evidence_ids, sources)
        for verification in self.verifications:
            if verification.challenge_id not in challenges or verification.input_snapshot_id not in snapshots or verification.output_snapshot_id not in snapshots:
                raise ValueError('verification binding missing')
            if snapshots[verification.output_snapshot_id].version <= snapshots[verification.input_snapshot_id].version:
                raise ValueError('verification must append a revision')
            refs(verification.evidence_ids, snapshots[verification.output_snapshot_id].evidence_ids)
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
        for review in self.search_reviews:
            if review.input_snapshot_id not in snapshots:
                raise ValueError('review input missing')
            refs(review.supporting_fact_ids, facts)
            refs(review.target_ids, (*hypotheses, *challenges))
            for fid in review.supporting_fact_ids:
                refs(facts[fid].evidence_ids, snapshots[review.input_snapshot_id].evidence_ids)
        for old, new in self.superseded_evidence.items():
            if old == new or old not in sources or new not in sources:
                raise ValueError('invalid evidence replacement')
        if self.assessment is not None:
            if self.assessment.input_snapshot_id != self.snapshots[-1].snapshot_id:
                raise ValueError('assessment requires final snapshot')
            refs(self.assessment.key_claim_ids, claims)
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
        from ._research_record import ResearchRecordV1
        ResearchRecordV1.validate_reference_graph(self)
        return self
