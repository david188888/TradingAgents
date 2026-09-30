"""Canonical public contract for the ``catalyst_v1`` research case.

This module owns ``catalyst-research-case-v1``.  It is a genuinely separate
contract from ``research-case-v2``: the two encode different research
questions, and the design explicitly forbids retro-fitting the catalyst
result into ``ResearchCaseV2`` by loosening its lens/scenario requirements.
Nothing here changes the meaning of an existing artifact.

The models describe only what a committed public artifact may say.  They are
not prompts, tool traces, or model reasoning, and they never carry a secret,
an internal locator, or a raw provider payload.

Every invariant in design section 7.3 is expressed as a validator so that a
malformed case cannot be constructed, serialized, or written to the run
store.  Each invariant is paired with a negative test in
``tests/agents/test_catalyst_research_schema.py``.

Three rules are worth calling out because they are the ones most easily
implemented incorrectly:

* An unknown is not a soft fact.  It carries no evidence, no confidence, and
  no date.  Only a requirement list and a review trigger.
* A date is a claim, not a field default.  Without a supporting evidence id a
  date is not merely imprecise -- it is a fabricated publication time, so it
  must stay ``None`` rather than default to a guess.
* The 420-character first-screen budget is a publish gate, not a rendering
  detail.  Overflow degrades to the safety template; it never truncates and
  it never buys length by deleting a risk.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Artifact identity. The contract name is shared with the request profile and
# the read endpoint; changing it is a wire-breaking change.
CATALYST_CASE_SCHEMA_VERSION = "catalyst-research-case-v1"
CATALYST_CASE_SCHEMA_NUMBER = 1

# Design section 4.3: ordinary first-screen body text is capped at 420
# Unicode characters, 200-300 is the target, and under-filling is acceptable.
# Padding is not. Excluded from the count: navigation, field labels, the
# company name, and time metadata.
BRIEF_CHARACTER_BUDGET = 420
BRIEF_CHARACTER_TARGET_MIN = 200
BRIEF_CHARACTER_TARGET_MAX = 300
# Design section 4.3 safety-overflow template. This rule outranks the length
# target; see ``_BriefBudget`` below.
SAFETY_OVERFLOW_TEMPLATE_BUDGET = 120
SAFETY_OVERFLOW_REASON = "brief_safety_overflow"
SAFETY_OVERFLOW_PRIORITY = "insufficient_information"

ResearchPriority = Literal[
    "verify_first",       # 优先核查
    "keep_watching",      # 持续观察
    "defer_research",     # 暂缓研究
    "insufficient_information",  # 信息不足
]

ClaimKind = Literal["fact", "inference", "unknown"]
SpecialistRole = Literal[
    "catalyst_events",
    "operating_delivery",
    "market_reaction",
]
EventStatus = Literal["planned", "in_progress", "completed", "cancelled"]
DatePrecision = Literal["unknown", "day", "month", "quarter", "range"]
SourceTier = Literal["official", "vendor", "media", "derived"]
ChallengeSeverity = Literal["minor", "material", "critical"]
ChallengeKind = Literal["counter_evidence", "missing_evidence"]
DispositionOutcome = Literal[
    "accepted",
    "partially_accepted",
    "refuted_by_evidence",
    "unresolved",
]
CaseCompleteness = Literal["complete", "partial", "blocked"]
ResearchQuality = Literal["PASS", "LOW_CONFIDENCE", "FAIL_STOP", "GATE_ERROR"]

# Reason codes that forbid publishing ``verify_first`` (design section 9.1).
# These are the conditions the code can decide from committed facts alone;
# a model proposing the category never gets to bypass them.
PRIORITY_BLOCKING_REASONS = frozenset(
    {
        "hard_error",
        "identity_conflict",
        "required_source_unqualified",
        "observation_window_unqualified",
        "refutation_stage_missing",
        "key_challenge_unresolved",
        "required_capability_unavailable",
        "required_coverage_insufficient",
        "pit_unverified",
        "required_specialist_failed",
        "synthesis_failed",
        "brief_safety_overflow",
    }
)

ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
REASON_CODE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CatalystEvidence(_PublicModel):
    """One source record observed during the current run.

    Carries the security identity it was resolved under, both the original
    publication/observation times and the local capture time, and the
    time/value basis the source is valid for.  ``source_family_id`` is what
    makes republication countable: three aggregators copying one filing are
    one independent source, not three.
    """

    evidence_id: str = Field(pattern=ID_PATTERN)
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    capability: str = Field(min_length=1, max_length=120)
    source_tier: SourceTier
    source_name: str = Field(min_length=1, max_length=160)
    public_url: str | None = Field(default=None, max_length=1024)
    source_family_id: str = Field(min_length=1, max_length=160)
    republished_from_evidence_id: str | None = Field(default=None, pattern=ID_PATTERN)
    published_at: datetime | None = None
    observed_at: datetime | None = None
    captured_at: datetime
    usable_as_of: datetime | None = None
    time_basis: str = Field(min_length=1, max_length=200)
    value_basis: str = Field(min_length=1, max_length=200)
    availability: Literal["available", "unavailable", "unverified"] = "available"

    @field_validator("public_url")
    @classmethod
    def _safe_public_url(cls, value: str | None) -> str | None:
        # A public citation is checked separately for a safe protocol and for
        # credential-shaped query parameters; a url that fails is dropped to
        # "source label plus limitation" by the assembler, not published.
        if value is None:
            return None
        if not value.startswith(("https://", "http://")):
            raise ValueError("public_url must use an http(s) scheme")
        return value

    @model_validator(mode="after")
    def _republication_is_not_self(self) -> CatalystEvidence:
        if self.republished_from_evidence_id == self.evidence_id:
            raise ValueError("an evidence record cannot be a republication of itself")
        return self


class CatalystEvent(_PublicModel):
    """A company event with a retained status chain.

    ``occurred_on`` stays ``None`` unless ``date_evidence_ids`` supports it.
    A precise date without evidence is the single most common way a
    published brief fabricates certainty, so the type system makes the
    fabricated shape unrepresentable rather than merely discouraged.
    """

    event_id: str = Field(pattern=ID_PATTERN)
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    event_type: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    status: EventStatus
    announced_at: datetime | None = None
    occurred_on: str | None = Field(default=None, max_length=40)
    occurred_period_end: str | None = Field(default=None, max_length=40)
    date_precision: DatePrecision = "unknown"
    date_evidence_ids: tuple[str, ...] = ()
    updated_by_evidence_id: str | None = Field(default=None, pattern=ID_PATTERN)
    supersedes_event_id: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def _unsourced_dates_stay_unknown(self) -> CatalystEvent:
        if self.supersedes_event_id == self.event_id:
            raise ValueError("an event cannot supersede itself")
        if self.date_precision == "unknown":
            if self.occurred_on or self.occurred_period_end:
                raise ValueError(
                    "an unknown-precision event must not carry an occurrence date"
                )
        elif not self.date_evidence_ids:
            # Design section 7.3: dates without evidence stay unknown.
            raise ValueError("a dated event requires date evidence ids")
        if len(set(self.date_evidence_ids)) != len(self.date_evidence_ids):
            raise ValueError("date evidence ids must be unique")
        return self


class SpecialistFinding(_PublicModel):
    """One bounded output of a specialist role.

    Facts stand alone.  Inferences must name the facts they stand on.  Unknowns
    carry neither evidence nor confidence, because a confident unknown is a
    disguised fact.  ``numeric_facts`` is a closed list rather than free prose
    so that "this number has a unit and a period" is a type-level property
    instead of a reviewer's memory.
    """

    finding_id: str = Field(pattern=ID_PATTERN)
    run_id: str = Field(min_length=1, max_length=128)
    role: SpecialistRole
    kind: ClaimKind
    text: str = Field(min_length=1, max_length=400)
    supporting_finding_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    numeric_facts: tuple[NumericFact, ...] = ()
    limitations: tuple[str, ...] = ()
    next_checks: tuple[str, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)
    survives: bool = True

    @field_validator("supporting_finding_ids", "evidence_ids", "event_ids")
    @classmethod
    def _unique_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("finding references must be unique")
        return value

    @model_validator(mode="after")
    def _kind_rules(self) -> SpecialistFinding:
        if self.finding_id in self.supporting_finding_ids:
            raise ValueError("a finding cannot support itself")
        if self.kind == "unknown":
            if self.evidence_ids or self.event_ids or self.numeric_facts:
                raise ValueError("an unknown finding cannot carry evidence")
            if self.confidence is not None:
                raise ValueError("an unknown finding must not carry confidence")
            if not self.next_checks:
                raise ValueError("an unknown finding must state what is needed")
        else:
            if not self.evidence_ids:
                raise ValueError("a fact or inference finding requires evidence")
            if self.confidence is None:
                raise ValueError("a fact or inference finding requires confidence")
        if self.kind == "fact" and self.supporting_finding_ids:
            raise ValueError("a fact finding cannot depend on other findings")
        if self.kind == "inference" and not self.supporting_finding_ids:
            raise ValueError("an inference finding must depend on surviving facts")
        return self


class NumericFact(_PublicModel):
    """A number with the unit and period that make it interpretable."""

    label: str = Field(min_length=1, max_length=80)
    value: float
    unit: str = Field(min_length=1, max_length=40)
    period: str = Field(min_length=1, max_length=80)
    basis: Literal["reported", "derived", "forecast_range"] = "reported"
    period_start: str | None = Field(default=None, max_length=40)
    period_end: str | None = Field(default=None, max_length=40)


class Challenge(_PublicModel):
    """One independent refutation item raised against a finding or event."""

    challenge_id: str = Field(pattern=ID_PATTERN)
    run_id: str = Field(min_length=1, max_length=128)
    kind: ChallengeKind
    severity: ChallengeSeverity
    target_finding_ids: tuple[str, ...] = Field(min_length=1)
    target_event_ids: tuple[str, ...] = ()
    statement: str = Field(min_length=1, max_length=400)
    evidence_ids: tuple[str, ...] = ()
    test_method: str = Field(min_length=1, max_length=300)
    is_key: bool = False

    @model_validator(mode="after")
    def _challenge_shape(self) -> Challenge:
        if self.kind == "counter_evidence" and not self.evidence_ids:
            raise ValueError("counter-evidence requires the evidence that raises it")
        if self.kind == "missing_evidence" and self.evidence_ids:
            raise ValueError(
                "a missing-evidence challenge cannot cite evidence; it names the gap"
            )
        if self.is_key and self.severity != "critical":
            raise ValueError("a key challenge must be critical")
        return self


class ChallengeDisposition(_PublicModel):
    """How one challenge was handled.

    Every challenge gets exactly one of these.  A key challenge that stays
    ``unresolved`` is what caps the final priority, and its limitation is
    carried into the brief rather than dropped.
    """

    challenge_id: str = Field(pattern=ID_PATTERN)
    outcome: DispositionOutcome
    rationale: str = Field(min_length=1, max_length=400)
    evidence_ids: tuple[str, ...] = ()
    retained_limitations: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _resolution_requires_basis(self) -> ChallengeDisposition:
        if (
            self.outcome in {"accepted", "partially_accepted", "refuted_by_evidence"}
            and not self.evidence_ids
        ):
            raise ValueError("a resolved challenge requires supporting evidence")
        if self.outcome == "unresolved" and not self.retained_limitations:
            raise ValueError("an unresolved challenge must retain its limitation")
        return self


class BriefLine(_PublicModel):
    """One first-screen line, bound to the object it restates.

    The brief never invents prose: each line points at the authoritative
    finding, event, or challenge it summarizes, and the projection renders
    that object's text.  This is what keeps first screen, detail, and
    Markdown from drifting apart.
    """

    text: str = Field(min_length=1, max_length=200)
    finding_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    challenge_ids: tuple[str, ...] = ()


class CatalystBrief(_PublicModel):
    """The single authoritative short artifact for the first screen.

    The character budget is enforced here, in the contract, because the
    budget is about what the reader may be shown, not about how one renderer
    happens to lay out a page.  Overflow degrades to the safety template; it
    never truncates a line and never drops a risk to fit.

    ``character_count`` is computed from the text rather than supplied by the
    producer.  A caller that could assert its own length would only have to
    lie accurately, and a producer optimising for the gate would have an
    incentive to do exactly that.
    """

    kind: Literal["ordinary", "safety_overflow"] = "ordinary"
    judgement: str = Field(min_length=1, max_length=200)
    priority: ResearchPriority
    primary_catalyst_event_id: str | None = Field(default=None, pattern=ID_PATTERN)
    primary_catalyst: BriefLine | None = None
    key_evidence: tuple[BriefLine, ...] = ()
    key_question: BriefLine
    next_check: BriefLine
    critical_limitations: tuple[BriefLine, ...] = ()
    overflow_reason: str | None = Field(default=None, pattern=REASON_CODE_PATTERN)

    def body_texts(self) -> tuple[str, ...]:
        """The first-screen body text, in reading order.

        Navigation, field labels, the company name, and time metadata are not
        part of this model, so they cannot inflate the count.
        """
        parts = [self.judgement]
        if self.primary_catalyst is not None:
            parts.append(self.primary_catalyst.text)
        parts.extend(line.text for line in self.key_evidence)
        parts.append(self.key_question.text)
        parts.append(self.next_check.text)
        parts.extend(line.text for line in self.critical_limitations)
        return tuple(parts)

    def budgeted_texts(self) -> tuple[str, ...]:
        """The text the applicable character budget is measured against.

        For an ordinary brief this is the whole first screen, critical
        limitations included: a limitation is one of the seven rows the
        reader is meant to see, so it may not be moved off the first screen
        to buy room for other text.

        For a safety-overflow brief it is the code template only.  Design
        section 4.3 explicitly exempts the adjacent limitation list from the
        budget, and the reason it is exempt is that it must stay complete --
        the list is the payload of the overflow result, and counting it
        against 120 characters would push the system back toward the
        truncation the rule forbids.
        """
        if self.kind == "ordinary":
            return self.body_texts()
        return (self.judgement, self.key_question.text, self.next_check.text)

    @property
    def character_count(self) -> int:
        """Unicode characters measured against the applicable budget.

        Derived, never stored: the wire payload carries the text and each
        side counts it, so a stale stored count cannot disagree with the text
        it claims to measure.
        """
        return sum(len(part) for part in self.budgeted_texts())

    @model_validator(mode="after")
    def _budget_and_shape(self) -> CatalystBrief:
        if self.kind == "ordinary":
            if len(self.key_evidence) > 3:
                raise ValueError("an ordinary brief carries at most three key evidence lines")
            if self.overflow_reason is not None:
                raise ValueError("an ordinary brief must not carry an overflow reason")
            if self.character_count > BRIEF_CHARACTER_BUDGET:
                raise ValueError(
                    "ordinary brief exceeds the first-screen character budget; "
                    "publish the safety-overflow template instead of truncating"
                )
        else:
            if self.overflow_reason != SAFETY_OVERFLOW_REASON:
                raise ValueError("a safety-overflow brief must carry the overflow reason")
            if self.priority != SAFETY_OVERFLOW_PRIORITY:
                raise ValueError("a safety-overflow brief must be information-insufficient")
            if self.character_count > SAFETY_OVERFLOW_TEMPLATE_BUDGET:
                raise ValueError("the safety-overflow template exceeds its own budget")
            if not self.critical_limitations:
                raise ValueError(
                    "a safety-overflow brief must keep the full limitation list adjacent"
                )
        if self.primary_catalyst_event_id is None and self.primary_catalyst is not None:
            raise ValueError("a primary catalyst line requires its event id")
        return self

    def lines(self) -> tuple[tuple[str, BriefLine], ...]:
        """Every referenced first-screen line, labelled for error messages."""
        lines: list[tuple[str, BriefLine]] = []
        if self.primary_catalyst is not None:
            lines.append(("primary_catalyst", self.primary_catalyst))
        for index, line in enumerate(self.key_evidence):
            lines.append((f"key_evidence[{index}]", line))
        lines.append(("key_question", self.key_question))
        lines.append(("next_check", self.next_check))
        for index, line in enumerate(self.critical_limitations):
            lines.append((f"critical_limitations[{index}]", line))
        return tuple(lines)


class BudgetUsage(_PublicModel):
    """What the run actually spent, including what it could not measure.

    Unknown usage is recorded as ``None`` with an explicit availability flag.
    Counting a missing token measurement as zero is the accounting error that
    makes a cost regression invisible, so the type forbids it.
    """

    model_attempts: int = Field(ge=0)
    structured_output_repairs: int = Field(ge=0)
    network_retries: int = Field(ge=0)
    data_capability_calls: int = Field(ge=0)
    http_attempts: int = Field(ge=0)
    semantic_preprocess_calls: int = Field(ge=0)
    model_usage_available: bool = True
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    stage_durations_ms: tuple[tuple[str, int], ...] = ()
    termination_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _usage_availability(self) -> BudgetUsage:
        for name, value in (("input_tokens", self.input_tokens), ("output_tokens", self.output_tokens)):
            if not self.model_usage_available and value is not None:
                raise ValueError(f"{name} must be absent when model usage is unavailable")
        return self


class ResearchPriorityDecision(_PublicModel):
    """The published category plus the deterministic ceiling applied to it."""

    priority: ResearchPriority
    candidate_priority: ResearchPriority
    proposed_by: Literal["synthesis", "code"] = "synthesis"
    blocking_reasons: tuple[str, ...] = ()
    rationale: str = Field(min_length=1, max_length=400)

    @field_validator("blocking_reasons")
    @classmethod
    def _registered_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("blocking reasons must be unique")
        unknown = [item for item in value if item not in PRIORITY_BLOCKING_REASONS]
        if unknown:
            raise ValueError(f"unregistered blocking reason(s): {unknown}")
        return value

    @model_validator(mode="after")
    def _ceiling_is_applied(self) -> ResearchPriorityDecision:
        if (
            self.priority == "verify_first"
            and not set(self.blocking_reasons).isdisjoint(PRIORITY_BLOCKING_REASONS)
        ):
            raise ValueError(
                "a blocking reason forbids publishing the top research priority"
            )
        if self.priority != self.candidate_priority and not self.blocking_reasons:
            raise ValueError(
                "a lowered priority must record the reason that lowered it"
            )
        return self


class CatalystResearchCase(_PublicModel):
    """The authoritative committed result of one ``catalyst_v1`` run."""

    schema_version: Literal["catalyst-research-case-v1"] = CATALYST_CASE_SCHEMA_VERSION
    schema_number: Literal[1] = CATALYST_CASE_SCHEMA_NUMBER
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    research_profile: Literal["catalyst_v1"] = "catalyst_v1"
    evidence_policy: str = Field(min_length=1, max_length=80)
    as_of: datetime
    source_sequence: int = Field(ge=0)
    completeness: CaseCompleteness
    quality: ResearchQuality
    reason_codes: tuple[str, ...] = ()
    research_question: str | None = Field(default=None, max_length=400)
    evidence: tuple[CatalystEvidence, ...] = ()
    events: tuple[CatalystEvent, ...] = ()
    findings: tuple[SpecialistFinding, ...] = ()
    challenges: tuple[Challenge, ...] = ()
    dispositions: tuple[ChallengeDisposition, ...] = ()
    priority_decision: ResearchPriorityDecision
    brief: CatalystBrief
    budget_usage: BudgetUsage

    @field_validator("reason_codes")
    @classmethod
    def _registered_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("reason codes must be unique")
        return value

    @field_validator("reason_codes")
    @classmethod
    def _reason_shape(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        import re

        for code in value:
            if re.fullmatch(REASON_CODE_PATTERN, code) is None:
                raise ValueError(f"reason code is not a registered-style code: {code}")
        return value

    @model_validator(mode="after")
    def _public_graph_is_closed(self) -> CatalystResearchCase:
        self._validate_identity_and_uniqueness()
        self._validate_dependencies_resolve()
        self._validate_inferences_depend_on_surviving_facts()
        self._validate_unknowns_are_bare()
        self._validate_challenge_dispositions()
        self._validate_priority_ceiling()
        self._validate_brief_is_bound()
        return self

    # -- identity ---------------------------------------------------------
    def _validate_identity_and_uniqueness(self) -> None:
        for label, ids in (
            ("evidence", [item.evidence_id for item in self.evidence]),
            ("event", [item.event_id for item in self.events]),
            ("finding", [item.finding_id for item in self.findings]),
            ("challenge", [item.challenge_id for item in self.challenges]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"{label} IDs must be unique within the run")
        for item in self.evidence:
            if item.run_id != self.run_id or item.ticker != self.ticker:
                raise ValueError("evidence must belong to the current run and ticker")
        for item in self.events:
            if item.run_id != self.run_id or item.ticker != self.ticker:
                raise ValueError("events must belong to the current run and ticker")
        for item in self.findings:
            if item.run_id != self.run_id:
                raise ValueError("findings must belong to the current run")
        for item in self.challenges:
            if item.run_id != self.run_id:
                raise ValueError("challenges must belong to the current run")

    # -- resolvability ----------------------------------------------------
    def _validate_dependencies_resolve(self) -> None:
        evidence_ids = {item.evidence_id for item in self.evidence}
        event_ids = {item.event_id for item in self.events}
        finding_ids = {item.finding_id for item in self.findings}
        challenge_ids = {item.challenge_id for item in self.challenges}

        for item in self.evidence:
            parent = item.republished_from_evidence_id
            if parent is not None and parent not in evidence_ids:
                raise ValueError("republication must point at an evidence record in this run")
        for item in self.events:
            for ref in item.date_evidence_ids:
                if ref not in evidence_ids:
                    raise ValueError("event date evidence is not present in this run")
            if item.updated_by_evidence_id and item.updated_by_evidence_id not in evidence_ids:
                raise ValueError("event update evidence is not present in this run")
            if item.supersedes_event_id and item.supersedes_event_id not in event_ids:
                raise ValueError("superseded event is not present in this run")
        for item in self.findings:
            for ref in item.evidence_ids:
                if ref not in evidence_ids:
                    raise ValueError("finding evidence is not present in this run")
            for ref in item.event_ids:
                if ref not in event_ids:
                    raise ValueError("finding event is not present in this run")
        for item in self.challenges:
            for ref in item.evidence_ids:
                if ref not in evidence_ids:
                    raise ValueError("challenge evidence is not present in this run")
            for ref in item.target_finding_ids:
                if ref not in finding_ids:
                    raise ValueError("challenge target finding is not present in this run")
            for ref in item.target_event_ids:
                if ref not in event_ids:
                    raise ValueError("challenge target event is not present in this run")
        for item in self.dispositions:
            if item.challenge_id not in challenge_ids:
                raise ValueError("disposition references an unknown challenge")
            for ref in item.evidence_ids:
                if ref not in evidence_ids:
                    raise ValueError("disposition evidence is not present in this run")
            for ref in item.finding_ids:
                if ref not in finding_ids:
                    raise ValueError("disposition finding is not present in this run")
        if (
            self.brief.primary_catalyst_event_id is not None
            and self.brief.primary_catalyst_event_id not in event_ids
        ):
            raise ValueError("brief primary catalyst is not present in this run")

    # -- inference grounding ---------------------------------------------
    def _validate_inferences_depend_on_surviving_facts(self) -> None:
        surviving = {item.finding_id for item in self.findings if item.survives}
        kinds = {item.finding_id: item.kind for item in self.findings}
        for item in self.findings:
            for ref in item.supporting_finding_ids:
                if ref not in kinds:
                    raise ValueError("inference support is not present in this run")
                if ref not in surviving:
                    raise ValueError("inference depends on a removed finding")
                if kinds[ref] != "fact":
                    raise ValueError("inference must depend on surviving facts")

    # -- unknowns ---------------------------------------------------------
    def _validate_unknowns_are_bare(self) -> None:
        for item in self.findings:
            if item.kind == "unknown" and (item.evidence_ids or item.confidence is not None):
                raise ValueError("an unknown must not carry evidence or confidence")

    # -- challenges -------------------------------------------------------
    def _validate_challenge_dispositions(self) -> None:
        by_challenge = {item.challenge_id: item for item in self.challenges}
        disposition_ids = [item.challenge_id for item in self.dispositions]
        if len(set(disposition_ids)) != len(disposition_ids):
            raise ValueError("each challenge may carry only one disposition")
        if set(disposition_ids) != set(by_challenge):
            raise ValueError("every challenge requires a disposition")

    # -- priority ceiling -------------------------------------------------
    def _validate_priority_ceiling(self) -> None:
        decision = self.priority_decision
        # A code-visible blocking condition always forbids the top category,
        # even if the synthesis model asked for it and nobody recorded a
        # reason. This is the deterministic half of design section 9.1.
        for code in self.reason_codes:
            if code in PRIORITY_BLOCKING_REASONS and decision.priority == "verify_first":
                raise ValueError(
                    f"reason code {code!r} forbids publishing the top research priority"
                )
        if decision.priority == "verify_first":
            for challenge in self.challenges:
                disposition = next(
                    item
                    for item in self.dispositions
                    if item.challenge_id == challenge.challenge_id
                )
                if challenge.is_key and disposition.outcome == "unresolved":
                    raise ValueError(
                        "an unresolved key challenge forbids publishing the top "
                        "research priority"
                    )
        if self.completeness == "blocked" and decision.priority != "insufficient_information":
            raise ValueError("a blocked case must publish insufficient-information priority")
        if self.brief.priority != decision.priority:
            raise ValueError("brief priority must match the published priority decision")

    # -- brief binding ----------------------------------------------------
    def _validate_brief_is_bound(self) -> None:
        surviving_findings = {item.finding_id for item in self.findings if item.survives}
        event_ids = {item.event_id for item in self.events}
        challenge_ids = {item.challenge_id for item in self.challenges}
        lines = self.brief_lines()
        for _label, line in lines:
            for ref in line.finding_ids:
                if ref not in surviving_findings:
                    raise ValueError("the brief must not reference a removed finding")
            for ref in line.event_ids:
                if ref not in event_ids:
                    raise ValueError("the brief must not reference an unknown event")
            for ref in line.challenge_ids:
                if ref not in challenge_ids:
                    raise ValueError("the brief must not reference an unknown challenge")
        if self.brief.primary_catalyst is not None:
            for ref in self.brief.primary_catalyst.event_ids:
                if ref != self.brief.primary_catalyst_event_id:
                    raise ValueError("the primary catalyst line must reference its own event")

    def brief_lines(self) -> tuple[tuple[str, BriefLine], ...]:
        """Every referenced first-screen line, forwarded from the brief."""
        return self.brief.lines()

    def removed_finding_ids(self) -> tuple[str, ...]:
        """Findings a gate dropped; the recursive check re-runs after each."""
        return tuple(item.finding_id for item in self.findings if not item.survives)


SpecialistFinding.model_rebuild()


def brief_character_count(brief: CatalystBrief) -> int:
    """Count the text the applicable first-screen budget is measured against.

    This is the single backend definition: the 420/120 publish gates and the
    shared cross-language fixture both read it, so a reader never has to know
    which brief kind it is holding to know which strings were measured.

    The count is in Unicode characters -- one per glyph, matching Python's
    ``len`` on a ``str`` -- and sums the applicable texts with no separator: a
    renderer joins lines with its own layout, and a join separator is not
    reader-facing text. Navigation, field labels, the company name, and time
    metadata are not part of ``CatalystBrief`` and therefore cannot enter the
    count by construction.

    The strings differ by brief kind; see ``CatalystBrief.budgeted_texts``.
    """
    return sum(len(part) for part in brief.budgeted_texts())
