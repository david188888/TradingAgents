"""Assembly of the frozen evidence draft for one ``catalyst_v1`` run.

Design SS5.1 places a freeze between bounded fetching and the specialist
fan-out, and SS9 defines the preconditions a specialist input must satisfy
before it may be shown to a reader.  The per-capability pieces those two
sections need already exist in :mod:`tradingagents.dataflows.catalyst_events`
(deterministic dedup, source families, point-in-time admissibility) and in
:mod:`tradingagents.research.catalyst_evidence_policy` (the window
parameters).  What was missing is the thing that joins them: a snapshot, taken
once, after which the specialists no longer fetch anything.

Three properties make the freeze worth having, and all three are enforced here
rather than documented:

* **Immutable.**  ``FrozenEvidenceDraft`` is a frozen dataclass holding tuples.
  A specialist cannot append to the draft it was handed, so "no free retrieval
  after the freeze" is a property of the type rather than a convention.
* **Per-role views.**  Each specialist receives a projection of the draft, not
  the draft.  SS5.2 requires duty isolation, and a view that omits what the
  role may not see is what makes the isolation testable instead of aspirational.
* **One supplement round, bounded.**  SS5.1 allows at most one pre-freeze
  supplement covering at most three missing capabilities, charged to the same
  run budget.  ``supplement`` accepts the extra capability results only while
  the round is open and refuses everything afterwards, and it charges the
  budget before accepting, so a supplement cannot be free.

A capability that failed is recorded as ``unavailable`` with its reason.  It is
never turned into an empty result: SS9.1 distinguishes "the source proved the
window and found nothing" from "the source could not answer", and collapsing
the second into the first is how a run concludes there is no catalyst because
the news vendor timed out.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.dataflows.catalyst_events import (
    CatalystEventV1,
    EventQueryOutcomeV1,
    dedupe_events,
    filter_admissible,
    group_by_source_family,
    independent_support_count,
    source_family_id,
    strictest_outcome,
)
from tradingagents.research.catalyst_evidence_policy import (
    CATALYST_EVIDENCE_POLICY_VERSION,
    CatalystEvidencePolicyV1,
    catalyst_evidence_policy_v1,
)

# Capability identifiers are a public contract: they appear in reason codes and
# in the audit trail, so they are declared here rather than spelled at call
# sites.
CAP_IDENTITY = "security_identity"
CAP_EVENT_COVERAGE = "event_coverage"
CAP_PRICE = "price_history"
CAP_FUNDAMENTALS = "fundamentals"
CAP_SENTIMENT = "sentiment"
CAP_CONSENSUS = "consensus_expectations"

# Design SS9: which capabilities a specialist may not proceed without.  These
# are *requirements* on the draft, not on the model.  A role whose required
# capability is unmet is skipped rather than fed a gap and asked to reason
# about it, because a model handed an empty evidence set will confidently
# describe what it cannot see.
REQUIRED_CAPABILITIES: tuple[str, ...] = (
    CAP_IDENTITY,
    CAP_EVENT_COVERAGE,
    CAP_PRICE,
    CAP_FUNDAMENTALS,
)

# Design SS9: sentiment and consensus are explicitly optional.  Their absence
# must not block formal event research, and a strong high-frequency reading
# must not stand in for evidence that is actually required.
OPTIONAL_CAPABILITIES: tuple[str, ...] = (CAP_SENTIMENT, CAP_CONSENSUS)

SpecialistRole = Literal["catalyst_events", "operating_delivery", "market_reaction"]

# Fixed read order for the merge node (design SS5.4).  Results must not depend
# on completion order, so the merge sorts by this tuple rather than by arrival.
ROLE_ORDER: tuple[SpecialistRole, ...] = (
    "catalyst_events",
    "operating_delivery",
    "market_reaction",
)

# The single question each specialist answers (design SS5.2).  It is part of the
# role's definition because a role that drifts from its question is no longer
# the role the budget and the audit trail assume.
ROLE_QUESTIONS: Mapping[SpecialistRole, str] = {
    "catalyst_events": (
        "为什么现在研究，什么事件可能在窗口内改变判断？"
        " Why now, and which events could change the judgement inside the window?"
    ),
    "operating_delivery": (
        "催化如何到收入、利润、现金流或约束条件？"
        " How does the catalyst reach revenue, profit, cash flow, or a constraint?"
    ),
    "market_reaction": (
        "已观察到什么价格/成交/关注变化，还有什么不能判断？"
        " What price, volume, or attention change is observed, and what cannot be judged?"
    ),
}

# Which capabilities each specialist is entitled to see.  Isolation is not
# about hiding one specialist's *output* from another -- it is about not mixing
# a market-reaction reading into the operating-delivery reasoning, which is how
# a sentiment spike ends up presented as operating evidence.
ROLE_CAPABILITY_ACCESS: Mapping[SpecialistRole, tuple[str, ...]] = {
    "catalyst_events": (CAP_IDENTITY, CAP_EVENT_COVERAGE, CAP_FUNDAMENTALS),
    "operating_delivery": (CAP_IDENTITY, CAP_EVENT_COVERAGE, CAP_FUNDAMENTALS, CAP_CONSENSUS),
    "market_reaction": (CAP_IDENTITY, CAP_PRICE, CAP_SENTIMENT, CAP_EVENT_COVERAGE),
}

# What each specialist may emit.  A role that cannot see a capability cannot
# make a finding that depends on it: allowing it would put an unresolvable
# citation in the public case.
ROLE_REQUIRED_CAPABILITIES: Mapping[SpecialistRole, tuple[str, ...]] = {
    "catalyst_events": (CAP_EVENT_COVERAGE,),
    "operating_delivery": (CAP_FUNDAMENTALS,),
    "market_reaction": (CAP_PRICE,),
}


class CapabilityStatus(str, Enum):
    """Whether a capability produced usable evidence for this run.

    ``UNAVAILABLE`` and ``COVERAGE_UNKNOWN`` are deliberately distinct from
    "no matching records": an empty list is a legitimate answer only when the
    source proved it looked and found nothing.
    """

    QUALIFIED = "qualified"
    COVERED_NO_MATCH = "covered_no_matching"
    UNAVAILABLE = "unavailable"
    COVERAGE_UNKNOWN = "coverage_unknown"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"

    @property
    def is_usable(self) -> bool:
        return self in {
            CapabilityStatus.QUALIFIED,
            CapabilityStatus.COVERED_NO_MATCH,
            CapabilityStatus.NOT_APPLICABLE,
        }

    @property
    def blocks_specialists(self) -> bool:
        """Whether a role that depends on this capability must be skipped.

        ``PARTIAL`` is deliberately *not* blocking.  Incomplete pagination
        means the source cannot prove it found everything -- it does not mean
        the items it did return are unusable.  Suppressing real filings because
        the last page was truncated would discard evidence; what must be
        withheld is the *absence* claim, which is a limitation on the finding
        rather than a reason to skip the role.
        """
        return self in {
            CapabilityStatus.UNAVAILABLE,
            CapabilityStatus.COVERAGE_UNKNOWN,
        }


class FrozenCapability(BaseModel):
    """One capability's result, as it stood when the draft was frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(min_length=1, max_length=120)
    status: CapabilityStatus
    required: bool = False
    # Why this status. Always populated: a status a reader cannot audit is a
    # status they have to take on trust.
    reason: str = Field(min_length=1, max_length=400)
    degradations: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    # Source provenance, one entry per source that answered. Empty for a
    # capability that was not applicable.
    sources: tuple[str, ...] = ()
    detail: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unusable_capability_states_why(self) -> FrozenCapability:
        # A failed capability with no recorded cause is indistinguishable from
        # a bug, and the run would publish an unexplained gap. An optional
        # capability that was never applicable is exempt: nothing went wrong,
        # and inventing a degradation for it would be noise.
        if (
            not self.status.is_usable
            and not (self.degradations or self.detail)
            and self.status is not CapabilityStatus.NOT_APPLICABLE
        ):
            raise ValueError("an unusable capability must record why it is unusable")
        if self.status in {
            CapabilityStatus.UNAVAILABLE,
            CapabilityStatus.COVERAGE_UNKNOWN,
            CapabilityStatus.PARTIAL,
        } and not self.reason:
            raise ValueError("a degraded capability must carry a reason")
        return self


class FrozenEvent(BaseModel):
    """A normalized event after dedup, family linking, and PIT filtering.

    ``rejected_after_cutoff`` items are kept out of the draft entirely. They
    are counted in the audit summary instead, so a reader can see that a
    post-cutoff filing existed and was excluded rather than wondering why a
    known announcement is missing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    publication_date: str = Field(min_length=10, max_length=10)
    channel: str = Field(min_length=1, max_length=40)
    status: str = Field(min_length=1, max_length=40)
    reporting_period: str | None = Field(default=None, max_length=40)
    source_family_id: str = Field(min_length=1, max_length=200)
    evidence_ids: tuple[str, ...] = ()
    # How many independent sources back this event. One reprint counted three
    # times is one fact, and reporting three would manufacture consensus.
    independent_support: int = Field(default=1, ge=1)
    strength: str = Field(min_length=1, max_length=40)
    notes: tuple[str, ...] = ()

    @property
    def is_fact_anchor(self) -> bool:
        return self.strength in {"official_filing", "official_exchange"}

    @property
    def is_executed(self) -> bool:
        return self.status in {"implemented", "completed"}


class PriceObservation(BaseModel):
    """A qualifying close, with the window it came from and whether it is PIT."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_on: str = Field(min_length=10, max_length=10)
    close: float
    volume: float | None = None
    adjustment: Literal["raw", "qfq", "none"] = "none"
    # SS8.5: a qfq series whose factor snapshot cannot be proven for a
    # historical cutoff must not enter the market specialist's context. The
    # flag travels with the observation so the view builder can exclude it
    # without re-deriving anything.
    pit_verified: bool = True
    source: str = Field(min_length=1, max_length=80)


class FrozenEvidenceDraft(BaseModel):
    """The immutable snapshot every specialist reads and nothing writes.

    ``frozen_at`` and ``draft_id`` make the freeze auditable: a result can be
    tied to the exact snapshot that produced it, and a second attempt to change
    the draft is visible as a different ``draft_id`` rather than as a silent
    mutation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    cutoff: str = Field(min_length=10, max_length=10)
    policy_version: str = Field(min_length=1, max_length=80)
    draft_id: str = Field(min_length=1, max_length=80)
    frozen_at: datetime
    capabilities: tuple[FrozenCapability, ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    events: tuple[FrozenEvent, ...] = ()
    prices: tuple[PriceObservation, ...] = ()
    # Items excluded by the point-in-time gate, kept for audit only. They are
    # never rendered into a specialist view or a public case.
    excluded_post_cutoff_count: int = Field(default=0, ge=0)
    # How many source families the surviving events collapse to.
    independent_support: int = Field(default=0, ge=0)
    supplement_rounds_used: int = Field(default=0, ge=0)
    supplement_capabilities_used: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _identity_is_required_and_window_is_consistent(self) -> FrozenEvidenceDraft:
        if self.cutoff != date.fromisoformat(self.cutoff).isoformat():
            raise ValueError("cutoff must be an ISO calendar date")
        for observation in self.prices:
            if observation.observed_on > self.cutoff:
                raise ValueError("a price observation is after the research cutoff")
        for event in self.events:
            if event.publication_date > self.cutoff:
                raise ValueError("a frozen event is after the research cutoff")
        return self

    # -- lookups ----------------------------------------------------------

    def capability(self, name: str) -> FrozenCapability | None:
        return next(
            (item for item in self.capabilities if item.capability == name), None
        )

    def status_of(self, name: str) -> CapabilityStatus:
        found = self.capability(name)
        return found.status if found is not None else CapabilityStatus.UNAVAILABLE

    def is_qualified(self, name: str) -> bool:
        return self.status_of(name).is_usable

    def evidence_by_id(self, evidence_id: str) -> Mapping[str, Any] | None:
        return next(
            (item for item in self.evidence if item.get("evidence_id") == evidence_id),
            None,
        )

    def event_by_id(self, event_id: str) -> FrozenEvent | None:
        return next((item for item in self.events if item.event_id == event_id), None)

    def usable_evidence_ids(self) -> tuple[str, ...]:
        """Evidence ids a specialist may cite.

        Only usable capabilities contribute. A finding that cites an
        unavailable source would put an unresolvable reference in the public
        case, which the case schema rejects outright.
        """
        usable = {
            item.capability
            for item in self.capabilities
            if item.status.is_usable
        }
        allowed = tuple(
            str(item["evidence_id"])
            for item in self.evidence
            if item.get("capability") in usable
        )
        return allowed

    def missing_required_capabilities(self) -> tuple[str, ...]:
        """Required capabilities that produced nothing a role may reason on."""
        return tuple(
            name
            for name in REQUIRED_CAPABILITIES
            if self.status_of(name).blocks_specialists
        )

    def degraded_optional_capabilities(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in OPTIONAL_CAPABILITIES
            if self.status_of(name) is not CapabilityStatus.QUALIFIED
        )

    def summary(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "capabilities": {
                item.capability: item.status.value for item in self.capabilities
            },
            "event_count": len(self.events),
            "independent_support": self.independent_support,
            "evidence_count": len(self.evidence),
            "price_observations": len(self.prices),
            "excluded_post_cutoff": self.excluded_post_cutoff_count,
        }


@dataclass(frozen=True)
class SpecialistEvidenceView:
    """The one thing a specialist role is allowed to read.

    Deliberately not a dict.  A role receives a projection that physically
    cannot carry another role's findings, so "specialists do not read each
    other" is checked by construction rather than by a convention a future
    edit could quietly break.
    """

    role: SpecialistRole
    run_id: str
    ticker: str
    cutoff: str
    question: str
    draft_id: str
    # Event ids this role may read, in draft order.
    visible_event_ids: tuple[str, ...]
    # Evidence ids this role may cite, restricted to its capability access.
    citable_evidence_ids: tuple[str, ...]
    # The visible events themselves, already filtered.  Present so a role does
    # not have to reach back into the draft and re-derive the filter.
    events: tuple[FrozenEvent, ...]
    prices: tuple[PriceObservation, ...] = ()
    capability_status: Mapping[str, str] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    def event_ids(self) -> tuple[str, ...]:
        return tuple(item.event_id for item in self.events)

    def may_cite_event(self, event_id: str) -> bool:
        return event_id in self.visible_event_ids

    def may_cite_evidence(self, evidence_id: str) -> bool:
        return evidence_id in self.citable_evidence_ids


def build_specialist_view(
    draft: FrozenEvidenceDraft, role: SpecialistRole
) -> SpecialistEvidenceView:
    """Project the frozen draft into one role's bounded input.

    The projection is the enforcement point for SS5.2's isolation rule and
    SS9's PIT rule: a role that is not entitled to a capability simply does not
    receive its evidence ids, and a price series that cannot be proven
    point-in-time is withheld from the market role rather than passed with a
    caveat attached.
    """
    access = ROLE_CAPABILITY_ACCESS[role]
    usable = {
        item.capability
        for item in draft.capabilities
        if item.status.is_usable and item.capability in access
    }
    citable = tuple(
        str(item["evidence_id"])
        for item in draft.evidence
        if item.get("capability") in usable
    )
    visible = tuple(item for item in draft.events if item.event_id and usable_event(item, draft, role))
    # SS8.5 / SS9.1: an unverified adjusted series may not enter the market
    # role's judgement context at all. Raw closes may still be shown as a
    # labelled audit observation, which is what an explicit limitation is for.
    prices = tuple(
        observation
        for observation in draft.prices
        if observation.pit_verified or observation.adjustment == "raw"
    )
    limitations = list(draft_view_limitations(draft, role))
    return SpecialistEvidenceView(
        role=role,
        run_id=draft.run_id,
        ticker=draft.ticker,
        cutoff=draft.cutoff,
        question=ROLE_QUESTIONS[role],
        draft_id=draft.draft_id,
        visible_event_ids=tuple(item.event_id for item in visible),
        citable_evidence_ids=citable,
        events=visible,
        prices=prices if role == "market_reaction" else (),
        capability_status={
            name: draft.status_of(name).value for name in access
        },
        limitations=tuple(limitations),
    )


def usable_event(event: FrozenEvent, draft: FrozenEvidenceDraft, role: SpecialistRole) -> bool:
    """Whether a role may see this event at all.

    An event backed only by a capability the role cannot read is not merely
    unreadable evidence -- presenting it would invite an inference the role has
    no evidence to support.
    """
    if draft.status_of(CAP_EVENT_COVERAGE).blocks_specialists:
        return False
    citable = {
        str(item["evidence_id"])
        for item in draft.evidence
        if item.get("capability") in ROLE_CAPABILITY_ACCESS[role]
    }
    return bool(set(event.evidence_ids) & citable)


def draft_view_limitations(
    draft: FrozenEvidenceDraft, role: SpecialistRole
) -> list[str]:
    """The limitations a role must be told about before it reasons.

    SS9.1: a degraded *required* capability caps the final priority, and a
    missing *optional* one is a disclosed gap rather than a blocker. The
    difference is what the reader sees, so the role is told which is which.
    """
    notes: list[str] = []
    for name in ROLE_REQUIRED_CAPABILITIES[role]:
        status = draft.status_of(name)
        if status.blocks_specialists:
            notes.append(
                f"required_capability_unqualified:{name}:{status.value}"
            )
        elif not status.is_usable:
            # Usable but not complete. The role may reason over what was
            # found; it may not claim the window is closed.
            notes.append(
                f"capability_coverage_incomplete:{name}:{status.value}"
            )
    for name in draft.degraded_optional_capabilities():
        if name in ROLE_CAPABILITY_ACCESS[role]:
            notes.append(f"optional_capability_missing:{name}:{draft.status_of(name).value}")
    withheld = sum(
        1
        for item in draft.prices
        if not item.pit_verified and item.adjustment != "raw"
    )
    if withheld and role == "market_reaction":
        notes.append(f"pit_unverified_price_observations:{withheld}")
    return notes


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


@dataclass
class FreezeInputs:
    """What the fetcher hands to the freeze.

    Kept as a plain mutable dataclass because this is the one place where a
    run is allowed to be incomplete; everything downstream reads a frozen
    projection of it.
    """

    run_id: str
    ticker: str
    cutoff: str
    policy: CatalystEvidencePolicyV1
    events: list[CatalystEventV1] = field(default_factory=list)
    event_outcomes: list[EventQueryOutcomeV1] = field(default_factory=list)
    capabilities: list[FrozenCapability] = field(default_factory=list)
    evidence: list[Mapping[str, Any]] = field(default_factory=list)
    prices: list[PriceObservation] = field(default_factory=list)


def _capability_from_outcome(
    name: str, outcome: EventQueryOutcomeV1, *, required: bool
) -> FrozenCapability:
    status = {
        "covered_no_matching_events": CapabilityStatus.COVERED_NO_MATCH,
        "coverage_unknown": CapabilityStatus.COVERAGE_UNKNOWN,
        "partial_pagination": CapabilityStatus.PARTIAL,
    }[outcome.outcome]
    return FrozenCapability(
        capability=name,
        status=status,
        required=required,
        reason=outcome.reason,
        # An outcome that is not a proven absence always has an explanation to
        # record.  ``coverage_unknown`` carries its degradation codes from the
        # source; the other two describe a real but incomplete look, which is
        # recorded as a degradation of the same shape so a reader sees the
        # cause rather than only the label.
        degradations=outcome.degradations
        or (() if outcome.outcome == "covered_no_matching_events" else (outcome.outcome,)),
        sources=(outcome.source_id,),
    )


def _event_id(event: CatalystEventV1, index: int) -> str:
    """A stable, readable, run-scoped id for a frozen event.

    Derived from the content fingerprint rather than the list position, so
    adding an unrelated event does not renumber the ones already cited by a
    finding.
    """
    family = event.source_family_id or source_family_id(
        event.security_id, event.content_fingerprint
    )
    digest = hashlib.sha256(family.encode("utf-8")).hexdigest()[:12]
    # Every dot-segment must start with a letter: the canonical ID_PATTERN used
    # by CatalystEvent rejects a bare numeric or hex-digest segment, so the
    # position and the digest are both spelled.
    return f"ev.{event.kind}.i{index}.d{digest}"


def freeze_evidence_draft(inputs: FreezeInputs) -> FrozenEvidenceDraft:
    """Take the freeze.

    Order of operations is fixed and deliberate:

    1. PIT filter first.  A post-cutoff filing is not an event that happens to
       be excluded later; admitting it and filtering afterwards would let it
       influence dedup and family grouping.
    2. Deterministic dedup, keeping the strongest-disclosure copy.
    3. Family grouping, so independent support counts families and not links.
    4. Capability status derived from the *strictest* query outcome, so one
       unknown source among several makes the absence unprovable.
    """
    date.fromisoformat(inputs.cutoff)
    admissible, rejected = filter_admissible(
        inputs.events, cutoff=inputs.cutoff
    )
    deduped = dedupe_events(admissible)
    families = group_by_source_family(deduped)

    capabilities = list(inputs.capabilities)
    outcome = strictest_outcome(inputs.event_outcomes)
    if outcome is not None:
        # The observed query outcome is authoritative and replaces any record
        # the fetch plan optimistically wrote.  A capability that claims
        # "qualified" while the only source that answered timed out would
        # publish an unprovable absence, which is the single most expensive
        # mistake this flow can make.
        capabilities = [
            item
            for item in capabilities
            if item.capability != CAP_EVENT_COVERAGE
        ] + [
            _capability_from_outcome(
                CAP_EVENT_COVERAGE,
                outcome,
                required=CAP_EVENT_COVERAGE in REQUIRED_CAPABILITIES,
            )
        ]
    for name in REQUIRED_CAPABILITIES:
        if name not in {item.capability for item in capabilities}:
            capabilities.append(
                FrozenCapability(
                    capability=name,
                    status=CapabilityStatus.UNAVAILABLE,
                    required=True,
                    reason="capability_not_produced_by_the_plan",
                    degradations=("capability_not_attempted",),
                )
            )
    capabilities.sort(key=lambda item: item.capability)

    # Independent support is a property of the family, so every reprint of one
    # filing carries the same count. A syndicated announcement therefore shows
    # "1" however many sites carried it.
    family_size: dict[str, int] = {}
    for group in families:
        key = group[0].source_family_id or source_family_id(
            group[0].security_id, group[0].content_fingerprint
        )
        family_size[key] = len(group)

    frozen_events: list[FrozenEvent] = []
    for position, event in enumerate(deduped):
        family = event.source_family_id or source_family_id(
            event.security_id, event.content_fingerprint
        )
        support = family_size.get(family, 1)
        frozen_events.append(
            FrozenEvent(
                event_id=_event_id(event, position),
                kind=event.kind,
                title=event.title[:200],
                publication_date=event.publication_date,
                channel=event.channel,
                status=event.state,
                reporting_period=event.reporting_period,
                source_family_id=family,
                independent_support=support,
                strength=event.strength.value,
                notes=event.notes,
            )
        )

    evidence_by_capability: dict[str, list[str]] = {}
    for record in inputs.evidence:
        evidence_by_capability.setdefault(
            str(record.get("capability", "")), []
        ).append(str(record.get("evidence_id", "")))

    frozen = FrozenEvidenceDraft(
        run_id=inputs.run_id,
        ticker=inputs.ticker,
        cutoff=inputs.cutoff,
        policy_version=CATALYST_EVIDENCE_POLICY_VERSION,
        draft_id=compute_draft_id(inputs),
        frozen_at=datetime.now(timezone.utc),
        capabilities=tuple(capabilities),
        evidence=tuple(dict(item) for item in inputs.evidence),
        events=tuple(frozen_events),
        prices=tuple(
            sorted(inputs.prices, key=lambda item: item.observed_on)
        ),
        excluded_post_cutoff_count=len(rejected),
        independent_support=independent_support_count(deduped),
    )
    # Wire the event evidence ids from the capability record, so a role can
    # check resolvability without reaching into the raw capability payload.
    return _attach_event_evidence(frozen, evidence_by_capability)


def _attach_event_evidence(
    draft: FrozenEvidenceDraft, by_capability: Mapping[str, list[str]]
) -> FrozenEvidenceDraft:
    coverage_ids = tuple(by_capability.get(CAP_EVENT_COVERAGE, ()))
    events = tuple(
        item if item.evidence_ids else item.model_copy(update={"evidence_ids": coverage_ids})
        for item in draft.events
    )
    return draft.model_copy(update={"events": events})


def compute_draft_id(inputs: FreezeInputs) -> str:
    """A content hash of everything the draft asserts.

    Two freezes of the same material produce the same id, which is what makes
    "the result came from this draft" checkable. Any change to the evidence
    base changes the id, so a stale result cannot be quietly attributed to a
    newer draft.
    """
    payload = {
        "run_id": inputs.run_id,
        "ticker": inputs.ticker,
        "cutoff": inputs.cutoff,
        "policy": inputs.policy.as_identity(),
        "events": sorted(
            (item.publication_date, item.content_fingerprint, item.channel)
            for item in inputs.events
        ),
        "capabilities": sorted(
            (item.capability, item.status.value, item.reason)
            for item in inputs.capabilities
        ),
        "evidence": sorted(
            str(item.get("evidence_id", "")) for item in inputs.evidence
        ),
        "prices": sorted(
            (item.observed_on, item.close, item.adjustment, item.pit_verified)
            for item in inputs.prices
        ),
    }
    import json

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"draft_{digest[:24]}"


def empty_draft(
    run_id: str,
    ticker: str,
    cutoff: str,
    *,
    policy: CatalystEvidencePolicyV1 | None = None,
    blocked_reason: str = "no_evidence_was_produced",
) -> FrozenEvidenceDraft:
    """A draft for a run that produced no usable evidence at all.

    SS9.1 requires a blocked case to be an honest artifact rather than an
    absent one. Every required capability is marked unavailable, so the case
    that carries this draft is capped at insufficient information by
    construction instead of by a special case in the assembler.
    """
    active = policy or catalyst_evidence_policy_v1()
    capabilities = [
        FrozenCapability(
            capability=name,
            status=(
                CapabilityStatus.NOT_APPLICABLE
                if name in OPTIONAL_CAPABILITIES
                else CapabilityStatus.UNAVAILABLE
            ),
            required=name in REQUIRED_CAPABILITIES,
            reason=blocked_reason,
            degradations=("no_evidence",),
        )
        for name in (*REQUIRED_CAPABILITIES, *OPTIONAL_CAPABILITIES)
    ]
    return FrozenEvidenceDraft(
        run_id=run_id,
        ticker=ticker,
        cutoff=cutoff,
        policy_version=CATALYST_EVIDENCE_POLICY_VERSION,
        draft_id=f"draft_empty_{abs(hash((run_id, ticker, cutoff))) % (10**16):016d}",
        frozen_at=datetime.now(timezone.utc),
        capabilities=tuple(capabilities),
        supplement_rounds_used=active.max_supplement_rounds,
    )


# ---------------------------------------------------------------------------
# The pre-freeze supplement round
# ---------------------------------------------------------------------------


class SupplementClosed(RuntimeError):
    """A capability was requested after the freeze closed.

    SS5.1 forbids open-ended retrieval after the freeze. Raising rather than
    returning an empty result keeps "we looked again" from being
    indistinguishable from "we did not look".
    """


class EvidenceFreezer:
    """Owns the single pre-freeze supplement window for one run.

    The freezer is the only object allowed to mutate the inputs between the
    first fetch and the freeze, and it does so only while the window is open.
    Every supplement is charged to the same run budget, which is what stops
    the "one LLM call triggers N HTTP fetches" amplification recorded in the
    hidden-call audit.
    """

    def __init__(
        self,
        inputs: FreezeInputs,
        *,
        ledger: Any | None = None,
    ) -> None:
        self._inputs = inputs
        self._ledger = ledger
        self._policy = inputs.policy
        self._rounds_used = 0
        self._capabilities_used: list[str] = []
        self._frozen: FrozenEvidenceDraft | None = None

    # -- window state -----------------------------------------------------

    @property
    def frozen(self) -> FrozenEvidenceDraft | None:
        return self._frozen

    @property
    def rounds_used(self) -> int:
        return self._rounds_used

    @property
    def capabilities_used(self) -> tuple[str, ...]:
        return tuple(self._capabilities_used)

    def is_open(self) -> bool:
        return (
            self._frozen is None
            and self._rounds_used < self._policy.max_supplement_rounds
            and len(self._capabilities_used) < self._policy.max_supplement_capabilities
        )

    def end_supplement_round(self) -> None:
        """Close the supplement window without freezing yet.

        A round is spent as soon as it is closed, whether or not it covered the
        full allowance.  Letting a caller keep topping up until the capability
        cap is hit would make "one round" a number nobody can rely on.
        """
        if self._capabilities_used and self._rounds_used < self._policy.max_supplement_rounds:
            self._rounds_used = self._policy.max_supplement_rounds

    def missing_required(self) -> tuple[str, ...]:
        """Required capabilities the first pass did not produce.

        This is what the supplement round is for, so it reports the same
        "nothing to reason on" test the specialists will apply -- otherwise a
        run would spend its one supplement on a capability that was merely
        incomplete rather than absent.
        """
        return tuple(
            name
            for name in REQUIRED_CAPABILITIES
            if name != CAP_EVENT_COVERAGE
            and not any(
                item.capability == name
                and not item.status.blocks_specialists
                for item in self._inputs.capabilities
            )
        )

    # -- mutation ---------------------------------------------------------

    def supplement(
        self,
        *,
        capability: str,
        events: Sequence[CatalystEventV1] = (),
        outcomes: Sequence[EventQueryOutcomeV1] = (),
        result: FrozenCapability | None = None,
        evidence: Sequence[Mapping[str, Any]] = (),
        prices: Sequence[PriceObservation] = (),
        window_start: str | None = None,
    ) -> FrozenCapability:
        """Accept one supplement capability, or refuse it.

        The order of the checks is the point: the window state is tested before
        the budget is charged, so a refused post-freeze request costs nothing,
        and the budget is charged before anything is accepted, so a capability
        can never be added for free.
        """
        if self._frozen is not None:
            raise SupplementClosed(
                "the evidence draft is frozen; a new run is required to gather more"
            )
        if self._rounds_used >= self._policy.max_supplement_rounds:
            raise SupplementClosed(
                "the single pre-freeze supplement round is already used"
            )
        if len(self._capabilities_used) >= self._policy.max_supplement_capabilities:
            raise SupplementClosed(
                "a supplement round covers at most "
                f"{self._policy.max_supplement_capabilities} capabilities"
            )
        if capability in self._capabilities_used:
            raise SupplementClosed(
                f"capability {capability!r} was already supplemented in this round"
            )
        if window_start is not None and not self._window_admits(window_start):
            # Design SS5.1 bounds the supplement by the same forward window as
            # the freeze. A round that reaches further back would quietly
            # become a different run with a longer horizon than the one that
            # was reviewed, so it is refused rather than trimmed.
            raise SupplementClosed(
                f"supplement window {window_start} reaches outside the "
                f"{self._policy.forward_window_max_calendar_days}-day forward "
                "window this run is bounded to"
            )
        if (
            len(self._capabilities_used) + 1
            > self._policy.max_supplement_capabilities
        ):
            raise SupplementClosed(
                "a supplement round covers at most "
                f"{self._policy.max_supplement_capabilities} capabilities"
            )
        if self._ledger is not None:
            from tradingagents.execution.budget import BudgetBucket, BudgetLimitHit

            for bucket in (
                BudgetBucket.DATA_CAPABILITY_CALLS,
                BudgetBucket.DATA_HTTP_ATTEMPTS,
            ):
                granted = self._ledger.reserve(
                    bucket, stage=f"supplement:{capability}"
                )
                if isinstance(granted, BudgetLimitHit):
                    raise SupplementClosed(
                        f"supplement refused by budget: {granted.as_dict()}"
                    )
                self._ledger.mark_dispatched(granted)
                self._ledger.settle(granted, ok=True, detail="supplement")

        capability_record = result or FrozenCapability(
            capability=capability,
            status=CapabilityStatus.UNAVAILABLE,
            required=capability in REQUIRED_CAPABILITIES,
            reason="supplement_produced_no_verified_result",
            degradations=("supplement_without_result",),
        )
        self._inputs.capabilities = [
            item
            for item in self._inputs.capabilities
            if item.capability != capability
        ] + [capability_record]
        self._inputs.events.extend(events)
        self._inputs.event_outcomes.extend(outcomes)
        self._inputs.evidence.extend(dict(item) for item in evidence)
        self._inputs.prices.extend(prices)
        self._capabilities_used.append(capability)
        if len(self._capabilities_used) >= self._policy.max_supplement_capabilities:
            self._rounds_used = self._policy.max_supplement_rounds
        return capability_record

    def _window_admits(self, window_start: str) -> bool:
        """Is a supplement window start inside the run's forward window?

        The comparison is on dates, not instants, because a filing's date is
        a day and a cutoff is a day; anything finer would reject a legitimate
        supplement on a timezone technicality.
        """
        try:
            start = date.fromisoformat(str(window_start)[:10])
        except ValueError:
            raise SupplementClosed(
                f"supplement window {window_start!r} is not a date"
            ) from None
        cutoff = date.fromisoformat(self._inputs.cutoff)
        if start > cutoff:
            return False
        return (cutoff - start).days <= self._policy.forward_window_max_calendar_days

    def close(self) -> FrozenEvidenceDraft:
        """Freeze. Calling twice returns the same snapshot, never a new one."""
        if self._frozen is not None:
            return self._frozen
        self.end_supplement_round()
        self._frozen = freeze_evidence_draft(self._inputs)
        return self._frozen
