"""Prompts must say when a report was never produced.

An empty report interpolated into a labelled section presents an absence as a
blank finding, and the reading agent fills it from nothing — the same failure
mode an empty opponent argument used to cause (#1176). A ``None`` report is
worse: it renders as the literal text ``None`` on the opening turn and raises
inside the bounded-excerpt helper on a rebuttal.

Upstream's `2ddfe4c` also fixed a fundamentals brief reaching the model as a
Python tuple and analysts emitting a trade call nothing reads; this fork already
covered both (verified: the bundle is a JSON string, and no analyst emits a
transaction proposal), so only the absent-report marker was missing here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tradingagents.agents.managers.research_manager as research_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.utils.agent_utils import report_or_absent

_ABSENT = "not an empty finding"


@pytest.mark.unit
@pytest.mark.parametrize("empty", ["", "   ", None])
def test_report_or_absent_marks_a_missing_report(empty):
    out = report_or_absent(empty, "market")

    assert "No market report in this run" in out
    assert _ABSENT in out


@pytest.mark.unit
def test_report_or_absent_passes_a_real_report_through():
    assert report_or_absent("  a real finding  ", "market") == "a real finding"


def _capturing_llm(captured: dict) -> MagicMock:
    """LLM that records the prompt handed to its free-text invoke."""
    llm = MagicMock()
    llm.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or MagicMock(content="reply")
    )
    return llm


def _debate_state(**reports):
    state = {
        "company_of_interest": "AAPL",
        "investment_debate_state": {
            "history": "h",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 1,
        },
    }
    state.update(reports)
    return state


@pytest.mark.unit
def test_bull_prompt_marks_absent_reports_instead_of_blank_sections():
    captured: dict = {}
    node = create_bull_researcher(_capturing_llm(captured))

    node(_debate_state(
        market_report="", sentiment_report=None, news_report="", fundamentals_report=""
    ))

    prompt = captured["prompt"]
    assert "No market report in this run" in prompt
    assert "No sentiment report in this run" in prompt
    assert "No news report in this run" in prompt
    assert "No fundamentals report in this run" in prompt
    assert _ABSENT in prompt


@pytest.mark.unit
def test_bear_prompt_marks_absent_reports_and_survives_a_none_report():
    captured: dict = {}
    node = create_bear_researcher(_capturing_llm(captured))

    # A rebuttal turn is the strict case: the bounded-excerpt helper would raise
    # on None before the marker existed.
    state = _debate_state(
        market_report=None, sentiment_report="", news_report=None,
        fundamentals_report="FUNDAMENTALS-PASSTHROUGH",
    )
    state["investment_debate_state"]["current_response"] = "bull case"

    node(state)

    prompt = captured["prompt"]
    assert "No market report in this run" in prompt
    assert "No news report in this run" in prompt
    assert "FUNDAMENTALS-PASSTHROUGH" in prompt  # a real report passes through


@pytest.mark.unit
def test_research_manager_learning_prompt_marks_absent_reports(monkeypatch):
    """The production research modes interpolate the same four reports."""
    captured: dict = {}
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or None
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    monkeypatch.setattr(research_manager, "bind_structured", lambda *a, **k: structured)

    create_research_manager(llm)(_debate_state(
        mode="company_research",
        market_report="",
        fundamentals_report=None,
        news_report="",
        sentiment_report="",
    ))

    prompt = captured["prompt"]
    assert "No market report in this run" in prompt
    assert "No fundamentals report in this run" in prompt
    assert "No news report in this run" in prompt
    assert "No sentiment report in this run" in prompt


@pytest.mark.unit
def test_research_manager_prompt_states_the_output_shape(monkeypatch):
    """A provider without structured output never sees the Pydantic schema, so
    the required top-level fields must be stated in the prompt itself."""
    captured: dict = {}
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: (
        captured.__setitem__("prompt", prompt) or None
    )
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    monkeypatch.setattr(research_manager, "bind_structured", lambda *a, **k: structured)

    create_research_manager(llm)(_debate_state(
        mode="company_research",
        market_report="m", fundamentals_report="f", news_report="n", sentiment_report="s",
    ))

    prompt = captured["prompt"]
    assert "输出形状" in prompt
    for field in (
        "research_tilt", "confidence", "facts", "inferences", "unknowns",
        "upside", "base", "downside", "catalysts", "invalidation_conditions",
        "next_review", "holding_thesis_assessment",
    ):
        assert field in prompt, field
