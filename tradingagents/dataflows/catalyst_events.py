"""Normalized catalyst events with point-in-time-safe semantics.

The adapters in this package return *text*: a CSV or a markdown block, with the
raw vendor rows preserved in provenance.  That is enough for a tool result but
not enough for research, which has to distinguish several things a flat list
cannot:

* **What kind of statement this is.**  A performance *forecast* (an announced
  range), a performance *express* (a preliminary figure), and a *formal report*
  (audited/reviewed accounts) are three different evidence strengths.  Collapsing
  them into "earnings" would let a forecast range be read as a result.
* **What period it describes versus when it became knowable.**  A statement about
  H1 published in October has a reporting period in the past and a publication
  date that is the only thing that makes it admissible.
* **Which link in a chain an item is.**  A buyback *plan* and a buyback
  *completed* are two states of one event, not two positives.  Summing them
  double-counts.
* **Whether a source family supports a claim once or many times.**  Three sites
  reprinting one exchange filing are one fact with one supporting source.

Every rule here is deterministic: no model decides whether an item is a fact, a
plan, or a duplicate.  The classification functions return a state that the
caller can inspect, and refuse rather than guess when the input is ambiguous.

The three-state coverage vocabulary from design SS9.1 lives in
:class:`EventQueryOutcomeV1`.  A source that failed, was rate limited, or could
not be paged to completion must never be reported as "no matching events" --
that upgrade is the named failure mode the design forbids.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVIDENCE_POLICY = "catalyst-evidence-policy-v1"

EventKind = Literal[
    "earnings_forecast",
    "earnings_express",
    "earnings_report",
    "buyback",
    "insider_transaction",
    "institutional_research",
    "other_disclosure",
]
# How the item was disclosed.  Only `official` is a fact anchor; the rest are
# discovery entry points that must be resolved to the filing before use
# (design SS8.4: "official disclosure is the fact anchor, structured listings
# are only a discovery entry point").
DisclosureChannel = Literal["official", "exchange", "aggregator", "media", "unknown"]
# Where an item sits in its event's state chain.
EventState = Literal[
    "planned",
    "changed",
    "in_progress",
    "implemented",
    "completed",
    "terminated",
    "point_in_time",
]
# The three answers to "did the query find anything", which are not
# interchangeable (design SS8.4 / SS9.1).
QueryOutcome = Literal[
    "covered_no_matching_events",
    "coverage_unknown",
    "partial_pagination",
]


class DisclosureStrength(str, Enum):
    """How much the item can be relied on as a fact, before any interpretation."""

    OFFICIAL_FILING = "official_filing"
    OFFICIAL_EXCHANGE = "official_exchange"
    AGGREGATOR_TRANSCRIPTION = "aggregator_transcription"
    MEDIA_REPORT = "media_report"
    UNKNOWN = "unknown"


_STRENGTH_BY_CHANNEL: dict[str, DisclosureStrength] = {
    "official": DisclosureStrength.OFFICIAL_FILING,
    "exchange": DisclosureStrength.OFFICIAL_EXCHANGE,
    "aggregator": DisclosureStrength.AGGREGATOR_TRANSCRIPTION,
    "media": DisclosureStrength.MEDIA_REPORT,
    "unknown": DisclosureStrength.UNKNOWN,
}

# Ordering used when several statuses coexist for one run: the most conservative
# outcome wins (design SS9.1, "take the strictest upper bound when states
# coexist").  Lower index == more conservative.
_OUTCOME_SEVERITY = {
    "coverage_unknown": 0,
    "partial_pagination": 1,
    "covered_no_matching_events": 2,
}


class EventQueryOutcomeV1(BaseModel):
    """Why a query returned what it returned, in terms a reader can audit.

    ``covered_no_matching_events`` is only legal when the source *proved* it
    covered the requested window.  A failure, an unsupported capability, a
    throttle, or pagination that did not exhaust all pages all yield
    ``coverage_unknown`` or ``partial_pagination`` instead -- never "no
    events".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: QueryOutcome
    source_id: str = Field(min_length=1, max_length=120)
    requested_start: str | None = None
    requested_end: str | None = None
    item_count: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=1)
    pagination_exhausted: bool | None = None
    reason: str = Field(min_length=1, max_length=400)
    degradations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> EventQueryOutcomeV1:
        if self.outcome == "covered_no_matching_events":
            if self.item_count:
                raise ValueError(
                    "covered_no_matching_events cannot carry items; use the events instead"
                )
            if self.pagination_exhausted is not True:
                raise ValueError(
                    "covered_no_matching_events requires proven pagination exhaustion"
                )
        if self.pagination_exhausted is False and self.outcome != "partial_pagination":
            raise ValueError(
                "unexhausted pagination must be reported as partial_pagination"
            )
        if self.outcome == "coverage_unknown" and not self.degradations:
            raise ValueError("coverage_unknown requires a public degradation code")
        if self.outcome == "covered_no_matching_events" and self.degradations:
            raise ValueError(
                "covered_no_matching_events cannot carry a degradation; it is complete"
            )
        return self

    @property
    def is_provable_absence(self) -> bool:
        """True only when the source proved the window and found nothing."""
        return self.outcome == "covered_no_matching_events"


def strictest_outcome(outcomes: list[EventQueryOutcomeV1]) -> EventQueryOutcomeV1 | None:
    """Reduce several source outcomes to the most conservative one.

    Two sources both reporting "nothing found" is still only "nothing found"
    when both proved coverage.  One unknown among them makes the absence
    unprovable, so the caller must degrade rather than assert a clean window.
    """
    if not outcomes:
        return None
    return min(outcomes, key=lambda item: _OUTCOME_SEVERITY[item.outcome])


class CatalystEventV1(BaseModel):
    """One normalized disclosure, with its evidence status made explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    security_id: str = Field(min_length=1, max_length=64)
    kind: EventKind
    channel: DisclosureChannel
    title: str = Field(min_length=1, max_length=400)
    publication_date: str = Field(min_length=10, max_length=10)
    # The period the item *describes*.  Kept separate from publication_date so
    # a reader cannot mistake "about H1" for "known in H1".
    reporting_period: str | None = Field(default=None, max_length=40)
    reporting_period_kind: Literal["quarter", "half_year", "annual", "point_in_time"] | None = None
    state: EventState = "point_in_time"
    announcement_id: str | None = Field(default=None, max_length=160)
    source_family_id: str | None = Field(default=None, max_length=160)
    content_fingerprint: str = Field(min_length=16, max_length=128)
    amount_low: float | None = None
    amount_high: float | None = None
    # Set for buyback/insider chains so several items can be folded into one.
    chain_id: str | None = Field(default=None, max_length=160)
    notes: tuple[str, ...] = ()

    @field_validator("publication_date")
    @classmethod
    def validate_publication_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("amount_low", "amount_high")
    @classmethod
    def validate_amounts(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("amounts cannot be negative")
        return value

    @model_validator(mode="after")
    def validate_amount_range(self) -> CatalystEventV1:
        if (
            self.amount_low is not None
            and self.amount_high is not None
            and self.amount_low > self.amount_high
        ):
            raise ValueError("amount_low cannot exceed amount_high")
        return self

    @property
    def strength(self) -> DisclosureStrength:
        return _STRENGTH_BY_CHANNEL[self.channel]

    @property
    def is_fact_anchor(self) -> bool:
        """Only an official filing or exchange posting anchors a fact."""
        return self.strength in {
            DisclosureStrength.OFFICIAL_FILING,
            DisclosureStrength.OFFICIAL_EXCHANGE,
        }

    @property
    def is_executed(self) -> bool:
        """A plan is not an execution; the distinction is what stops double-counting."""
        return self.state in {"implemented", "completed"}


# --------------------------------------------------------------- fingerprints


def content_fingerprint(title: str, body: str = "") -> str:
    """Stable fingerprint for "same announcement" across reprints.

    Publishers prepend boilerplate and reformat whitespace, so the fingerprint
    is taken over a normalized token stream rather than the raw string.  This is
    what lets a three-site reprint collapse to one event.
    """
    # Collapse *all* whitespace rather than squeezing runs to a single space.
    # In Chinese text a space carries no meaning, so "1200万股" and
    # "1200 万股" are the same fact retypeset, not two facts.  Keeping one
    # space would split the fingerprint on pure formatting.
    normalized = re.sub(r"[\s\u3000]+", "", f"{title}{body}".lower())
    normalized = re.sub(r"[^\w一-鿿%.,()\-:]", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def source_family_id(security_id: str, content_fp: str) -> str:
    """Identity of the underlying fact, independent of who reprinted it.

    Two items with the same security and content fingerprint describe the same
    disclosure no matter which aggregator published them, so they belong to one
    source family and contribute one independent support, not three.
    """
    return f"{security_id}:{content_fp}"


def dedupe_key(event: CatalystEventV1) -> tuple[str, str, str, str]:
    """Deterministic dedup key: security + announcement id + time + fingerprint.

    Deliberately not semantic.  Design SS8.4 requires deterministic dedup first
    and reserves semantic clustering for a budgeted assist; a model must not be
    able to merge two events by paraphrasing them.
    """
    return (
        event.security_id,
        event.announcement_id or "",
        event.publication_date,
        event.content_fingerprint,
    )


def dedupe_events(events: list[CatalystEventV1]) -> list[CatalystEventV1]:
    """Collapse exact duplicates, keeping the strongest-disclosure copy.

    When the same announcement arrives from an aggregator and from the filing
    itself, the official copy wins: it is the fact anchor, and keeping the
    transcription would let a lower-quality source stand in for it.
    """
    best: dict[tuple[str, str, str, str], CatalystEventV1] = {}
    for event in events:
        key = dedupe_key(event)
        current = best.get(key)
        if current is None or _precedence(event) > _precedence(current):
            best[key] = event
    return sorted(best.values(), key=lambda item: (item.publication_date, item.title))


def _precedence(event: CatalystEventV1) -> int:
    """Rank copies of the same announcement; higher wins."""
    return {
        DisclosureStrength.OFFICIAL_FILING: 3,
        DisclosureStrength.OFFICIAL_EXCHANGE: 2,
        DisclosureStrength.AGGREGATOR_TRANSCRIPTION: 1,
        DisclosureStrength.MEDIA_REPORT: 0,
        DisclosureStrength.UNKNOWN: 0,
    }[event.strength]


def group_by_source_family(events: list[CatalystEventV1]) -> list[list[CatalystEventV1]]:
    """Group reprints of the same filing into one family.

    Independent support count is the number of families, never the number of
    items, so a widely syndicated announcement does not manufacture consensus.
    """
    families: dict[str, list[CatalystEventV1]] = {}
    for event in events:
        family = event.source_family_id or source_family_id(
            event.security_id, event.content_fingerprint
        )
        families.setdefault(family, []).append(event)
    return [families[key] for key in sorted(families)]


def independent_support_count(events: list[CatalystEventV1]) -> int:
    """How many *distinct* facts the evidence contains."""
    return len(group_by_source_family(events))


# ------------------------------------------------------ earnings: three states

_FORECAST_TERMS = ("业绩预告", "业绩预亏", "预增", "预减", "预亏", "扭亏", "业绩预告更正")
_EXPRESS_TERMS = ("业绩快报", "快报")
_REPORT_TERMS = ("年度报告", "半年度报告", "季度报告", "第一季度", "第三季度", "业绩报告")


def classify_earnings_title(title: str) -> EventKind:
    """Separate 预告 / 快报 / 正式报表 by title.

    A forecast and a formal report are different evidence strengths: a forecast
    is a company's own estimate of a *range*, a report is an actual period.  If
    the title matches none of the three families the item is kept as
    ``other_disclosure`` rather than being forced into one, because guessing
    would be the same defect as misreading Tencent's column order.
    """
    if any(term in title for term in _REPORT_TERMS):
        return "earnings_report"
    if any(term in title for term in _EXPRESS_TERMS):
        return "earnings_express"
    if any(term in title for term in _FORECAST_TERMS):
        return "earnings_forecast"
    return "other_disclosure"


class EarningsRangeV1(BaseModel):
    """A forecast's announced range, kept as a range.

    The mid-point is deliberately *not* exposed.  Design SS8.4 forbids it:
    "预告区间不取中点冒充实绩".  A caller that wants a point estimate has to
    choose one and say so; the type does not hand it out by default.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    low: float
    high: float
    currency: str = "CNY"
    basis: Literal["net_profit", "revenue", "eps", "unspecified"] = "unspecified"
    # A period expressed as a single figure is a point forecast, not a range.
    # It is recorded as a degenerate range and flagged, so the difference
    # between "we know the number" and "we know a range" survives.
    is_point_estimate: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> EarningsRangeV1:
        if self.low > self.high:
            raise ValueError("forecast low cannot exceed forecast high")
        if self.is_point_estimate and self.low != self.high:
            raise ValueError("a point estimate must have low == high")
        return self

    def as_text(self) -> str:
        """Render the announced range. Never collapses to a single number."""
        if self.low == self.high:
            return f"{self.low:,.2f} {self.currency}（点值预估）"
        return f"{self.low:,.2f} – {self.high:,.2f} {self.currency}"


def reporting_period_for(publication_date: str, *, kind: str) -> str | None:
    """Infer the period a filing describes from its publication date.

    A-share filing deadlines are stable enough to make this deterministic, and
    the *publication* date is what the caller filters on.  The inferred period is
    metadata for the reader, never a substitute for the filing's own statement.
    """
    try:
        published = date.fromisoformat(publication_date)
    except ValueError:
        return None
    year = published.year
    month = published.month
    if kind == "earnings_forecast":
        # Forecasts are published ahead of the period they describe.
        return f"{year - 1}Q4" if month >= 1 and month <= 3 else f"{year}H1"
    if kind == "earnings_express":
        return _period_for_month(month, year)
    if kind == "earnings_report":
        return _period_for_report_month(month, year)
    return None


def _period_for_month(month: int, year: int) -> str:
    if month <= 4:
        return f"{year - 1}Q4"
    if month <= 8:
        return f"{year}H1"
    return f"{year}Q3"


def _period_for_report_month(month: int, year: int) -> str:
    """Map a *report* publication month to the period the report covers.

    The A-share deadline calendar has a genuine ambiguity in April: a company
    may file either the first-quarter report or the prior year's annual report
    in that window, and the publication month alone cannot distinguish them.
    Rather than pick one and be silently wrong for half of all filers, April
    resolves to ``None`` -- the period is unknown, not guessed.

    A caller holding the filing itself reads ``reporting_period`` off the
    document; this helper is only the fallback for when it does not.
    """
    if month == 4:
        # Ambiguous by construction: Q1 of this year, or the prior annual.
        return None
    if month <= 8:
        return f"{year}H1"
    if month <= 10:
        return f"{year}Q3"
    if month <= 12:
        return f"{year}annual"
    return f"{year}Q1"


# --------------------------------------------------------- PIT admissibility


def is_admissible(
    event: CatalystEventV1,
    *,
    cutoff: str,
) -> tuple[bool, str]:
    """Can this event be used in research as of ``cutoff``?

    Design SS8.4: "official announcements published after the cutoff must not
    enter historical research, even when the financial reporting period is
    earlier".  The reporting period being in the past does not make a filing
    knowable before it was published, so the publication date is the only gate.
    """
    if event.publication_date > cutoff:
        return (
            False,
            f"published {event.publication_date}, after cutoff {cutoff}"
            + (
                f" (describes {event.reporting_period}, which does not make it knowable earlier)"
                if event.reporting_period
                else ""
            ),
        )
    return True, ""


def filter_admissible(
    events: list[CatalystEventV1], *, cutoff: str
) -> tuple[list[CatalystEventV1], list[CatalystEventV1]]:
    """Split events into (admissible, rejected) for a historical cutoff."""
    kept: list[CatalystEventV1] = []
    rejected: list[CatalystEventV1] = []
    for event in events:
        (kept if is_admissible(event, cutoff=cutoff)[0] else rejected).append(event)
    return kept, rejected


# -------------------------------------------- buyback / insider state chains

# A-share buyback titles interleave their keywords rather than using a fixed
# phrase: "关于调整回购公司股份的方案" carries an adjustment word, a plan word and
# a noun phrase at once, and none of them are adjacent. Substring matching on a
# phrase list therefore misses the real titles entirely, so classification is
# done on separate *marker* sets -- advancement first, plan second.
_BUYBACK_SUBJECT_MARKERS: tuple[str, ...] = ("回购", "购回")
_BUYBACK_ADVANCEMENT_MARKERS: dict[EventState, tuple[str, ...]] = {
    "terminated": ("终止", "撤销", "作废", "失败"),
    "completed": ("实施完毕", "完成", "完毕", "结果"),
    "changed": ("调整", "变更", "修订"),
    "in_progress": ("首次", "进展", "实施", "已回购", "回购进展"),
}
_BUYBACK_PLAN_MARKERS: tuple[str, ...] = ("方案", "计划", "预案", "拟", "报告书")


def classify_buyback_state(title: str) -> EventState | None:
    """Place a buyback announcement on its state chain.

    Order matters in two directions.  A title carrying both a plan and an
    adjustment word is an *adjustment* of an existing plan, not a new plan.
    A title carrying both "实施" and "完毕" is *complete*, not in progress.
    """
    # Not a buyback announcement at all.
    if not any(marker in title for marker in _BUYBACK_SUBJECT_MARKERS):
        return None

    # An advancement marker wins outright: "实施完毕" is completion no matter
    # how many plan markers the title also carries.
    for state in ("terminated", "completed", "changed", "in_progress"):
        if any(marker in title for marker in _BUYBACK_ADVANCEMENT_MARKERS[state]):
            return state
    # No advancement marker: this is the original intention.
    if any(marker in title for marker in _BUYBACK_PLAN_MARKERS):
        return "planned"
    return None


class ChainFoldV1(BaseModel):
    """One event's collapsed state chain, with its latest state and amounts.

    A chain is the unit of evidence.  Summing a plan and its completion would
    count one buyback twice, so the fold reports the *latest* state and the
    executed amount separately from the planned amount.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chain_id: str
    security_id: str
    latest_state: EventState
    planned_amount: float | None = None
    executed_amount: float | None = None
    positive_state_count: int = Field(ge=0, default=0)
    member_publications: tuple[str, ...] = ()

    @property
    def is_executed(self) -> bool:
        return self.latest_state in {"implemented", "completed"}


def fold_chain(events: list[CatalystEventV1]) -> ChainFoldV1:
    """Collapse one buyback / insider chain into a single evidence unit.

    ``positive_state_count`` counts how many *distinct* states the chain passed
    through, so a state change reported twice does not inflate it.  This is the
    assertion behind "状态变更不重复计为两个利好".
    """
    if not events:
        raise ValueError("cannot fold an empty chain")
    chain_id = events[0].chain_id
    security = events[0].security_id
    if any(event.chain_id != chain_id for event in events):
        raise ValueError("all events in a fold must share one chain_id")
    if any(event.security_id != security for event in events):
        raise ValueError("all events in a chain must share one security")

    ordered = sorted(events, key=lambda item: (item.publication_date, item.title))
    latest_state = ordered[-1].state
    # Distinct (state, publication) pairs: a re-published state is one state.
    distinct_states = {(event.state, event.publication_date) for event in ordered}
    return ChainFoldV1(
        chain_id=chain_id or "",
        security_id=security,
        latest_state=latest_state,
        planned_amount=_max_amount(ordered, states={"planned", "changed"}),
        executed_amount=_max_amount(ordered, states={"implemented", "completed"}),
        positive_state_count=len(distinct_states),
        member_publications=tuple(
            dict.fromkeys(event.publication_date for event in ordered)
        ),
    )


def _max_amount(events: list[CatalystEventV1], *, states: set[str]) -> float | None:
    values = [
        event.amount_high if event.amount_high is not None else event.amount_low
        for event in events
        if event.state in states
        and (event.amount_high is not None or event.amount_low is not None)
    ]
    return max(values) if values else None


def planned_is_not_executed(events: list[CatalystEventV1]) -> bool:
    """A plan must never be read as a completed action.

    Design SS8.4: "计划金额不等于已执行金额".  True means a reader who summed
    these items as completed executions would be wrong.
    """
    if not any(event.state in {"planned", "changed"} for event in events):
        return False
    return not any(event.state in {"implemented", "completed"} for event in events)


# ------------------------------------- institutional research: statement gate

_MANAGEMENT_STATEMENT_TERMS = (
    "表示",
    "认为",
    "预计将",
    "有望",
    "计划",
    "拟",
    "战略合作",
)
_ORDER_TERMS = ("中标", "已签订", "订单", "合同金额", "签署", "成交")


class InferenceRejected(Exception):
    """A prohibited upgrade was attempted on a disclosure."""


def assert_not_upgraded_to_order_fact(text: str) -> None:
    """Refuse to read a management statement as an executed order.

    Design SS9/T16: "管理层表述不升级为订单事实".  A company *saying* it expects
    orders, or describing a plan, is not a disclosed contract.  The gate raises
    rather than returning a softened value, so a caller cannot ignore it.
    """
    if any(term in text for term in _ORDER_TERMS) and any(
        term in text for term in _MANAGEMENT_STATEMENT_TERMS
    ):
        raise InferenceRejected(
            "text mixes a management statement with order vocabulary; "
            "a stated intention or plan is not a disclosed contract and "
            "must not be recorded as an order fact"
        )


def is_institutional_research(ticker_events: list[CatalystEventV1]) -> bool:
    """Whether any item is an institutional research visit record."""
    return any(event.kind == "institutional_research" for event in ticker_events)


def summarize_for_audit(events: list[CatalystEventV1]) -> dict[str, Any]:
    """Small deterministic summary used by the audit trail and by tests."""
    families = group_by_source_family(events)
    return {
        "policy": EVIDENCE_POLICY,
        "event_count": len(events),
        "source_family_count": len(families),
        "independent_support": len(families),
        "fact_anchor_count": sum(1 for event in events if event.is_fact_anchor),
        "executed_count": sum(1 for event in events if event.is_executed),
    }
