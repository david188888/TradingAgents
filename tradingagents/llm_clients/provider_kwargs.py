"""Provider-specific LLM construction kwargs derived from a config mapping.

Shared by the main graph (TradingAgentsGraph) and the side-channel LLM
factories in ``dataflows`` (e.g. ``consistency.create_llm_from_config``) so
auxiliary calls honor the same thinking/effort/token settings as the primary
agents instead of silently falling back to provider defaults.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _coerce_max_retries(value):
    """Validate an ``llm_max_retries`` value to a non-negative int.

    Accepts an int or a numeric string (env vars arrive as strings). Rejects
    booleans and negatives loudly so a misconfiguration fails at startup rather
    than silently disabling retries.
    """
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries must be an integer, got {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries must be >= 0, got {n}")
    return n


def provider_llm_kwargs(config: Mapping[str, Any]) -> dict[str, Any]:
    """Get provider-specific kwargs for LLM client creation."""
    kwargs = {}
    provider = config.get("llm_provider", "").lower()

    if provider == "google":
        thinking_level = config.get("google_thinking_level")
        if thinking_level:
            kwargs["thinking_level"] = thinking_level

    elif provider == "openai":
        reasoning_effort = config.get("openai_reasoning_effort")
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

    elif provider == "anthropic":
        effort = config.get("anthropic_effort")
        if effort:
            kwargs["effort"] = effort

    elif provider == "deepseek":
        # DeepSeek V4 thinking mode toggle ("enabled"/"disabled").
        thinking = config.get("deepseek_thinking")
        if thinking and str(thinking).strip().lower() == "enabled":
            kwargs["thinking"] = {"type": "enabled"}
        # reasoning_effort is honored by the API in thinking mode;
        # it is ignored (harmlessly) in non-thinking mode.
        effort = config.get("deepseek_reasoning_effort")
        if effort:
            kwargs["reasoning_effort"] = str(effort).strip().lower()

    # Sampling temperature is cross-provider: forward it whenever set.
    # float() here so a value coming from a TRADINGAGENTS_TEMPERATURE env
    # string ("0.2") works the same as a programmatic float.
    temperature = config.get("temperature")
    if temperature is not None and temperature != "":
        kwargs["temperature"] = float(temperature)

    # SDK retry budget is cross-provider. Forward it only when explicitly set
    # so each provider keeps its own default (usually 2) otherwise (#1091).
    max_retries = config.get("llm_max_retries")
    if max_retries is not None and max_retries != "":
        kwargs["max_retries"] = _coerce_max_retries(max_retries)

    # Output-token cap is cross-provider (DeepSeek V4 supports up to 384K
    # and recommends a sane max_tokens so long JSON reports do not truncate).
    max_tokens = config.get("llm_max_tokens")
    if max_tokens is not None and max_tokens != "":
        kwargs["max_tokens"] = int(max_tokens)

    return kwargs
