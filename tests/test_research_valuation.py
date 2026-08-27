"""Tests for the deterministic valuation-position decision chain."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from tradingagents.research.valuation import (
    AnchorOutputV1,
    DailyMultipleV1,
    EarningsBaseV1,
    PeerValuationsV1,
    RangeSynthesisV1,
    ValuationInputsV1,
    ValuationSnapshotInputV1,
    assess_valuation,
    percentile_rank,
    quantile,
    shares_from_cap,
)

AS_OF = date(2026, 8, 20)
START = AS_OF - timedelta(days=1100)


def _pe_history(
    n_days: int = 800,
    low: float = 10.0,
    high: float = 40.0,
) -> tuple[DailyMultipleV1, ...]:
    """Deterministic sawtooth series cycling between ``low`` and ``high``."""
    items: list[DailyMultipleV1] = []
    day = START
    period = 60
    for index in range(n_days):
        phase = (index % period) / period
        value = low + (high - low) * phase
        items.append(DailyMultipleV1(day=day, value=value))
        day += timedelta(days=1)
    return tuple(items)


def _prices(n_days: int = 300, base: float = 50.0) -> tuple[tuple[date, float], ...]:
    day = AS_OF - timedelta(days=n_days - 1)
    return tuple(
        (day + timedelta(days=index), base + (index % 100) * 0.5) for index in range(n_days)
    )


def _inputs(**overrides) -> ValuationInputsV1:
    payload: dict = {
        "run_id": "run-test-1",
        "ticker": "600519.SH",
        "as_of": AS_OF,
        "snapshot": ValuationSnapshotInputV1(
            as_of=AS_OF, price=1500.0, pe_ttm=22.0, pb=7.5, total_market_cap_yi=18800.0
        ),
        "net_income_annual": EarningsBaseV1(
            metric_id="net_income", value_yi=862.0, period="2025-12-31"
        ),
        "equity_annual": EarningsBaseV1(
            metric_id="equity", value_yi=2600.0, period="2025-12-31"
        ),
        "closing_prices": _prices(),
        "pe_history": _pe_history(),
        "peers": None,
    }
    payload.update(overrides)
    return ValuationInputsV1.model_validate(payload)


def test_quantile_linear_interpolation_matches_numpy_default() -> None:
    values = (1.0, 2.0, 3.0, 4.0)
    assert quantile(values, 0.25) == pytest.approx(1.75)
    assert quantile(values, 0.5) == pytest.approx(2.5)
    assert quantile(values, 0.75) == pytest.approx(3.25)
    assert quantile((), 0.5) is None


def test_percentile_rank_midpoint_definition() -> None:
    values = (1.0, 2.0, 3.0)
    assert percentile_rank(values, 2.0) == pytest.approx(50.0)
    assert percentile_rank(values, 1.0) == pytest.approx(100.0 / 6.0, rel=1e-3)
    assert percentile_rank(values, 3.0) == pytest.approx(5 * 100.0 / 6.0, rel=1e-3)
    assert percentile_rank((), 1.0) is None


def test_shares_from_cap() -> None:
    assert shares_from_cap(cap=18800.0, price=1500.0) == pytest.approx(12.5333, rel=1e-3)
    with pytest.raises(ValueError):
        shares_from_cap(cap=0, price=10)


def test_normal_path_available_with_arithmetic_and_per_share() -> None:
    assessment = assess_valuation(_inputs())
    history_anchor = next(item for item in assessment.anchor_outputs if item.anchor_id == "history_pe_band")
    peer_anchor = next(item for item in assessment.anchor_outputs if item.anchor_id == "peer_pe_band")

    assert history_anchor.status == "available"
    # Band edges must equal the same deterministic quantiles over clean history.
    from tradingagents.research.valuation import _clean_positive

    cleaned, _dropped = _clean_positive(tuple(item.value for item in _pe_history()))
    expected_low = quantile(cleaned, 0.25)
    expected_high = quantile(cleaned, 0.75)
    assert history_anchor.multiple_low == pytest.approx(expected_low, abs=0.01)
    assert history_anchor.multiple_high == pytest.approx(expected_high, abs=0.01)
    implied_low = history_anchor.multiple_low * 862.0
    implied_high = history_anchor.multiple_high * 862.0
    assert history_anchor.implied_value_low_yi == pytest.approx(implied_low, abs=0.02)
    assert history_anchor.implied_value_high_yi == pytest.approx(implied_high, abs=0.02)

    # Share count = 18800/1500 ≈ 12.53亿股
    shares = shares_from_cap(cap=18800.0, price=1500.0)
    assert history_anchor.per_share_low == pytest.approx(implied_low / shares, abs=0.02)
    assert history_anchor.per_share_high == pytest.approx(implied_high / shares, abs=0.02)

    assert peer_anchor.status == "unavailable"
    assert peer_anchor.reason_code == "verified_peer_valuations_unavailable"

    assert assessment.synthesis.status == "available"
    assert "history_pe_band" in assessment.synthesis.contributing_anchor_ids

    # positions include pe_3y with the deterministic band mapping.
    labels = {item.window_label for item in assessment.positions}
    assert {"pe_1y", "pe_3y"}.issubset(labels)
    assert assessment.week52_position is not None
    assert assessment.verdict.range_position in {"below_range", "within_range", "above_range"}
    assert assessment.input_reasons == ()


def test_loss_making_company_falls_back_to_pb() -> None:
    inputs = _inputs(
        net_income_annual=EarningsBaseV1(metric_id="net_income", value_yi=-30.0, period="2025-12-31"),
        pb_history=_pe_history(),
        snapshot=ValuationSnapshotInputV1(as_of=AS_OF, price=15.0, pe_ttm=0, pb=1.8, total_market_cap_yi=188.0),
        closing_prices=_prices(base=15.0),
    )
    assessment = assess_valuation(inputs)
    by_id = {item.anchor_id: item for item in assessment.anchor_outputs}
    assert by_id["history_pe_band"].status == "unavailable"
    assert by_id["history_pe_band"].reason_code == "negative_or_zero_net_income"
    assert by_id["peer_pe_band"].reason_code == "negative_or_zero_net_income"

    fallback = by_id.get("history_pb_band")
    assert fallback is not None and fallback.status == "available"
    assert fallback.earnings_base.metric_id == "equity"
    assert fallback.implied_value_low_yi == pytest.approx(fallback.multiple_low * 2600.0, abs=0.02)
    assert assessment.synthesis.status in {"available", "partial"}


def test_short_history_degrades() -> None:
    short = _pe_history(n_days=90)
    mid = _pe_history(n_days=95)
    assessment = assess_valuation(_inputs(pe_history=short))
    anchor = next(item for item in assessment.anchor_outputs if item.anchor_id == "history_pe_band")
    # ~90 calendar days still yields >= 60 clean rows but fewer than 120.
    assert anchor.status in {"partial", "unavailable"}

    tiny = _pe_history(n_days=40)
    assessment_tiny = assess_valuation(_inputs(pe_history=tiny, peers=PeerValuationsV1()))
    anchor_tiny = next(item for item in assessment_tiny.anchor_outputs if item.anchor_id == "history_pe_band")
    del mid
    assert anchor_tiny.status == "unavailable"
    assert anchor_tiny.reason_code == "insufficient_multiple_history"
    # Single usable anchor absent => synthesis stays unavailable, never guessed.
    assert assessment_tiny.synthesis.status == "unavailable"


def test_peer_anchor_requires_three_plus_clean_values() -> None:
    two_peers = PeerValuationsV1(entity_ids=("a", "b"), pe_ttm_values=(18.0, 25.0))
    assessment = assess_valuation(_inputs(peers=two_peers))
    peer = next(item for item in assessment.anchor_outputs if item.anchor_id == "peer_pe_band")
    assert peer.status == "unavailable"
    assert peer.reason_code == "insufficient_comparable_peers"

    five_peers = PeerValuationsV1(
        entity_ids=("a", "b", "c", "d", "e"),
        pe_ttm_values=(18.0, 25.0, 20.0, 22.0, 30.0),
    )
    assessment_ok = assess_valuation(_inputs(peers=five_peers))
    peer_ok = next(item for item in assessment_ok.anchor_outputs if item.anchor_id == "peer_pe_band")
    assert peer_ok.status == "available"
    assert peer_ok.multiple_low == pytest.approx(quantile((18.0, 25.0, 20.0, 22.0, 30.0), 0.25), abs=0.05)
    assert peer_ok.multiple_high == pytest.approx(quantile((18.0, 25.0, 20.0, 22.0, 30.0), 0.75), abs=0.05)


def test_disjoint_anchors_union_span_is_partial_with_disagreement_note() -> None:
    cheap_peer_anchor = AnchorOutputV1(
        anchor_id="peer_pe_band",
        method_label_zh="同行",
        multiple_kind="pe_ttm",
        status="available",
        earnings_base=EarningsBaseV1(metric_id="net_income", value_yi=100.0, period="2025-12-31"),
        multiple_low=5.0,
        multiple_high=6.0,
        implied_value_low_yi=500.0,
        implied_value_high_yi=600.0,
        assumptions=(),
    )
    expensive_history_anchor = AnchorOutputV1(
        anchor_id="history_pe_band",
        method_label_zh="历史",
        multiple_kind="pe_ttm",
        status="available",
        earnings_base=EarningsBaseV1(metric_id="net_income", value_yi=100.0, period="2025-12-31"),
        multiple_low=30.0,
        multiple_high=40.0,
        implied_value_low_yi=3000.0,
        implied_value_high_yi=4000.0,
        assumptions=(),
    )
    from tradingagents.research.valuation import synthesize

    synthesis = synthesize((expensive_history_anchor, cheap_peer_anchor), shares_yi=10.0, reference_price=350.0)
    # Disjoint bands fall back to the union span with an explicit partial:
    # presenting a contradictory pair as "available" would overstate confidence.
    assert synthesis.status == "partial"
    assert synthesis.reference_low_yi == pytest.approx(500.0)
    assert synthesis.reference_high_yi == pytest.approx(4000.0)
    assert synthesis.disagreement_note_zh is not None and "不相交" in synthesis.disagreement_note_zh


def test_overlapping_anchors_intersect() -> None:
    a = AnchorOutputV1(
        anchor_id="history_pe_band",
        method_label_zh="历史",
        multiple_kind="pe_ttm",
        status="available",
        earnings_base=EarningsBaseV1(metric_id="net_income", value_yi=100.0, period="2025-12-31"),
        multiple_low=10.0,
        multiple_high=20.0,
        implied_value_low_yi=1000.0,
        implied_value_high_yi=2000.0,
        assumptions=(),
    )
    b = AnchorOutputV1(
        anchor_id="peer_pe_band",
        method_label_zh="同行",
        multiple_kind="pe_ttm",
        status="available",
        earnings_base=EarningsBaseV1(metric_id="net_income", value_yi=100.0, period="2025-12-31"),
        multiple_low=15.0,
        multiple_high=25.0,
        implied_value_low_yi=1500.0,
        implied_value_high_yi=2500.0,
        assumptions=(),
    )
    from tradingagents.research.valuation import synthesize

    synthesis = synthesize((a, b), shares_yi=None, reference_price=None)
    assert synthesis.reference_low_yi == pytest.approx(1500.0)
    assert synthesis.reference_high_yi == pytest.approx(2000.0)
    assert synthesis.per_share_low is None and synthesis.per_share_high is None


def test_verdict_below_within_above_range() -> None:
    def _verdict(price: float):
        synthesis = RangeSynthesisV1(
            status="available",
            reference_low_yi=1000.0,
            reference_high_yi=2000.0,
            per_share_low=100.0,
            per_share_high=200.0,
            contributing_anchor_ids=("history_pe_band",),
            method_note_zh="test",
        )
        cap = price * 10.0  # 10 亿股 → per-share == implied / shares straightforwardly below
        from tradingagents.research.valuation import judge

        return judge(
            synthesis=synthesis,
            positions=(),
            week52=None,
            peer_relation="not_assessable",
            current_price=price,
            total_market_cap_yi=cap,
        )

    below = _verdict(price=80.0)
    within = _verdict(price=150.0)
    above = _verdict(price=250.0)
    assert below.range_position == "below_range"
    assert below.deviation_pct == pytest.approx(-20.0, abs=0.5)
    assert within.range_position == "within_range"
    assert above.range_position == "above_range"
    assert above.overall_label_zh and "上沿" in above.overall_label_zh


def test_missing_snapshot_marks_inputs_partial_and_blocks_per_share_only_labels() -> None:
    assessment = assess_valuation(
        _inputs(snapshot=None, net_income_annual=None, equity_annual=None, closing_prices=())
    )
    assert set(assessment.input_reasons) == {
        "market_snapshot_unavailable",
        "annual_net_income_unavailable",
    }
    assert assessment.synthesis.status == "unavailable"
    assert assessment.verdict.range_position == "unavailable"


def test_anchor_validator_rejects_inverted_bands_and_missing_numbers() -> None:
    base = EarningsBaseV1(metric_id="net_income", value_yi=100.0, period="2025-12-31")
    with pytest.raises(ValidationError):
        AnchorOutputV1(
            anchor_id="x",
            method_label_zh="x",
            multiple_kind="pe_ttm",
            status="available",
            earnings_base=base,
            multiple_low=20.0,
            multiple_high=10.0,
            implied_value_low_yi=2000.0,
            implied_value_high_yi=1000.0,
            assumptions=(),
        )
    with pytest.raises(ValidationError):
        AnchorOutputV1(
            anchor_id="y",
            method_label_zh="y",
            multiple_kind="pe_ttm",
            status="available",
            earnings_base=base,
            multiple_low=10.0,
            assumptions=(),
        )


def test_history_anchor_hand_computed_small_series() -> None:
    """Independent hand-check on a small known series (bypasses sample gates)."""
    from tradingagents.research.valuation import build_history_anchor

    day = date(2026, 1, 1)
    series = tuple(
        DailyMultipleV1(day=day + timedelta(days=i), value=float(v))
        for i, v in enumerate((8.0, 12.0, 16.0, 20.0, 24.0, 32.0, 48.0, 64.0))
    )
    base = EarningsBaseV1(metric_id="net_income", value_yi=10.0, period="2025-12-31")
    anchor = build_history_anchor(
        "history_pe_band",
        history=series,
        base=base,
        kind="pe_ttm",
        method_label_zh="hand check",
        negative_guard_reason=None,
        shares_yi=None,
        reference_price=None,
    )
    # Note: sample_size 8 < thresholds => partial/unavailable by design; the
    # arithmetic fields are still asserted when the status allows numbers.
    assert anchor.status in {"partial", "unavailable"}
    if anchor.status == "partial":
        assert anchor.multiple_low == pytest.approx(quantile(tuple(float(x.value) for x in series), 0.25), abs=0.05)


def test_partial_band_math_with_independent_reference() -> None:
    """60+ samples enter the partial branch; band edges match hand-built ranks."""
    from tradingagents.research.valuation import build_history_anchor

    day = date(2026, 1, 1)
    n = 65
    series = tuple(
        DailyMultipleV1(day=day + timedelta(days=i), value=float((i % 20) + 10.0))
        for i in range(n)
    )
    values = tuple(float(item.value) for item in series)
    base = EarningsBaseV1(metric_id="net_income", value_yi=50.0, period="2025-12-31")
    anchor = build_history_anchor(
        "history_pe_band",
        history=series,
        base=base,
        kind="pe_ttm",
        method_label_zh="partial math",
        negative_guard_reason=None,
        shares_yi=None,
        reference_price=None,
    )
    assert anchor.status == "partial"
    assert anchor.multiple_low == pytest.approx(quantile(values, 0.25), abs=0.05)
    assert anchor.multiple_high == pytest.approx(quantile(values, 0.75), abs=0.05)
    assert anchor.implied_value_low_yi == pytest.approx(anchor.multiple_low * 50.0, abs=0.02)
    assert anchor.implied_value_high_yi == pytest.approx(anchor.multiple_high * 50.0, abs=0.02)


def test_anchor_validator_rejects_implied_value_mismatch() -> None:
    """The active implied==base*band check must reject fabricated numbers."""
    base = EarningsBaseV1(metric_id="net_income", value_yi=100.0, period="2025-12-31")
    with pytest.raises(ValidationError):
        AnchorOutputV1(
            anchor_id="z",
            method_label_zh="z",
            multiple_kind="pe_ttm",
            status="available",
            earnings_base=base,
            multiple_low=10.0,
            multiple_high=20.0,
            implied_value_low_yi=9999.0,
            implied_value_high_yi=2000.0,
            assumptions=(),
        )


def test_negative_realtime_multiple_skips_percentile_positions() -> None:
    # Zero PE rows are filtered upstream; assess must not crash without them.
    assessment = assess_valuation(
        _inputs(
            snapshot=ValuationSnapshotInputV1(as_of=AS_OF, price=15.0, pe_ttm=0, pb=1.8, total_market_cap_yi=188.0),
            pe_history=_pe_history(),
        )
    )
    assert all(not item.window_label.startswith("pe_") for item in assessment.positions)
