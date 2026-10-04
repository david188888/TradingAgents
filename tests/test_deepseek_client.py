import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.llm_clients.openai_client import (
    DeepSeekChatOpenAI,
    OpenAIClient,
    reject_retired_deepseek_model,
    strip_deepseek_reasoning_content,
)
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs
from tradingagents.llm_clients.validators import validate_model


def test_deepseek_catalog_defaults_to_v4_models():
    assert get_model_options("deepseek", "quick")[0][1] == "deepseek-v4-flash"
    assert get_model_options("deepseek", "deep")[0][1] == "deepseek-v4-pro"
    assert ("DeepSeek V4.1 Flash (expires 09-10) - Temporary fast model option", "deepseek-v4.1-flash-expires-on-0910") in get_model_options("deepseek", "quick")
    assert ("DeepSeek V4.1 Flash (expires 09-10) - Temporary fast model option", "deepseek-v4.1-flash-expires-on-0910") in get_model_options("deepseek", "deep")


def test_official_flash_is_available_without_removing_legacy_alias():
    for tier in ("quick", "deep"):
        models = {model for _, model in get_model_options("deepseek", tier)}
        assert {"deepseek-flash", "deepseek-v4-flash"} <= models
    assert validate_model("deepseek", "deepseek-flash")


@pytest.mark.parametrize("thinking", ("enabled", "disabled"))
@pytest.mark.parametrize("effort", ("low", "high", "max"))
def test_official_flash_config_reaches_payload_and_supported_tool_binding(thinking, effort):
    class Result(BaseModel):
        summary: str

    kwargs = provider_llm_kwargs({
        "llm_provider": "deepseek", "deepseek_thinking": thinking,
        "deepseek_reasoning_effort": effort,
    })
    llm = OpenAIClient(
        "deepseek-flash", provider="deepseek", api_key="test-key", **kwargs,
    ).get_llm()
    payload = llm._get_request_payload([HumanMessage(content="Summarize the supplied facts.")])
    assert payload["model"] == "deepseek-flash"
    assert payload["extra_body"]["thinking"] == {"type": thinking}
    if thinking == "enabled":
        assert payload["reasoning_effort"] == effort
    else:
        assert "reasoning_effort" not in payload
    binding = llm.with_structured_output(Result).steps[0]
    assert binding.kwargs["tools"][0]["function"]["name"] == "Result"
    if thinking == "enabled":
        assert binding.kwargs.get("tool_choice") is None
    else:
        assert binding.kwargs["tool_choice"]["function"]["name"] == "Result"


def test_explicit_disabled_client_does_not_send_an_effort_that_reenables_thinking():
    llm = OpenAIClient(
        "deepseek-flash", provider="deepseek", api_key="test-key",
        thinking={"type": "disabled"}, reasoning_effort="high", temperature=0.3,
    ).get_llm()
    payload = llm._get_request_payload([HumanMessage(content="Summarize the supplied facts.")])
    assert payload["extra_body"]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
    assert payload["temperature"] == 0.3


def test_deepseek_old_model_names_are_rejected():
    for model in ("deepseek-chat", "deepseek-reasoner"):
        try:
            reject_retired_deepseek_model(model)
        except ValueError as exc:
            assert "deepseek-v4-flash" in str(exc)
            assert "deepseek-v4-pro" in str(exc)
        else:
            raise AssertionError(f"{model} should be rejected")


def test_deepseek_client_enables_thinking_by_default():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
    ).get_llm()

    assert llm.model_name == "deepseek-v4-pro"
    assert llm.extra_body == {"thinking": {"type": "enabled"}}


def test_deepseek_client_can_opt_out_of_thinking():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        thinking={"type": "disabled"},
    ).get_llm()

    assert llm.extra_body == {"thinking": {"type": "disabled"}}


def test_deepseek_client_enables_thinking_when_configured():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        thinking={"type": "enabled"},
    ).get_llm()

    assert llm.extra_body == {"thinking": {"type": "enabled"}}


def test_deepseek_client_forwards_reasoning_effort():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        reasoning_effort="max",
    ).get_llm()

    assert llm.reasoning_effort == "max"


def test_deepseek_client_drops_temperature_in_thinking_mode():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        temperature=0.7,
        thinking={"type": "enabled"},
    ).get_llm()

    # Thinking mode ignores temperature/top_p (official guide) — drop silently
    # rather than let users think it is being applied.
    assert llm.temperature is None
    assert llm.extra_body == {"thinking": {"type": "enabled"}}


def test_deepseek_client_keeps_temperature_in_non_thinking_mode():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        temperature=0.3,
        thinking={"type": "disabled"},
    ).get_llm()

    assert llm.temperature == 0.3


def test_deepseek_client_forwards_max_tokens():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        max_tokens=16384,
    ).get_llm()

    assert llm.max_tokens == 16384


def test_deepseek_client_non_thinking_supports_tool_choice():
    # Probed 2026-08-15: V4 in non-thinking mode accepts a function-spec
    # tool_choice (returns tool_calls). The static table says False (thinking
    # mode rejects it); the runtime capability flips it when thinking is off.
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        thinking={"type": "disabled"},
    ).get_llm()
    assert isinstance(llm, DeepSeekChatOpenAI)
    assert llm._get_capabilities().supports_tool_choice is True


def test_deepseek_client_default_thinking_suppresses_tool_choice():
    # Default (thinking enabled) rejects a function-spec tool_choice with a
    # 400; the runtime capability must keep it off unless thinking is off.
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
    ).get_llm()
    assert llm._get_capabilities().supports_tool_choice is False


def test_deepseek_client_thinking_suppresses_tool_choice():
    llm = OpenAIClient(
        "deepseek-v4-pro",
        provider="deepseek",
        api_key="test-key",
        thinking={"type": "enabled"},
    ).get_llm()
    assert llm._get_capabilities().supports_tool_choice is False


def test_deepseek_client_rejects_old_model_names():
    try:
        OpenAIClient(
            "deepseek-reasoner",
            provider="deepseek",
            api_key="test-key",
        ).get_llm()
    except ValueError as exc:
        assert "retired" in str(exc)
    else:
        raise AssertionError("deepseek-reasoner should be rejected")


def test_mimo_catalog_defaults_and_uses_anthropic_endpoint(monkeypatch):
    assert get_model_options("mimo", "quick")[0][1] == "mimo-v2.5"
    assert get_model_options("mimo", "deep")[0][1] == "mimo-v2.5-pro"

    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    llm = create_llm_client("mimo", "mimo-v2.5").get_llm()

    assert llm.model == "mimo-v2.5"
    assert str(llm.anthropic_api_url) == "https://token-plan-sgp.xiaomimimo.com/anthropic"
    assert llm.anthropic_api_key.get_secret_value() == "test-key"


def test_strip_deepseek_reasoning_content_from_message_history():
    messages = [
        HumanMessage(content="Analyze AAPL"),
        AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": "private thinking",
                "tool_calls": [{"id": "call_1", "type": "function"}],
            },
        ),
        {
            "role": "assistant",
            "content": "final answer",
            "reasoning_content": "old thinking",
        },
    ]

    cleaned = strip_deepseek_reasoning_content(messages)

    assert "reasoning_content" not in cleaned[1].additional_kwargs
    assert cleaned[1].additional_kwargs["tool_calls"] == [{"id": "call_1", "type": "function"}]
    assert "reasoning_content" not in cleaned[2]
    assert "reasoning_content" in messages[1].additional_kwargs
    assert "reasoning_content" in messages[2]
