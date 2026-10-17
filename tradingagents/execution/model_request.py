"""One provider request with injected lifecycle hooks, without a research journal."""

from collections.abc import Callable

from tradingagents.llm_clients.chatgpt_errors import ChatGPTError
from tradingagents.llm_clients.chatgpt_policy import validate_request_policy
from tradingagents.llm_clients.provider_kwargs import provider_llm_kwargs


def invoke_model_request(*, config, model, task, prompt, client_factory, slots,
                         ensure_active, cancelled, deadline, dispatch,
                         on_error: Callable, on_usage: Callable, chatgpt_auth=None,
                         chatgpt_request_policy=None):
    ensure_active()
    while not slots.acquire(timeout=min(0.1, ensure_active())):
        ensure_active()
    try:
        remaining = ensure_active()
        try:
            kwargs = provider_llm_kwargs(config, task=task)
            kwargs.update(max_retries=0, timeout=remaining)
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
        usage = getattr(response, "usage_metadata", None)
        if isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0
                                           for k in ("input_tokens", "output_tokens")):
            on_usage(usage)
        ensure_active()
        return response
    finally:
        slots.release()
