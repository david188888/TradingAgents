"""The Evidence Steward split and hidden-call accounting (plan T23).

Two things are being defended here, and the tests are shaped to fail loudly if
either is lost.

**Separability.** A caller that wants a verdict must not be able to start a
model call, and a caller that wants enrichment must be able to see what it
cost. The old steward was one function that did both, so "it is gated" and
"it is budgeted" were the same claim and neither was checkable.

**Accountability for hidden calls.** The audit
(``docs/superpowers/plans/hidden-llm-audit.md``) found four model call points
inside the steward that no budget could see, one of which could append an
unbounded round of vendor HTTP. A stage that is not charged before it runs is
exactly the finding, reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tradingagents.agents.evidence_steward_gating import (
    DEFAULT_STAGE_ALLOWANCE,
    STAGE_COSTS,
    EnrichmentOutcome,
    EnrichmentRefused,
    EnrichmentStage,
    EvidenceGateDecision,
    audited_stages,
    enrich_evidence,
)
from tradingagents.execution.budget import BudgetBucket, BudgetLedger

RUN_ID = "run_steward"


@dataclass
class _Advisor:
    """Stands in for the coverage advisor's structured result."""

    should_enrich: bool = False
    queries: tuple[str, ...] = ()
    layer1_sentiment: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Separability
# ---------------------------------------------------------------------------


def test_a_gate_with_no_pure_evaluator_refuses_rather_than_enriching() -> None:
    """The reusable half must not fall back to the side-effecting one.

    Defaulting to ``evaluate_and_enrich_evidence`` here would reintroduce the
    exact coupling the split removes: a verdict would cost a model call.
    """
    with pytest.raises(EnrichmentRefused):
        EvidenceGateDecision().evaluate({"company_of_interest": "600519"})


def test_a_pure_evaluator_is_used_verbatim_and_enrichment_is_not_reached() -> None:
    seen: list[dict] = []

    def pure(state):
        seen.append(state)
        return {"evidence_status": "PASS"}

    result = EvidenceGateDecision(evaluator=pure).evaluate({"company_of_interest": "600519"})
    assert result == {"evidence_status": "PASS"}
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# Audit coverage
# ---------------------------------------------------------------------------


def test_every_audited_hidden_call_site_has_a_charged_stage() -> None:
    """The audit's H1-H4 list, item by item.

    If a call point is missing, it is unbudgeted again -- which is how it got
    here in the first place. Asserted as a set so adding a stage without
    adding a cost also fails.
    """
    assert set(audited_stages()) == {
        "consistency.clustering",          # H1
        "evidence.news_advisor",           # H2
        "evidence.news_layer1_sentiment",  # H3
        "evidence.news_layer2_review",     # H4
        "evidence.enrichment_retrieval",   # H2's amplification
    }
    for stage in EnrichmentStage:
        assert STAGE_COSTS[stage], f"{stage} has no budget cost"
        assert stage in DEFAULT_STAGE_ALLOWANCE


def test_the_advisors_amplifying_stage_is_charged_as_data_retrieval() -> None:
    """H2 is one model call that can cause N HTTP requests.

    Charging only MAIN_ANALYSIS would let a budgeted advisor trigger an
    unbudgeted fetch round, which is the amplification the audit warns about.
    """
    costs = STAGE_COSTS[EnrichmentStage.RETRIEVAL_ROUND]
    assert BudgetBucket.DATA_CAPABILITY_CALLS in costs
    assert BudgetBucket.DATA_HTTP_ATTEMPTS in costs


# ---------------------------------------------------------------------------
# Charging before the call
# ---------------------------------------------------------------------------


def test_a_stage_the_budget_cannot_afford_never_starts() -> None:
    ledger = BudgetLedger(RUN_ID, limits={BudgetBucket.MAIN_ANALYSIS: 0})
    started: list[str] = []
    outcome = enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: (started.append("advisor"), _Advisor())[1],
    )
    assert started == []
    assert EnrichmentStage.ADVISOR in [stage for stage, _ in outcome.skipped]
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0


def test_an_affordable_advisor_is_charged_exactly_once() -> None:
    ledger = BudgetLedger(RUN_ID)
    enrich_evidence({}, ledger=ledger, advisor=lambda: _Advisor())
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1


def test_enrichment_retrieval_is_charged_before_the_advisor_that_causes_it() -> None:
    """Order matters: charge the consequence, then the cause.

    Charging the advisor first and the retrieval after would let the advisor
    run and only then discover it cannot afford what it asked for.
    """
    ledger = BudgetLedger(RUN_ID, limits={BudgetBucket.DATA_HTTP_ATTEMPTS: 0})
    started: list[str] = []

    def advisor():
        started.append("advisor")
        return _Advisor(should_enrich=True, queries=("补证",))

    def retrieve(_result):
        started.append("retrieval")
        return ({"title": "x"},)

    outcome = enrich_evidence({}, ledger=ledger, advisor=advisor, retrieval=retrieve)
    # Neither the advisor nor the fetch it would have caused may start: the
    # consequence is checked first, so no provider call is made at all.
    assert started == []
    assert outcome.enriched_items == ()
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0


def test_an_advisor_that_asks_to_enrich_and_cannot_is_reported_not_dropped() -> None:
    """A refused enrichment is disclosed; silence would read as "nothing found"."""
    ledger = BudgetLedger(RUN_ID, limits={BudgetBucket.DATA_CAPABILITY_CALLS: 0})
    outcome = enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: _Advisor(should_enrich=True, queries=("补证",)),
        retrieval=lambda _a: ({"title": "x"},),
    )
    # The retrieval is refused first, so the advisor is never asked. This is
    # the stronger order: the model call that would have requested the fetch
    # is not spent on a request the budget has already refused to fund. The
    # disclosure is the point -- a reader must see that enrichment was wanted
    # and not obtained, never an outcome that looks like "there was nothing".
    stages = [stage for stage, _ in outcome.skipped]
    assert EnrichmentStage.RETRIEVAL_ROUND in stages
    reasons = dict(outcome.skipped)[EnrichmentStage.RETRIEVAL_ROUND]
    assert "budget" in reasons or "allowance" in reasons
    assert outcome.enriched_items == ()
    assert outcome.ran == ()
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0


def test_the_allowance_caps_a_stage_that_the_budget_would_otherwise_allow() -> None:
    """Two advisor calls need a wider budget, and a run may refuse them anyway."""
    calls: list[int] = []
    outcome = enrich_evidence(
        {},
        ledger=BudgetLedger(RUN_ID),
        advisor=lambda: (calls.append(1), _Advisor())[1],
        stage_allowance={EnrichmentStage.ADVISOR: 1},
    )
    assert len(calls) == 1
    assert outcome.ran.count(EnrichmentStage.ADVISOR) == 1


def test_a_successful_enrichment_returns_items_and_records_the_stages() -> None:
    ledger = BudgetLedger(RUN_ID)
    outcome = enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: _Advisor(should_enrich=True, queries=("补证",), layer1_sentiment={"a": 0.5}),
        retrieval=lambda _a: ({"title": "补证结果"},),
    )
    assert isinstance(outcome, EnrichmentOutcome)
    assert outcome.performed_enrichment is True
    assert outcome.directions == {"a": 0.5}
    assert EnrichmentStage.ADVISOR in outcome.ran
    assert ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 1


def test_a_no_op_advisor_costs_one_model_call_and_no_retrieval() -> None:
    ledger = BudgetLedger(RUN_ID)
    outcome = enrich_evidence({}, ledger=ledger, advisor=lambda: _Advisor())
    assert outcome.enriched_items == ()
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1
    assert ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 0


def test_a_failing_advisor_is_a_type_name_not_an_exception_message() -> None:
    """A vendor URL or provider payload must not reach the artifact."""

    def broken():
        raise RuntimeError("POST https://vendor.internal/x failed: key sk-live-abc")

    outcome = enrich_evidence({}, ledger=BudgetLedger(RUN_ID), advisor=broken)
    reasons = dict(outcome.skipped)
    assert reasons[EnrichmentStage.ADVISOR] == "RuntimeError"
    assert "sk-live" not in str(outcome)
    assert "vendor.internal" not in str(outcome)


def test_no_advisor_means_no_stage_is_charged() -> None:
    """A caller that only wants a gate pays nothing."""
    ledger = BudgetLedger(RUN_ID)
    outcome = enrich_evidence({}, ledger=ledger, advisor=None)
    assert outcome.ran == ()
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0
    assert ledger.consumed(BudgetBucket.SEMANTIC_PREPROCESS) == 0


# ---------------------------------------------------------------------------
# H3/H4: the real advisor is not one model call
# ---------------------------------------------------------------------------
#
# ``dataflows.news_advisor.analyze_news_coverage`` -- the actual H2
# implementation -- internally runs ``_run_layer1_sentiment`` (H3, line 102)
# and ``_attach_layer2_conclusion`` (H4, line 115) before it returns, gated
# by ``news_layer1_enabled``/``news_layer2_enabled`` config that the audit
# found set to ``true`` in real runs. A caller whose ``advisor`` is bound to
# that function and who does not say so with ``layer1_enabled``/
# ``layer2_enabled`` would have those two calls happen for free: one charged
# unit, up to three real model calls.


def test_a_caller_that_declares_layer1_pays_for_it_before_the_advisor_runs() -> None:
    ledger = BudgetLedger(RUN_ID)
    outcome = enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: _Advisor(),
        layer1_enabled=True,
    )
    assert EnrichmentStage.LAYER1 in outcome.ran
    assert ledger.consumed(BudgetBucket.SEMANTIC_PREPROCESS) == 1
    # H2 is still its own separate charge -- layer 1 does not replace it.
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1


def test_a_caller_that_declares_layer2_pays_for_it_before_the_advisor_runs() -> None:
    ledger = BudgetLedger(RUN_ID)
    outcome = enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: _Advisor(),
        layer2_enabled=True,
    )
    assert EnrichmentStage.LAYER2 in outcome.ran
    assert ledger.consumed(BudgetBucket.SEMANTIC_PREPROCESS) == 1
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1


def test_declaring_both_layers_charges_all_three_stages_of_a_real_advisor_call() -> None:
    """The full H2+H3+H4 cost of one ``analyze_news_coverage`` call, pinned."""
    ledger = BudgetLedger(RUN_ID)
    enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: _Advisor(),
        layer1_enabled=True,
        layer2_enabled=True,
    )
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1  # H2
    assert ledger.consumed(BudgetBucket.SEMANTIC_PREPROCESS) == 2  # H3 + H4


def test_an_unaffordable_layer1_blocks_the_advisor_it_would_have_ridden_inside(
) -> None:
    """Charge the consequence before the cause, same as the retrieval round."""
    ledger = BudgetLedger(RUN_ID, limits={BudgetBucket.SEMANTIC_PREPROCESS: 0})
    started: list[str] = []
    outcome = enrich_evidence(
        {},
        ledger=ledger,
        advisor=lambda: (started.append("advisor"), _Advisor())[1],
        layer1_enabled=True,
    )
    assert started == []
    assert EnrichmentStage.LAYER1 in [stage for stage, _ in outcome.skipped]
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0


def test_an_advisor_with_neither_layer_declared_still_pays_only_for_itself() -> None:
    """The default keeps every existing caller's accounting unchanged: an
    advisor that cannot trigger layer 1/2 must not be charged for them.
    """
    ledger = BudgetLedger(RUN_ID)
    enrich_evidence({}, ledger=ledger, advisor=lambda: _Advisor())
    assert ledger.consumed(BudgetBucket.SEMANTIC_PREPROCESS) == 0
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 1


# ---------------------------------------------------------------------------
# The frozen-draft rule
# ---------------------------------------------------------------------------


def test_nothing_rebuilds_facts_from_a_natural_language_report() -> None:
    """Design SS5.3: after the freeze, a report is a rendering, not a source.

    The whole steward runs on structured records. A module that could turn a
    prose report into a fact would make every unsourced claim in a brief
    reachable by writing a sentence, so the check is structural: no
    ``report``/``summary`` field may be read by the enrichment path at all.
    """
    import inspect

    from tradingagents.agents import evidence_steward_gating as gating

    source = inspect.getsource(gating)
    for forbidden in ("news_report", "sentiment_report", "final_trade_decision"):
        assert forbidden not in source, (
            f"{forbidden} must not be an input to the frozen-profile steward"
        )


def test_the_classic_steward_still_works_unchanged(monkeypatch) -> None:
    """T25 adjacent: the split is additive.

    ``create_evidence_steward`` is what the classic graph calls; it must keep
    returning the same shape for the same state, because the split is offered
    to the new profile rather than imposed on the old one. The LLM advisor is
    neutralised so the test is offline and key-independent.
    """
    from tradingagents.agents.evidence_steward import create_evidence_steward
    from tradingagents.dataflows.news_advisor import NewsAdvisorResult

    monkeypatch.setattr(
        "tradingagents.dataflows.evidence.create_llm_from_config",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.evidence.analyze_news_coverage",
        lambda *a, **kw: NewsAdvisorResult(should_enrich=False, queries=[]),
    )

    result = create_evidence_steward()({})
    assert "evidence_status" in result
    assert "research_dossier" in result
