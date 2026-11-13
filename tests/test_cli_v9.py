"""The terminal is an adapter for the current Insight research workflow."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

import cli.config as cli_config
from cli.main import app


def test_config_builds_current_request_without_classic_scheduling(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-placeholder")
    request = cli_config.build_request(
        {
            "llm": {"provider": "deepseek", "quick_think_llm": "quick", "deep_think_llm": "deep"},
            "run": {"ticker": "002130", "research_question": "经营改善是否持续？", "output_language": "Chinese"},
        }
    )
    assert request.ticker == "002130.SZ"
    assert request.research_profile == "evidence_v1"
    assert request.mode == "company_research"
    assert request.research_question == "经营改善是否持续？"
    assert request.analysis_date == datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    assert request.effective_config["quick_think_llm"] == "quick"
    assert request.effective_config["deep_think_llm"] == "deep"


def test_explicit_terminal_options_override_json_without_mutating_it():
    local = {"llm": {"provider": "deepseek", "quick_think_llm": "json-quick", "deep_think_llm": "json-deep"},
             "run": {"ticker": "600519", "deepseek_reasoning_effort": "max"}}
    request = cli_config.build_request(local, ticker="002130", analysis_date="2026-10-30", quick_model="flag-quick")
    assert request.ticker == "002130.SZ"
    assert request.analysis_date == "2026-10-30"
    assert request.effective_config["quick_think_llm"] == "flag-quick"
    assert request.effective_config["deep_think_llm"] == "json-deep"
    assert request.effective_config["deepseek_reasoning_effort"] == "max"
    assert local["llm"]["quick_think_llm"] == "json-quick"


@pytest.mark.parametrize("ticker", ["AAPL", "BTC-USD", "0700.HK"])
def test_terminal_rejects_markets_unsupported_by_current_research(ticker):
    with pytest.raises(ValueError, match="A.share|A 股"):
        cli_config.build_request({}, ticker=ticker)


@pytest.mark.parametrize("key,value", [("research_depth", 5), ("save_report", False), ("llm_max_retries", 6)])
def test_obsolete_config_is_not_silently_accepted(key, value):
    with pytest.raises(ValueError, match=key):
        cli_config.build_request({"run": {"ticker": "002130", key: value}})


def test_chatgpt_requires_an_account_before_research():
    with pytest.raises(ValueError, match="chatgpt_account_ref"):
        cli_config.build_request({"llm": {"provider": "chatgpt", "quick_think_llm": "model", "deep_think_llm": "model"}}, ticker="002130")


def test_changing_provider_does_not_reuse_another_providers_default_models():
    request = cli_config.build_request({}, ticker="002130", provider="openai")
    assert request.effective_config["quick_think_llm"].startswith("gpt-")
    assert request.effective_config["deep_think_llm"].startswith("gpt-")


def test_bailian_cli_selects_research_models():
    request = cli_config.build_request({}, ticker="002130", provider="bailian")
    assert request.effective_config["quick_think_llm"] == "deepseek-v4.1-flash-1017"
    assert request.effective_config["deep_think_llm"] == "kimi-k3.1-pro"


def test_jev_verification_requires_openrouter_key_and_reaches_config(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-placeholder")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    local = {"run": {"jev_verification_enabled": True, "jev_model": "typesafe/jev-1.14"}}
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        cli_config.build_request(local, ticker="002130")

    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-openrouter-key")
    config = cli_config.build_request(local, ticker="002130").effective_config
    assert config["jev_verification_enabled"] is True
    assert config["jev_model"] == "typesafe/jev-1.14"


def test_resume_endpoint_credentials_are_runtime_only_and_identity_cannot_change():
    from types import SimpleNamespace

    from cli.research import _saved_request
    from tradingagents.execution.config_identity import prepare_effective_config

    snapshot = SimpleNamespace(ticker="002130.SZ", analysis_date="2026-10-30", metadata={
        "native_workflow_version": "evidence-production-v9",
        "effective_config": prepare_effective_config({"backend_url": "https://gateway.example/v1?key=offline-secret"}),
    })
    request = _saved_request(snapshot, "https://gateway.example/v1?key=offline-rotated")
    assert request.effective_config["backend_url"].endswith("key=offline-rotated")
    assert "offline-secret" not in json.dumps(snapshot.metadata)
    assert "offline-rotated" not in json.dumps(snapshot.metadata)
    with pytest.raises(ValueError, match="端点"):
        _saved_request(snapshot, "https://different.example/v1")


def test_local_keys_are_available_to_providers_without_entering_request(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / "local.json"
    path.write_text(json.dumps({"api_keys": {"DEEPSEEK_API_KEY": "offline-secret"}, "run": {"ticker": "002130"}}))
    request = cli_config.build_request(cli_config.load_cli_config(path))
    import os

    assert os.environ["DEEPSEEK_API_KEY"] == "offline-secret"
    assert "offline-secret" not in json.dumps(dict(request.effective_config))


def test_analysis_help_describes_current_research_and_resume():
    result = CliRunner().invoke(app, ["analyze", "--help"], env={"COLUMNS": "160"})
    assert result.exit_code == 0, result.output
    assert "--ticker" in result.output
    assert "--resume" in result.output
    assert "V9" in result.output


@pytest.mark.parametrize("position", ["root", "analyze"])
def test_config_option_reaches_analysis_from_either_command_position(tmp_path, monkeypatch, position):
    import cli.main as terminal

    supplied = tmp_path / "custom.json"
    supplied.write_text("{}")
    options = []
    monkeypatch.setattr(terminal, "run_analysis", lambda **kw: options.append(kw))
    args = ["--config", str(supplied), "analyze"] if position == "root" else ["analyze", "--config", str(supplied)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert options[0]["config"] == supplied


def test_bad_ticker_exits_before_provider_dispatch(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    result = CliRunner().invoke(app, ["analyze", "--ticker", "AAPL", "--config", str(path)])
    assert result.exit_code != 0
    assert "A 股" in result.output or "A-share" in result.output


def test_terminal_publishes_real_insight_report_and_completed_resume_is_read_only(tmp_path, monkeypatch):
    from cli.research import run_research
    from tests.test_insight_protocol import proposal
    from tests.v9_fixtures import Session, Sources, setup
    from tradingagents.execution.native_runner import NativeRunner
    from tradingagents.runtime.store import RunStore

    _, request, _, _, _, _ = setup(tmp_path / "fixture", monkeypatch, enabled=False)
    calls = []

    def call(stage, context, *, phase="main"):
        calls.append(stage)
        if stage in {"operating_quality", "event_context", "market_context"}:
            return {"insights": [proposal(evidence_refs=[context["evidence"][0]["ref"]])]}
        if stage == "challenge":
            return {"reviews": [{"target": item["ref"], "concern": None,
                                 "reasoning": "审阅后未发现有效反证。", "evidence_refs": []}
                                for item in context["insights"]]}
        if stage == "synthesis":
            return {"judgement": "现有证据支持有边界的判断。", "stance": "neutral",
                    "insight_refs": [context["insights"][0]["ref"]], "reasoning": "参考已保存专项观点。",
                    "limitations": "部分资料仍缺失。", "next_check": "关注后续披露。"}
        raise AssertionError(stage)

    def factory(observer):
        return NativeRunner(observer, sources_factory=Sources, caller_factory=lambda **kw: call,
                            search_session_factory=Session)

    root = tmp_path / "cli"
    result = run_research(request, root, runner_factory=factory)
    assert "公司研究" in result.report.read_text()
    assert result.record["schema_version"] == "insight-research-v1"
    snapshot = RunStore(root).read_snapshot(result.run_id)
    assert snapshot.status == "completed"
    assert snapshot.final_report_artifact_id
    count = len(calls)
    resumed = run_research(None, root, resume_run_id=result.run_id, runner_factory=factory)
    assert resumed.record == result.record
    assert len(calls) == count
