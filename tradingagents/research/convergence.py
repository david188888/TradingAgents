"""Deterministic Lollapalooza-style convergence detection over research lenses.

Munger's Lollapalooza effect (Poor Charlie's Almanack): when several
independent forces push in the same direction, the outcome is a critical-mass
event rather than a linear sum.  Two opposite readings must never be merged:

* **Thesis confluence** (constructive use, cf. Captain Cook's sauerkraut):
  independent evidence channels agreeing strengthens a research thesis.
* **Crowd divergence warning** (the misjudgment reading): participant-side
  biases converging — social proof plus momentum running ahead of
  fundamentals — is a caution flag, never confirmation.

Boundary rules distilled from the same source keep the detector honest: a
single clear driver, weak signals, or tied sides yield ``not_applicable`` /
``none`` instead of a fabricated verdict.  Sentiment is treated as a derived
echo of price and news flow (a coupling social media only amplifies), so it
counts as an independent voice solely alongside market or news agreement.
Likewise, a ``strong`` confluence verdict requires fundamentals inside the
agreeing set: tape and narrative alone never reach critical mass.

Pure domain layer: no LLM calls and no state access.  Inputs are the already-
validated :class:`StrategySignal` values emitted with the Research Manager's
plan; thresholds are nominal magnitudes in the spirit of the evidence gate's
directional codes — decision boundaries, not measured precision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .strategy import StrategySignal

ConfluenceLevel = Literal["not_applicable", "none", "partial", "strong"]
WarningSeverity = Literal["not_applicable", "none", "watch", "elevated"]
CrowdPattern = Literal["euphoria", "panic"]

# Nominal decision thresholds (see module docstring on precision).
STRONG_MEAN_CONVICTION = 0.5  # critical-mass strength gate for "strong"
CROWD_MOVE_CONVICTION = 0.5  # market/sentiment commitment needed for a warning
FUNDAMENTAL_CONFIRMATION = 0.2  # below this, fundamentals is not confirming
ELEVATED_MEAN_CONVICTION = 0.75  # escalation trigger inside an active warning
MIN_PARTICIPATING_LENSES = 2  # fewer voices: nothing to assess
CRITICAL_INDEPENDENT_VOICES = 3  # Munger: "two, three or four forces"

# Independence model: sentiment is an echo of price and event flow, so it only
# adds an independent voice next to market or news agreement.  Fundamentals is
# the substance anchor: "strong" confluence must include it.
_ECHO_CHANNEL = "sentiment"
_INDEPENDENCE_BACKBONE = frozenset({"market", "news"})
_SUBSTANCE_ANCHOR = "fundamentals"


@dataclass(frozen=True)
class ThesisConfluence:
    """Constructive reading: independent channels reinforcing one thesis."""

    level: ConfluenceLevel
    direction: Literal["bullish", "bearish"] | None
    channel_ids: tuple[str, ...]
    effective_independent_count: int
    mean_conviction: float | None


@dataclass(frozen=True)
class CrowdDivergenceWarning:
    """Misjudgment reading: participant biases converging off-substance."""

    severity: WarningSeverity
    pattern: CrowdPattern | None
    channel_ids: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class ConvergenceAssessment:
    """Replayable result of the two separate Lollapalooza readings."""

    thesis_confluence: ThesisConfluence
    crowd_warning: CrowdDivergenceWarning


_NOT_APPLICABLE_CONFLUENCE = ThesisConfluence(
    level="not_applicable",
    direction=None,
    channel_ids=(),
    effective_independent_count=0,
    mean_conviction=None,
)
_NO_WARNING = CrowdDivergenceWarning(
    severity="none", pattern=None, channel_ids=(), note=""
)


def assess_convergence(
    signals: Sequence[StrategySignal],
) -> ConvergenceAssessment:
    """Assess both Lollapalooza readings without ever blending them."""
    seen: set[str] = set()
    for signal in signals:
        if signal.strategy_id in seen:
            raise ValueError(f"duplicate strategy_id: {signal.strategy_id}")
        seen.add(signal.strategy_id)

    participants = [signal for signal in signals if signal.conviction is not None]
    if len(participants) < MIN_PARTICIPATING_LENSES:
        return ConvergenceAssessment(
            thesis_confluence=_NOT_APPLICABLE_CONFLUENCE,
            crowd_warning=_NO_WARNING,
        )

    confluence = _assess_thesis_confluence(participants)
    warning = _assess_crowd_divergence(participants)
    return ConvergenceAssessment(
        thesis_confluence=confluence,
        crowd_warning=warning,
    )


def _assess_thesis_confluence(
    participants: list[StrategySignal],
) -> ThesisConfluence:
    bullish = [signal for signal in participants if signal.conviction > 0]
    bearish = [signal for signal in participants if signal.conviction < 0]

    # A genuine majority side is required; a tie means the lenses disagree,
    # which is the consensus engine's job to describe, not convergence.
    if len(bullish) == len(bearish):
        return ThesisConfluence(
            level="none",
            direction=None,
            channel_ids=tuple(sorted(signal.strategy_id for signal in participants)),
            effective_independent_count=0,
            mean_conviction=None,
        )
    side = bullish if len(bullish) > len(bearish) else bearish
    if len(side) < MIN_PARTICIPATING_LENSES:
        return ThesisConfluence(
            level="none",
            direction=None,
            channel_ids=(),
            effective_independent_count=0,
            mean_conviction=None,
        )

    channel_ids = tuple(sorted(signal.strategy_id for signal in side))
    channels = set(channel_ids)
    effective = len(channels)
    if (
        _ECHO_CHANNEL in channels
        and not channels & _INDEPENDENCE_BACKBONE
    ):
        # Sentiment alone next to a non-backbone partner is an echo, not a
        # second independent voice (social-media amplification makes this
        # discount heavier, not lighter).
        effective -= 1
    mean_conviction = sum(signal.conviction or 0.0 for signal in side) / len(side)

    if effective < MIN_PARTICIPATING_LENSES:
        return ThesisConfluence(
            level="none",
            direction=_direction_of(mean_conviction),
            channel_ids=channel_ids,
            effective_independent_count=max(effective, 0),
            mean_conviction=round(mean_conviction, 4),
        )

    reaches_critical_mass = (
        effective >= CRITICAL_INDEPENDENT_VOICES
        and abs(mean_conviction) >= STRONG_MEAN_CONVICTION
        and _SUBSTANCE_ANCHOR in channels
    )
    level: ConfluenceLevel = "partial"
    if reaches_critical_mass:
        level = "strong"
    return ThesisConfluence(
        level=level,
        direction=_direction_of(mean_conviction),
        channel_ids=channel_ids,
        effective_independent_count=effective,
        mean_conviction=round(mean_conviction, 4),
    )


def _assess_crowd_divergence(
    participants: list[StrategySignal],
) -> CrowdDivergenceWarning:
    by_id = {signal.strategy_id: signal for signal in participants}
    market = by_id.get("market")
    sentiment = by_id.get("sentiment")
    fundamentals = by_id.get("fundamentals")
    news = by_id.get("news")
    if market is None or sentiment is None:
        return _NO_WARNING

    market_conviction = market.conviction or 0.0
    sentiment_conviction = sentiment.conviction or 0.0
    if abs(market_conviction) < CROWD_MOVE_CONVICTION:
        return _NO_WARNING
    if abs(sentiment_conviction) < CROWD_MOVE_CONVICTION:
        return _NO_WARNING
    if (market_conviction > 0) != (sentiment_conviction > 0):
        return _NO_WARNING

    # Substance must fail to confirm before participant convergence becomes a
    # warning.  When fundamentals genuinely agrees, the alignment belongs to
    # the thesis-confluence reading instead.
    fundamental_conviction = fundamentals.conviction if fundamentals else None
    if fundamental_conviction is not None:
        confirmed = (fundamental_conviction > 0) == (market_conviction > 0) and (
            abs(fundamental_conviction) >= FUNDAMENTAL_CONFIRMATION
        )
        if confirmed:
            return _NO_WARNING

    pattern: CrowdPattern = "euphoria" if market_conviction > 0 else "panic"
    crowd_channels = ["market", "sentiment"]
    if news is not None and news.conviction is not None:
        news_joins = (news.conviction > 0) == (market_conviction > 0)
        if news_joins and abs(news.conviction) >= CROWD_MOVE_CONVICTION:
            crowd_channels.append("news")

    magnitudes = [
        abs(by_id[channel].conviction or 0.0) for channel in crowd_channels
    ]
    peak = max(magnitudes)
    news_joined = len(crowd_channels) >= 3
    if news_joined or peak >= ELEVATED_MEAN_CONVICTION:
        severity: WarningSeverity = "elevated"
    else:
        severity = "watch"

    if pattern == "euphoria":
        note = (
            "social proof and momentum converging ahead of fundamentals; "
            "treat unanimity as a caution flag, not confirmation"
        )
    else:
        note = (
            "deprival super-reaction and capitulation converging ahead of "
            "fundamentals; treat uniform pessimism as a caution flag"
        )
    return CrowdDivergenceWarning(
        severity=severity,
        pattern=pattern,
        channel_ids=tuple(crowd_channels),
        note=note,
    )


def _direction_of(mean_conviction: float) -> Literal["bullish", "bearish"]:
    return "bullish" if mean_conviction > 0 else "bearish"


def render_convergence_assessment(assessment: ConvergenceAssessment) -> str:
    """Render the assessment as markdown appended to the research plan."""
    parts: list[str] = []

    confluence = assessment.thesis_confluence
    if confluence.level == "not_applicable":
        parts.append(
            "- Thesis confluence: not applicable "
            "(fewer than two directional lenses)"
        )
    elif confluence.level == "none":
        if confluence.direction is None:
            parts.append(
                "- Thesis confluence: none (lenses disagree or lack independence)"
            )
        else:
            parts.append(
                f"- Thesis confluence: none ({confluence.direction} voices present "
                "but below critical mass)"
            )
    else:
        conviction = (
            "abstain"
            if confluence.mean_conviction is None
            else f"{confluence.mean_conviction:+.2f}"
        )
        state = "critical mass reached" if confluence.level == "strong" else "still accumulating"
        parts.append(
            f"- Thesis confluence: {confluence.level} ({state}) — "
            f"{confluence.effective_independent_count} independent channel(s) "
            f"{list(confluence.channel_ids)} leaning {confluence.direction}, "
            f"mean conviction {conviction}"
        )

    warning = assessment.crowd_warning
    if warning.severity == "watch":
        parts.append(
            f"- Crowd divergence warning: watch ({warning.pattern}) — "
            f"{list(warning.channel_ids)}; {warning.note}"
        )
    elif warning.severity == "elevated":
        parts.append(
            f"- Crowd divergence warning: elevated ({warning.pattern}) — "
            f"{list(warning.channel_ids)}; {warning.note}"
        )

    return "\n".join(parts)
