"""Local-only checks for the structural config validator."""

import pytest

from tradingagents.default_config import DEFAULT_CONFIG, validate_config


def test_default_config_is_valid():
    assert validate_config(DEFAULT_CONFIG) == []


def test_missing_provider_is_detected():
    assert any("llm_provider" in p for p in validate_config({"llm_provider": ""}))


def test_non_positive_round_count_is_detected():
    assert any(
        "max_debate_rounds" in p
        for p in validate_config({**DEFAULT_CONFIG, "max_debate_rounds": 0})
    )


def test_non_boolean_switch_is_detected():
    assert any(
        "checkpoint_enabled" in p
        for p in validate_config({**DEFAULT_CONFIG, "checkpoint_enabled": "yes"})
    )


def test_invalid_temperature_is_detected():
    assert any(
        "temperature" in p
        for p in validate_config({**DEFAULT_CONFIG, "temperature": "hot"})
    )


def test_negative_tool_budget_is_detected():
    assert any(
        "max_tool_calls_per_turn" in p
        for p in validate_config({**DEFAULT_CONFIG, "max_tool_calls_per_turn": -1})
    )


def test_invalid_deepseek_thinking_is_detected():
    assert any(
        "deepseek_thinking" in p
        for p in validate_config({**DEFAULT_CONFIG, "deepseek_thinking": "maybe"})
    )


def test_valid_deepseek_thinking_choices_pass():
    for value in ("enabled", "disabled", None, ""):
        assert validate_config({**DEFAULT_CONFIG, "deepseek_thinking": value}) == []


def test_invalid_deepseek_effort_is_detected():
    assert any(
        "deepseek_reasoning_effort" in p
        for p in validate_config({**DEFAULT_CONFIG, "deepseek_reasoning_effort": "ultra"})
    )


def test_valid_deepseek_effort_choices_pass():
    for value in ("low", "medium", "high", "xhigh", "max", None):
        assert validate_config({**DEFAULT_CONFIG, "deepseek_reasoning_effort": value}) == []


def test_negative_max_tokens_is_detected():
    assert any(
        "llm_max_tokens" in p
        for p in validate_config({**DEFAULT_CONFIG, "llm_max_tokens": -5})
    )


def test_max_tokens_passes():
    assert validate_config({**DEFAULT_CONFIG, "llm_max_tokens": 8192}) == []


def test_graph_init_rejects_invalid_config_before_llm_creation():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = {
        "llm_provider": "openai",
        "deep_think_llm": "model",
        "quick_think_llm": "model",
        "data_vendors": {"core_stock_apis": "bogus_vendor"},
    }
    with pytest.raises(ValueError, match="bogus_vendor"):
        graph._validate_effective_config()


def test_graph_init_accepts_default_config():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = object.__new__(TradingAgentsGraph)
    graph.config = DEFAULT_CONFIG
    assert graph._validate_effective_config() is None
