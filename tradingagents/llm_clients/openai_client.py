import os
import re
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .api_key_env import get_api_key_env
from .base_client import BaseLLMClient, normalize_content
from .capabilities import ModelCapabilities, get_capabilities
from .validators import validate_model


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with normalized content output and capability-aware binding.

    The Responses API returns content as a list of typed blocks
    (reasoning, text, etc.). ``invoke`` normalizes to string for
    consistent downstream handling.

    ``with_structured_output`` consults the per-model capability table
    (``capabilities.get_capabilities`` via ``_get_capabilities``) to pick
    the method and to decide whether ``tool_choice`` may be sent. Models
    that reject ``tool_choice`` in the current mode (e.g. DeepSeek V4 in
    thinking mode — per their official tool-calling guide and a direct
    probe) still bind the schema as a tool, but no ``tool_choice``
    parameter is sent.

    Provider-specific quirks beyond structured-output (e.g. DeepSeek's
    reasoning_content roundtrip) live in subclasses so this base class
    stays small.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def _get_capabilities(self) -> ModelCapabilities:
        """Capabilities for this client's current runtime mode.

        Base implementation is purely model-name driven; subclasses that
        switch behavior at runtime (e.g. DeepSeek thinking on/off) override
        this to return mode-adjusted capabilities.
        """
        return get_capabilities(self.model_name)

    def with_structured_output(self, schema, *, method=None, **kwargs):
        caps = self._get_capabilities()
        if caps.preferred_structured_method == "none":
            raise NotImplementedError(
                f"{self.model_name} has no structured-output method available; "
                f"agent factories will fall back to free-text generation."
            )
        method = method or caps.preferred_structured_method
        # When the model rejects tool_choice, suppress langchain's hardcoded
        # value. The schema is still bound as a tool — exactly what
        # DeepSeek's official tool-calling examples do.
        if method == "function_calling" and not caps.supports_tool_choice:
            kwargs.setdefault("tool_choice", None)
        return super().with_structured_output(schema, method=method, **kwargs)


def _input_to_messages(input_: Any) -> list:
    """Normalise a langchain LLM input to a list of message objects.

    Accepts a list of messages, a ``ChatPromptValue`` (from a
    ChatPromptTemplate), or anything else (treated as no messages).
    Used by providers that need to walk the outgoing message history;
    in particular DeepSeek thinking-mode propagation must work for
    both bare-list invocations and ChatPromptTemplate-driven ones, so
    treating only ``list`` here would silently skip half the call sites.
    """
    if isinstance(input_, list):
        return input_
    if hasattr(input_, "to_messages"):
        return input_.to_messages()
    return []


_RETIRED_DEEPSEEK_MODELS = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}


def reject_retired_deepseek_model(model: str) -> None:
    """Reject retired DeepSeek model names in this fork's runtime path."""
    replacement = _RETIRED_DEEPSEEK_MODELS.get(model)
    if replacement:
        raise ValueError(
            f"{model} is retired for this workflow. Use deepseek-v4-flash "
            f"or deepseek-v4-pro instead. Suggested replacement: {replacement}."
        )


def strip_deepseek_reasoning_content(messages: list[Any]) -> list[Any]:
    """Return a copy of messages without DeepSeek reasoning_content fields."""
    cleaned = []
    for message in messages:
        if isinstance(message, AIMessage):
            cloned = message.model_copy(deep=True)
            cloned.additional_kwargs.pop("reasoning_content", None)
            cleaned.append(cloned)
            continue
        if isinstance(message, dict):
            cloned = deepcopy(message)
            cloned.pop("reasoning_content", None)
            cleaned.append(cloned)
            continue
        cleaned.append(message)
    return cleaned


class DeepSeekChatOpenAI(NormalizedChatOpenAI):
    """DeepSeek-specific overrides on top of the OpenAI-compatible client.

    Thinking-mode round-trip is the only DeepSeek-specific behavior that
    stays here. When DeepSeek's thinking models return a response with
    ``reasoning_content``, that field must be echoed back as part of the
    assistant message on the next turn or the API fails with HTTP 400.
    ``_create_chat_result`` captures it on receive and
    ``_get_request_payload`` re-attaches it on send.

    Tool-choice handling for V4 thinking mode — those requests reject a
    function-spec ``tool_choice`` (400 "Thinking mode does not support
    this tool_choice", probed 2026-08-15) — is handled by the capability
    dispatch in ``NormalizedChatOpenAI.with_structured_output``. In
    non-thinking mode the same V4 models DO accept ``tool_choice``, so
    ``_get_capabilities`` flips ``supports_tool_choice`` at runtime based
    on the ``thinking`` setting carried in ``extra_body``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        body = kwargs.get("extra_body") or {}
        thinking = body.get("thinking") or {}
        # Absent thinking config means the API default: thinking ENABLED.
        self._thinking_enabled = thinking.get("type") != "disabled"

    def _get_capabilities(self) -> ModelCapabilities:
        caps = get_capabilities(self.model_name)
        if not self._thinking_enabled and not caps.supports_tool_choice:
            # Non-thinking path accepts a function-spec tool_choice
            # (probed 2026-08-15), so structured output can bind it and
            # get a more deterministic schema pick.
            return replace(caps, supports_tool_choice=True)
        return caps

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        outgoing = payload.get("messages", [])
        # Echo back real reasoning_content from prior DeepSeek assistant turns so
        # multi-turn thinking-mode conversations round-trip correctly.
        for message_dict, message in zip(outgoing, _input_to_messages(input_), strict=False):
            if not isinstance(message, AIMessage):
                continue
            reasoning = message.additional_kwargs.get("reasoning_content")
            if reasoning is not None:
                message_dict["reasoning_content"] = reasoning
        # DeepSeek thinking mode rejects ANY assistant message that lacks
        # reasoning_content (probed 2026-08-21): prompts that inject static data
        # bundles as assistant turns (e.g. prefetched adjusted-price / A-share
        # supplement messages) fail with HTTP 400 "reasoning_content ... must be
        # passed back". Give such assistant turns an empty reasoning_content so
        # the request passes validation; real reasoning_content (set above) is
        # preserved untouched.
        if self._thinking_enabled:
            for message_dict in outgoing:
                if message_dict.get("role") == "assistant":
                    message_dict.setdefault("reasoning_content", "")
        return payload

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for generation, choice in zip(
            chat_result.generations, response_dict.get("choices", []), strict=False
        ):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return chat_result


class MinimaxChatOpenAI(NormalizedChatOpenAI):
    """MiniMax-specific overrides on top of the OpenAI-compatible client.

    M2.x reasoning models embed ``<think>...</think>`` blocks directly in
    ``message.content`` by default, which would pollute saved reports.
    Per platform.minimax.io/docs/api-reference/text-openai-api,
    ``reasoning_split=True`` redirects the thinking block into
    ``reasoning_details`` so ``content`` stays clean. It is sent via
    ``extra_body`` (not a top-level kwarg) because the openai SDK validates
    top-level params and rejects unknown ones like reasoning_split (#826).

    The flag is gated by ``ModelCapabilities.requires_reasoning_split`` so
    only M2.x reasoning models receive it; non-reasoning MiniMax endpoints
    (Coding Plan, MiniMax-Text-01) never see it.

    Tool-choice handling for M2.x — those models accept only the string
    enum ``{"none", "auto"}`` and reject langchain's function-spec dict —
    is handled by the capability dispatch in
    ``NormalizedChatOpenAI.with_structured_output``, not here.
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if get_capabilities(self.model_name).requires_reasoning_split:
            # Pass via extra_body, not as a top-level kwarg: the openai SDK
            # (>=1.56) validates top-level params against Completions.create
            # and rejects unknown ones like reasoning_split (#826). extra_body
            # is forwarded into the request body untouched.
            extra_body = payload.setdefault("extra_body", {})
            extra_body.setdefault("reasoning_split", True)
        return payload


# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort", "temperature",
    "api_key", "callbacks", "http_client", "http_async_client",
    "max_tokens",
)

# OpenAI's ``reasoning_effort`` is only accepted by reasoning models — the GPT-5
# family and the o-series. Non-reasoning models (gpt-4.1, gpt-4o, ...) 400 with
# "Unsupported parameter: 'reasoning.effort' is not supported with this model".
# Drop the kwarg for those rather than crash the run.
_OPENAI_REASONING_MODEL = re.compile(r"^(gpt-5|o[1-9])")


def _supports_reasoning_effort(model: str, provider: str | None = None) -> bool:
    """Whether ``model`` accepts the ``reasoning_effort`` parameter.

    Native OpenAI reasoning models accept it. DeepSeek V4 accepts
    ``reasoning_effort`` ([low, high, max], default high) as a top-level
    parameter when thinking mode is enabled — it is ignored outside that
    mode, but sending it is harmless (DeepSeek ignores unsupported
    params rather than 400; probe 2026-08-15).
    """
    normalized = model.lower().strip()
    if bool(_OPENAI_REASONING_MODEL.match(normalized)):
        return True
    return provider == "deepseek"


@dataclass(frozen=True)
class ProviderSpec:
    """Declarative config for one OpenAI-compatible provider.

    The OpenAI-compatible family (OpenAI, xAI, DeepSeek, Qwen, GLM, MiniMax,
    OpenRouter, Ollama, and any user endpoint) all speak the same Chat
    Completions API and differ only by these fields — so one row here replaces
    the former per-provider base-URL dict, auth handling, and client-class
    branches. Native Anthropic / Google use their own clients (genuinely
    different APIs) and are intentionally NOT in this registry.

    The API-key env var stays in ``api_key_env.PROVIDER_API_KEY_ENV`` (the single
    source consulted by both this client and the CLI prompt); only behavior that
    is provider-specific (base URL, key optionality, wire-format quirks via
    ``chat_class``) lives here.
    """

    chat_class: type = NormalizedChatOpenAI   # provider quirks live in the subclass
    base_url: str | None = None            # default endpoint (None -> SDK default)
    base_url_env: str | None = None        # env var that overrides base_url (e.g. OLLAMA_BASE_URL)
    key_optional: bool = False                # don't require/prompt; send a placeholder if unset
    placeholder_key: str = "EMPTY"            # sent when no key is available (keyless local servers)
    require_base_url: bool = False            # error if no base_url is resolved (generic endpoint)
    use_responses_api: bool = False           # native OpenAI Responses API


# Single source of truth for the OpenAI-compatible provider family. Dual-region
# providers (qwen/glm/minimax) keep separate endpoints because international and
# China accounts cannot share credentials (#758).
OPENAI_COMPATIBLE_PROVIDERS: dict[str, ProviderSpec] = {
    "openai":     ProviderSpec(use_responses_api=True),
    "xai":        ProviderSpec(base_url="https://api.x.ai/v1"),
    "deepseek":   ProviderSpec(base_url="https://api.deepseek.com", chat_class=DeepSeekChatOpenAI),
    "qwen":       ProviderSpec(base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "qwen-cn":    ProviderSpec(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "glm":        ProviderSpec(base_url="https://api.z.ai/api/paas/v4/"),
    "glm-cn":     ProviderSpec(base_url="https://open.bigmodel.cn/api/paas/v4/"),
    "minimax":    ProviderSpec(base_url="https://api.minimax.io/v1", chat_class=MinimaxChatOpenAI),
    "minimax-cn": ProviderSpec(base_url="https://api.minimaxi.com/v1", chat_class=MinimaxChatOpenAI),
    "openrouter": ProviderSpec(base_url="https://openrouter.ai/api/v1"),
    "ollama":     ProviderSpec(base_url="http://localhost:11434/v1", base_url_env="OLLAMA_BASE_URL",
                               key_optional=True, placeholder_key="ollama"),
}


def is_openai_compatible(provider: str) -> bool:
    """Whether ``provider`` is served by the OpenAI-compatible registry."""
    return provider.lower() in OPENAI_COMPATIBLE_PROVIDERS


def _is_native_openai_base_url(base_url: str | None) -> bool:
    """True when ``base_url`` is unset or points at api.openai.com.

    The Responses API (/v1/responses) only exists on native OpenAI. A custom
    base_url on the ``openai`` provider (a proxy, gateway, or local server)
    speaks only Chat Completions, so the Responses API must stay off there even
    though the provider spec enables it (#1024).
    """
    if not base_url:
        return True
    if "://" not in base_url:
        base_url = "https://" + base_url
    host = urlparse(base_url).hostname or ""
    return host == "api.openai.com" or host.endswith(".openai.com")


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers.

    For native OpenAI models, uses the Responses API (/v1/responses) which
    supports reasoning_effort with function tools across all model families
    (GPT-4.1, GPT-5). Third-party compatible providers (xAI, OpenRouter,
    Ollama) use standard Chat Completions.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return a configured ChatOpenAI instance, driven by the provider registry."""
        if self.provider == "deepseek":
            reject_retired_deepseek_model(self.model)
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}
        spec = OPENAI_COMPATIBLE_PROVIDERS.get(self.provider)
        chat_cls = NormalizedChatOpenAI

        # DeepSeek thinking mode is configurable via ``thinking`` kwarg
        # (dict like {"type": "enabled"} / {"type": "disabled"}); absent
        # config falls back to this fork's default (thinking enabled with
        # max effort, see DEFAULT_CONFIG). The non-thinking path is available
        # via TRADINGAGENTS_DEEPSEEK_THINKING=disabled / CLI choice.
        deepseek_thinking = self.kwargs.get("thinking")

        if spec is not None:
            chat_cls = spec.chat_class

            # base_url precedence: explicit client base_url (carries the config /
            # TRADINGAGENTS_LLM_BACKEND_URL value) > provider env override (e.g.
            # OLLAMA_BASE_URL) > provider default. None means use the SDK default.
            env_base_url = os.environ.get(spec.base_url_env) if spec.base_url_env else None
            base_url = self.base_url or env_base_url or spec.base_url
            if spec.require_base_url and not base_url:
                raise ValueError(
                    f"Provider '{self.provider}' requires a base_url. Set it via "
                    "backend_url / TRADINGAGENTS_LLM_BACKEND_URL to your endpoint, "
                    "e.g. http://localhost:8000/v1 (vLLM) or http://localhost:1234/v1 "
                    "(LM Studio)."
                )
            if base_url:
                llm_kwargs["base_url"] = base_url

            # API key: required unless key_optional; keyless local servers get a
            # placeholder. The env-var name is the single source in api_key_env.
            api_key_env = get_api_key_env(self.provider)
            api_key = os.environ.get(api_key_env) if api_key_env else None
            if api_key:
                llm_kwargs["api_key"] = api_key
            elif spec.key_optional:
                llm_kwargs["api_key"] = spec.placeholder_key
            elif api_key_env:
                raise ValueError(
                    f"API key for provider '{self.provider}' is not set. "
                    f"Please set the {api_key_env} environment variable "
                    f"(e.g. add {api_key_env}=your_key to your .env file)."
                )

            # The Responses API only exists on native OpenAI; if the user points
            # the openai provider at a custom base_url (proxy/gateway/local), it
            # only speaks Chat Completions, so keep Responses off there (#1024).
            if spec.use_responses_api and _is_native_openai_base_url(base_url):
                llm_kwargs["use_responses_api"] = True
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # DeepSeek thinking mode ignores temperature/top_p (per the official
        # Thinking Mode guide; they are accepted but have no effect). Drop them
        # when thinking is enabled so users are not misled by silent no-ops.
        thinking_enabled = bool(
            deepseek_thinking and deepseek_thinking.get("type") != "disabled"
        )

        # Forward user-provided kwargs
        for key in _PASSTHROUGH_KWARGS:
            if key not in self.kwargs:
                continue
            if key == "reasoning_effort" and not _supports_reasoning_effort(
                self.model, self.provider
            ):
                continue
            if key in ("temperature", "top_p") and thinking_enabled:
                continue
            llm_kwargs[key] = self.kwargs[key]

        # DeepSeek: enable thinking by default (this fork's default is max-effort
        # thinking; DeepSeekChatOpenAI handles the reasoning_content round-trip).
        # Opt out with thinking={"type": "disabled"} for the non-thinking path
        # (tool_choice + temperature supported).
        if self.provider == "deepseek":
            llm_kwargs.setdefault("extra_body", {})
            llm_kwargs["extra_body"].setdefault(
                "thinking", deepseek_thinking or {"type": "enabled"}
            )

        # The subclass (provider quirks) comes from the registry spec.
        return chat_cls(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
