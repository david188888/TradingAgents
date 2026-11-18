"""The research adapters must admit the same point-in-time inputs."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from cli.config import build_request
from tradingagents.web.api import ApiBoundaryError, _analysis_request
from tradingagents.web.manager import _complete_request
from tradingagents.web.schemas import RunCreateRequest


@pytest.mark.parametrize("field,model", [("quick_think_llm", "not-in-catalog"),
                                        ("deep_think_llm", "not-in-catalog"),
                                        ("challenge", "not-in-catalog"),
                                        ("quick_think_llm", "custom")])
def test_cli_and_web_reject_the_same_unsupported_openai_models(monkeypatch, field, model):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    llm = {"provider": "openai", "quick_think_llm": "gpt-5.6-luna", "deep_think_llm": "gpt-5.6"}
    body = {"ticker": "002130", "llm_provider": "openai", "quick_think_llm": "gpt-5.6-luna",
            "deep_think_llm": "gpt-5.6"}
    if field == "challenge":
        stages = {"challenge": {"provider": "openai", "model": model}}
        llm["stage_models"] = stages
        body["stage_models"] = stages
    else:
        llm[field] = model
        body[field] = model
    with pytest.raises(ValueError):
        build_request({"llm": llm}, ticker="002130")
    with pytest.raises(ApiBoundaryError, match="not available"):
        _analysis_request(RunCreateRequest(**body), {"OPENAI_API_KEY": "offline"})


def test_cli_and_web_allow_custom_model_for_supported_provider(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cli = build_request({"llm": {"provider": "deepseek", "quick_think_llm": "my-model",
                                  "deep_think_llm": "my-model"}}, ticker="002130")
    web, _ = _analysis_request(RunCreateRequest(ticker="002130", llm_provider="deepseek",
        quick_think_llm="my-model", deep_think_llm="my-model"), {"DEEPSEEK_API_KEY": "offline"})
    assert cli.effective_config["quick_think_llm"] == web.effective_config["quick_think_llm"] == "my-model"


@pytest.mark.parametrize("provider", ["azure", "openrouter"])
def test_cli_requests_explicit_model_when_provider_has_no_default_catalog(provider):
    with pytest.raises(ValueError, match="显式配置"):
        build_request({}, ticker="002130", provider=provider)


@pytest.mark.parametrize("stage_only", [False, True])
def test_chatgpt_models_unavailable_to_account_are_rejected_before_cli_run(tmp_path, monkeypatch, stage_only):
    import json

    from typer.testing import CliRunner

    from cli.main import app
    from tradingagents.llm_clients.chatgpt_errors import ChatGPTError

    class Auth:
        def access(self, ref, *, for_inference=False):
            return "offline", 1

        def models(self, ref):
            return {"models": [{"id": "available-model"}]}

    monkeypatch.setattr("tradingagents.llm_clients.chatgpt_auth.ChatGPTAuth", Auth)
    monkeypatch.setattr("cli.research.run_research", lambda *args, **kwargs: pytest.fail("run was started"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline")
    ref = "cg_" + "a" * 32
    path = tmp_path / "config.json"
    if stage_only:
        stage = {"synthesis": {"provider": "chatgpt", "model": "unavailable-model"}}
        llm = {"provider": "deepseek", "chatgpt_account_ref": ref, "stage_models": stage}
        body = {"llm_provider": "deepseek", "quick_think_llm": "deepseek-flash",
                "deep_think_llm": "deepseek-flash", "stage_models": stage}
    else:
        llm = {"provider": "chatgpt", "chatgpt_account_ref": ref,
               "quick_think_llm": "unavailable-model", "deep_think_llm": "available-model"}
        body = {"llm_provider": "chatgpt", "quick_think_llm": "unavailable-model",
                "deep_think_llm": "available-model"}
    path.write_text(json.dumps({"llm": llm}))
    result = CliRunner().invoke(app, ["analyze", "--ticker", "002130", "--config", str(path)])
    assert result.exit_code != 0
    assert "所选模型" in result.output
    with pytest.raises(ChatGPTError, match="所选模型"):
        _analysis_request(RunCreateRequest(ticker="002130", chatgpt_account_ref=ref, **body),
                          {"DEEPSEEK_API_KEY": "offline"}, chatgpt_auth=Auth())


@pytest.mark.parametrize("missing", ["AZURE_OPENAI_ENDPOINT", "OPENAI_API_VERSION"])
def test_azure_missing_configuration_is_rejected_before_cli_and_web_run(tmp_path, monkeypatch, missing):
    import json

    from typer.testing import CliRunner

    from cli.main import app

    environment = {"AZURE_OPENAI_API_KEY": "offline", "AZURE_OPENAI_ENDPOINT": "https://example.test",
                   "OPENAI_API_VERSION": "2025-01-01"}
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("cli.research.run_research", lambda *args, **kwargs: pytest.fail("run was started"))
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"llm": {"provider": "azure", "quick_think_llm": "deployment",
                                       "deep_think_llm": "deployment"}}))
    result = CliRunner().invoke(app, ["analyze", "--ticker", "002130", "--config", str(path)])
    assert result.exit_code != 0
    assert missing in result.output
    environment.pop(missing)
    with pytest.raises(ApiBoundaryError):
        _analysis_request(RunCreateRequest(ticker="002130", llm_provider="azure",
            quick_think_llm="deployment", deep_think_llm="deployment"), environment)


def test_future_cutoff_is_rejected_by_both_research_entries():
    future = (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        build_request({}, ticker="002130", analysis_date=future)
    with pytest.raises(ValidationError):
        RunCreateRequest(ticker="002130", analysis_date=future, llm_provider="deepseek",
                         quick_think_llm="deepseek-flash", deep_think_llm="deepseek-flash")


@pytest.mark.parametrize("stage_settings", [{"effort": "high"}, {"thinking": "disabled"}],
                         ids=["high-effort", "thinking-disabled"])
def test_equivalent_cli_and_web_inputs_freeze_the_same_research_config(monkeypatch, stage_settings):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    stages = {"challenge": {"provider": "deepseek", "model": "deepseek-v4-pro", **stage_settings}}
    cli = build_request({"llm": {"provider": "deepseek", "quick_think_llm": "deepseek-flash",
                                  "deep_think_llm": "deepseek-v4-pro", "stage_models": stages},
                         "run": {"research_question": "现金流如何？", "output_language": "Chinese"}},
                        ticker="002130", analysis_date="2026-10-28")
    web, _ = _analysis_request(RunCreateRequest(ticker="002130", analysis_date="2026-10-28",
        llm_provider="deepseek", quick_think_llm="deepseek-flash", deep_think_llm="deepseek-v4-pro",
        stage_models=stages, research_question="现金流如何？", output_language="Chinese"),
        {"DEEPSEEK_API_KEY": "offline"})
    web = _complete_request(web)
    assert cli == web


def test_equivalent_runs_publish_the_same_research_content(tmp_path, monkeypatch):
    from cli.research import run_research
    from scripts.e2e_server import InsightFixtureCaller, InsightFixtureSources
    from tests.web.test_v9_api import BODY, workbench
    from tradingagents.execution.native_runner import NativeRunner

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    request = build_request({"llm": {"provider": "deepseek", "quick_think_llm": "deepseek-v4-flash",
                                      "deep_think_llm": "deepseek-v4-pro"},
                             "run": {"output_language": "Chinese"}},
                            ticker=BODY["ticker"], analysis_date=BODY["analysis_date"], focus="客户结构如何？")
    def factory(observer):
        return NativeRunner(observer, sources_factory=InsightFixtureSources,
                            caller_factory=lambda **kwargs: InsightFixtureCaller())

    terminal = run_research(request, tmp_path / "cli", runner_factory=factory)
    with workbench(tmp_path / "web") as (client, manager, _store, _calls):
        response = client.post("/api/runs", json={**BODY, "research_question": "客户结构如何？"})
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        assert manager.wait(run_id, timeout=5).status == "completed"
        web = client.get(f"/api/runs/{run_id}/reader/record").json()["record"]
    for field in ("ticker", "schema_version", "stages", "gaps"):
        assert terminal.record[field] == web[field]
    for field in ("judgement", "stance", "reasoning", "limitations", "next_check"):
        assert terminal.record["synthesis"][field] == web["synthesis"][field]
    for record in (terminal.record, web):
        assert record["synthesis"]["insight_ids"] == [record["insights"][0]["insight_id"]]
    assert terminal.record["insights"][0]["proposal"] == web["insights"][0]["proposal"]
    assert terminal.record["insights"][0]["fact_ids"] == web["insights"][0]["fact_ids"]
    assert terminal.record["focus_question"] == web["focus_question"] == "客户结构如何？"
    assert terminal.record["focus_insights"][0]["proposal"] == web["focus_insights"][0]["proposal"]
    assert terminal.record["focus_insights"][0]["rendered"]["claim"] in terminal.report.read_text()
