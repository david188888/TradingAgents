"""Stage model routing: role over group over the legacy tiers, one validated policy."""

import pytest

from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs
from tradingagents.llm_clients.stage_models import (
    resolve_stage_model,
    stage_model_overrides,
    stage_model_providers,
)

BASE = {"llm_provider": "deepseek", "quick_think_llm": "deepseek-flash", "deep_think_llm": "deepseek-v4-pro",
        "backend_url": "https://proxy.example/v1"}
POLICY = {
    "specialist": {"provider": "deepseek", "model": "deepseek-v4-pro"},
    "market_context": {"provider": "qwen-cn", "model": "qwen3.7-plus"},
    "challenge": {"provider": "anthropic", "model": "claude-opus-4-8", "effort": "max"},
}


def test_role_then_group_then_legacy_tiers_and_responses_follow_their_author():
    config = {**BASE, "stage_models": POLICY}
    assert resolve_stage_model(config, "market_context")[1] == "qwen3.7-plus"
    assert resolve_stage_model(config, "response_market_context")[1] == "qwen3.7-plus"
    assert resolve_stage_model(config, "operating_quality")[1] == "deepseek-v4-pro"
    assert resolve_stage_model(config, "response_event_context")[1] == "deepseek-v4-pro"
    assert resolve_stage_model(config, "synthesis") == (config, "deepseek-v4-pro")
    assert resolve_stage_model(config, "focus_response") == (config, "deepseek-flash")
    assert resolve_stage_model(BASE, "challenge") == (BASE, "deepseek-flash")


def test_cross_provider_stage_drops_foreign_endpoint_and_maps_effort():
    config = {**BASE, "stage_models": POLICY}
    call, model = resolve_stage_model(config, "challenge")
    assert (call["llm_provider"], model, call["backend_url"]) == ("anthropic", "claude-opus-4-8", None)
    assert provider_llm_kwargs(call)["effort"] == "max"
    same, _ = resolve_stage_model(config, "event_context")
    assert same["backend_url"] == "https://proxy.example/v1"
    assert stage_model_providers(config) == ("deepseek", "qwen-cn", "anthropic")


@pytest.mark.parametrize("policy,message", [
    ([], "must be a mapping"),
    ({"challenge": {"provider": [], "model": "x"}}, "unsupported provider"),
    ({"challenge": {"provider": "deepseek", "model": "x", "effort": []}}, "unsupported for deepseek"),
    ({"risk": {"provider": "deepseek", "model": "x"}}, "unknown stage"),
    ({"challenge": {"provider": "nope", "model": "x"}}, "unsupported provider"),
    ({"challenge": {"provider": "deepseek", "model": " "}}, "model is required"),
    ({"challenge": {"provider": "qwen", "model": "x", "effort": "high"}}, "unsupported for qwen"),
    ({"challenge": {"provider": "deepseek", "model": "x", "base": "y"}}, "accepts only"),
])
def test_invalid_policy_is_rejected_whole(policy, message):
    with pytest.raises(ValueError, match=message):
        stage_model_overrides({**BASE, "stage_models": policy})


def test_deepseek_stage_effort_conflicts_with_disabled_thinking():
    with pytest.raises(ValueError, match="disabled DeepSeek thinking"):
        stage_model_overrides({**BASE, "deepseek_thinking": "disabled",
            "stage_models": {"synthesis": {"provider": "deepseek", "model": "x", "effort": "max"}}})


def test_subscription_stage_freezes_chatgpt_request_policy():
    def identity(stages):
        return native_identity(AnalysisRequest("002130.SZ", "2026-10-28", effective_config={**BASE, "stage_models": stages}))
    assert "chatgpt_request_policy" not in identity({})
    assert "chatgpt_request_policy" in identity({"synthesis": {"provider": "chatgpt", "model": "gpt-5.6"}})


def test_hunyuan_stage_uses_tokenhub_and_json_schema_without_effort(monkeypatch):
    from tradingagents.llm_clients.capabilities import native_structured_method
    from tradingagents.llm_clients.factory import create_llm_client

    call, model = resolve_stage_model({**BASE, "stage_models": {
        "challenge": {"provider": "hunyuan", "model": "hy4-preview"}}}, "challenge")
    assert native_structured_method(call["llm_provider"], model) == "json_schema"
    monkeypatch.setenv("HUNYUAN_API_KEY", "test-key")
    llm = create_llm_client(call["llm_provider"], model, base_url=call["backend_url"],
                            **provider_llm_kwargs(call)).get_llm()
    assert (llm.model_name, llm.openai_api_base) == ("hy4-preview", "https://tokenhub.tencentmaas.com/v1")
    assert llm.reasoning_effort is None
    with pytest.raises(ValueError, match="unsupported for hunyuan"):
        stage_model_overrides({**BASE, "stage_models": {"challenge": {
            "provider": "hunyuan", "model": model, "effort": "high"}}})
