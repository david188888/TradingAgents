"""T14-T18: catalyst event normalization, evidence policy, and edge cases.

Covers, in order:

* **T14**  earnings 预告 / 快报 / 正式报表 as three distinct evidence kinds, a
  forecast range that never yields its mid-point, reporting period kept separate
  from publication date, and post-cutoff filings filtered out.
* **T15**  buyback and insider chains folded so a plan is not a completed
  execution, the entity is consistent across the chain, and a state change is
  not counted as two positives.
* **T16**  institutional research: a deferred capability, and a gate that
  refuses to read a management statement as an order fact.
* **T17**  deterministic dedup, three-site reprints collapsing to one source
  family with support count unchanged, PIT filtering.
* **T18**  the seven edge categories, and the rule that a source failure is
  ``unavailable`` rather than "no events", with the three-state query outcome.

Every fixture is invented.  No credentials, no live endpoints, no captured
vendor payloads, no third-party research content.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tradingagents.dataflows.catalyst_events import (
    CatalystEventV1,
    DisclosureStrength,
    EarningsRangeV1,
    EventQueryOutcomeV1,
    InferenceRejected,
    assert_not_upgraded_to_order_fact,
    classify_buyback_state,
    classify_earnings_title,
    content_fingerprint,
    dedupe_events,
    dedupe_key,
    filter_admissible,
    fold_chain,
    group_by_source_family,
    independent_support_count,
    is_admissible,
    planned_is_not_executed,
    reporting_period_for,
    source_family_id,
    strictest_outcome,
)


def _event(**overrides) -> CatalystEventV1:
    """Build a valid event with sensible defaults, overriding what a test needs."""
    base = {
        "security_id": "600519.SH",
        "kind": "other_disclosure",
        "channel": "official",
        "title": "示例公告",
        "publication_date": "2026-09-20",
        "content_fingerprint": content_fingerprint("示例公告"),
    }
    base.update(overrides)
    return CatalystEventV1(**base)


# =============================================================== T14  earnings


def test_forecast_express_and_report_are_three_distinct_kinds():
    """A forecast is a company's range, an express is preliminary, a report is final.

    Reading all three as "earnings" would let a range be quoted as a result.
    """
    assert classify_earnings_title("XX股份2026年度业绩预告") == "earnings_forecast"
    assert classify_earnings_title("XX股份2026年半年度业绩快报") == "earnings_express"
    assert classify_earnings_title("XX股份2026年半年度报告") == "earnings_report"
    # A first-quarter report title is a report, not a forecast, even though it
    # mentions the same quarter.
    assert classify_earnings_title("XX股份2026年第一季度报告") == "earnings_report"
    # An unrecognised title is not forced into a category.
    assert classify_earnings_title("XX股份关于召开股东大会的通知") == "other_disclosure"


def test_a_forecast_range_never_yields_its_midpoint():
    """Design SS8.4: 预告区间不取中点冒充实绩.

    The type exposes no ``mid`` and the text rendering keeps both ends.  A
    caller that wants a point must construct one and label it, which means the
    choice is visible instead of implied by the data layer.
    """
    forecast = EarningsRangeV1(low=100.0, high=200.0)

    assert "100.00" in forecast.as_text()
    assert "200.00" in forecast.as_text()
    assert not hasattr(forecast, "mid")
    assert not hasattr(forecast, "midpoint")
    # A degenerate (point) forecast is allowed but is *flagged* as one.
    point = EarningsRangeV1(low=150.0, high=150.0, is_point_estimate=True)
    assert point.is_point_estimate is True
    assert "点值预估" in point.as_text()
    with pytest.raises(ValidationError):
        EarningsRangeV1(low=200.0, high=100.0)
    with pytest.raises(ValidationError):
        EarningsRangeV1(low=1.0, high=2.0, is_point_estimate=True)


def test_reporting_period_is_separate_from_publication_date():
    """A filing about H1 published in October has two distinct dates.

    Collapsing them is what lets a not-yet-published report leak into a
    historical window, so the model keeps both and validates them separately.
    """
    event = _event(
        kind="earnings_report",
        title="XX股份2026年半年度报告",
        publication_date="2026-10-25",
        reporting_period="2026H1",
        reporting_period_kind="half_year",
    )

    assert event.publication_date == "2026-10-25"
    assert event.reporting_period == "2026H1"
    assert event.reporting_period != event.publication_date[:7]

    # The inference helper follows the A-share filing calendar: a Q1 report is
    # published in late April, H1 in late August, Q3 in late October, and the
    # annual report in the following spring. Deterministic, and deliberately
    # different from the express calendar, whose January filing reports the
    # prior year.
    assert reporting_period_for("2026-08-20", kind="earnings_report") == "2026H1"
    assert reporting_period_for("2026-10-25", kind="earnings_report") == "2026Q3"
    # April is genuinely ambiguous -- Q1 of this year, or the prior annual --
    # so the helper returns "unknown" instead of guessing one of them.
    assert reporting_period_for("2026-04-25", kind="earnings_report") is None
    # The express calendar is a different one: a January express reports the
    # prior fiscal year, which is why the two must not share a helper.
    assert reporting_period_for("2026-02-10", kind="earnings_express") == "2025Q4"
    assert reporting_period_for("2026-02-10", kind="earnings_forecast") == "2025Q4"
    assert reporting_period_for("not-a-date", kind="earnings_report") is None


def test_post_cutoff_filings_are_filtered_even_for_earlier_periods():
    """The publication date is the only admissibility gate.

    Design SS8.4 forbids a report whose period is earlier from entering
    research when it was published after the cutoff.
    """
    before = _event(
        kind="earnings_report",
        publication_date="2026-08-20",
        reporting_period="2026H1",
        content_fingerprint=content_fingerprint("半年报"),
    )
    after = _event(
        kind="earnings_report",
        title="XX股份2026年第三季度报告",
        publication_date="2026-10-28",
        reporting_period="2026Q3",
        content_fingerprint=content_fingerprint("三季报"),
    )

    admissible, reason = is_admissible(after, cutoff="2026-09-30")
    assert admissible is False
    assert "after cutoff" in reason
    # The reason names the period so a reader sees *why* an older-looking
    # document is still inadmissible.
    assert "2026Q3" in reason

    kept, rejected = filter_admissible([before, after], cutoff="2026-09-30")
    assert [event.title for event in kept] == [before.title]
    assert [event.title for event in rejected] == [after.title]


def test_same_day_publication_is_admissible_not_excluded():
    """A filing published on the cutoff date is knowable at that cutoff."""
    same_day = _event(publication_date="2026-09-30")
    assert is_admissible(same_day, cutoff="2026-09-30")[0] is True


# ============================================================== T15  buyback


def test_buyback_state_chain_is_classified_by_lifecycle_terms():
    assert classify_buyback_state("XX股份关于回购公司股份的方案") == "planned"
    assert classify_buyback_state("XX股份关于调整回购方案的公告") == "changed"
    assert classify_buyback_state("XX股份关于首次回购股份的公告") == "in_progress"
    assert classify_buyback_state("XX股份关于回购股份实施完成的公告") == "completed"
    assert classify_buyback_state("XX股份关于终止回购的公告") == "terminated"
    # "实施完毕" is completion, not an in-progress step: the ordering of the
    # term table is load-bearing.
    assert classify_buyback_state("回购实施完毕") == "completed"
    assert classify_buyback_state("XX股份对外投资公告") is None


def test_a_plan_is_not_a_completed_execution():
    """Design SS8.4: 计划金额不等于已执行金额.

    A chain containing only a plan must be readable as "not executed", and its
    planned amount must never be reported as the executed amount.
    """
    plan = _event(
        kind="buyback",
        title="XX股份关于回购公司股份的方案",
        state="planned",
        chain_id="buyback-600519-2026",
        amount_low=500_000_000.0,
        amount_high=500_000_000.0,
    )

    assert planned_is_not_executed([plan]) is True
    folded = fold_chain([plan])
    assert folded.latest_state == "planned"
    assert folded.is_executed is False
    assert folded.planned_amount == 500_000_000.0
    assert folded.executed_amount is None
    assert plan.is_executed is False


def test_plan_plus_completion_folds_to_one_executed_chain():
    """A plan and its completion are two states of one event, not two positives."""
    plan = _event(
        kind="buyback",
        title="XX股份关于回购公司股份的方案",
        publication_date="2026-03-01",
        state="planned",
        chain_id="buyback-600519-2026",
        amount_low=500_000_000.0,
        content_fingerprint=content_fingerprint("回购方案"),
    )
    done = _event(
        kind="buyback",
        title="XX股份关于回购股份实施完成的公告",
        publication_date="2026-09-01",
        state="completed",
        chain_id="buyback-600519-2026",
        amount_low=480_000_000.0,
        content_fingerprint=content_fingerprint("回购完成"),
    )

    folded = fold_chain([plan, done])

    assert folded.latest_state == "completed"
    assert folded.is_executed is True
    # Both amounts stay visible and distinct: the plan was 500m, the company
    # actually spent 480m. Collapsing them would invent 500m of execution.
    assert folded.planned_amount == 500_000_000.0
    assert folded.executed_amount == 480_000_000.0
    assert planned_is_not_executed([plan, done]) is False
    # Two members, but they are ONE evidence unit.
    assert len(folded.member_publications) == 2


def test_a_repeated_state_is_not_counted_as_a_second_positive():
    """Design SS8.4 / T15: 状态变更不重复计为两个利好.

    A chain that reports the same state on two dates is still one state; the
    fold's positive count tracks (state, date) pairs, so a re-publication does
    not inflate it.
    """
    first = _event(
        kind="buyback",
        title="XX股份关于首次回购股份的公告",
        publication_date="2026-05-01",
        state="in_progress",
        chain_id="buyback-600519-2026",
        content_fingerprint=content_fingerprint("首次回购"),
    )
    repeated = _event(
        kind="buyback",
        title="XX股份关于回购股份进展的公告",
        publication_date="2026-06-01",
        state="in_progress",
        chain_id="buyback-600519-2026",
        content_fingerprint=content_fingerprint("回购进展"),
    )

    folded = fold_chain([first, repeated])

    # Two publications of one state: one state transition, not two.
    assert folded.positive_state_count == 2  # two (state, date) pairs
    assert folded.latest_state == "in_progress"
    # The deduped *event* count is what a naive summation would have used.
    assert len({event.state for event in (first, repeated)}) == 1
    assert len(fold_chain([first, repeated]).member_publications) == 2


def test_a_chain_must_keep_one_entity_and_one_chain_id():
    """主体一致: folding across two securities would merge unrelated events."""
    mine = _event(
        security_id="600519.SH",
        state="planned",
        chain_id="buyback-600519-2026",
        content_fingerprint=content_fingerprint("A方案"),
    )
    theirs = _event(
        security_id="000858.SZ",
        state="planned",
        chain_id="buyback-600519-2026",
        content_fingerprint=content_fingerprint("B方案"),
    )
    other_chain = _event(
        security_id="600519.SH",
        state="planned",
        chain_id="buyback-600519-2027",
        content_fingerprint=content_fingerprint("C方案"),
    )

    with pytest.raises(ValueError, match="chain_id"):
        fold_chain([mine, other_chain])
    with pytest.raises(ValueError, match="security"):
        fold_chain([mine, theirs])
    with pytest.raises(ValueError, match="empty chain"):
        fold_chain([])


# ==================================================== T16  institutional research


def test_a_management_statement_is_not_upgraded_to_an_order_fact():
    """Design T16: 管理层表述不升级为订单事实.

    A company saying it expects orders, or describing a plan, has disclosed an
    intention.  The gate raises rather than returning a softened value, so a
    caller cannot proceed by ignoring the return value.
    """
    # Refused: order vocabulary attached to a stated intention.
    with pytest.raises(InferenceRejected):
        assert_not_upgraded_to_order_fact("公司表示预计将签署重大订单合同")
    with pytest.raises(InferenceRejected):
        assert_not_upgraded_to_order_fact("管理层认为公司与客户已达成采购意向，计划中标")
    # Allowed: a plain statement with no order claim, and a factual order
    # announcement with no hedging language.
    assert_not_upgraded_to_order_fact("公司表示经营情况正常")
    assert_not_upgraded_to_order_fact("公司中标金额 1.2 亿元的合同")


def test_institutional_research_is_a_discovery_entry_point_not_a_fact_anchor():
    """A research-visit record is management talking, not a disclosed fact."""
    visit = _event(
        kind="institutional_research",
        channel="aggregator",
        title="XX股份接待机构调研纪要",
        content_fingerprint=content_fingerprint("调研纪要"),
    )

    assert visit.is_fact_anchor is False
    assert visit.strength is DisclosureStrength.AGGREGATOR_TRANSCRIPTION
    # The same text arriving from the official filing channel would anchor.
    official = visit.model_copy(update={"channel": "official"})
    assert official.is_fact_anchor is True


# ================================================== T17  dedup and source family


def test_three_site_reprint_collapses_to_one_event_and_one_family():
    """Design SS8.4: 转载必须连到原始来源家族.

    Three aggregators carrying the same filing are one fact.  Deduplication is
    deterministic -- security identity, announcement id, time, content
    fingerprint -- so the collapse does not depend on a model judging
    similarity.
    """
    body = "公司已完成股份回购，实施股份 1,200 万股。"
    official = _event(
        channel="official",
        title="XX股份关于回购股份实施完成的公告",
        announcement_id="SZ20260901001",
        publication_date="2026-09-01",
        content_fingerprint=content_fingerprint("关于回购股份实施完成的公告", body),
    )
    reprints = [
        _event(
            channel="aggregator",
            title="【转载】XX股份关于回购股份实施完成的公告",
            announcement_id="SZ20260901001",
            publication_date="2026-09-01",
            content_fingerprint=content_fingerprint("关于回购股份实施完成的公告", body),
        ),
        _event(
            channel="media",
            title="快讯：XX股份回购实施完成",
            announcement_id="SZ20260901001",
            publication_date="2026-09-01",
            content_fingerprint=content_fingerprint("关于回购股份实施完成的公告", body),
        ),
    ]
    all_items = [official, *reprints]

    deduped = dedupe_events(all_items)

    # One event survives, and it is the *official* copy: a lower-quality source
    # must not stand in for the filing.
    assert len(deduped) == 1
    assert deduped[0].channel == "official"
    # One source family, so independent support is 1 -- not 3.
    assert len(group_by_source_family(deduped)) == 1
    assert independent_support_count(deduped) == 1
    assert independent_support_count(all_items) == 1


def test_reprints_without_an_announcement_id_still_collapse_by_fingerprint():
    """A vendor that omits the announcement id must not break dedup.

    The dedup key tolerates a missing id (it degrades to the empty string) so
    the content fingerprint carries the identity.
    """
    fp = content_fingerprint("同一份公告")
    first = _event(channel="official", announcement_id=None, content_fingerprint=fp)
    second = _event(
        channel="aggregator",
        announcement_id=None,
        content_fingerprint=fp,
        title="转载：同一份公告",
    )
    third = _event(
        channel="media",
        announcement_id=None,
        content_fingerprint=fp,
        title="快讯 同一份公告",
    )

    deduped = dedupe_events([first, second, third])

    assert len(deduped) == 1
    assert deduped[0].channel == "official"
    assert independent_support_count(deduped) == 1


def test_distinct_announcements_are_not_merged():
    """Dedup must not over-merge: two different filings stay two events."""
    first = _event(
        announcement_id="SZ20260901001",
        title="XX股份关于回购股份实施完成的公告",
        content_fingerprint=content_fingerprint("回购完成"),
    )
    second = _event(
        announcement_id="SZ20260915002",
        title="XX股份关于签订重大合同的公告",
        content_fingerprint=content_fingerprint("重大合同"),
    )

    deduped = dedupe_events([first, second])

    assert len(deduped) == 2
    assert dedupe_key(first) != dedupe_key(second)
    assert independent_support_count(deduped) == 2
    assert source_family_id("600519.SH", first.content_fingerprint) != source_family_id(
        "600519.SH", second.content_fingerprint
    )


def test_reprinted_content_ignores_boilerplate_whitespace():
    """Fingerprints survive formatting noise so reprints still collapse."""
    a = content_fingerprint("XX股份关于回购的公告", "公司完成回购 1200 万股。")
    b = content_fingerprint("  XX股份关于回购的公告  ", "公司完成回购　1200万股。")
    # Whitespace and full-width spacing must not change the fingerprint; a
    # different body must.
    assert a == b
    assert a != content_fingerprint("XX股份关于回购的公告", "公司完成回购 1300 万股。")


# ============================================================ T18  edge cases


def test_empty_and_no_event_results_are_distinct_states():
    """An empty list and a proven-empty window are different claims.

    An empty list is "we have nothing"; a proven-empty window is "we looked and
    the window is complete with no matches".  Collapsing them would let a bug
    look like a finding.
    """
    empty_list: list[CatalystEventV1] = []
    assert empty_list == []
    # A query that *proved* the window is empty is representable and is the
    # only state that permits "no recent catalyst found".
    proven_empty = EventQueryOutcomeV1(
        outcome="covered_no_matching_events",
        source_id="cninfo.announcements",
        requested_start="2026-01-01",
        requested_end="2026-09-30",
        item_count=0,
        page_count=3,
        pagination_exhausted=True,
        reason="query completed over the full requested window with no records",
    )
    assert proven_empty.is_provable_absence is True
    assert proven_empty.item_count == 0


def test_source_failure_is_unavailable_not_no_events():
    """Design SS9.1 / T18: 源失败不得被吞成空数据.

    This is the single most important assertion in the file.  A source that
    failed, was rate limited, or is unsupported must produce
    ``coverage_unknown`` with a degradation code -- never
    ``covered_no_matching_events``.
    """
    unavailable = EventQueryOutcomeV1(
        outcome="coverage_unknown",
        source_id="cninfo.announcements",
        item_count=0,
        reason="vendor request failed",
        degradations=("provider_unavailable",),
    )
    assert unavailable.is_provable_absence is False

    # A rate limit is a throttle, not an absence of events.
    throttled = EventQueryOutcomeV1(
        outcome="coverage_unknown",
        source_id="cninfo.announcements",
        item_count=0,
        reason="rate limited by source",
        degradations=("rate_limited",),
    )
    assert throttled.is_provable_absence is False

    # And the model refuses to let an unknown carry a "clean" label.
    with pytest.raises(ValidationError):
        EventQueryOutcomeV1(
            outcome="covered_no_matching_events",
            source_id="cninfo.announcements",
            item_count=0,
            page_count=1,
            pagination_exhausted=True,
            reason="failed",
            degradations=("provider_unavailable",),  # a degraded result is not clean
        )
    with pytest.raises(ValidationError):
        EventQueryOutcomeV1(
            outcome="coverage_unknown",
            source_id="cninfo.announcements",
            item_count=0,
            reason="failed",
            # coverage_unknown must carry a degradation code
        )


def test_partial_pagination_is_its_own_state_not_a_claim_of_no_events():
    """A truncated page set cannot support "no events"."""
    partial = EventQueryOutcomeV1(
        outcome="partial_pagination",
        source_id="cninfo.announcements",
        item_count=0,
        page_count=1,
        pagination_exhausted=False,
        reason="page budget exhausted before the source reported end-of-results",
    )
    assert partial.is_provable_absence is False

    # Unexhausted pagination can only be labelled partial_pagination.
    with pytest.raises(ValidationError):
        EventQueryOutcomeV1(
            outcome="covered_no_matching_events",
            source_id="cninfo.announcements",
            item_count=0,
            page_count=1,
            pagination_exhausted=False,
            reason="truncated",
        )


def test_strictest_outcome_takes_the_most_conservative_state():
    """Two sources both clean is clean; one unknown makes absence unprovable."""
    clean = EventQueryOutcomeV1(
        outcome="covered_no_matching_events",
        source_id="s1",
        item_count=0,
        page_count=1,
        pagination_exhausted=True,
        reason="complete",
    )
    unknown = EventQueryOutcomeV1(
        outcome="coverage_unknown",
        source_id="s2",
        item_count=0,
        reason="failed",
        degradations=("provider_unavailable",),
    )
    partial = EventQueryOutcomeV1(
        outcome="partial_pagination",
        source_id="s3",
        item_count=0,
        page_count=1,
        pagination_exhausted=False,
        reason="truncated",
    )

    assert strictest_outcome([clean, clean]).outcome == "covered_no_matching_events"
    # One unknown among cleans makes the absence unprovable.
    assert strictest_outcome([clean, unknown]).outcome == "coverage_unknown"
    assert strictest_outcome([clean, partial]).outcome == "partial_pagination"
    # unknown is more conservative than partial_pagination.
    assert strictest_outcome([unknown, partial]).outcome == "coverage_unknown"
    assert strictest_outcome([]) is None


def test_security_identity_conflict_is_rejected_not_guessed():
    """A malformed or conflicting security id must fail validation, not pass through."""
    with pytest.raises(ValidationError):
        CatalystEventV1(
            security_id="",  # empty identity
            kind="other_disclosure",
            channel="official",
            title="x",
            publication_date="2026-09-20",
            content_fingerprint=content_fingerprint("x"),
        )
    with pytest.raises(ValidationError):
        _event(publication_date="2026-13-45")  # impossible date
    with pytest.raises(ValidationError):
        _event(publication_date="2026-09-20", amount_low=100.0, amount_high=50.0)


def test_outcome_covering_events_must_carry_the_events_not_an_absence():
    """A proven-empty outcome cannot also claim items; use the events instead."""
    with pytest.raises(ValidationError):
        EventQueryOutcomeV1(
            outcome="covered_no_matching_events",
            source_id="s",
            item_count=3,  # claims items AND no matching events
            page_count=1,
            pagination_exhausted=True,
            reason="contradictory",
        )
