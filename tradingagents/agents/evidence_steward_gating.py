"""The Evidence Steward split: reusable gate, then accounted-for enrichment.

Design SS5.3 requires the Evidence Steward's two jobs to be separable. Today
they are one function, ``evaluate_and_enrich_evidence``, which decides whether
the evidence is good enough *and* -- in the same breath -- calls a model, may
call a second model, and may trigger a fresh round of vendor HTTP requests.
Nothing about that is visible to a caller that only wants the verdict, and
nothing about the model calls is visible to a budget.

This module separates them:

* :func:`evaluate_evidence_gate` is pure with respect to the network. It runs
  the existing assessment and returns a decision. It never constructs an LLM.
* :func:`enrich_evidence` is the side-effecting half. Every model call and every
  additional retrieval round it causes is charged to the run's budget *before*
  it happens, so a stage the budget cannot afford is not started at all.

The hidden-call audit (``docs/archive/reviews/2026-09-29-hidden-llm-audit.md``)
identified four model call points inside the old steward that sat outside the
budget entirely:

===== ========================================== ==========================
id    call site                                  budget bucket
===== ========================================== ==========================
H1    ``consistency.clustering``                 SEMANTIC_PREPROCESS
H2    ``evidence.news_advisor``                   MAIN_ANALYSIS
H3    ``evidence.news_layer1_sentiment``          SEMANTIC_PREPROCESS
H4    ``evidence.news_layer2_review``             SEMANTIC_PREPROCESS
===== ========================================== ==========================

H2 has an amplification the others do not: the advisor's ``should_enrich``
triggers another round of vendor retrieval, so one unbudgeted model call can
append N unbudgeted HTTP requests. Charging the model call is therefore not
enough -- the retrieval round it may cause is charged as well, before the
advisor is allowed to run.

The frozen-draft rule is separate and equally strict: for the ``catalyst_v1``
profile this module is not used to rebuild facts at all. Once a draft is frozen,
a natural-language report is a *rendering* of facts, and parsing a rendering
back into facts is how a summary becomes an unsourced claim. The gate reports
on the draft; it never contributes facts to it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from tradingagents.execution.budget import (
    BudgetBucket,
    BudgetLedger,
    BudgetLimitHit,
)

logger = logging.getLogger(__name__)


class EnrichmentStage(str, Enum):
    """Every stage the enrichment half can start, named for the audit.

    The values are the audit's invocation paths, so a reviewer can check
    coverage by comparing two lists rather than reading the code.
    """

    ADVISOR = "evidence.news_advisor"
    LAYER1 = "evidence.news_layer1_sentiment"
    LAYER2 = "evidence.news_layer2_review"
    CLUSTERING = "consistency.clustering"
    RETRIEVAL_ROUND = "evidence.enrichment_retrieval"


#: What each audited call point costs, and what it may additionally cause.
#: A stage with an ``also_charges`` entry cannot start unless the *whole* set
#: is affordable, because the extra work happens inside it.
STAGE_COSTS: dict[EnrichmentStage, tuple[BudgetBucket, ...]] = {
    EnrichmentStage.ADVISOR: (BudgetBucket.MAIN_ANALYSIS,),
    EnrichmentStage.LAYER1: (BudgetBucket.SEMANTIC_PREPROCESS,),
    EnrichmentStage.LAYER2: (BudgetBucket.SEMANTIC_PREPROCESS,),
    EnrichmentStage.CLUSTERING: (BudgetBucket.SEMANTIC_PREPROCESS,),
    # Not a model call: the HTTP attempts the advisor's should_enrich can
    # cause. Counted here so a budgeted advisor cannot buy free retrieval.
    EnrichmentStage.RETRIEVAL_ROUND: (
        BudgetBucket.DATA_CAPABILITY_CALLS,
        BudgetBucket.DATA_HTTP_ATTEMPTS,
    ),
}

#: The stages a run may never exceed, whatever the policy says. The audit's
#: finding is that an unbudgeted stage is worse than an absent one, so the
#: default is to refuse and let a caller opt in explicitly.
DEFAULT_STAGE_ALLOWANCE: dict[EnrichmentStage, int] = {
    EnrichmentStage.ADVISOR: 1,
    EnrichmentStage.LAYER1: 1,
    EnrichmentStage.LAYER2: 1,
    EnrichmentStage.CLUSTERING: 2,
    EnrichmentStage.RETRIEVAL_ROUND: 1,
}


class EnrichmentRefused(RuntimeError):
    """A stage the run could not afford, or was not allowed to run.

    Carries the stage and the reason so a caller can publish *which* step was
    skipped rather than degrading silently into a report that looks complete.
    """

    def __init__(self, stage: EnrichmentStage, reason: str):
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage.value} refused: {reason}")


@dataclass
class EnrichmentOutcome:
    """What the enrichment half did, and what it declined to do.

    ``skipped`` is a first-class field rather than a log line: a reader asking
    why the evidence is thin deserves an answer in the artifact.
    """

    enriched_items: tuple[Mapping[str, Any], ...] = ()
    ran: tuple[EnrichmentStage, ...] = ()
    skipped: tuple[tuple[EnrichmentStage, str], ...] = ()
    directions: Mapping[str, float] = field(default_factory=dict)

    @property
    def performed_enrichment(self) -> bool:
        return bool(self.enriched_items)


class EvidenceGateDecision:
    """The reusable, side-effect-free half of the steward.

    Wraps the existing gate so that a caller who only wants a verdict does not
    have to know that enrichment exists -- and, more importantly, so that a
    caller who wants a verdict *cannot* accidentally start a model call.
    """

    def __init__(self, *, evaluator: Callable[[dict[str, Any]], dict[str, Any]] | None = None):
        self._evaluator = evaluator

    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the gate without constructing an LLM or fetching anything.

        The legacy evaluator is used only when it is known not to enrich. It
        is, in the common case, not -- so a caller that has not explicitly
        supplied a pure evaluator gets a refusal rather than a silent model
        call. That is the point of the split: enrichment must be asked for.
        """
        if self._evaluator is None:
            raise EnrichmentRefused(
                EnrichmentStage.ADVISOR,
                "no pure gate evaluator was supplied; the legacy evaluator "
                "enriches as a side effect and must not be used as a gate",
            )
        return self._evaluator(state)


def _charge(
    ledger: BudgetLedger | None,
    stage: EnrichmentStage,
    *,
    allowed: int,
    used: int,
) -> None:
    """Reserve everything a stage will cost, or refuse it.

    Every bucket is reserved before the work starts, and nothing is given back
    on failure: an attempt that was made is an attempt that happened. This is
    the difference between a budget and a report written after the fact.
    """
    if used >= allowed:
        raise EnrichmentRefused(
            stage, f"stage allowance exhausted ({used}/{allowed})"
        )
    if ledger is None:
        return
    for bucket in STAGE_COSTS[stage]:
        granted = ledger.reserve(bucket, stage=stage.value)
        if isinstance(granted, BudgetLimitHit):
            raise EnrichmentRefused(stage, f"budget refused {bucket.value}")
        ledger.mark_dispatched(granted)
        ledger.settle(granted, ok=True, detail=stage.value)


def enrich_evidence(
    state: dict[str, Any],
    *,
    ledger: BudgetLedger | None = None,
    advisor: Callable[[], Any] | None = None,
    retrieval: Callable[[Any], tuple[Mapping[str, Any], ...]] | None = None,
    stage_allowance: Mapping[EnrichmentStage, int] | None = None,
    layer1_enabled: bool = False,
    layer2_enabled: bool = False,
) -> EnrichmentOutcome:
    """Run the audited enrichment stages, charging each before it happens.

    A stage that cannot be afforded is recorded in ``skipped`` and the run
    continues with whatever it already has. It is never silently substituted:
    the most expensive mistake this code can make is the one the audit found,
    where a model that decided to enrich set off an unbudgeted fetch round.

    ``layer1_enabled``/``layer2_enabled`` exist because H2's real
    implementation, ``dataflows.news_advisor.analyze_news_coverage``, is not
    one model call -- it is a function that, under
    ``news_layer1_enabled``/``news_layer2_enabled`` config (observed ``true``
    in real runs per the hidden-llm-audit), *internally* also runs H3
    (``_run_layer1_sentiment``) and H4 (``_attach_layer2_conclusion``) before
    returning. A caller that knows its ``advisor`` may do this must say so
    here, so those two calls are charged *before* the advisor runs rather
    than never charged at all -- silently trusting the callable to be H2 alone
    would exactly reproduce the undercount the audit found. Both default to
    ``False``: an advisor that cannot trigger layer 1/2 (every advisor in
    this module's own test suite, and any future advisor built specifically
    for the frozen-draft profile) must not pay for calls it cannot make.
    """
    allowance = dict(DEFAULT_STAGE_ALLOWANCE)
    allowance.update(stage_allowance or {})
    used: dict[EnrichmentStage, int] = {}
    ran: list[EnrichmentStage] = []
    skipped: list[tuple[EnrichmentStage, str]] = []

    def attempt(stage: EnrichmentStage) -> bool:
        try:
            _charge(
                ledger,
                stage,
                allowed=allowance.get(stage, 0),
                used=used.get(stage, 0),
            )
        except EnrichmentRefused as refusal:
            skipped.append((stage, refusal.reason))
            return False
        used[stage] = used.get(stage, 0) + 1
        ran.append(stage)
        return True

    if advisor is None:
        return EnrichmentOutcome(skipped=tuple(skipped))

    # The advisor may cause retrieval, but a caller that supplied no retrieval
    # callable cannot cause any, so nothing is charged for it. Charging an
    # unspent allowance is its own kind of wrong: a run that never fetched
    # would report a data-capability spend it did not make.
    retrieval_possible = retrieval is not None
    if retrieval_possible and not attempt(EnrichmentStage.RETRIEVAL_ROUND):
        return EnrichmentOutcome(skipped=tuple(skipped))
    # Layer 1/2 are charged before the advisor call they ride inside of, for
    # the same reason the retrieval round is charged before the advisor that
    # causes it: the consequence must be affordable before the cause is
    # allowed to run, or the advisor could start a call this run cannot pay
    # for and only discover that afterwards.
    if layer1_enabled and not attempt(EnrichmentStage.LAYER1):
        return EnrichmentOutcome(skipped=tuple(skipped))
    if layer2_enabled and not attempt(EnrichmentStage.LAYER2):
        return EnrichmentOutcome(skipped=tuple(skipped))
    if not attempt(EnrichmentStage.ADVISOR):
        return EnrichmentOutcome(skipped=tuple(skipped))

    try:
        result = advisor()
    except Exception as exc:
        # A vendor URL or a provider message must not reach the artifact; the
        # fault category is a type name and nothing more.
        logger.warning(
            "evidence advisor failed (fault category: %s)", type(exc).__name__
        )
        skipped.append((EnrichmentStage.ADVISOR, type(exc).__name__))
        return EnrichmentOutcome(ran=tuple(ran), skipped=tuple(skipped))

    directions = dict(getattr(result, "layer1_sentiment", {}) or {})
    should_enrich = bool(getattr(result, "should_enrich", False))
    queries = tuple(getattr(result, "queries", ()) or ())
    if not (should_enrich and queries and retrieval is not None):
        return EnrichmentOutcome(
            ran=tuple(ran), skipped=tuple(skipped), directions=directions
        )

    try:
        items = tuple(retrieval(result))
    except Exception as exc:
        logger.warning(
            "evidence enrichment retrieval failed (fault category: %s)",
            type(exc).__name__,
        )
        skipped.append((EnrichmentStage.RETRIEVAL_ROUND, type(exc).__name__))
        return EnrichmentOutcome(
            ran=tuple(ran), skipped=tuple(skipped), directions=directions
        )
    return EnrichmentOutcome(
        enriched_items=items,
        ran=tuple(ran),
        skipped=tuple(skipped),
        directions=directions,
    )


def audited_stages() -> tuple[str, ...]:
    """The audit's call points, as a list a reviewer can check by eye.

    A test asserts this set is covered by the budgeted stages, so a new hidden
    call site cannot be added without appearing here first.
    """
    return tuple(sorted(stage.value for stage in EnrichmentStage))
