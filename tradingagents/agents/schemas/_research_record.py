"""Shared, evidence-bound research record; never an agent conversation log.

Compatibility producers retain the source case's claims and label converted
inferences explicitly. Only the tool verification executor may write an
executed verification. Neither a citation nor a model disposition proves it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from tradingagents.research.valuation import (
    ValuationAssessmentV1,
    ValuationInputsV1,
    assess_valuation,
)

from ._research_assessment import DIMENSIONS_BY_MODE, ResearchAssessmentV1
from ._verification_plan import canonical_sha256

RESEARCH_RECORD_CONTRACT = "research-record-v1"


class _RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SourceContentV1(_RecordModel):
    kind: Literal["excerpt", "source_fields", "saved_summary"]
    text: str = Field(min_length=1, max_length=4000)
    locator_label: str = Field(min_length=1, max_length=200)
    # Digest of the saved public content, not a private storage path.
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    truncated: bool = False

    @model_validator(mode="after")
    def content_matches_digest(self):
        import hashlib
        if hashlib.sha256(self.text.encode()).hexdigest() != self.content_sha256:
            raise ValueError("source content digest mismatch")
        return self


class SourceEvidenceV1(_RecordModel):
    evidence_id: str = Field(min_length=1, max_length=512)
    source_name: str = Field(min_length=1, max_length=512)
    source_kind: Literal["official", "vendor", "media", "derived", "analysis_report", "unknown"]
    source_family_id: str | None = Field(default=None, max_length=512)
    availability: Literal["available", "unavailable", "unverified"]
    public_url: str | None = Field(default=None, max_length=1024)
    published_at: datetime | None = None
    usable_as_of: datetime | None = None
    captured_at: datetime | None = None
    content: SourceContentV1 | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def public_source_is_safe(self):
        if self.public_url:
            parsed = urlsplit(self.public_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("unsafe public source URL")
            if any(any(part in key.lower() for part in ("token", "secret", "key", "signature", "auth"))
                   for key, _ in parse_qsl(parsed.query)):
                raise ValueError("credential-shaped source URL")
        for timestamp in (self.published_at, self.usable_as_of, self.captured_at):
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError("source timestamps require a timezone")
        if self.content is None and not self.limitations:
            raise ValueError("missing source content requires an explicit limitation")
        return self


class EvidenceSnapshotV1(_RecordModel):
    version: Literal[0, 1]
    snapshot_id: str = Field(min_length=1, max_length=160)
    parent_snapshot_id: str | None = Field(default=None, max_length=160)
    evidence_ids: tuple[str, ...] = ()
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def make_evidence_snapshot(evidence: tuple[SourceEvidenceV1, ...], *, version: Literal[0, 1] = 0,
                           parent_snapshot_id: str | None = None) -> EvidenceSnapshotV1:
    content = json.dumps([item.model_dump(mode="json") for item in evidence],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(content.encode()).hexdigest()
    return EvidenceSnapshotV1(version=version, snapshot_id=f"v{version}.{digest}",
        parent_snapshot_id=parent_snapshot_id, evidence_ids=tuple(item.evidence_id for item in evidence), content_sha256=digest)


class RecordClaimV1(_RecordModel):
    claim_id: str = Field(min_length=1, max_length=512)
    kind: Literal["fact", "inference", "unknown"]
    statement: str = Field(min_length=1, max_length=1200)
    evidence_ids: tuple[str, ...] = ()
    supporting_fact_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def kind_is_not_strengthened(self):
        if self.kind == "unknown":
            if self.evidence_ids or self.supporting_fact_ids or not self.limitations:
                raise ValueError("unknowns carry requirements, not evidence or supporting facts")
        elif not self.evidence_ids:
            raise ValueError("known claims require evidence")
        if self.kind == "fact" and self.supporting_fact_ids:
            raise ValueError("a fact cannot depend on an inference")
        if self.kind == "inference" and not self.supporting_fact_ids:
            raise ValueError("an inference requires supporting facts")
        return self


class ResearchHypothesisV1(_RecordModel):
    hypothesis_id: str = Field(min_length=1, max_length=512)
    claim_id: str = Field(min_length=1, max_length=512)
    input_snapshot_id: str = Field(min_length=1, max_length=160)
    origin: Literal["hypothesis_stage", "adapted_inference"]
    assumptions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def native_hypothesis_is_falsifiable(self):
        if self.origin == "hypothesis_stage" and not self.invalidation_conditions:
            raise ValueError("a native hypothesis requires a falsification condition")
        if self.origin == "adapted_inference" and not self.limitations:
            raise ValueError("adapted inferences must state their compatibility limit")
        return self


class ResearchChallengeV1(_RecordModel):
    challenge_id: str = Field(min_length=1, max_length=512)
    target_claim_ids: tuple[str, ...] = Field(min_length=1)
    statement: str = Field(min_length=1, max_length=400)
    severity: Literal["minor", "material", "critical"]
    risk_type: Literal["evidence_quality", "operations", "governance", "market", "valuation", "unclassified"]
    evidence_ids: tuple[str, ...] = ()
    proposed_test: str = Field(min_length=1, max_length=300)
    # A disposition is a model assessment, not a tool execution record.
    reported_disposition: str | None = Field(default=None, max_length=40)


class VerificationRecordV1(_RecordModel):
    verification_id: str = Field(min_length=1, max_length=512)
    challenge_id: str = Field(min_length=1, max_length=512)
    input_snapshot_id: str = Field(min_length=1, max_length=160)
    output_snapshot_id: str = Field(min_length=1, max_length=160)
    method: Literal["source_check", "vendor_lookup", "calculation"]
    status: Literal["supports", "contradicts", "inconclusive", "unavailable"]
    evidence_ids: tuple[str, ...] = ()
    executed_at: datetime
    result: str = Field(min_length=1, max_length=1200)
    scope: Literal["unspecified", "predicate_only"] = "unspecified"
    hypothesis_id: str | None = Field(default=None, min_length=1, max_length=512)
    plan_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    condition_role: Literal["necessary", "invalidation"] | None = None
    condition_text: str | None = Field(default=None, min_length=1, max_length=1200)

    @model_validator(mode="after")
    def execution_requires_a_basis(self):
        if self.executed_at.tzinfo is None:
            raise ValueError("verification execution requires a timezone")
        if self.status in {"supports", "contradicts"} and not self.evidence_ids:
            raise ValueError("a conclusive verification requires evidence")
        binding = (self.hypothesis_id, self.plan_sha256, self.condition_role, self.condition_text)
        if self.scope == "predicate_only" and not all(binding):
            raise ValueError("predicate verification requires hypothesis and condition binding")
        if self.scope == "unspecified" and any(binding):
            raise ValueError("condition binding requires an explicit predicate scope")
        return self


class QuantitativeMetricV1(_RecordModel):
    metric_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    availability: Literal["available", "unavailable"]
    value: float | None = None
    unit: str = Field(min_length=1, max_length=80)
    method: str = Field(min_length=1, max_length=300)
    calculation_version: str = Field(min_length=1, max_length=120)
    input_evidence_ids: tuple[str, ...] = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    window_start: date | None = None
    window_end: date | None = None
    sample_size: int | None = Field(default=None, ge=0)
    tail_sample_size: int | None = Field(default=None, ge=0)
    unavailable_reason: str | None = Field(default=None, max_length=400)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def availability_requires_provenance(self):
        if self.availability == "available":
            if self.value is None or self.sample_size is None or self.window_start is None or self.window_end is None or self.unavailable_reason:
                raise ValueError("available metrics require a value, sample and window")
        elif self.value is not None or not self.unavailable_reason:
            raise ValueError("unavailable metrics cannot carry an estimated value")
        if self.window_start and self.window_end and self.window_start > self.window_end:
            raise ValueError("metric window is reversed")
        if self.tail_sample_size is not None and (self.sample_size is None or self.tail_sample_size > self.sample_size):
            raise ValueError("tail sample exceeds return sample")
        return self


class NativeValuationV1(_RecordModel):
    inputs: ValuationInputsV1
    assessment: ValuationAssessmentV1
    input_evidence_ids: tuple[str, ...] = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def deterministic_assessment(self):
        if self.input_sha256 != canonical_sha256(self.inputs):
            raise ValueError("native valuation input hash mismatch")
        if self.assessment != assess_valuation(self.inputs):
            raise ValueError("native valuation arithmetic or input identity changed")
        return self


class ResearchRecordV1(_RecordModel):
    schema_version: Literal["research-record-v1"] = RESEARCH_RECORD_CONTRACT
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    mode: Literal["company_research", "catalyst_research", "holding_review"]
    analysis_date: date
    construction: Literal["adapted_case", "native"]
    source_case_contract: Literal["research-case-v2", "catalyst-research-case-v1"] | None = None
    source_case_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    snapshots: tuple[EvidenceSnapshotV1, ...] = Field(min_length=1, max_length=2)
    evidence: tuple[SourceEvidenceV1, ...] = ()
    claims: tuple[RecordClaimV1, ...] = ()
    hypotheses: tuple[ResearchHypothesisV1, ...] = ()
    challenges: tuple[ResearchChallengeV1, ...] = ()
    verifications: tuple[VerificationRecordV1, ...] = ()
    metrics: tuple[QuantitativeMetricV1, ...] = ()
    assessment: ResearchAssessmentV1 | None = None
    valuation: NativeValuationV1 | None = None
    limitations: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_compatible_record(self, handler):
        value = handler(self)
        # Preserve existing checkpoint digests and old wire records exactly.
        if self.assessment is None:
            value.pop("assessment", None)
        if self.valuation is None:
            value.pop("valuation", None)
        return value

    @model_validator(mode="after")
    def validate_reference_graph(self):
        def index(items, key):
            result = {getattr(item, key): item for item in items}
            if len(result) != len(items):
                raise ValueError(f"duplicate {key}")
            return result
        def refs(values, allowed):
            if len(set(values)) != len(values) or not set(values) <= allowed:
                raise ValueError("duplicate or dangling research reference")
        evidence = index(self.evidence, "evidence_id")
        claims = index(self.claims, "claim_id")
        snapshots = index(self.snapshots, "snapshot_id")
        hypotheses = index(self.hypotheses, "hypothesis_id")
        challenges = index(self.challenges, "challenge_id")
        index(self.verifications, "verification_id")
        index(self.metrics, "metric_id")
        if self.construction == "adapted_case" and (not self.source_case_contract or not self.source_case_sha256):
            raise ValueError("adapted research must bind its source case")
        if self.snapshots[0].version != 0 or self.snapshots[0].parent_snapshot_id is not None:
            raise ValueError("research must start from V0")
        for snapshot in self.snapshots:
            refs(snapshot.evidence_ids, evidence.keys())
            expected = make_evidence_snapshot(tuple(evidence[key] for key in snapshot.evidence_ids),
                version=snapshot.version, parent_snapshot_id=snapshot.parent_snapshot_id)
            if snapshot != expected:
                raise ValueError("evidence snapshot content or identity changed")
        if set(self.snapshots[-1].evidence_ids) != evidence.keys():
            raise ValueError("evidence is outside the recorded snapshot")
        if len(self.snapshots) == 2:
            v0, v1 = self.snapshots
            if v1.version != 1 or v1.parent_snapshot_id != v0.snapshot_id or not set(v0.evidence_ids) <= set(v1.evidence_ids):
                raise ValueError("V1 must preserve its V0 evidence")
            if not self.verifications:
                raise ValueError("V1 requires an executed verification")
        for item in evidence.values():
            if item.usable_as_of and item.usable_as_of.date() > self.analysis_date:
                raise ValueError("source evidence became usable after cutoff")
        if self.valuation is not None:
            inputs = self.valuation.inputs
            if (inputs.run_id, inputs.ticker, inputs.as_of) != (self.run_id, self.ticker, self.analysis_date):
                raise ValueError("native valuation record identity mismatch")
            if inputs.snapshot is None or inputs.snapshot.as_of > self.analysis_date:
                raise ValueError("native valuation snapshot missing or after cutoff")
            refs(self.valuation.input_evidence_ids, evidence.keys())
            if any(evidence[key].availability != "available" for key in self.valuation.input_evidence_ids):
                raise ValueError("native valuation inputs require qualified evidence")
            if any(item.day > self.analysis_date for item in (*inputs.pe_history, *inputs.pb_history)):
                raise ValueError("native valuation history after cutoff")
        facts = {key for key, item in claims.items() if item.kind == "fact"}
        for claim in self.claims:
            refs(claim.evidence_ids, evidence.keys())
            refs(claim.supporting_fact_ids, facts)
        for hypothesis in self.hypotheses:
            if hypothesis.claim_id not in claims or claims[hypothesis.claim_id].kind != "inference":
                raise ValueError("hypothesis requires an inference claim")
            if hypothesis.input_snapshot_id not in snapshots:
                raise ValueError("hypothesis input snapshot missing")
            refs(claims[hypothesis.claim_id].evidence_ids, set(snapshots[hypothesis.input_snapshot_id].evidence_ids))
            for fact_id in claims[hypothesis.claim_id].supporting_fact_ids:
                refs(claims[fact_id].evidence_ids, set(snapshots[hypothesis.input_snapshot_id].evidence_ids))
        for challenge in self.challenges:
            refs(challenge.target_claim_ids, claims.keys())
            refs(challenge.evidence_ids, evidence.keys())
        for verification in self.verifications:
            if verification.challenge_id not in challenges or verification.input_snapshot_id not in snapshots or verification.output_snapshot_id not in snapshots:
                raise ValueError("verification target or snapshot missing")
            if snapshots[verification.output_snapshot_id].version != 1 or snapshots[verification.input_snapshot_id].version != 0:
                raise ValueError("verification must record V0 to V1")
            refs(verification.evidence_ids, set(snapshots[verification.output_snapshot_id].evidence_ids))
            if verification.status in {"supports", "contradicts"} and any(evidence[eid].availability != "available" for eid in verification.evidence_ids):
                raise ValueError("unavailable evidence cannot resolve verification")
            if verification.scope == "predicate_only":
                hypothesis = hypotheses.get(verification.hypothesis_id)
                challenge = challenges[verification.challenge_id]
                if hypothesis is None or hypothesis.origin != "hypothesis_stage" or hypothesis.input_snapshot_id != verification.input_snapshot_id:
                    raise ValueError("predicate verification requires a native input hypothesis")
                if challenge.target_claim_ids != (hypothesis.claim_id,):
                    raise ValueError("predicate verification must target exactly its hypothesis")
                conditions = hypothesis.assumptions if verification.condition_role == "necessary" else hypothesis.invalidation_conditions
                if verification.condition_text not in conditions:
                    raise ValueError("verification condition is not saved in hypothesis")
                if verification.condition_role == "invalidation" and verification.status == "supports":
                    raise ValueError("absence of an invalidation cannot prove a hypothesis")
        for metric in self.metrics:
            refs(metric.input_evidence_ids, evidence.keys())
            if metric.window_end and metric.window_end > self.analysis_date:
                raise ValueError("metric window is after research cutoff")
            if metric.availability == "available" and any(evidence[eid].availability != "available" for eid in metric.input_evidence_ids):
                raise ValueError("available metrics require available input evidence")
        if self.assessment is not None:
            assessment = self.assessment
            if self.construction != "native" or assessment.input_snapshot_id != self.snapshots[-1].snapshot_id:
                raise ValueError("assessment requires the native final snapshot")
            if tuple(item.dimension for item in assessment.dimensions) != DIMENSIONS_BY_MODE[self.mode]:
                raise ValueError("native mode dimensions are missing, duplicated or reordered")
            refs(assessment.key_claim_ids, {key for key, item in claims.items() if item.kind != "unknown"})
            if assessment.primary_challenge_id is not None and assessment.primary_challenge_id not in challenges:
                raise ValueError("primary challenge is missing")
            dispositions = index(assessment.challenge_assessments, "challenge_id")
            if dispositions.keys() != challenges.keys():
                raise ValueError("every native challenge requires an explicit assessment")
            if (assessment.forward_window_calendar_days == 84) != (self.mode == "catalyst_research"):
                raise ValueError("only catalyst research has an 84-day forward window")
            for dimension in assessment.dimensions:
                refs(dimension.claim_ids, {key for key, item in claims.items() if item.kind != "unknown"})
                refs(dimension.challenge_ids, challenges.keys())
                if dimension.status != "unresolved" and not dimension.claim_ids:
                    raise ValueError("a dimensional judgement requires claim references")
                if dimension.status == "supported" and any(claims[key].kind != "fact" for key in dimension.claim_ids):
                    raise ValueError("inference-based judgements remain conditional")
                if dimension.status != "unresolved" and any(evidence[eid].availability != "available"
                    for key in dimension.claim_ids for eid in claims[key].evidence_ids):
                    raise ValueError("unqualified evidence cannot support dimensional judgement")
                if dimension.status == "unresolved" and not dimension.limitations:
                    raise ValueError("unresolved dimension requires a limitation")
                if dimension.challenge_ids and dimension.status == "supported":
                    raise ValueError("challenged judgement cannot be asserted as proven")
            if assessment.quality == "PASS" and (assessment.completeness != "complete" or challenges
                or any(item.status == "unresolved" for item in assessment.dimensions)):
                raise ValueError("partial or challenged native research is LOW_CONFIDENCE")
        return self
