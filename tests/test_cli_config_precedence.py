"""CLI config precedence (#976, #977).

An explicit environment override for the debate/risk round counts, or the
checkpoint flag, must win over the interactive research-depth selection — the CLI
must not clobber an env-configured value back to a prompt/flag default.
"""

from unittest import mock

import pytest

import cli.main as m
from cli.config import build_configured_selections

# Minimal selections dict shaped like get_user_selections()'s return value.
SELECTIONS = {
    "research_depth": 5,
    "shallow_thinker": "gpt-5.4-mini",
    "deep_thinker": "gpt-5.5",
    "backend_url": None,
    "llm_provider": "openai",
    "google_thinking_level": None,
    "openai_reasoning_effort": None,
    "anthropic_effort": None,
    "output_language": "English",
}


def test_local_json_efforts_reach_runtime_and_keep_copy(monkeypatch):
    monkeypatch.setattr(m, "validate_provider_api_key", lambda provider: None)
    local = {"llm": {"provider": "deepseek", "quick_think_llm": "deepseek-flash",
                      "deep_think_llm": "deepseek-flash"},
             "run": {"deepseek_thinking": "enabled", "deepseek_reasoning_effort": "max",
                     "deepseek_task_efforts": {"aux.news_cluster": "low"}}}
    selections = build_configured_selections(local, ticker="600519", analysis_date="2026-10-04")
    config = m._build_run_config(selections, checkpoint=None)
    assert config["deepseek_reasoning_effort"] == "max"
    assert config["deepseek_thinking"] == "enabled"
    assert config["deepseek_task_efforts"] == {"aux.news_cluster": "low"}
    local["run"]["deepseek_task_efforts"]["aux.news_cluster"] = "max"
    assert config["deepseek_task_efforts"] == {"aux.news_cluster": "low"}


def test_cli_absent_settings_keep_defaults_but_null_task_policy_is_not_hidden(monkeypatch):
    monkeypatch.setattr(m, "validate_provider_api_key", lambda provider: None)
    config = m._build_run_config({**SELECTIONS, "deepseek_thinking": None,
                                  "deepseek_reasoning_effort": None}, checkpoint=None)
    assert config["deepseek_reasoning_effort"] == m.DEFAULT_CONFIG["deepseek_reasoning_effort"]
    assert "deepseek_task_efforts" not in config
    config = m._build_run_config({**SELECTIONS, "deepseek_task_efforts": None}, checkpoint=None)
    assert config["deepseek_task_efforts"] is None


def test_research_depth_sets_both_rounds_without_env(monkeypatch):
    for var in ("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "TRADINGAGENTS_MAX_RISK_ROUNDS"):
        monkeypatch.delenv(var, raising=False)
    cfg = m._build_run_config(SELECTIONS, checkpoint=None)
    assert cfg["max_debate_rounds"] == 5
    assert cfg["max_risk_discuss_rounds"] == 5


def test_env_round_counts_win_over_selection(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")
    monkeypatch.setenv("TRADINGAGENTS_MAX_RISK_ROUNDS", "4")
    # DEFAULT_CONFIG already reflects the env (applied at import); emulate that.
    patched = dict(m.DEFAULT_CONFIG, max_debate_rounds=2, max_risk_discuss_rounds=4)
    with mock.patch.object(m, "DEFAULT_CONFIG", patched):
        cfg = m._build_run_config(SELECTIONS, checkpoint=None)
    assert cfg["max_debate_rounds"] == 2  # env value, not research_depth=5
    assert cfg["max_risk_discuss_rounds"] == 4


def test_partial_env_only_overrides_that_count(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "2")
    monkeypatch.delenv("TRADINGAGENTS_MAX_RISK_ROUNDS", raising=False)
    patched = dict(m.DEFAULT_CONFIG, max_debate_rounds=2)
    with mock.patch.object(m, "DEFAULT_CONFIG", patched):
        cfg = m._build_run_config(SELECTIONS, checkpoint=None)
    assert cfg["max_debate_rounds"] == 2  # env wins
    assert cfg["max_risk_discuss_rounds"] == 5  # falls through to research_depth


def test_checkpoint_none_preserves_env_default():
    patched = dict(m.DEFAULT_CONFIG, checkpoint_enabled=True)  # e.g. env-enabled
    with mock.patch.object(m, "DEFAULT_CONFIG", patched):
        cfg = m._build_run_config(SELECTIONS, checkpoint=None)
    assert cfg["checkpoint_enabled"] is True  # not clobbered back to False


@pytest.mark.parametrize("flag", [True, False])
def test_checkpoint_flag_overrides_env(flag):
    patched = dict(m.DEFAULT_CONFIG, checkpoint_enabled=not flag)
    with mock.patch.object(m, "DEFAULT_CONFIG", patched):
        cfg = m._build_run_config(SELECTIONS, checkpoint=flag)
    assert cfg["checkpoint_enabled"] is flag
