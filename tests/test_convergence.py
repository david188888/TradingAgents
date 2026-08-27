import pytest

from tradingagents.research import (
    StrategySignal,
    assess_convergence,
    render_convergence_assessment,
)


def test_single_directional_lens_is_not_applicable():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.8, 0.9),
            StrategySignal("fundamentals", None, 1.0, "no filings coverage"),
        ]
    )

    assert assessment.thesis_confluence.level == "not_applicable"
    assert assessment.crowd_warning.severity == "none"


def test_three_independent_channels_with_substance_reach_critical_mass():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.8, 0.9),
            StrategySignal("fundamentals", 0.6, 0.8),
            StrategySignal("news", 0.7, 0.9),
            StrategySignal("sentiment", None, 0.4),
        ]
    )

    confluence = assessment.thesis_confluence
    assert confluence.level == "strong"
    assert confluence.direction == "bullish"
    assert confluence.effective_independent_count == 3
    assert assessment.crowd_warning.severity == "none"


def test_sentiment_without_backbone_partner_is_an_echo_not_a_voice():
    # fundamentals + sentiment agreeing is the classic echo trap: social
    # sentiment rarely originates from filings, so independence discounts to
    # a single voice and no confluence verdict survives.
    assessment = assess_convergence(
        [
            StrategySignal("fundamentals", 0.8, 0.9),
            StrategySignal("sentiment", 0.7, 0.8),
        ]
    )

    confluence = assessment.thesis_confluence
    assert confluence.level == "none"
    assert confluence.effective_independent_count == 1


def test_tape_and_narrative_never_reach_strong_without_substance_anchor():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.8, 0.9),
            StrategySignal("news", 0.7, 0.9),
            StrategySignal("sentiment", 0.8, 0.8),
            StrategySignal("fundamentals", None, 1.0, "awaiting filings"),
        ]
    )

    confluence = assessment.thesis_confluence
    assert confluence.level == "partial"
    assert confluence.effective_independent_count == 3


def test_market_and_sentiment_running_ahead_of_silent_fundamentals_warns():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.8, 0.9),
            StrategySignal("sentiment", 0.8, 0.8),
            StrategySignal("fundamentals", None, 1.0, "awaiting filings"),
        ]
    )

    warning = assessment.crowd_warning
    assert warning.severity == "elevated"
    assert warning.pattern == "euphoria"
    assert warning.note


def test_news_joining_the_crowd_escalates_to_elevated():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.7, 0.9),
            StrategySignal("sentiment", 0.8, 0.8),
            StrategySignal("news", 0.6, 0.7),
            StrategySignal("fundamentals", None, 1.0, "awaiting filings"),
        ]
    )

    warning = assessment.crowd_warning
    assert warning.severity == "elevated"
    assert set(warning.channel_ids) == {"market", "sentiment", "news"}


def test_panic_mirror_triggers_on_bearish_crowd_move():
    assessment = assess_convergence(
        [
            StrategySignal("market", -0.8, 0.9),
            StrategySignal("sentiment", -0.9, 0.8),
            StrategySignal("fundamentals", 0.1, 0.5),
        ]
    )

    warning = assessment.crowd_warning
    assert warning.pattern == "panic"
    assert warning.severity == "elevated"


def test_fundamentals_confirming_absorbs_alignment_into_thesis_reading():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.8, 0.9),
            StrategySignal("sentiment", 0.8, 0.8),
            StrategySignal("fundamentals", 0.7, 0.9),
        ]
    )

    assert assessment.thesis_confluence.level == "strong"
    assert assessment.crowd_warning.severity == "none"


def test_tied_sides_yield_no_confluence_verdict():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.9, 1.0),
            StrategySignal("news", 0.2, 0.5),
            StrategySignal("fundamentals", -0.8, 1.0),
            StrategySignal("sentiment", -0.7, 0.8),
        ]
    )

    # 2 bullish vs 2 bearish: no majority side exists to assess.
    assert assessment.thesis_confluence.level == "none"
    assert assessment.thesis_confluence.direction is None
    assert assessment.crowd_warning.severity == "none"


def test_majority_side_with_a_weak_vote_stays_partial():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.9, 1.0),
            StrategySignal("news", 0.2, 0.5),
        ]
    )

    confluence = assessment.thesis_confluence
    assert confluence.level == "partial"
    assert confluence.direction == "bullish"


def test_zero_conviction_votes_do_not_form_a_side():
    assessment = assess_convergence(
        [
            StrategySignal("market", 0.0, 0.9),
            StrategySignal("sentiment", 0.0, 0.9),
        ]
    )

    assert assessment.thesis_confluence.level == "none"
    assert assessment.crowd_warning.severity == "none"


def test_duplicate_strategy_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        assess_convergence(
            [StrategySignal("market", 0.5, 0.5), StrategySignal("market", 0.4, 0.4)]
        )


def test_render_covers_all_sections():
    rendered = render_convergence_assessment(
        assess_convergence(
            [
                StrategySignal("market", 0.8, 0.9),
                StrategySignal("fundamentals", None, 1.0),
                StrategySignal("news", 0.6, 0.7),
                StrategySignal("sentiment", 0.8, 0.8),
            ]
        )
    )

    assert "- Thesis confluence:" in rendered
    assert "- Crowd divergence warning:" in rendered
