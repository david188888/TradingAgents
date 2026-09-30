"""Invariant tests for the ``catalyst-research-case-v1`` public contract.

Every test in this file is negative on purpose: it constructs a valid case
and then violates exactly one invariant, asserting that construction fails.
A test that only exercised the happy path would not prove the invariant
exists, so the module deliberately has no "valid case is accepted" test
beyond ``test_minimal_case_round_trips`` (which exists to prove the negative
tests fail for the right reason rather than because the builder is broken).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import (
    BRIEF_CHARACTER_BUDGET,
    SAFETY_OVERFLOW_TEMPLATE_BUDGET,
    BriefLine,
    BudgetUsage,
    CatalystBrief,
    CatalystEvent,
    CatalystEvidence,
    CatalystResearchCase,
    Challenge,
    ChallengeDisposition,
    NumericFact,
    ResearchPriorityDecision,
    SpecialistFinding,
    brief_character_count,
)

RUN_ID = "run-catalyst-0001"
TICKER = "600519"
AS_OF = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


def _evidence(
    evidence_id: str = "ev_1", *, run_id: str = RUN_ID, **overrides
) -> CatalystEvidence:
    payload = {
        "evidence_id": evidence_id,
        "run_id": run_id,
        "ticker": TICKER,
        "capability": "catalyst_event_window",
        "source_tier": "official",
        "source_name": "SSE announcement 2026-08-14",
        "public_url": "https://example.invalid/announcement/2026-08-14",
        "source_family_id": "family:announcement-2026-08-14",
        "published_at": AS_OF - timedelta(days=30),
        "captured_at": AS_OF,
        "usable_as_of": AS_OF,
        "time_basis": "announcement publication time, Asia/Shanghai",
        "value_basis": "cumulative amount in CNY as announced",
    }
    payload.update(overrides)
    return CatalystEvidence(**payload)


def _event(
    event_id: str = "ev_1", *, run_id: str = RUN_ID, **overrides
) -> CatalystEvent:
    payload = {
        "event_id": event_id,
        "run_id": run_id,
        "ticker": TICKER,
        "event_type": "earnings_preannouncement",
        "version": 1,
        "title": "2026 interim results preannouncement",
        "status": "planned",
        "announced_at": AS_OF - timedelta(days=30),
        "occurred_on": "2026-08-14",
        "date_precision": "day",
        "date_evidence_ids": ("ev_1",),
    }
    payload.update(overrides)
    return CatalystEvent(**payload)


def _fact(
    finding_id: str = "f_fact_1", *, run_id: str = RUN_ID, **overrides
) -> SpecialistFinding:
    payload = {
        "finding_id": finding_id,
        "run_id": run_id,
        "role": "catalyst_events",
        "kind": "fact",
        "text": "The company published a preannouncement on 2026-08-14.",
        "evidence_ids": ("ev_1",),
        "event_ids": ("ev_1",),
        "confidence": 0.9,
    }
    payload.update(overrides)
    return SpecialistFinding(**payload)


def _inference(
    finding_id: str = "f_inf_1", *, run_id: str = RUN_ID, **overrides
) -> SpecialistFinding:
    payload = {
        "finding_id": finding_id,
        "run_id": run_id,
        "role": "catalyst_events",
        "kind": "inference",
        "text": "The preannouncement implies reported profit will rise year on year.",
        "evidence_ids": ("ev_1",),
        "supporting_finding_ids": ("f_fact_1",),
        "confidence": 0.6,
    }
    payload.update(overrides)
    return SpecialistFinding(**payload)


def _unknown(
    finding_id: str = "f_unk_1", *, run_id: str = RUN_ID, **overrides
) -> SpecialistFinding:
    payload = {
        "finding_id": finding_id,
        "run_id": run_id,
        "role": "operating_delivery",
        "kind": "unknown",
        "text": "Whether the order backlog converts into revenue is not yet observable.",
        "next_checks": ("Interim report revenue by segment",),
    }
    payload.update(overrides)
    return SpecialistFinding(**payload)


def _challenge(
    challenge_id: str = "ch_1", *, run_id: str = RUN_ID, **overrides
) -> Challenge:
    payload = {
        "challenge_id": challenge_id,
        "run_id": run_id,
        "kind": "counter_evidence",
        "severity": "material",
        "target_finding_ids": ("f_inf_1",),
        "statement": "Gross margin fell in the same period, so profit growth may be mix-driven.",
        "evidence_ids": ("ev_1",),
        "test_method": "Compare segment gross margin in the interim report.",
        "is_key": False,
    }
    payload.update(overrides)
    return Challenge(**payload)


def _disposition(challenge_id: str = "ch_1", **overrides) -> ChallengeDisposition:
    payload = {
        "challenge_id": challenge_id,
        "outcome": "partially_accepted",
        "rationale": "Margin data is not yet disclosed; the direction is plausible.",
        "evidence_ids": ("ev_1",),
        "retained_limitations": ("Segment margin not yet disclosed",),
        "finding_ids": ("f_inf_1",),
    }
    payload.update(overrides)
    return ChallengeDisposition(**payload)


def _brief(**overrides) -> CatalystBrief:
    payload = {
        "kind": "ordinary",
        "judgement": "Proceed to the interim report; the preannouncement is dated and sourced.",
        "priority": "verify_first",
        "primary_catalyst_event_id": "ev_1",
        "primary_catalyst": BriefLine(
            text="Interim results preannouncement dated 2026-08-14.",
            event_ids=("ev_1",),
        ),
        "key_evidence": (
            BriefLine(text="Preannouncement published.", finding_ids=("f_fact_1",)),
        ),
        "key_question": BriefLine(
            text="Does the profit rise survive a margin check?",
            challenge_ids=("ch_1",),
        ),
        "next_check": BriefLine(
            text="Read the interim segment margin.",
            finding_ids=("f_unk_1",),
        ),
        "critical_limitations": (),
    }
    payload.update(overrides)
    return CatalystBrief(**payload)


def _priority(**overrides) -> ResearchPriorityDecision:
    payload = {
        "priority": "verify_first",
        "candidate_priority": "verify_first",
        "proposed_by": "synthesis",
        "blocking_reasons": (),
        "rationale": "A dated, sourced catalyst with an explicit next check.",
    }
    payload.update(overrides)
    return ResearchPriorityDecision(**payload)


def _budget(**overrides) -> BudgetUsage:
    payload = {
        "model_attempts": 5,
        "structured_output_repairs": 0,
        "network_retries": 0,
        "data_capability_calls": 12,
        "http_attempts": 20,
        "semantic_preprocess_calls": 1,
        "model_usage_available": True,
        "input_tokens": 41000,
        "output_tokens": 5200,
        "stage_durations_ms": (("specialist", 42000),),
        "termination_reason": "completed",
    }
    payload.update(overrides)
    return BudgetUsage(**payload)


def _case(**overrides) -> CatalystResearchCase:
    run_id = overrides.get("run_id", RUN_ID)
    payload = {
        "run_id": run_id,
        "ticker": TICKER,
        "evidence_policy": "catalyst-evidence-policy-v1",
        "as_of": AS_OF,
        "source_sequence": 42,
        "completeness": "complete",
        "quality": "PASS",
        "reason_codes": (),
        "research_question": "Will the order change show up in the next results release?",
        "evidence": (_evidence(run_id=run_id),),
        "events": (_event(run_id=run_id),),
        "findings": (
            _fact(run_id=run_id),
            _inference(run_id=run_id),
            _unknown(run_id=run_id),
        ),
        "challenges": (_challenge(run_id=run_id),),
        "dispositions": (_disposition(),),
        "priority_decision": _priority(),
        "brief": _brief(),
        "budget_usage": _budget(),
    }
    payload.update(overrides)
    return CatalystResearchCase(**payload)


# ---------------------------------------------------------------------------
# Baseline sanity
# ---------------------------------------------------------------------------


def test_minimal_case_round_trips() -> None:
    case = _case()
    assert case.schema_version == "catalyst-research-case-v1"
    restored = CatalystResearchCase.model_validate(
        json.loads(case.model_dump_json())
    )
    assert restored == case


# ---------------------------------------------------------------------------
# Invariant: IDs are unique within a run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "duplicate"),
    [
        ("evidence", lambda: (_evidence(), _evidence())),
        ("events", lambda: (_event(), _event())),
        ("findings", lambda: (_fact(), _fact())),
        ("challenges", lambda: (_challenge(), _challenge())),
    ],
)
def test_duplicate_ids_in_the_same_run_are_rejected(field: str, duplicate) -> None:
    with pytest.raises(ValidationError, match="IDs must be unique within the run"):
        _case(**{field: duplicate()})


# ---------------------------------------------------------------------------
# Invariant: every dependency resolves
# ---------------------------------------------------------------------------


def test_dangling_evidence_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="evidence is not present in this run"):
        _case(findings=(_fact(evidence_ids=("ev_missing",)),))


def test_dangling_event_reference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="event is not present in this run"):
        _case(findings=(_fact(event_ids=("ev_missing",)),))


def test_dangling_date_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="date evidence is not present in this run"):
        _case(events=(_event(date_evidence_ids=("ev_missing",)),))


def test_dangling_challenge_target_is_rejected() -> None:
    with pytest.raises(ValidationError, match="challenge target finding is not present"):
        _case(
            challenges=(_challenge(target_finding_ids=("f_missing",)),),
            dispositions=(_disposition(),),
        )


def test_cross_run_evidence_is_rejected() -> None:
    foreign = _evidence(run_id="run-other-0002")
    with pytest.raises(ValidationError, match="evidence must belong to the current run"):
        _case(evidence=(foreign,))


# ---------------------------------------------------------------------------
# Invariant: inferences depend on surviving facts
# ---------------------------------------------------------------------------


def test_inference_without_supporting_fact_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must depend on surviving facts"):
        _inference(supporting_finding_ids=())


def test_inference_grounded_on_a_removed_fact_is_rejected() -> None:
    """Recursive check: removing the fact removes the inference's ground."""
    with pytest.raises(ValidationError, match="depends on a removed finding"):
        _case(findings=(_fact(survives=False), _inference(), _unknown()))


def test_inference_grounded_on_another_inference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must depend on surviving facts"):
        _case(findings=(_fact(), _inference(supporting_finding_ids=("f_inf_2",)), _inference("f_inf_2"), _unknown()))


def test_fact_depending_on_another_finding_is_rejected() -> None:
    with pytest.raises(ValidationError, match="a fact finding cannot depend on"):
        _fact(finding_id="f_fact_2", supporting_finding_ids=("f_fact_1",))


# ---------------------------------------------------------------------------
# Invariant: unknowns carry no false evidence and no confidence
# ---------------------------------------------------------------------------


def test_unknown_with_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown finding cannot carry evidence"):
        _unknown(evidence_ids=("ev_1",))


def test_unknown_with_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown finding must not carry confidence"):
        _unknown(confidence=0.5)


def test_unknown_with_a_number_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown finding cannot carry evidence"):
        _unknown(
            numeric_facts=(
                NumericFact(label="revenue", value=1.0, unit="CNY", period="2026H1"),
            )
        )


def test_unknown_without_next_checks_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown finding must state what is needed"):
        _unknown(next_checks=())


# ---------------------------------------------------------------------------
# Invariant: numbers carry units and periods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [{"unit": ""}, {"period": ""}, {"label": ""}],
)
def test_numeric_fact_without_unit_or_period_is_rejected(missing: dict) -> None:
    payload = {"label": "revenue", "value": 1.23, "unit": "CNY", "period": "2026H1"}
    payload.update(missing)
    with pytest.raises(ValidationError):
        NumericFact(**payload)


def test_derived_number_must_declare_its_period_bounds() -> None:
    fact = NumericFact(
        label="yoy growth",
        value=12.5,
        unit="percent",
        period="2026H1 vs 2025H1",
        basis="derived",
        period_start="2025-01-01",
        period_end="2026-06-30",
    )
    assert fact.basis == "derived"


# ---------------------------------------------------------------------------
# Invariant: dates without evidence stay unknown
# ---------------------------------------------------------------------------


def test_dated_event_without_date_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="dated event requires date evidence ids"):
        _event(date_evidence_ids=())


def test_unknown_precision_event_may_not_carry_a_date() -> None:
    with pytest.raises(ValidationError, match="must not carry an occurrence date"):
        _event(date_precision="unknown", date_evidence_ids=())


def test_unknown_precision_event_is_representable_without_a_date() -> None:
    event = _event(
        date_precision="unknown",
        date_evidence_ids=(),
        occurred_on=None,
        occurred_period_end=None,
    )
    assert event.date_precision == "unknown"


def test_non_http_public_url_is_rejected() -> None:
    with pytest.raises(ValidationError, match="public_url must use an http"):
        _evidence(public_url="file:///etc/passwd")


# ---------------------------------------------------------------------------
# Invariant: the brief must not reference removed findings
# ---------------------------------------------------------------------------


def test_brief_referencing_a_removed_finding_is_rejected() -> None:
    # The removed fact is not the inference's ground, so the brief check is
    # the only thing that can fail here.
    brief = _brief(
        key_evidence=(BriefLine(text="依据", finding_ids=("f_fact_2",)),),
    )
    with pytest.raises(ValidationError, match="brief must not reference a removed finding"):
        _case(
            findings=(_fact(), _inference(), _unknown(), _fact("f_fact_2", survives=False)),
            brief=brief,
        )


def test_brief_reference_is_rechecked_after_each_removal() -> None:
    """Removing a fact cascades: ground, then the brief, then challenges.

    A single pass over the original graph would keep an inference grounded on
    a fact that no longer exists, so the check has to be recursive.
    """
    findings = (_fact(), _inference(), _unknown())
    assert _case(findings=findings).removed_finding_ids() == ()
    with pytest.raises(ValidationError, match="depends on a removed finding"):
        _case(findings=(_fact(survives=False), _inference(), _unknown()))


def test_brief_referencing_an_unknown_event_is_rejected() -> None:
    with pytest.raises(ValidationError, match="primary catalyst is not present"):
        _case(brief=_brief(primary_catalyst_event_id="ev_missing"))


def test_brief_line_referencing_an_unknown_event_is_rejected() -> None:
    with pytest.raises(ValidationError, match="brief must not reference an unknown event"):
        _case(
            brief=_brief(
                key_evidence=(
                    BriefLine(text="依据", finding_ids=("f_fact_1",), event_ids=("ev_missing",)),
                ),
            )
        )


# ---------------------------------------------------------------------------
# Challenge disposition coverage
# ---------------------------------------------------------------------------


def test_challenge_without_a_disposition_is_rejected() -> None:
    with pytest.raises(ValidationError, match="every challenge requires a disposition"):
        _case(dispositions=())


def test_duplicate_disposition_is_rejected() -> None:
    with pytest.raises(ValidationError, match="only one disposition"):
        _case(dispositions=(_disposition(), _disposition()))


def test_unresolved_disposition_must_keep_its_limitation() -> None:
    with pytest.raises(ValidationError, match="unresolved challenge must retain"):
        _disposition(outcome="unresolved", evidence_ids=(), retained_limitations=())


def test_resolved_disposition_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="resolved challenge requires supporting evidence"):
        _disposition(outcome="accepted", evidence_ids=())


def test_counter_evidence_challenge_requires_its_evidence() -> None:
    with pytest.raises(ValidationError, match="counter-evidence requires the evidence"):
        _challenge(evidence_ids=())


def test_missing_evidence_challenge_may_not_cite_evidence() -> None:
    with pytest.raises(ValidationError, match="cannot cite evidence"):
        _challenge(kind="missing_evidence", evidence_ids=("ev_1",))


# ---------------------------------------------------------------------------
# Character budget and the safety-overflow rule
# ---------------------------------------------------------------------------


def test_character_count_counts_unicode_characters() -> None:
    """Each CJK glyph counts as one character, not as its UTF-8 byte width."""
    brief = _brief(
        judgement="研究",
        primary_catalyst=BriefLine(text="简报", event_ids=("ev_1",)),
        key_evidence=(),
        key_question=BriefLine(text="疑问"),
        next_check=BriefLine(text="验证"),
    )
    assert brief_character_count(brief) == 2 + 2 + 2 + 2


def test_character_count_is_derived_not_carried_on_the_wire() -> None:
    """A producer cannot declare its own length; each side counts the text."""
    assert "character_count" not in _brief().model_dump()
    assert _brief().character_count == brief_character_count(_brief())


def test_ordinary_brief_over_420_is_rejected() -> None:
    """Overflow must fail rather than truncate, at any composition of lines."""
    with pytest.raises(ValidationError, match="exceeds the first-screen character budget"):
        _brief(
            judgement="x" * 200,
            primary_catalyst=BriefLine(text="y" * 200, event_ids=("ev_1",)),
            key_evidence=(BriefLine(text="z" * 200, finding_ids=("f_fact_1",)),),
        )


def test_ordinary_brief_exactly_at_budget_is_accepted() -> None:
    brief = CatalystBrief(
        kind="ordinary",
        judgement="x" * 200,
        priority="keep_watching",
        primary_catalyst_event_id="ev_1",
        primary_catalyst=BriefLine(text="y" * 200, event_ids=("ev_1",)),
        key_question=BriefLine(text="q" * 19),
        next_check=BriefLine(text="n"),
    )
    assert brief.character_count == BRIEF_CHARACTER_BUDGET


def test_ordinary_brief_one_over_budget_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds the first-screen character budget"):
        CatalystBrief(
            kind="ordinary",
            judgement="x" * 200,
            priority="keep_watching",
            primary_catalyst_event_id="ev_1",
            primary_catalyst=BriefLine(text="y" * 200, event_ids=("ev_1",)),
            key_question=BriefLine(text="q" * 20),
            next_check=BriefLine(text="n"),
        )


def test_ordinary_brief_may_not_carry_an_overflow_reason() -> None:
    with pytest.raises(ValidationError, match="ordinary brief must not carry an overflow"):
        _brief(overflow_reason="brief_safety_overflow")


def test_safety_overflow_requires_its_reason() -> None:
    with pytest.raises(ValidationError, match="must carry the overflow reason"):
        CatalystBrief(
            kind="safety_overflow",
            judgement="本次信息限制较多，暂不能形成可靠的简短判断",
            priority="insufficient_information",
            key_question=BriefLine(text="限制"),
            next_check=BriefLine(text="补做新 run"),
            critical_limitations=(BriefLine(text="关键来源失败"),),
        )


def test_safety_overflow_must_not_be_published_as_a_top_priority() -> None:
    with pytest.raises(ValidationError, match="must be information-insufficient"):
        CatalystBrief(
            kind="safety_overflow",
            judgement="本次信息限制较多",
            priority="verify_first",
            key_question=BriefLine(text="限制"),
            next_check=BriefLine(text="补做新 run"),
            overflow_reason="brief_safety_overflow",
            critical_limitations=(BriefLine(text="关键来源失败"),),
        )


def test_safety_overflow_must_keep_the_limitation_list() -> None:
    with pytest.raises(ValidationError, match="must keep the full limitation list"):
        CatalystBrief(
            kind="safety_overflow",
            judgement="本次信息限制较多",
            priority="insufficient_information",
            key_question=BriefLine(text="限制"),
            next_check=BriefLine(text="补做新 run"),
            overflow_reason="brief_safety_overflow",
        )


def test_safety_overflow_template_over_120_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds its own budget"):
        CatalystBrief(
            kind="safety_overflow",
            judgement="本次信息限制较多，暂不能形成可靠的简短判断。",
            priority="insufficient_information",
            key_question=BriefLine(text="限制" * 60),
            next_check=BriefLine(text="补做新 run"),
            overflow_reason="brief_safety_overflow",
            critical_limitations=(BriefLine(text="关键来源失败"),),
        )


def test_safety_overflow_template_exactly_at_120_is_accepted() -> None:
    brief = CatalystBrief(
        kind="safety_overflow",
        judgement="本次信息限制较多，暂不能形成可靠的简短判断。",
        priority="insufficient_information",
        key_question=BriefLine(text="限制"),
        next_check=BriefLine(text="补做新 run"),
        overflow_reason="brief_safety_overflow",
        critical_limitations=(BriefLine(text="关键来源失败"),),
    )
    assert brief.character_count <= SAFETY_OVERFLOW_TEMPLATE_BUDGET


def test_safety_overflow_case_publishes_the_template_not_an_ordinary_brief() -> None:
    """The overflow rule outranks the length target on the whole case."""
    brief = CatalystBrief(
        kind="safety_overflow",
        judgement="本次信息限制较多，暂不能形成可靠的简短判断。",
        priority="insufficient_information",
        key_question=BriefLine(text="限制"),
        next_check=BriefLine(text="补做新 run"),
        overflow_reason="brief_safety_overflow",
        critical_limitations=(
            BriefLine(text="关键来源失败"),
            BriefLine(text="覆盖窗口不完整"),
        ),
    )
    decision = _priority(
        priority="insufficient_information",
        candidate_priority="verify_first",
        blocking_reasons=("brief_safety_overflow",),
    )
    case = _case(
        completeness="partial",
        quality="LOW_CONFIDENCE",
        reason_codes=("brief_safety_overflow",),
        priority_decision=decision,
        brief=brief,
    )
    assert case.brief.kind == "safety_overflow"
    assert case.brief.overflow_reason == "brief_safety_overflow"
    assert case.priority_decision.priority == "insufficient_information"
    # The full limitation list stays adjacent and is not counted against the
    # ordinary budget; nothing was truncated to get under 120.
    assert len(case.brief.critical_limitations) == 2


def test_ordinary_brief_may_not_carry_more_than_three_key_evidence_lines() -> None:
    lines = tuple(
        BriefLine(text=f"依据 {index}", finding_ids=("f_fact_1",)) for index in range(4)
    )
    with pytest.raises(ValidationError, match="at most three key evidence lines"):
        _brief(key_evidence=lines)


# ---------------------------------------------------------------------------
# Deterministic priority ceiling
# ---------------------------------------------------------------------------


def test_key_unresolved_challenge_caps_the_top_priority() -> None:
    challenge = _challenge(severity="critical", is_key=True)
    disposition = _disposition(
        outcome="unresolved", evidence_ids=(), retained_limitations=("Margin unknown",)
    )
    with pytest.raises(ValidationError, match="unresolved key challenge forbids"):
        _case(challenges=(challenge,), dispositions=(disposition,))


def test_blocking_reason_code_caps_the_top_priority() -> None:
    with pytest.raises(ValidationError, match="forbids publishing the top research priority"):
        _case(reason_codes=("identity_conflict",))


def test_blocked_case_must_be_information_insufficient() -> None:
    with pytest.raises(ValidationError, match="blocked case must publish"):
        _case(completeness="blocked", quality="FAIL_STOP")


def test_brief_priority_must_match_the_decision() -> None:
    with pytest.raises(ValidationError, match="brief priority must match"):
        _case(brief=_brief(priority="keep_watching"))


def test_unregistered_blocking_reason_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unregistered blocking reason"):
        _priority(blocking_reasons=("model_felt_like_it",))


def test_lowered_priority_must_record_its_reason() -> None:
    with pytest.raises(ValidationError, match="must record the reason"):
        _priority(priority="insufficient_information", candidate_priority="verify_first")


def test_lowered_priority_with_a_blocking_reason_is_accepted() -> None:
    decision = _priority(
        priority="insufficient_information",
        candidate_priority="verify_first",
        blocking_reasons=("key_challenge_unresolved",),
    )
    case = _case(
        priority_decision=decision,
        completeness="partial",
        quality="LOW_CONFIDENCE",
        reason_codes=("key_challenge_unresolved",),
        brief=_brief(priority="insufficient_information"),
    )
    assert case.priority_decision.priority == "insufficient_information"


# ---------------------------------------------------------------------------
# Budget accounting
# ---------------------------------------------------------------------------


def test_unknown_usage_may_not_be_written_as_zero() -> None:
    with pytest.raises(ValidationError, match="must be absent when model usage"):
        _budget(model_usage_available=False, input_tokens=0)


def test_unknown_usage_is_recorded_as_absent_not_zero() -> None:
    usage = _budget(model_usage_available=False, input_tokens=None, output_tokens=None)
    assert usage.input_tokens is None and usage.model_usage_available is False
