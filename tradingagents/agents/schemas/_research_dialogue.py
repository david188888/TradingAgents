"""Closed, evidence-bound replies and adjudications; never raw conversations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpecialistRole = Literal["operating_quality", "event_context", "market_context"]
Disposition = Literal["maintained", "revised", "withdrawn", "unanswerable"]


class _DialogueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResponseProposal(_DialogueModel):
    challenge_id: str
    hypothesis_id: str
    disposition: Disposition
    rationale: str = Field(min_length=1, max_length=600)
    supporting_fact_ids: tuple[str, ...] = Field(default=(), max_length=6)
    check_ids: tuple[str, ...] = Field(default=(), max_length=3)
    remaining_unknowns: tuple[str, ...] = Field(default=(), max_length=3)


class ResponsesProposalV1(_DialogueModel):
    responses: tuple[ResponseProposal, ...] = Field(min_length=1, max_length=3)


class HypothesisOriginV1(_DialogueModel):
    hypothesis_id: str
    role: SpecialistRole


class ResearchResponseV1(ResponseProposal):
    response_id: str
    role: SpecialistRole
    status: Literal["available", "unavailable"]
    reason_code: str | None = None

    @model_validator(mode="after")
    def unavailable_is_not_support(self):
        if self.status == "unavailable" and (
            not self.reason_code or self.disposition != "unanswerable"
            or self.supporting_fact_ids or self.check_ids
        ):
            raise ValueError("unavailable reply cannot provide support")
        if self.status == "available" and self.reason_code is not None:
            raise ValueError("available reply cannot carry an unavailable reason")
        if self.disposition in {"maintained", "revised"} and not self.supporting_fact_ids:
            raise ValueError("a maintained or revised reply requires facts")
        return self


class ResearchDialogueV1(_DialogueModel):
    schema_version: Literal["research-dialogue-v1"] = "research-dialogue-v1"
    input_snapshot_id: str
    origins: tuple[HypothesisOriginV1, ...] = ()
    responses: tuple[ResearchResponseV1, ...] = Field(default=(), max_length=3)


class ChallengeAdjudicationV1(_DialogueModel):
    challenge_id: str
    response_id: str
    disposition: Disposition
    rationale: str = Field(min_length=1, max_length=600)


class InvestmentArgumentV1(_DialogueModel):
    rationale: str = Field(min_length=1, max_length=600)
    claim_ids: tuple[str, ...] = Field(min_length=1, max_length=6)
    response_ids: tuple[str, ...] = Field(default=(), max_length=3)


class JudgementConditionV1(_DialogueModel):
    hypothesis_id: str
    invalidation_index: int = Field(ge=0, le=3)
    text: str = Field(min_length=1, max_length=300)


def excluded_support(record):
    """Preserve original assertions for tracing, exclude retracted support."""
    if record.dialogue is None:
        return set()
    changed = {r.hypothesis_id for r in record.dialogue.responses
               if r.status == "available" and r.disposition in {"revised", "withdrawn"}}
    replies = {r.response_id: r for r in record.dialogue.responses}
    changed.update(replies[a.response_id].hypothesis_id
                   for a in getattr(record.assessment, "adjudications", ())
                   if a.disposition in {"revised", "withdrawn"} and a.response_id in replies)
    return {h.claim_id for h in record.hypotheses if h.hypothesis_id in changed}


def response_fact_ids(record, role, challenge_id):
    from tradingagents.research.native_policy import fact_views

    baseline = set(record.snapshots[0].evidence_ids)
    allowed = {f.claim_id for f in fact_views(record, valuation=True)[role]
               if set(f.evidence_ids) <= baseline}
    challenge = next((c for c in record.challenges if c.challenge_id == challenge_id), None)
    if challenge is not None and challenge.test is not None:
        allowed.update(challenge.test.supporting_fact_ids)
    verification_evidence = {e for v in record.verifications if v.challenge_id == challenge_id
                             for e in v.evidence_ids}
    sources = {s.evidence_id: s for s in record.evidence}
    allowed.update(f.claim_id for f in record.claims if f.kind == "fact" and f.evidence_ids
                   and set(f.evidence_ids) <= verification_evidence
                   and all(sources[e].availability == "available" and sources[e].content is not None
                           and sources[e].usable_as_of is not None for e in f.evidence_ids))
    return allowed


def validate_dialogue(record):
    """Validate public bindings without reading any journal or live data."""
    dialogue = record.dialogue
    if dialogue is None:
        return
    if record.construction != "native" or record.mode != "company_research":
        raise ValueError("unified dialogue requires native company research")
    if dialogue.input_snapshot_id != record.snapshots[-1].snapshot_id:
        raise ValueError("dialogue snapshot mismatch")
    origins = {o.hypothesis_id: o.role for o in dialogue.origins}
    hypotheses = {h.hypothesis_id: h for h in record.hypotheses}
    if len(origins) != len(dialogue.origins) or origins.keys() != hypotheses.keys():
        raise ValueError("dialogue must bind every hypothesis once")
    from tradingagents.research.native_policy import fact_views
    views = fact_views(record, valuation=True)
    claims = {c.claim_id: c for c in record.claims}
    for hid, role in origins.items():
        if not set(claims[hypotheses[hid].claim_id].supporting_fact_ids) <= {f.claim_id for f in views[role]}:
            raise ValueError("hypothesis origin does not match its fact partition")
    challenges = {c.challenge_id: c for c in record.challenges}
    responses = {r.challenge_id: r for r in dialogue.responses}
    ids = {r.response_id for r in dialogue.responses}
    if len(ids) != len(dialogue.responses) or len(responses) != len(dialogue.responses) or responses.keys() != challenges.keys():
        raise ValueError("every challenge requires exactly one unique reply")
    checks = {b.challenge_id: b.check_id for b in record.challenge_bindings or ()}
    for cid, reply in responses.items():
        hypothesis = hypotheses.get(reply.hypothesis_id)
        if hypothesis is None or reply.role != origins[reply.hypothesis_id] or challenges[cid].target_claim_ids != (hypothesis.claim_id,):
            raise ValueError("reply targets another specialist or hypothesis")
        allowed = response_fact_ids(record, reply.role, cid)
        if len(set(reply.supporting_fact_ids)) != len(reply.supporting_fact_ids) or not set(reply.supporting_fact_ids) <= allowed:
            raise ValueError("reply contains invalid facts")
        if len(set(reply.check_ids)) != len(reply.check_ids) or not set(reply.check_ids) <= ({checks[cid]} - {None}):
            raise ValueError("reply contains an unbound local check")
