"""The first-screen character budget, measured on the shared cross-language fixture.

Design section 4.3 caps ordinary first-screen body text at 420 Unicode
characters (200-300 is the target; under-filling is fine, padding is not), and
exempts nothing from the count except navigation, field labels, the company
name, and time metadata -- none of which exist in ``CatalystBrief`` at all.

The fixture at ``frontend/src/test/fixtures/catalyst-brief-budget.json`` is
loaded unchanged by this module and by
``frontend/src/test/catalystBriefBudget.test.ts``. Both sides must compute the
same integer for the same body text; if the two ever disagree, the frontend
would be enforcing a budget the backend did not apply, and the reader would
see a differently-truncated page from the one that was published.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import (
    BRIEF_CHARACTER_BUDGET,
    SAFETY_OVERFLOW_TEMPLATE_BUDGET,
    CatalystBrief,
    brief_character_count,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "test"
    / "fixtures"
    / "catalyst-brief-budget.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _cases() -> list[tuple[str, dict, int]]:
    return [
        (case["name"], case["body"], case["expected_characters"])
        for case in _fixture()["cases"]
    ]


def test_fixture_pins_the_contract_budgets() -> None:
    data = _fixture()
    assert data["budget"] == BRIEF_CHARACTER_BUDGET
    assert data["safety_overflow_budget"] == SAFETY_OVERFLOW_TEMPLATE_BUDGET
    assert data["schema_version"] == "catalyst-research-case-v1"


@pytest.mark.parametrize(
    ("name", "body", "expected"),
    _cases(),
    ids=[case[0] for case in _cases()],
)
def test_backend_counts_the_same_characters_the_fixture_pins(
    name: str, body: dict, expected: int
) -> None:
    brief = CatalystBrief.model_validate(body)
    assert brief_character_count(brief) == expected, name


def test_every_ordinary_fixture_case_fits_the_budget() -> None:
    for name, body, expected in _cases():
        if body["kind"] != "ordinary":
            continue
        assert expected <= BRIEF_CHARACTER_BUDGET, name


def test_ordinary_fixture_case_sits_exactly_on_the_boundary() -> None:
    """The boundary case must actually be the boundary, or it proves nothing."""
    boundary = [
        body for name, body, _ in _cases() if name == "ordinary_exactly_at_budget"
    ]
    assert len(boundary) == 1
    assert brief_character_count(CatalystBrief.model_validate(boundary[0])) == (
        BRIEF_CHARACTER_BUDGET
    )


def test_safety_overflow_fixture_keeps_its_full_limitation_list() -> None:
    """The list is exempt from the ordinary budget, so nothing may be cut."""
    body = next(body for name, body, _ in _cases() if name == "safety_overflow")
    brief = CatalystBrief.model_validate(body)
    assert brief.character_count <= SAFETY_OVERFLOW_TEMPLATE_BUDGET
    assert len(brief.critical_limitations) == 4
    assert brief.overflow_reason == "brief_safety_overflow"
    assert brief.priority == "insufficient_information"


def test_ordinary_fixture_case_turns_into_the_overflow_template_when_it_overflows() -> None:
    """One character over the cap must not be published as an ordinary brief.

    The overflow case is the only legal response. Truncating the judgement or
    dropping the last risk to fit is exactly the failure the design forbids.
    """
    body = next(
        body for name, body, _ in _cases() if name == "ordinary_exactly_at_budget"
    )
    over = dict(body, judgement=body["judgement"] + "。")
    with pytest.raises(ValidationError, match="exceeds the first-screen character budget"):
        CatalystBrief.model_validate(over)


def test_ordinary_brief_cannot_dodge_the_budget_with_limitations() -> None:
    """The exemption belongs to the overflow template, not to ordinary briefs.

    If ordinary briefs could push their risks into ``critical_limitations``
    and stop counting them, the budget would stop binding on exactly the
    content that most needs to fit.
    """
    body = next(
        body for name, body, _ in _cases() if name == "ordinary_exactly_at_budget"
    )
    dodged = json.loads(json.dumps(body))
    dodged["judgement"] = "。"
    dodged["critical_limitations"] = [
        {"text": "x" * 200} for _ in range(3)
    ]
    with pytest.raises(ValidationError, match="exceeds the first-screen character budget"):
        CatalystBrief.model_validate(dodged)


def test_safety_overflow_budget_covers_the_code_template_only() -> None:
    """A long limitation list stays legal; a long template does not.

    The two budgets measure different things and the fixture makes the
    difference visible, so a frontend that counted the wrong set of strings
    would disagree with the backend on the same payload.
    """
    body = next(body for name, body, _ in _cases() if name == "safety_overflow")
    long_limitations = json.loads(json.dumps(body))
    long_limitations["critical_limitations"] = [
        {"text": f"限制 {index}：来源状态与覆盖完整性均未通过校验。"} for index in range(9)
    ]
    brief = CatalystBrief.model_validate(long_limitations)
    assert brief.character_count <= SAFETY_OVERFLOW_TEMPLATE_BUDGET
    assert len(brief.critical_limitations) == 9

    long_template = json.loads(json.dumps(body))
    long_template["judgement"] = "x" * 121
    with pytest.raises(ValidationError, match="exceeds its own budget"):
        CatalystBrief.model_validate(long_template)
