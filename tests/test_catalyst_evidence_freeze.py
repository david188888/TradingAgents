"""Evidence freeze assembly and per-role isolation (plan T19, T20, T24).

These tests encode three rules that are easy to state and easy to lose:

* A source that failed must not become "no events".  The most expensive
  failure mode in this system is a run that concludes there is no catalyst
  because a vendor timed out, so almost every test here is about the
  difference between an empty result and an unusable one.
* Isolation is a property of the view a role receives, not a promise about
  how a prompt was written.
* The freeze is a boundary.  Everything after it is closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from tradingagents.dataflows.catalyst_events import (
    CatalystEventV1,
    EventQueryOutcomeV1,
    content_fingerprint,
)
from tradingagents.execution.budget import BudgetBucket, BudgetLedger
from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
from tradingagents.research.evidence_freeze import (
    CAP_CONSENSUS,
    CAP_EVENT_COVERAGE,
    CAP_FUNDAMENTALS,
    CAP_IDENTITY,
    CAP_PRICE,
    CAP_SENTIMENT,
    REQUIRED_CAPABILITIES,
    ROLE_ORDER,
    CapabilityStatus,
    EvidenceFreezer,
    FreezeInputs,
    FrozenCapability,
    PriceObservation,
    SupplementClosed,
    build_specialist_view,
    empty_draft,
    freeze_evidence_draft,
)

CUTOFF = "2026-09-29"


def _event(
    title: str = "关于回购公司股份的方案",
    *,
    publication_date: str = "2026-09-20",
    channel: str = "official",
    kind: str = "buyback",
    security_id: str = "600519",
    body: str = "",
) -> CatalystEventV1:
    return CatalystEventV1(
        security_id=security_id,
        kind=kind,
        channel=channel,
        title=title,
        publication_date=publication_date,
        content_fingerprint=content_fingerprint(title, body),
    )


def _covered(source: str = "cninfo", count: int = 0) -> EventQueryOutcomeV1:
    return EventQueryOutcomeV1(
        outcome="covered_no_matching_events",
        source_id=source,
        item_count=0,
        pagination_exhausted=True,
        reason="source proved the requested window and found nothing",
    )


def _qualified(name: str) -> FrozenCapability:
    return FrozenCapability(
        capability=name,
        status=CapabilityStatus.QUALIFIED,
        required=name in REQUIRED_CAPABILITIES,
        reason="capability produced a verified result",
    )


def _inputs(**kwargs) -> FreezeInputs:
    base = {
        "run_id": "run_freeze",
        "ticker": "600519",
        "cutoff": CUTOFF,
        "policy": catalyst_evidence_policy_v1(),
    }
    base.update(kwargs)
    return FreezeInputs(**base)


def _complete_inputs(**kwargs) -> FreezeInputs:
    return _inputs(
        capabilities=[_qualified(name) for name in REQUIRED_CAPABILITIES],
        evidence=[
            {"evidence_id": f"ev.{name}", "capability": name}
            for name in REQUIRED_CAPABILITIES
        ],
        **kwargs,
    )


# -- the three answer states ------------------------------------------------


def test_a_proven_empty_window_is_usable_and_an_absent_one_is_not() -> None:
    """Design SS8.4/SS9.1: "found nothing" and "could not look" are different.

    Treating a timeout as an empty result is how a run publishes "no recent
    catalyst" on the strength of a vendor that never answered.
    """
    covered = freeze_evidence_draft(
        _complete_inputs(event_outcomes=[_covered()])
    )
    assert covered.status_of(CAP_EVENT_COVERAGE) is CapabilityStatus.COVERED_NO_MATCH
    assert covered.status_of(CAP_EVENT_COVERAGE).is_usable is True

    failed = EventQueryOutcomeV1(
        outcome="coverage_unknown",
        source_id="eastmoney",
        item_count=0,
        reason="request timed out",
        degradations=("vendor_timeout",),
    )
    unknown = freeze_evidence_draft(
        _complete_inputs(event_outcomes=[failed])
    )
    assert unknown.status_of(CAP_EVENT_COVERAGE) is CapabilityStatus.COVERAGE_UNKNOWN
    assert unknown.status_of(CAP_EVENT_COVERAGE).is_usable is False
    assert "required_capability_unqualified:event_coverage:coverage_unknown" in (
        build_specialist_view(unknown, "catalyst_events").limitations
    )


def test_an_unusable_coverage_source_also_withholds_the_events_it_returned() -> None:
    """A source that could not prove its window is not evidence at all.

    A capability record can be "qualified" while the query that filled it
    timed out. If the events from that source stayed citable, a specialist
    could cite a filing whose completeness was never established -- and the
    role would have no way to know. This is the mutation the
    ``usable_event`` gate exists to prevent.
    """
    # The event cites the coverage evidence record, so the only thing that can
    # withhold it is the coverage status itself.
    inputs = _inputs(
        capabilities=[_qualified(name) for name in REQUIRED_CAPABILITIES],
        evidence=[
            {
                "evidence_id": f"ev.{name}",
                "capability": name,
                "evidence_ids": [f"ev.{CAP_EVENT_COVERAGE}"],
            }
            for name in REQUIRED_CAPABILITIES
        ],
        events=[_event()],
        event_outcomes=[
            EventQueryOutcomeV1(
                outcome="coverage_unknown",
                source_id="cninfo",
                item_count=0,
                reason="request timed out",
                degradations=("vendor_timeout",),
            )
        ],
    )
    draft = freeze_evidence_draft(inputs)
    assert draft.status_of(CAP_EVENT_COVERAGE) is CapabilityStatus.COVERAGE_UNKNOWN
    assert draft.events, "fixture should have produced an event to withhold"

    view = build_specialist_view(draft, "catalyst_events")
    assert view.event_ids() == ()
    assert not any(view.may_cite_event(item.event_id) for item in draft.events)


def test_one_unknown_source_makes_a_multi_source_absence_unprovable() -> None:
    """Two sources both silent is still only silence if both proved coverage."""
    outcomes = [
        _covered("cninfo"),
        EventQueryOutcomeV1(
            outcome="coverage_unknown",
            source_id="eastmoney",
            item_count=0,
            reason="rate limited",
            degradations=("rate_limited",),
        ),
    ]
    draft = freeze_evidence_draft(_complete_inputs(event_outcomes=outcomes))
    assert draft.status_of(CAP_EVENT_COVERAGE) is CapabilityStatus.COVERAGE_UNKNOWN


def test_truncated_pagination_keeps_found_events_but_forbids_an_absence_claim() -> None:
    """Incomplete pagination is not a reason to discard real filings.

    The events that were returned are still evidence. What is withheld is the
    claim that the window is closed, which is a limitation on the finding.
    """
    outcomes = [
        EventQueryOutcomeV1(
            outcome="partial_pagination",
            source_id="cninfo",
            item_count=1,
            pagination_exhausted=False,
            reason="page cap reached before the window was exhausted",
        )
    ]
    draft = freeze_evidence_draft(
        _complete_inputs(events=[_event()], event_outcomes=outcomes)
    )
    assert draft.status_of(CAP_EVENT_COVERAGE) is CapabilityStatus.PARTIAL
    view = build_specialist_view(draft, "catalyst_events")
    assert view.visible_event_ids, "a returned filing must not be discarded"
    assert "capability_coverage_incomplete:event_coverage:partial" in view.limitations


# -- republication and independence ----------------------------------------


def test_three_sites_reprinting_one_filing_yield_one_event_and_one_support() -> None:
    """Design SS13.5: one source family, one event, no manufactured consensus."""
    title = "关于回购公司股份的方案"
    reprints = [
        _event(title, channel="official"),
        # Same fact, boilerplate-wrapped and respaced, as aggregators do.
        _event(f"【转载】{title}（东方财富）", channel="aggregator", body="  "),
        _event(f"{title} - 财联社", channel="aggregator"),
    ]
    # A distinct body would be a distinct fingerprint, so use the same
    # fingerprint explicitly for the reprints the way a syndicator does.
    reprints[1] = reprints[0].model_copy(update={"channel": "aggregator"})
    reprints[2] = reprints[0].model_copy(update={"channel": "aggregator"})

    draft = freeze_evidence_draft(
        _complete_inputs(events=reprints, event_outcomes=[_covered(count=3)])
    )
    assert len(draft.events) == 1
    assert draft.independent_support == 1
    assert draft.events[0].independent_support == 1
    assert draft.events[0].is_fact_anchor is True


def test_independent_support_counts_families_not_links() -> None:
    first = _event("关于回购公司股份的方案", kind="buyback")
    second = _event("2026年半年度报告", kind="earnings_report")
    draft = freeze_evidence_draft(
        _complete_inputs(
            events=[first, first.model_copy(update={"channel": "aggregator"}), second]
        )
    )
    assert len(draft.events) == 2
    assert draft.independent_support == 2


# -- point in time ----------------------------------------------------------


def test_a_post_cutoff_filing_is_excluded_and_counted() -> None:
    """Design SS13.5: cutoff before the execution notice shows only the plan.

    The excluded item is counted rather than dropped silently, so a reader can
    tell "there was nothing" from "something was withheld".
    """
    draft = freeze_evidence_draft(
        _complete_inputs(
            events=[
                _event("关于回购公司股份的方案", publication_date="2026-09-10"),
                _event("回购实施完毕公告", publication_date="2026-10-08"),
            ]
        )
    )
    titles = [item.title for item in draft.events]
    assert titles == ["关于回购公司股份的方案"]
    assert draft.excluded_post_cutoff_count == 1


def test_an_earlier_reporting_period_does_not_rescue_a_future_filing() -> None:
    """A filing about a past period is not knowable before it was published."""
    future = _event("2026年半年度报告", publication_date="2026-10-08").model_copy(
        update={"reporting_period": "2026H1"}
    )
    draft = freeze_evidence_draft(_complete_inputs(events=[future]))
    assert draft.events == ()
    assert draft.excluded_post_cutoff_count == 1


# -- role isolation ---------------------------------------------------------


def test_a_role_cannot_cite_evidence_from_a_capability_it_cannot_see() -> None:
    """Design SS5.2 duty isolation, enforced by the view rather than by prompt.

    Without this, the market role could cite a fundamentals document it was
    never shown and the resulting finding would carry a reference no reader
    could follow.
    """
    base = _complete_inputs()
    draft = freeze_evidence_draft(
        _inputs(
            capabilities=[
                *base.capabilities,
                _qualified(CAP_SENTIMENT),
                _qualified(CAP_CONSENSUS),
            ],
            evidence=[
                *base.evidence,
                {"evidence_id": "ev.sentiment", "capability": CAP_SENTIMENT},
                {"evidence_id": "ev.consensus", "capability": CAP_CONSENSUS},
            ],
        )
    )

    operating = build_specialist_view(draft, "operating_delivery")
    market = build_specialist_view(draft, "market_reaction")

    assert "ev.consensus" in operating.citable_evidence_ids
    assert "ev.consensus" not in market.citable_evidence_ids
    assert "ev.sentiment" in market.citable_evidence_ids
    assert "ev.sentiment" not in operating.citable_evidence_ids
    assert market.may_cite_evidence("ev.consensus") is False
    assert operating.may_cite_evidence("ev.sentiment") is False


def test_evidence_from_an_unusable_capability_is_not_citable() -> None:
    """A finding citing an unavailable source is an unresolvable reference."""
    draft = freeze_evidence_draft(
        _inputs(
            capabilities=[
                _qualified(CAP_IDENTITY),
                _qualified(CAP_EVENT_COVERAGE),
                _qualified(CAP_PRICE),
                FrozenCapability(
                    capability=CAP_FUNDAMENTALS,
                    status=CapabilityStatus.UNAVAILABLE,
                    required=True,
                    reason="vendor returned no parsable statement",
                    degradations=("parse_failed",),
                ),
            ],
            evidence=[
                {"evidence_id": f"ev.{name}", "capability": name}
                for name in REQUIRED_CAPABILITIES
            ],
        )
    )
    operating = build_specialist_view(draft, "operating_delivery")
    assert "ev.fundamentals" not in operating.citable_evidence_ids
    assert draft.missing_required_capabilities() == (CAP_FUNDAMENTALS,)


def test_each_role_carries_only_its_own_question() -> None:
    """Design SS5.2: one question per unit, and roles do not borrow each
    other's question."""
    draft = freeze_evidence_draft(_complete_inputs())
    questions = {build_specialist_view(draft, role).question for role in ROLE_ORDER}
    assert len(questions) == len(ROLE_ORDER)


def test_unverified_adjusted_prices_are_withheld_from_the_market_role() -> None:
    """Design SS8.5/SS13.5: an unprovable qfq series must not enter the view.

    Passing it with a caveat is not enough: a model handed a plausible price
    chain will reason from it, and the caveat competes with the numbers for
    attention.
    """
    draft = freeze_evidence_draft(
        _complete_inputs(
            prices=[
                PriceObservation(
                    observed_on="2026-09-20",
                    close=10.0,
                    adjustment="qfq",
                    pit_verified=False,
                    source="tencent",
                ),
                PriceObservation(
                    observed_on="2026-09-20",
                    close=10.4,
                    adjustment="raw",
                    pit_verified=False,
                    source="tencent",
                ),
                PriceObservation(
                    observed_on="2026-09-21",
                    close=10.6,
                    adjustment="qfq",
                    pit_verified=True,
                    source="wind",
                ),
            ]
        )
    )
    market = build_specialist_view(draft, "market_reaction")
    adjustments = {item.adjustment for item in market.prices}
    assert "qfq" in adjustments
    assert all(
        item.pit_verified or item.adjustment == "raw" for item in market.prices
    )
    assert "pit_unverified_price_observations:1" in market.limitations
    # No other role receives prices at all.
    assert build_specialist_view(draft, "catalyst_events").prices == ()


def test_a_price_observation_after_the_cutoff_is_rejected() -> None:
    with pytest.raises(ValueError):
        freeze_evidence_draft(
            _complete_inputs(
                prices=[
                    PriceObservation(
                        observed_on="2026-10-01", close=10.0, source="wind"
                    )
                ]
            )
        )


# -- required-capability blocking ------------------------------------------


def test_a_role_whose_required_capability_failed_is_told_so() -> None:
    """Design SS9.1: a degraded required capability caps the final priority.

    The role is not handed a gap and asked to reason about it -- a model given
    an empty price set will describe the price action it cannot see.
    """
    draft = freeze_evidence_draft(
        _inputs(
            capabilities=[
                _qualified(CAP_IDENTITY),
                _qualified(CAP_EVENT_COVERAGE),
                _qualified(CAP_FUNDAMENTALS),
                FrozenCapability(
                    capability=CAP_PRICE,
                    status=CapabilityStatus.UNAVAILABLE,
                    required=True,
                    reason="no qualifying trading history",
                    degradations=("insufficient_history",),
                ),
            ],
        )
    )
    assert build_specialist_view(draft, "market_reaction").prices == ()
    assert "required_capability_unqualified:price_history:unavailable" in (
        build_specialist_view(draft, "market_reaction").limitations
    )
    # A required capability for a *different* role is not this role's gap.
    assert not any(
        "price_history" in note
        for note in build_specialist_view(draft, "operating_delivery").limitations
    )


def test_optional_capability_absence_does_not_block() -> None:
    """Design SS9: sentiment is optional; missing it must not stop research."""
    base = _complete_inputs()
    draft = freeze_evidence_draft(
        _inputs(
            capabilities=[
                *base.capabilities,
                FrozenCapability(
                    capability=CAP_SENTIMENT,
                    status=CapabilityStatus.UNAVAILABLE,
                    required=False,
                    reason="no sentiment source configured",
                    degradations=("not_configured",),
                ),
            ]
        )
    )
    assert draft.missing_required_capabilities() == ()
    # Both optional capabilities are disclosed as gaps; neither blocks.
    assert set(draft.degraded_optional_capabilities()) == {
        CAP_SENTIMENT,
        CAP_CONSENSUS,
    }


def test_empty_draft_marks_every_required_capability_unavailable() -> None:
    """Design SS9.1: a blocked run is an honest artifact, not an absent one."""
    draft = empty_draft("run_x", "600519", CUTOFF)
    assert draft.missing_required_capabilities() == REQUIRED_CAPABILITIES
    for role in ROLE_ORDER:
        assert any(
            "required_capability_unqualified" in note
            for note in build_specialist_view(draft, role).limitations
        )


# -- the freeze boundary ----------------------------------------------------


def test_draft_id_is_content_addressed_and_changes_with_the_evidence() -> None:
    """A result must be tieable to the exact snapshot that produced it."""
    first = freeze_evidence_draft(_complete_inputs(events=[_event()]))
    same = freeze_evidence_draft(_complete_inputs(events=[_event()]))
    other = freeze_evidence_draft(
        _complete_inputs(events=[_event("2026年半年度报告", kind="earnings_report")])
    )
    assert first.draft_id == same.draft_id
    assert first.draft_id != other.draft_id


def test_the_draft_is_immutable_once_frozen() -> None:
    """Design SS5.1: nothing writes to the draft after the freeze."""
    freezer = EvidenceFreezer(_complete_inputs(events=[_event()]))
    draft = freezer.close()
    with pytest.raises(ValidationError):
        draft.cutoff = "2026-10-01"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        draft.events = ()  # type: ignore[misc]


def test_supplement_is_allowed_once_before_the_freeze() -> None:
    freezer = EvidenceFreezer(_complete_inputs())
    assert freezer.is_open() is True
    freezer.supplement(
        capability=CAP_SENTIMENT,
        result=FrozenCapability(
            capability=CAP_SENTIMENT,
            status=CapabilityStatus.QUALIFIED,
            reason="fetched in the supplement round",
        ),
    )
    assert freezer.capabilities_used == (CAP_SENTIMENT,)
    assert freezer.is_open() is True  # the round is still open, under its cap


def test_supplement_after_the_freeze_is_refused() -> None:
    """Design SS5.1: no open-ended retrieval once the draft is frozen."""
    freezer = EvidenceFreezer(_complete_inputs())
    freezer.close()
    with pytest.raises(SupplementClosed):
        freezer.supplement(capability=CAP_SENTIMENT)


def test_a_second_supplement_round_is_refused() -> None:
    """Design SS5.1 allows one round, not one capability per round."""
    freezer = EvidenceFreezer(_complete_inputs())
    freezer.supplement(capability=CAP_SENTIMENT)
    freezer.end_supplement_round()
    with pytest.raises(SupplementClosed):
        freezer.supplement(capability=CAP_CONSENSUS)


def test_a_supplement_covers_at_most_three_capabilities() -> None:
    """Design SS5.1: one round, at most three missing capabilities."""
    freezer = EvidenceFreezer(_complete_inputs())
    for name in (CAP_SENTIMENT, CAP_CONSENSUS, CAP_PRICE):
        freezer.supplement(capability=name)
    with pytest.raises(SupplementClosed):
        freezer.supplement(capability=CAP_FUNDAMENTALS)


def test_a_supplement_outside_the_lookback_window_is_refused() -> None:
    """Design SS5.1: the supplement is bounded by the same window as the freeze.

    A free-form second retrieval round is how a run quietly becomes a different
    run with a longer horizon than the one that was reviewed and frozen.
    """
    policy = catalyst_evidence_policy_v1()
    lookback_days = policy.forward_window_max_calendar_days
    inside = (datetime(2026, 9, 29) - timedelta(days=lookback_days - 1)).date().isoformat()
    outside = (datetime(2026, 9, 29) - timedelta(days=lookback_days + 10)).date().isoformat()

    freezer = EvidenceFreezer(_complete_inputs())
    freezer.supplement(capability=CAP_SENTIMENT, window_start=inside)
    assert freezer.capabilities_used == (CAP_SENTIMENT,)

    strict = EvidenceFreezer(_complete_inputs())
    with pytest.raises(SupplementClosed):
        strict.supplement(capability=CAP_CONSENSUS, window_start=outside)
    assert strict.capabilities_used == ()


def test_the_same_capability_cannot_be_supplemented_twice_in_one_round() -> None:
    freezer = EvidenceFreezer(_complete_inputs())
    freezer.supplement(capability=CAP_SENTIMENT)
    with pytest.raises(SupplementClosed):
        freezer.supplement(capability=CAP_SENTIMENT)


def test_a_supplement_is_charged_to_the_run_budget() -> None:
    """Design SS5.1/SS5.5: the supplement spends the same run budget.

    This is the amplification recorded in the hidden-call audit: one extra
    fetch round that is free is a round that will be taken every time.
    """
    ledger = BudgetLedger("run_freeze")
    freezer = EvidenceFreezer(_complete_inputs(), ledger=ledger)
    freezer.supplement(capability=CAP_SENTIMENT)
    assert ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 1
    assert ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 1


def test_a_supplement_refused_by_the_budget_is_not_applied() -> None:
    """An exhausted budget must close the window, not silently admit the work."""
    ledger = BudgetLedger("run_freeze", limits={
        BudgetBucket.DATA_CAPABILITY_CALLS: 0,
        BudgetBucket.DATA_HTTP_ATTEMPTS: 10,
    })
    freezer = EvidenceFreezer(_complete_inputs(), ledger=ledger)
    with pytest.raises(SupplementClosed):
        freezer.supplement(capability=CAP_SENTIMENT)
    assert freezer.capabilities_used == ()


def test_closing_twice_returns_the_same_snapshot() -> None:
    """A repeated commit must be idempotent (design SS5.4)."""
    freezer = EvidenceFreezer(_complete_inputs())
    assert freezer.close().draft_id == freezer.close().draft_id
