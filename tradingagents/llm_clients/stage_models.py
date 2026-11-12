"""Code-owned V9 stage model routing: one provider/model per stage or specialist role."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api_key_env import PROVIDER_API_KEY_ENV
from .chatgpt_policy import REASONING_EFFORTS

SPECIALIST_ROLES = ("operating_quality", "event_context", "market_context")
STAGE_MODEL_KEYS = ("specialist", "challenge", "synthesis", "focus_response", *SPECIALIST_ROLES)
# The unified ``effort`` lands on each provider's existing setting; others reject it.
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
EFFORT_CONFIG_KEYS = {
    "deepseek": ("deepseek_reasoning_effort", _EFFORTS),
    "openai": ("openai_reasoning_effort", REASONING_EFFORTS),
    "chatgpt": ("openai_reasoning_effort", REASONING_EFFORTS),
    "anthropic": ("anthropic_effort", _EFFORTS),
    "google": ("google_thinking_level", frozenset({"minimal", "low", "medium", "high"})),
}


def stage_model_overrides(config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Validate the complete optional policy, including entries unused by this run."""
    policy = config.get("stage_models", {})
    if not isinstance(policy, Mapping):
        raise ValueError("stage_models must be a mapping")
    thinking_disabled = str(config.get("deepseek_thinking") or "").strip().lower() == "disabled"
    for key, entry in policy.items():
        if key not in STAGE_MODEL_KEYS:
            raise ValueError(f"stage_models: unknown stage {key!r}")
        if not isinstance(entry, Mapping) or entry.keys() - {"provider", "model", "effort"}:
            raise ValueError(f"stage_models[{key!r}] accepts only provider/model/effort")
        provider, model, effort = entry.get("provider"), entry.get("model"), entry.get("effort")
        if not isinstance(provider, str) or (provider not in PROVIDER_API_KEY_ENV and provider != "chatgpt"):
            raise ValueError(f"stage_models[{key!r}]: unsupported provider {provider!r}")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"stage_models[{key!r}]: model is required")
        if effort is not None:
            if not isinstance(effort, str) or provider not in EFFORT_CONFIG_KEYS or effort not in EFFORT_CONFIG_KEYS[provider][1]:
                raise ValueError(f"stage_models[{key!r}]: effort {effort!r} is unsupported for {provider}")
            if provider == "deepseek" and thinking_disabled:
                raise ValueError(f"stage_models[{key!r}]: effort conflicts with disabled DeepSeek thinking")
    return {key: dict(entry) for key, entry in policy.items()}


def stage_model_providers(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Every provider a run may call, the top-level provider first."""
    stages = [entry["provider"] for entry in stage_model_overrides(config).values()]
    return tuple(p for p in dict.fromkeys([config.get("llm_provider"), *stages]) if p)


def resolve_stage_model(config: Mapping[str, Any], stage: str) -> tuple[dict[str, Any], str]:
    """Return the call config and model; role, then group, then the legacy two tiers.

    ``response_<role>`` follows its specialist so the author defends its own Insights.
    """
    role = stage.removeprefix("response_")
    keys = (role, "specialist") if role in SPECIALIST_ROLES else (stage,)
    policy = stage_model_overrides(config)
    entry = next((policy[key] for key in keys if key in policy), None)
    if entry is None:
        return dict(config), config["deep_think_llm"] if stage == "synthesis" else config["quick_think_llm"]
    call = dict(config, llm_provider=entry["provider"])
    if entry["provider"] != config["llm_provider"]:
        # The top-level endpoint belongs to the top-level provider.
        call["backend_url"] = None
    if entry.get("effort") is not None:
        call[EFFORT_CONFIG_KEYS[entry["provider"]][0]] = entry["effort"]
    return call, entry["model"]
