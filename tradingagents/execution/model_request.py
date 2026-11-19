"""One provider request with injected lifecycle hooks, without a research journal."""

from collections.abc import Callable

from tradingagents.llm_clients.chatgpt_errors import ChatGPTError
from tradingagents.llm_clients.chatgpt_policy import validate_request_policy
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs


def _token_usage(response) -> dict[str, int]:
    def mapping(value):
        return value if isinstance(value, dict) else {}

    usage = mapping(getattr(response, "usage_metadata", None))
    raw = mapping(mapping(getattr(response, "response_metadata", None)).get("token_usage"))
    input_details = mapping(usage.get("input_token_details"))
    output_details = mapping(usage.get("output_token_details"))
    prompt_details = mapping(raw.get("prompt_tokens_details"))
    completion_details = mapping(raw.get("completion_tokens_details"))
    counters = {
        "input_tokens": (usage.get("input_tokens"), raw.get("prompt_tokens")),
        "output_tokens": (usage.get("output_tokens"), raw.get("completion_tokens")),
        "cached_tokens": (input_details.get("cache_read"), prompt_details.get("cached_tokens")),
        "cache_creation_tokens": (input_details.get("cache_creation"), raw.get("cache_creation_input_tokens"),
                                  prompt_details.get("cache_creation_input_tokens")),
        "reasoning_tokens": (output_details.get("reasoning"), completion_details.get("reasoning_tokens")),
    }
    normalized = {}
    for key, candidates in counters.items():
        for value in candidates:
            if type(value) is int and value >= 0:
                normalized[key] = value
                break
    # Within one reported request, zero is an observation; a missing counter is not.
    return normalized if {"input_tokens", "output_tokens"} <= normalized.keys() else {}


def invoke_model_request(*, config, model, task, prompt, client_factory, slots,
                         ensure_active, cancelled, deadline, dispatch,
                         on_error: Callable, on_usage: Callable, chatgpt_auth=None,
                         chatgpt_request_policy=None, response_format=None):
    ensure_active()
    while not slots.acquire(timeout=min(0.1, ensure_active())):
        ensure_active()
    try:
        remaining = ensure_active()
        try:
            kwargs = provider_llm_kwargs(config, task=task)
            kwargs.update(max_retries=0, timeout=remaining)
            if response_format is not None:
                kwargs["response_format"] = response_format
            if config["llm_provider"] == "chatgpt":
                if validate_request_policy(chatgpt_request_policy) is None:
                    # Unmarked frozen runs predate effort transmission.
                    kwargs.pop("reasoning_effort", None)
                if chatgpt_auth is None:
                    raise ChatGPTError("not_signed_in")
                kwargs.update(auth=chatgpt_auth, account_ref=config.get("chatgpt_account_ref"),
                              cancelled=cancelled, deadline=deadline, before_request=dispatch)
            client = client_factory(provider=config["llm_provider"], model=model,
                                    base_url=config.get("backend_url"), **kwargs)
        except Exception as exc:
            on_error("configuration_unavailable", exc)
            raise
        ensure_active()
        if config["llm_provider"] != "chatgpt":
            dispatch()
        try:
            response = client.get_llm().invoke(prompt)
        except Exception as exc:
            on_error("request_failed", exc)
            raise
        if usage := _token_usage(response):
            on_usage(usage)
        ensure_active()
        return response
    finally:
        slots.release()
