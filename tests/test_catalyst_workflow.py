"""Bounded research workflow behaviour (plan T19-T22, T24).

The load-bearing claims in this file are the ones a reader would otherwise have
to take on trust:

* Serial and parallel execution produce the *same public bytes*, not merely
  equivalent-looking results.  This is checked by comparing serialized cases
  from runs whose roles completed in deliberately opposite orders.
* A specialist cannot see another specialist's material, and the refuter is
  shown findings rather than a conclusion.
* A failed role, an exhausted budget, a cancelled run, and an unresolved key
  challenge each produce a *bounded* result rather than a confident one.
"""

from __future__ import annotations

import inspect
import itertools
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tradingagents.agents.schemas._catalyst_research import (
    Challenge,
    ChallengeDisposition,
    SpecialistFinding,
)
from tradingagents.execution.budget import BudgetBucket, BudgetLedger
from tradingagents.graph.catalyst_workflow import (
    MAX_CHALLENGES,
    MAX_FINDINGS_PER_ROLE,
    CaseCommitter,
    CatalystRunRequest,
    CommitRefused,
    ProcessState,
    RefutationResult,
    RoleStatus,
    SpecialistResult,
    SpecialistSlots,
    SynthesisDraft,
    build_brief,
    build_process_state,
    decide_priority,
    execute_specialists,
    key_unresolved_challenges,
    normalize_findings,
    render_refutation_prompt,
    run_catalyst_research,
    run_refutation,
    run_specialist,
    run_synthesis,
    validate_dispositions,
)
from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
from tradingagents.research.evidence_freeze import (
    CAP_FUNDAMENTALS,
    CAP_PRICE,
    CAP_SENTIMENT,
    REQUIRED_CAPABILITIES,
    ROLE_ORDER,
    CapabilityStatus,
    EvidenceFreezer,
    FreezeInputs,
    build_specialist_view,
)

RUN_ID = "run_wf"
TICKER = "600519"
CUTOFF = "2026-09-29"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _qualified(name: str):
    from tradingagents.research.evidence_freeze import FrozenCapability

    return FrozenCapability(
        capability=name,
        status=CapabilityStatus.QUALIFIED,
        required=name in REQUIRED_CAPABILITIES,
        reason="capability produced a verified result",
    )


def _evidence_record(capability: str) -> dict:
    """A frozen evidence row in the shape the case schema publishes.

    A specialist must cite an id the reader can resolve, so the fixture builds
    real records rather than placeholder strings.
    """
    from datetime import datetime, timezone

    from tradingagents.research.evidence_freeze import source_family_id

    fingerprint = f"fingerprint.{capability}"
    captured = datetime(2026, 9, 29, 6, 0, tzinfo=timezone.utc)
    return {
        "evidence_id": f"evcap.{capability}",
        "run_id": RUN_ID,
        "ticker": TICKER,
        "capability": capability,
        "source_tier": "official",
        "source_name": f"src_{capability}",
        "source_family_id": source_family_id(TICKER, fingerprint),
        "published_at": datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc),
        "observed_at": captured,
        "captured_at": captured,
        "usable_as_of": captured,
        "time_basis": "publication timestamp as published by the source",
        "value_basis": "as published",
    }


def _draft(*, drop: str | None = None, sentiment: bool = False):
    from tradingagents.dataflows.catalyst_events import (
        CatalystEventV1,
        EventQueryOutcomeV1,
        content_fingerprint,
    )
    from tradingagents.research.evidence_freeze import PriceObservation

    event = CatalystEventV1(
        security_id=TICKER,
        kind="buyback",
        channel="official",
        title="关于回购公司股份的方案",
        publication_date="2026-09-20",
        content_fingerprint=content_fingerprint("关于回购公司股份的方案"),
    )
    capabilities = [
        item
        for name in REQUIRED_CAPABILITIES
        if name != drop
        for item in (_qualified(name),)
    ]
    if sentiment:
        capabilities.append(_qualified(CAP_SENTIMENT))
    inputs = FreezeInputs(
        run_id=RUN_ID,
        ticker=TICKER,
        cutoff=CUTOFF,
        policy=catalyst_evidence_policy_v1(),
        events=[event],
        event_outcomes=[
            EventQueryOutcomeV1(
                outcome="covered_no_matching_events",
                source_id="cninfo",
                item_count=0,
                pagination_exhausted=True,
                reason="source proved the window and found nothing beyond the returned filing",
            )
        ],
        capabilities=capabilities,
        evidence=[
            _evidence_record(name) for name in REQUIRED_CAPABILITIES
        ] + ([_evidence_record(CAP_SENTIMENT)] if sentiment else []),
        prices=[
            PriceObservation(
                observed_on="2026-09-20", close=10.0, adjustment="qfq", source="wind"
            )
        ],
    )
    return EvidenceFreezer(inputs).close()


class RecordingCaller:
    """A model stand-in that records every prompt it is given.

    ``delays`` lets a test force roles to complete in a chosen order, which is
    the only honest way to test that completion order cannot reach the output.
    """

    def __init__(self, delays: dict[str, float] | None = None) -> None:
        self.prompts: list[tuple[str, str]] = []
        self.calls: list[str] = []
        self.delays = delays or {}
        self._lock = threading.Lock()

    def __call__(self, *, role: str, prompt: str) -> dict:
        with self._lock:
            self.prompts.append((role, prompt))
            self.calls.append(role)
        delay = self.delays.get(role, 0.0)
        if delay:
            time.sleep(delay)
        if role in ROLE_ORDER:
            return {
                "findings": [
                    {
                        "kind": "fact",
                        "text": f"{role} 观察到一条已核实事实。",
                        "evidence_ids": ["evcap.event_coverage"],
                        "confidence": 0.7,
                    }
                ],
                "usage": {"input_tokens": 100, "output_tokens": 40},
            }
        if role == "independent_refutation":
            return {
                "challenges": [
                    {
                        "kind": "missing_evidence",
                        "severity": "minor",
                        "target_finding_ids": ["f.catalyst_events.i0"],
                        "statement": "回购规模口径未在披露中给出。",
                        "test_method": "核对回购公告的数量上限与资金上限。",
                    }
                ],
                "usage": {"input_tokens": 80, "output_tokens": 20},
            }
        return {
            "judgement": "存在一个可验证的近期催化，判断优先级取决于补证速度。",
            "priority": "verify_first",
            "primary_catalyst_event_id": None,
            "key_evidence_finding_ids": ["f.catalyst_events.i0"],
            "key_question": "回购是否已获股东大会通过并进入实施？",
            "next_check": "核对股东大会决议公告与首次回购进展公告。",
            "critical_limitations": ["回购公告仅披露方案，未披露实施进度。"],
            "dispositions": [
                {
                    "challenge_id": "ch.i0",
                    "outcome": "accepted",
                    "rationale": "采纳该缺证提示，并写入关键限制。",
                    "evidence_ids": ["evcap.event_coverage"],
                }
            ],
            "usage": {"input_tokens": 90, "output_tokens": 60},
        }


def _request() -> CatalystRunRequest:
    from datetime import datetime, timezone

    return CatalystRunRequest(
        run_id=RUN_ID,
        ticker=TICKER,
        as_of=datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc),
        research_question="本次研究窗口内是否存在需要优先核查的催化？",
    )


# ---------------------------------------------------------------------------
# Partitioned state and fixed-order merge
# ---------------------------------------------------------------------------


def _merge_shuffle_invariant(slots: SpecialistSlots) -> None:
    assert [item.role for item in slots.ordered_results()] == list(ROLE_ORDER)
    # Every arrival order must yield the same merged list, not merely a
    # re-sortable one.  ROLE_ORDER is *not* alphabetical, so a merge that read
    # in arrival order is observably different from one that does not.
    expected = list(ROLE_ORDER)
    for permutation in itertools.permutations(ROLE_ORDER):
        shuffled = SpecialistSlots()
        for role in permutation:
            shuffled.put(slots.get(role))
        assert [item.role for item in shuffled.ordered_results()] == expected
        assert shuffled.merged_findings() == slots.merged_findings()


def test_merge_reads_roles_in_a_fixed_order_not_completion_order() -> None:
    """Design SS5.4: results must not depend on which role finished first."""
    slots = SpecialistSlots()
    for role in ROLE_ORDER:
        slots.put(
            SpecialistResult(
                role=role,
                status=RoleStatus.OK,
                findings=(
                    SpecialistFinding(
                        finding_id=f"f.{role}.i0",
                        run_id=RUN_ID,
                        role=role,
                        kind="fact",
                        text=f"{role} 的事实",
                        evidence_ids=("evcap.event_coverage",),
                        confidence=0.5,
                    ),
                ),
            )
        )
    _merge_shuffle_invariant(slots)


def test_writing_one_role_twice_with_different_content_is_a_conflict() -> None:
    """Design SS5.4: the same id with different content must not overwrite."""
    from tradingagents.execution.budget import BudgetConflictError

    slots = SpecialistSlots()
    slots.put(SpecialistResult(role="market_reaction", status=RoleStatus.OK))
    with pytest.raises(BudgetConflictError):
        slots.put(SpecialistResult(role="market_reaction", status=RoleStatus.FAILED))


def test_a_failed_role_is_not_reported_as_zero_findings() -> None:
    """Design SS5.4: partial means partial, and says which stage failed."""
    slots = SpecialistSlots()
    slots.put(SpecialistResult(role="catalyst_events", status=RoleStatus.OK))
    slots.put(SpecialistResult(role="operating_delivery", status=RoleStatus.FAILED))
    assert slots.incomplete_roles() == ("operating_delivery", "market_reaction")
    assert slots.missing_roles() == ("market_reaction",)


def test_specialist_output_is_bounded_per_role() -> None:
    """Design SS5.5: three core findings and three unknowns per role."""
    raw = [
        {
            "kind": "fact",
            "text": f"事实 {index}",
            "evidence_ids": ["evcap.event_coverage"],
            "confidence": 0.5,
        }
        for index in range(6)
    ] + [
        {
            "kind": "unknown",
            "text": f"未知 {index}",
            "next_checks": ["补取公告全文"],
        }
        for index in range(6)
    ]
    findings = normalize_findings("catalyst_events", RUN_ID, raw)
    assert len([item for item in findings if item.kind in {"fact", "inference"}]) <= (
        MAX_FINDINGS_PER_ROLE * 2
    )
    assert len([item for item in findings if item.kind == "unknown"]) == 3


def test_a_malformed_finding_is_dropped_rather_than_crashing_the_role() -> None:
    """One bad record must not take down a role that produced good ones."""
    findings = normalize_findings(
        "catalyst_events",
        RUN_ID,
        [
            {"kind": "fact", "text": "无证据的事实", "confidence": 0.5},
            {
                "kind": "fact",
                "text": "有证据的事实",
                "evidence_ids": ["evcap.event_coverage"],
                "confidence": 0.5,
            },
        ],
    )
    assert [item.text for item in findings] == ["有证据的事实"]


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_each_specialist_receives_only_its_own_view() -> None:
    """Design SS5.2: no role reads another role's material."""
    draft = _draft(sentiment=True)
    ledger = BudgetLedger(RUN_ID)
    views = {}
    prompts = {}

    def per_role_caller(*, role: str, prompt: str):
        views[role] = build_specialist_view(draft, role)
        prompts[role] = prompt
        return RecordingCaller()(role=role, prompt=prompt)

    for role in ROLE_ORDER:
        run_specialist(
            role,
            views[role] if role in views else build_specialist_view(draft, role),
            caller=per_role_caller,
            ledger=ledger,
            run_id=RUN_ID,
        )
    # The operating role must not be able to cite a sentiment record, and the
    # market role must not be handed a fundamentals document.
    assert "evcap.sentiment" not in views["operating_delivery"].citable_evidence_ids
    assert "evcap.fundamentals" not in views["market_reaction"].citable_evidence_ids
    for role, prompt in prompts.items():
        assert views[role].draft_id in prompt


def test_a_specialist_is_skipped_when_its_required_capability_failed() -> None:
    """Design SS9.1: never ask a model to reason about evidence it never got."""
    draft = _draft(drop=CAP_PRICE)
    caller = RecordingCaller()
    result = run_specialist(
        "market_reaction",
        build_specialist_view(draft, "market_reaction"),
        caller=caller,
        ledger=BudgetLedger(RUN_ID),
        run_id=RUN_ID,
    )
    assert result.status is RoleStatus.SKIPPED
    assert "price_history" in result.error_category
    assert caller.calls == []


def _anchor_findings() -> tuple[SpecialistFinding, ...]:
    return (
        SpecialistFinding(
            finding_id="f.market_reaction.i0",
            run_id=RUN_ID,
            role="market_reaction",
            kind="fact",
            text="股价在公告后三个交易日上涨 8%。",
            evidence_ids=("evcap.price_history",),
            confidence=0.6,
        ),
    )


# Anything that would anchor the refuter on someone else's conclusion.
ANCHORING_MARKERS = (
    "verify_first",
    "keep_watching",
    "defer_research",
    "insufficient_information",
    "优先核查",
    "优先关注",
    "judgement",
    "brief",
    "综合结论",
    "推荐",
)


def test_the_refuter_prompt_contains_no_conclusion_to_anchor_on() -> None:
    """Design SS5.2: the refuter sees findings, never a conclusion.

    Checked as a marker scan rather than a single string, so a refuter that is
    handed the brief, the candidate priority, or a summary under different
    wording is caught too.
    """
    prompt = render_refutation_prompt(_anchor_findings(), RUN_ID)
    assert "f.market_reaction.i0" in prompt
    lowered = prompt.lower()
    for marker in ANCHORING_MARKERS:
        assert marker not in prompt, f"refutation prompt leaked {marker!r}"
        assert marker not in lowered


def test_the_refuter_call_receives_no_conclusion() -> None:
    """The prompt builder is only half the property; the call must use it.

    A refuter that receives a clean prompt from the builder but is then handed
    a conclusion by its caller is anchored just the same.
    """
    caller = RecordingCaller()
    run_refutation(
        _anchor_findings(),
        caller=caller,
        ledger=BudgetLedger(RUN_ID),
        run_id=RUN_ID,
    )
    assert len(caller.prompts) == 1
    role, prompt = caller.prompts[0]
    assert role == "independent_refutation"
    lowered = prompt.lower()
    for marker in ANCHORING_MARKERS:
        assert marker not in prompt
        assert marker not in lowered


def test_the_refuter_returns_at_most_three_challenges() -> None:
    raw = {
        "challenges": [
            {
                "kind": "missing_evidence",
                "severity": "minor",
                "target_finding_ids": ["f.market_reaction.i0"],
                "statement": f"缺证 {index}",
                "test_method": "补证",
            }
            for index in range(6)
        ]
    }
    result = run_refutation(
        (
            SpecialistFinding(
                finding_id="f.market_reaction.i0",
                run_id=RUN_ID,
                role="market_reaction",
                kind="fact",
                text="事实",
                evidence_ids=("evcap.price_history",),
                confidence=0.5,
            ),
        ),
        caller=lambda **kwargs: raw,
        ledger=BudgetLedger(RUN_ID),
        run_id=RUN_ID,
    )
    assert len(result.challenges) == MAX_CHALLENGES


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------


def _challenge(challenge_id: str = "ch.i0", *, is_key: bool = False) -> Challenge:
    return Challenge(
        challenge_id=challenge_id,
        run_id=RUN_ID,
        kind="missing_evidence",
        severity="critical" if is_key else "minor",
        target_finding_ids=("f.catalyst_events.i0",),
        statement="关键假设缺少证据。",
        test_method="核对公告全文。",
        is_key=is_key,
    )


def test_every_challenge_needs_exactly_one_disposition() -> None:
    """Design A08: a challenge without a disposition is a silent deletion."""
    challenges = (_challenge("ch.i0"), _challenge("ch.i1"))
    with pytest.raises(ValueError):
        validate_dispositions(challenges, ())

    disposition = ChallengeDisposition(
        challenge_id="ch.i0",
        outcome="unresolved",
        rationale="暂时无法解决",
        retained_limitations=("关键假设未验证",),
    )
    with pytest.raises(ValueError):
        validate_dispositions(challenges, (disposition,))

    both = (
        disposition,
        ChallengeDisposition(
            challenge_id="ch.i1",
            outcome="unresolved",
            rationale="同样无法解决",
            retained_limitations=("第二条限制",),
        ),
    )
    validate_dispositions(challenges, both)


def test_an_unresolved_key_challenge_is_detected() -> None:
    challenges = (_challenge("ch.i0", is_key=True), _challenge("ch.i1"))
    dispositions = (
        ChallengeDisposition(
            challenge_id="ch.i0",
            outcome="unresolved",
            rationale="无法用现有证据解决",
            retained_limitations=("核心收入确认缺证",),
        ),
        ChallengeDisposition(
            challenge_id="ch.i1",
            outcome="unresolved",
            rationale="非关键但未解决",
            retained_limitations=("次要限制",),
        ),
    )
    assert key_unresolved_challenges(challenges, dispositions) == ("ch.i0",)


def test_a_resolved_challenge_does_not_cap_the_priority() -> None:
    challenges = (_challenge("ch.i0", is_key=True),)
    dispositions = (
        ChallengeDisposition(
            challenge_id="ch.i0",
            outcome="refuted_by_evidence",
            rationale="公告全文已给出资金上限",
            evidence_ids=("evcap.event_coverage",),
        ),
    )
    assert key_unresolved_challenges(challenges, dispositions) == ()


# ---------------------------------------------------------------------------
# The SS9.1 priority matrix
# ---------------------------------------------------------------------------


CLEAN = ProcessState(completeness="complete", quality="PASS")


def test_a_clean_run_permits_the_proposed_category() -> None:
    decision = decide_priority("verify_first", CLEAN)
    assert decision.priority == "verify_first"
    assert decision.blocking_reasons == ()


def test_a_missing_required_capability_caps_the_priority() -> None:
    state = ProcessState(
        completeness="partial",
        quality="LOW_CONFIDENCE",
        missing_required_capabilities=(CAP_PRICE,),
    )
    decision = decide_priority("verify_first", state)
    assert decision.priority == "insufficient_information"
    assert "required_capability_unavailable" in decision.blocking_reasons


def test_a_failed_specialist_caps_the_priority() -> None:
    state = ProcessState(
        completeness="partial",
        quality="LOW_CONFIDENCE",
        incomplete_roles=("market_reaction",),
    )
    assert decide_priority("keep_watching", state).priority == "insufficient_information"


def test_a_missing_refutation_stage_caps_the_priority() -> None:
    state = ProcessState(
        completeness="partial", quality="LOW_CONFIDENCE", refutation_missing=True
    )
    decision = decide_priority("verify_first", state)
    assert "refutation_stage_missing" in decision.blocking_reasons


def test_an_unresolved_key_challenge_caps_the_priority() -> None:
    state = ProcessState(
        completeness="partial", quality="LOW_CONFIDENCE", key_unresolved=("ch.i0",)
    )
    decision = decide_priority("verify_first", state)
    assert decision.priority == "insufficient_information"
    assert "key_challenge_unresolved" in decision.blocking_reasons


def test_a_hard_error_blocks_and_forces_information_insufficient() -> None:
    """Design SS9.1 row 2: an identity conflict stops directional research."""
    state = ProcessState(
        completeness="blocked",
        quality="FAIL_STOP",
        reason_codes=("identity_conflict",),
    )
    assert state.ceiling_priority() == "insufficient_information"
    decision = decide_priority("verify_first", state)
    assert decision.priority == "insufficient_information"
    assert "identity_conflict" in decision.blocking_reasons


def test_a_registered_blocking_reason_from_the_case_also_caps() -> None:
    state = ProcessState(
        completeness="partial",
        quality="LOW_CONFIDENCE",
        reason_codes=("pit_unverified",),
    )
    assert "pit_unverified" in state.blocking_reasons()


def test_a_lower_proposed_category_is_left_alone() -> None:
    """The code bounds the answer; it does not compute it."""
    assert decide_priority("keep_watching", CLEAN).priority == "keep_watching"
    assert decide_priority("defer_research", CLEAN).priority == "defer_research"


def test_an_unrecognised_candidate_degrades_to_information_insufficient() -> None:
    assert decide_priority("buy_now", CLEAN).priority == "insufficient_information"


def test_optional_capability_loss_alone_does_not_block_a_complete_run() -> None:
    """Design SS9: a missing optional input is a disclosed gap, not a cap."""
    state = build_process_state(
        _draft(),
        _all_ok_slots(),
        refutation=RefutationResult(),
        unresolved_key=(),
        synthesis=SynthesisDraft(judgement="x", priority="verify_first"),
        brief_overflow=False,
    )
    assert state.completeness == "complete"
    assert state.blocking_reasons() == ()


def _all_ok_slots() -> SpecialistSlots:
    slots = SpecialistSlots()
    for role in ROLE_ORDER:
        slots.put(SpecialistResult(role=role, status=RoleStatus.OK))
    return slots


# ---------------------------------------------------------------------------
# Budget interaction
# ---------------------------------------------------------------------------


def test_a_role_refused_by_the_budget_does_not_call_the_model() -> None:
    """Design SS5.5/A09: hitting a ceiling stops the call, not just the result."""
    ledger = BudgetLedger(RUN_ID, limits={BudgetBucket.MAIN_ANALYSIS: 0, BudgetBucket.MODEL_ATTEMPTS: 12})
    caller = RecordingCaller()
    result = run_specialist(
        "catalyst_events",
        build_specialist_view(_draft(), "catalyst_events"),
        caller=caller,
        ledger=ledger,
        run_id=RUN_ID,
    )
    assert result.status is RoleStatus.REFUSED
    assert caller.calls == []


def test_synthesis_degrades_to_a_code_template_when_the_budget_is_gone() -> None:
    """Design SS5.5: never spend a model call explaining a timeout."""
    ledger = BudgetLedger(RUN_ID, limits={BudgetBucket.MAIN_ANALYSIS: 0, BudgetBucket.MODEL_ATTEMPTS: 12})
    caller = RecordingCaller()
    draft = run_synthesis(
        (),
        (),
        (),
        ProcessState(completeness="partial", quality="LOW_CONFIDENCE"),
        caller=caller,
        ledger=ledger,
        run_id=RUN_ID,
    )
    assert caller.calls == []
    assert draft.priority == "insufficient_information"
    assert "综合阶段未产出可用简报" in draft.critical_limitation_texts[0]


def test_synthesis_runs_exactly_once() -> None:
    """Design SS5.2 forbids a second summarization model."""
    caller = RecordingCaller()
    ledger = BudgetLedger(RUN_ID)
    run_synthesis(
        (),
        (),
        (),
        ProcessState(completeness="complete", quality="PASS"),
        caller=caller,
        ledger=ledger,
        run_id=RUN_ID,
    )
    assert caller.calls == ["synthesis"]


def test_synthesis_drops_to_a_template_when_dispositions_are_incomplete() -> None:
    """Design A08: a synthesis that forgets a challenge is not accepted."""
    def forgetful(*, role: str, prompt: str):
        # Returns a plausible brief that silently ignores the challenge: no
        # disposition at all.  This is the failure the gate exists for.
        return {
            "judgement": "看起来有一条催化。",
            "priority": "verify_first",
            "key_question": "疑点？",
            "next_check": "下一步？",
            "dispositions": [],
        }

    ledger = BudgetLedger(RUN_ID)
    challenges = (_challenge("ch.i0"),)
    draft = run_synthesis(
        (),
        challenges,
        (),
        ProcessState(completeness="complete", quality="PASS"),
        caller=forgetful,
        ledger=ledger,
        run_id=RUN_ID,
    )
    assert draft.rationale.startswith("code template")
    assert draft.priority == "insufficient_information"


# ---------------------------------------------------------------------------
# Brief assembly and the overflow template
# ---------------------------------------------------------------------------


def _synth(**kwargs) -> SynthesisDraft:
    base = {
        "judgement": "判断。",
        "priority": "verify_first",
        "key_evidence_finding_ids": ("f.catalyst_events.i0",),
        "key_question_text": "疑点？",
        "next_check_text": "下一步？",
        "critical_limitation_texts": ("限制一", "限制二"),
    }
    base.update(kwargs)
    return SynthesisDraft(**base)


def test_a_line_referencing_a_removed_finding_is_dropped() -> None:
    """A brief must not cite a finding the evidence gate removed."""
    brief = build_brief(
        _synth(),
        priority="keep_watching",
        surviving_finding_ids=frozenset(),
        event_ids=frozenset(),
        challenge_ids=frozenset(),
    )
    assert brief.key_evidence == ()
    assert brief.character_count <= 420


def test_the_safety_template_keeps_every_limitation() -> None:
    """Design A02/A07: overflow degrades, it never drops a risk."""
    long_limitations = tuple(f"第 {index} 条重大限制说明。" for index in range(6))
    brief = build_brief(
        _synth(
            judgement="判断。" * 90,
            key_question_text="疑点？" * 60,
            next_check_text="下一步？" * 60,
            critical_limitation_texts=long_limitations,
        ),
        priority="keep_watching",
        surviving_finding_ids=frozenset({"f.catalyst_events.i0"}),
        event_ids=frozenset(),
        challenge_ids=frozenset(),
    )
    assert brief.kind == "safety_overflow"
    assert brief.overflow_reason == "brief_safety_overflow"
    assert brief.priority == "insufficient_information"
    assert len(brief.critical_limitations) == 6
    assert brief.character_count <= 120


def test_an_ordinary_brief_carries_at_most_three_evidence_lines() -> None:
    draft = _synth(
        key_evidence_finding_ids=(
            "f.catalyst_events.i0",
            "f.operating_delivery.i0",
            "f.market_reaction.i0",
            "f.catalyst_events.i1",
        )
    )
    brief = build_brief(
        draft,
        priority="keep_watching",
        surviving_finding_ids=frozenset(
            {
                "f.catalyst_events.i0",
                "f.operating_delivery.i0",
                "f.market_reaction.i0",
                "f.catalyst_events.i1",
            }
        ),
        event_ids=frozenset(),
        challenge_ids=frozenset(),
    )
    assert len(brief.key_evidence) <= 3


# ---------------------------------------------------------------------------
# Concurrency: serial and parallel must be indistinguishable
# ---------------------------------------------------------------------------


def test_serial_and_parallel_runs_produce_identical_public_cases() -> None:
    """Design P3 acceptance: "串并行公共结果逐字相同".

    The parallel caller is given delays that force the *last* role in the
    fixed order to finish first, which is the ordering that would corrupt a
    shared-buffer implementation. The two serialized cases are then compared
    byte for byte, not field for field.
    """
    draft = _draft()
    serial = run_catalyst_research(
        _request(),
        draft,
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
        concurrency=1,
    )
    inverted = RecordingCaller(
        delays={"market_reaction": 0.0, "catalyst_events": 0.06}
    )
    parallel = run_catalyst_research(
        _request(),
        draft,
        caller=inverted,
        ledger=BudgetLedger(RUN_ID),
        concurrency=2,
    )
    left = serial.case.model_dump_json()
    right = parallel.case.model_dump_json()
    assert left == right
    assert serial.published is True and parallel.published is True
    # The case sorts findings by id, which would hide a merge that read in
    # completion order. Pin the order the flow actually produced, so the
    # equivalence claim covers the merge and not only the serialisation.
    assert [item.finding_id for item in serial.slots.merged_findings()] == [
        f"f.{role}.i0" for role in ROLE_ORDER
    ]
    assert [item.finding_id for item in parallel.slots.merged_findings()] == [
        f"f.{role}.i0" for role in ROLE_ORDER
    ]


def test_parallel_roles_still_return_in_the_fixed_order() -> None:
    draft = _draft(sentiment=True)
    caller = RecordingCaller(delays={"catalyst_events": 0.06})
    slots = execute_specialists(
        draft,
        caller=caller,
        ledger=BudgetLedger(RUN_ID),
        concurrency=3,
    )
    assert [item.role for item in slots.ordered_results()] == list(ROLE_ORDER)


def test_the_global_model_semaphore_bounds_in_flight_calls() -> None:
    """Design SS5.4: the cap is process-wide, not per run and not per role.

    Two runs fan out three roles each at concurrency 3. A per-run semaphore
    would put six model calls in flight; a per-role one would too. Only a
    process-wide cap holds the peak at the configured bound, which is what
    keeps a batch of runs from multiplying the provider load.
    """
    from tradingagents.graph import catalyst_workflow as workflow

    peak = {"now": 0, "max": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def instrumented(*, role: str, prompt: str):
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        time.sleep(0.03)
        with lock:
            peak["now"] -= 1
        return {"findings": [], "usage": {"input_tokens": 1, "output_tokens": 1}}

    def one_run(tag: str):
        # Both runs start at the same moment, so the peak really reflects
        # concurrent work from two batches rather than one run's own fan-out.
        barrier.wait(timeout=5)
        return execute_specialists(
            _draft(),
            caller=instrumented,
            ledger=BudgetLedger(f"{RUN_ID}_{tag}"),
            concurrency=3,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(one_run, "a"), pool.submit(one_run, "b")]]

    assert all(len(item.results) == 3 for item in results)
    assert workflow.DEFAULT_SPECIALIST_CONCURRENCY == 2
    assert peak["max"] <= 2, f"observed {peak['max']} concurrent model calls"


# ---------------------------------------------------------------------------
# A short budget must not make the scheduler the decision maker
# ---------------------------------------------------------------------------


def _ledger_with_specialist_ceiling(ceiling: int) -> BudgetLedger:
    """A ledger whose specialist budget is exactly ``ceiling`` units.

    The run-wide attempt total is lifted so the specialist ceiling is the only
    binding constraint; otherwise the test would be measuring whichever limit
    happens to be smaller.
    """
    return BudgetLedger(
        RUN_ID,
        limits={BudgetBucket.MAIN_ANALYSIS: ceiling, BudgetBucket.MODEL_ATTEMPTS: 99},
    )


def _roles_that_ran(slots: SpecialistSlots) -> tuple[str, ...]:
    return tuple(
        role for role in ROLE_ORDER if slots.get(role) is not None and slots.get(role).status is RoleStatus.OK
    )


@pytest.mark.parametrize("ceiling", [1, 2])
def test_a_short_budget_refuses_the_same_role_serially_and_in_parallel(ceiling: int) -> None:
    """The last unit must go to the first role in the fixed order, not to
    whichever thread the pool scheduled first.

    Before the fix this was the one property the suite could not see: with a
    ceiling of 2, the serial run always refused `market_reaction` while 7 of 8
    parallel runs refused `operating_delivery` instead. The ceiling was never
    breached -- the ledger is thread-safe -- but *which* role was refused is
    part of the conclusion, so the two paths produced different cases.
    """
    serial = _roles_that_ran(
        execute_specialists(
            _draft(),
            caller=RecordingCaller(),
            ledger=_ledger_with_specialist_ceiling(ceiling),
            concurrency=1,
        )
    )
    # Delays put the last role in the fixed order first, which is the ordering
    # that used to decide the loser.
    delays = {"market_reaction": 0.0, ROLE_ORDER[1]: 0.02}
    parallel = [
        _roles_that_ran(
            execute_specialists(
                _draft(),
                caller=RecordingCaller(delays=delays),
                ledger=_ledger_with_specialist_ceiling(ceiling),
                concurrency=2,
            )
        )
        for _ in range(8)
    ]

    # The fixed order is what decides, so the survivors are a prefix of it.
    assert serial == ROLE_ORDER[:ceiling]
    assert parallel == [serial] * 8, f"parallel diverged from serial: {set(parallel)}"


def test_a_short_budget_produces_byte_identical_public_cases() -> None:
    """The public artifact, not merely the role statuses, must match.

    Status equality is the weaker claim: two runs can agree that a role was
    refused and still publish different bytes if the refusal changed which
    findings the merge saw.
    """
    draft = _draft()
    serial = run_catalyst_research(
        _request(),
        draft,
        caller=RecordingCaller(),
        ledger=_ledger_with_specialist_ceiling(2),
        concurrency=1,
    )
    parallel = run_catalyst_research(
        _request(),
        draft,
        caller=RecordingCaller(delays={"market_reaction": 0.0, "catalyst_events": 0.03}),
        ledger=_ledger_with_specialist_ceiling(2),
        concurrency=2,
    )
    assert serial.case.model_dump_json() == parallel.case.model_dump_json()


def test_a_ample_budget_leaves_the_parallel_path_actually_concurrent() -> None:
    """Fixing the ordering must not have been bought by serialising the work.

    The reservation happens on the calling thread, so a fix that accidentally
    held that thread across the provider calls would pass every equivalence
    test above while quietly reducing the design SS5.4 concurrency ceiling to
    one. This measures overlap directly.
    """
    peak = {"now": 0, "max": 0}
    lock = threading.Lock()

    def instrumented(*, role: str, prompt: str):
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        time.sleep(0.03)
        with lock:
            peak["now"] -= 1
        return {"findings": [], "usage": {"input_tokens": 1, "output_tokens": 1}}

    execute_specialists(
        _draft(),
        caller=instrumented,
        ledger=_ledger_with_specialist_ceiling(3),
        concurrency=2,
    )
    assert peak["max"] == 2, f"expected genuinely concurrent calls, peak was {peak['max']}"


def test_a_cancelled_parallel_run_returns_its_reserved_units() -> None:
    """A reservation claimed for a role that is then cancelled must go back.

    The parallel path claims its units up front, before any role runs. Without
    an explicit release, a cancelled run would keep the quota it never spent
    and every later run on that ledger would start with a smaller ceiling.
    """
    ledger = _ledger_with_specialist_ceiling(3)
    slots = execute_specialists(
        _draft(),
        caller=RecordingCaller(),
        ledger=ledger,
        concurrency=2,
        cancel=lambda: True,
    )
    assert all(item.status is RoleStatus.CANCELLED for item in slots.ordered_results())
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 0
    # And the ceiling is genuinely whole again, not merely under-reported.
    assert ledger.remaining(BudgetBucket.MAIN_ANALYSIS) == 3


def test_a_capability_blocked_role_does_not_consume_a_unit_in_either_path() -> None:
    """A role that is skipped before it calls anything must not be charged.

    If the reservation loop charged roles that were about to report SKIPPED,
    the unit would go to a call that cannot happen and the next role would be
    refused a budget the serial path would have had. Dropping `fundamentals`
    blocks `operating_delivery`, which sits in the *middle* of the fixed order
    -- so a loop that charged it would take the second unit and refuse
    `market_reaction`, the last role. Both surviving roles running is therefore
    the assertion that tells the two behaviours apart.
    """
    blocked_role = "operating_delivery"
    statuses = {}
    for concurrency in (1, 2):
        ledger = _ledger_with_specialist_ceiling(2)
        slots = execute_specialists(
            _draft(drop=CAP_FUNDAMENTALS),
            caller=RecordingCaller(),
            ledger=ledger,
            concurrency=concurrency,
        )
        statuses[concurrency] = {item.role: item.status for item in slots.ordered_results()}
        assert statuses[concurrency][blocked_role] is RoleStatus.SKIPPED
        # Two roles remain callable, so a ceiling of two must run both.
        assert _roles_that_ran(slots) == tuple(
            role for role in ROLE_ORDER if role != blocked_role
        ), f"concurrency={concurrency} ran {_roles_that_ran(slots)}"
    assert statuses[1] == statuses[2]


# ---------------------------------------------------------------------------
# Commit barrier, cancellation, and idempotence
# ---------------------------------------------------------------------------


def test_a_case_is_published_only_behind_an_authorised_commit() -> None:
    committer = CaseCommitter()
    draft = _draft()
    refused = run_catalyst_research(
        _request(),
        draft,
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
        committer=committer,
        authorised=False,
    )
    assert refused.published is False
    assert committer.is_committed(RUN_ID) is False


def test_committing_the_same_case_twice_is_idempotent() -> None:
    """Design SS5.4: repeated submission of the same content is a no-op."""
    result = run_catalyst_research(
        _request(),
        _draft(),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
    )
    committer = CaseCommitter()
    first = committer.commit(result.case, authorised=True)
    second = committer.commit(result.case, authorised=True)
    assert first == second


def test_committing_different_content_under_one_run_id_is_a_conflict() -> None:
    committer = CaseCommitter()
    serial = run_catalyst_research(
        _request(),
        _draft(),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
    )
    committer.commit(serial.case, authorised=True)
    with pytest.raises(CommitRefused):
        committer.commit(
            serial.case.model_copy(
                update={"research_question": "different question"}
            ),
            authorised=True,
        )


def test_a_cancelled_run_publishes_nothing() -> None:
    """Design SS5.5: a late result may finish but must not be the conclusion."""
    committer = CaseCommitter()
    result = run_catalyst_research(
        _request(),
        _draft(),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
        committer=committer,
        cancel=lambda: True,
    )
    assert result.published is False
    assert result.not_published_reason
    assert committer.is_committed(RUN_ID) is False
    assert result.case.priority_decision.priority == "insufficient_information"


def test_cancelling_after_the_specialists_also_withholds_publication() -> None:
    committer = CaseCommitter()
    counter = {"n": 0}

    def cancel() -> bool:
        counter["n"] += 1
        # Let the three specialists run, then cancel.
        return counter["n"] > 3

    result = run_catalyst_research(
        _request(),
        _draft(),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
        committer=committer,
        concurrency=1,
        cancel=cancel,
    )
    assert result.published is False
    assert committer.is_committed(RUN_ID) is False


# ---------------------------------------------------------------------------
# End-to-end invariants
# ---------------------------------------------------------------------------


def test_a_healthy_run_produces_a_case_with_resolvable_references() -> None:
    result = run_catalyst_research(
        _request(),
        _draft(),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
    )
    case = result.case
    assert case.completeness == "complete"
    assert case.quality == "PASS"
    assert case.brief.priority == case.priority_decision.priority
    # The case schema validates resolvability on construction, so reaching here
    # is the assertion; this checks the shape a reader depends on.
    assert case.brief.kind == "ordinary"
    assert case.budget_usage.model_attempts == 5


def test_a_run_missing_a_required_capability_never_reaches_the_top_priority() -> None:
    """Design SS9.1 row 4 end to end."""
    result = run_catalyst_research(
        _request(),
        _draft(drop=CAP_FUNDAMENTALS),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
    )
    case = result.case
    assert case.completeness == "partial"
    assert case.priority_decision.priority == "insufficient_information"
    assert "required_capability_unavailable" in case.reason_codes
    assert case.brief.priority == "insufficient_information"


def test_the_published_case_is_json_serialisable_and_stable() -> None:
    """A reader fetches this; it must round-trip and be order-independent."""
    result = run_catalyst_research(
        _request(),
        _draft(),
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
    )
    payload = result.case.model_dump(mode="json")
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_budget_usage_in_the_case_reflects_the_real_spend() -> None:
    ledger = BudgetLedger(RUN_ID)
    run_catalyst_research(
        _request(), _draft(), caller=RecordingCaller(), ledger=ledger
    )
    usage = run_catalyst_research(
        _request(), _draft(), caller=RecordingCaller(), ledger=BudgetLedger(RUN_ID)
    ).case.budget_usage
    assert usage.model_attempts == 5
    assert usage.input_tokens is not None
    assert usage.termination_reason == "complete"


def test_a_provider_that_reports_no_usage_marks_the_tokens_unknown() -> None:
    """Design SS5.5: missing usage is unknown, never zero."""

    def silent(*, role: str, prompt: str):
        if role in ROLE_ORDER:
            return {"findings": []}
        if role == "independent_refutation":
            return {"challenges": []}
        return {
            "judgement": "判断。",
            "priority": "keep_watching",
            "key_question": "疑点？",
            "next_check": "下一步？",
            "dispositions": [],
        }

    result = run_catalyst_research(
        _request(), _draft(), caller=silent, ledger=BudgetLedger(RUN_ID)
    )
    assert result.case.budget_usage.model_usage_available is False
    assert result.case.budget_usage.input_tokens is None


# ---------------------------------------------------------------------------
# Degenerate-path serial/parallel equivalence (T20/T24 follow-up)
# ---------------------------------------------------------------------------


def test_serial_and_parallel_runs_stay_identical_when_a_role_is_capability_blocked() -> None:
    """The happy-path equivalence test alone would miss a merge bug that only
    shows up when a role never ran at all.

    Dropping ``CAP_FUNDAMENTALS`` blocks ``operating_delivery`` -- the middle
    role in ``ROLE_ORDER`` -- before it ever reaches the caller, so the merge
    has to handle a hole in the middle of the fixed order, not just at either
    end. This is the same fixture ``test_a_run_missing_a_required_capability_...``
    already trusts for the single-run case; here it is run at both
    concurrency levels and compared byte for byte.
    """
    draft = _draft(drop=CAP_FUNDAMENTALS)
    serial = run_catalyst_research(
        _request(),
        draft,
        caller=RecordingCaller(),
        ledger=BudgetLedger(RUN_ID),
        concurrency=1,
    )
    inverted = RecordingCaller(
        delays={"market_reaction": 0.0, "catalyst_events": 0.06}
    )
    parallel = run_catalyst_research(
        _request(),
        draft,
        caller=inverted,
        ledger=BudgetLedger(RUN_ID),
        concurrency=2,
    )
    assert serial.case.completeness == "partial"
    assert parallel.case.completeness == "partial"
    assert serial.case.model_dump_json() == parallel.case.model_dump_json()


# ---------------------------------------------------------------------------
# T24: resume/reconnect must not recompute
# ---------------------------------------------------------------------------


def test_reinvoking_the_workflow_on_the_same_ledger_dispatches_no_new_calls() -> None:
    """Defense in depth for design §7 ("刷新和 SSE 重连都不得触发重算").

    The executor must never call ``run_catalyst_research`` a second time for
    a run that already committed -- that guarantee lives in the executor,
    which is out of this module's scope to wire (see the engineering
    handoff's narrow-T24 decision). What this module *can* guarantee, and
    what this test pins, is that if a second invocation ever shared the run's
    own ledger and committer -- the only continuity a resume or a reconnect
    could restore -- the budget ceiling that already paid for the first run
    refuses every further model call before the caller is dispatched again,
    and the commit barrier refuses the divergent result that would result.
    A recompute is not merely discouraged; it is unaffordable and unpublishable.
    """
    ledger = BudgetLedger(RUN_ID)
    committer = CaseCommitter()
    draft = _draft()
    caller = RecordingCaller()

    first = run_catalyst_research(
        _request(), draft, caller=caller, ledger=ledger, committer=committer
    )
    assert first.published is True
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 5
    calls_after_first = len(caller.calls)

    second = run_catalyst_research(
        _request(), draft, caller=caller, ledger=ledger, committer=committer
    )
    # No new dispatch to the model: the budget was already spent.
    assert len(caller.calls) == calls_after_first
    assert ledger.consumed(BudgetBucket.MAIN_ANALYSIS) == 5
    # The commit barrier refuses to publish a second, divergent result.
    assert second.published is False


def test_reading_a_committed_case_touches_neither_the_ledger_nor_the_caller() -> None:
    """The read side of design §7: ``project_catalyst`` (T09, already merged
    on ``main`` as ``tradingagents/web/catalyst_projection.py``) is the actual
    reconnect/refresh path, and it is out of this worktree's scope to modify.
    Its own test suite (``tests/web/test_catalyst_projection.py``) already
    asserts 0 LLM/provider calls around a read. What this test additionally
    pins, at the module boundary this worktree does own, is that the module
    has no budget or model dependency at all -- so a read literally cannot
    reach either, regardless of how the executor wires it up.
    """
    from tradingagents.web import catalyst_projection

    source = inspect.getsource(catalyst_projection)
    assert "BudgetLedger" not in source
    assert "ModelCaller" not in source
    assert "run_catalyst_research" not in source
    assert "catalyst_workflow" not in source


# ---------------------------------------------------------------------------
# T24: audit records disclose shape, never secrets or raw prompts
# ---------------------------------------------------------------------------


def test_the_audit_trail_never_carries_prompts_secrets_or_provider_urls() -> None:
    """Design §4.3: an auditable record may show shape (bucket, stage,
    counts, outcome) -- never the prompt that produced it, a secret, or a raw
    provider payload. ``_invoke_budgeted`` is supposed to reduce every
    failure to a type name before it reaches the ledger; this asserts that
    guarantee end to end, through both the ledger the operator reads and the
    published case a reader sees.
    """
    secret = "sk-live-should-never-appear-anywhere"
    leaked_url = "https://vendor.internal/x"

    def leaky(*, role: str, prompt: str):
        if role == "catalyst_events":
            raise RuntimeError(f"POST {leaked_url} failed: key {secret}")
        if role in ROLE_ORDER:
            return {
                "findings": [],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        if role == "independent_refutation":
            return {"challenges": []}
        return {
            "judgement": "判断。",
            "priority": "keep_watching",
            "key_question": "疑点？",
            "next_check": "下一步？",
            "dispositions": [],
        }

    ledger = BudgetLedger(RUN_ID)
    result = run_catalyst_research(_request(), _draft(), caller=leaky, ledger=ledger)

    for record in ledger.records():
        assert secret not in record.detail
        assert leaked_url not in record.detail
        # The prompt itself is never a field on the record at all.
        assert not hasattr(record, "prompt")

    dumped = result.case.model_dump_json()
    assert secret not in dumped
    assert leaked_url not in dumped
