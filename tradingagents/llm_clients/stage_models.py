"""Code-owned V9 stage model routing: one provider/model per stage or specialist role."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api_key_env import PROVIDER_API_KEY_ENV
from .chatgpt_policy import REASONING_EFFORTS

SPECIALIST_ROLES = ("operating_quality", "event_context", "market_context")
STAGE_MODEL_KEYS = ("specialist", "challenge", "synthesis", "focus_response", "repair",
                    "report_explanation", *SPECIALIST_ROLES)
_BAILIAN_OUTPUT_CAPS = {"operating_quality": 10_240, "event_context": 6_144, "market_context": 6_144,
                        "challenge": 12_288, "response": 6_144, "synthesis": 8_192,
                        "repair": 4_096, "report_explanation": 4_096}
# The unified ``effort`` lands on each provider's existing setting; others reject it.
_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
STAGE_THINKING_MODELS = {
    "deepseek": ("deepseek-flash", "deepseek-v4-pro"),
    "bailian": ("deepseek-v4.1-flash-1017", "kimi-k3.1-pro"),
}

EFFORT_CONFIG_KEYS = {
    "deepseek": ("deepseek_reasoning_effort", _EFFORTS),
    "bailian": ("bailian_reasoning_effort", frozenset({"low", "medium", "high", "max"})),
    "openai": ("openai_reasoning_effort", REASONING_EFFORTS),
    "chatgpt": ("openai_reasoning_effort", REASONING_EFFORTS),
    "anthropic": ("anthropic_effort", _EFFORTS),
    "google": ("google_thinking_level", frozenset({"minimal", "low", "medium", "high"})),
}


def stage_model_overrides(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate the complete optional policy, including entries unused by this run."""
    policy = config.get("stage_models", {})
    if not isinstance(policy, Mapping):
        raise ValueError("stage_models must be a mapping")
    thinking_disabled = str(config.get("deepseek_thinking") or "").strip().lower() == "disabled"
    for key, entry in policy.items():
        if key not in STAGE_MODEL_KEYS:
            raise ValueError(f"stage_models: unknown stage {key!r}")
        if not isinstance(entry, Mapping) or entry.keys() - {"provider", "model", "effort", "thinking", "max_tokens"}:
            raise ValueError(f"stage_models[{key!r}] accepts only provider/model/effort/thinking/max_tokens")
        if "max_tokens" in entry and (type(entry["max_tokens"]) is not int or entry["max_tokens"] <= 0):
            raise ValueError(f"stage_models[{key!r}]: max_tokens must be a positive integer")
        provider, model, effort = entry.get("provider"), entry.get("model"), entry.get("effort")
        if not isinstance(provider, str) or (provider not in PROVIDER_API_KEY_ENV and provider != "chatgpt"):
            raise ValueError(f"stage_models[{key!r}]: unsupported provider {provider!r}")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"stage_models[{key!r}]: model is required")
        mode = entry.get("thinking")
        switchable = model.strip() in STAGE_THINKING_MODELS.get(provider, ())
        if mode is not None and (mode not in ("enabled", "disabled") or not switchable):
            raise ValueError(f"stage_models[{key!r}]: thinking setting is unsupported for {provider}/{model}")
        if effort is not None:
            if not isinstance(effort, str) or provider not in EFFORT_CONFIG_KEYS or effort not in EFFORT_CONFIG_KEYS[provider][1]:
                raise ValueError(f"stage_models[{key!r}]: effort {effort!r} is unsupported for {provider}")
            if provider == "bailian" and not switchable:
                raise ValueError(f"stage_models[{key!r}]: effort is unsupported for {provider}/{model}")
            if mode == "disabled" or (provider == "deepseek" and mode is None and thinking_disabled):
                name = "DeepSeek" if provider == "deepseek" else "Bailian"
                raise ValueError(f"stage_models[{key!r}]: effort conflicts with disabled {name} thinking")
    return {key: dict(entry) for key, entry in policy.items()}


def stage_model_providers(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Every provider a run may call, the top-level provider first."""
    stages = [entry["provider"] for entry in stage_model_overrides(config).values()]
    return tuple(p for p in dict.fromkeys([config.get("llm_provider"), *stages]) if p)


def resolve_stage_model(config: Mapping[str, Any], stage: str, *, phase="main",
                        economical=False) -> tuple[dict[str, Any], str]:
    """Route repair first, then author role, group and legacy tiers."""
    role = stage.removeprefix("response_")
    keys = (role, "specialist") if role in SPECIALIST_ROLES else (stage,)
    if phase == "repair":
        keys = ("repair", *keys)
    policy = stage_model_overrides(config)
    selected = next((key for key in keys if key in policy), None)
    entry = policy.get(selected, {})
    provider = entry.get("provider", config["llm_provider"])
    model = entry.get("model") or config["deep_think_llm" if stage == "synthesis" else "quick_think_llm"]
    call = dict(config, llm_provider=provider)
    if provider != config["llm_provider"]:
        call["backend_url"] = None
    mode = entry.get("thinking")
    effort = entry.get("effort")
    budget_stage = "repair" if phase == "repair" else "response" if role != stage else stage
    budget = entry.get("max_tokens")
    if economical and provider == "bailian" and model in STAGE_THINKING_MODELS["bailian"]:
        if (model == "deepseek-v4.1-flash-1017" and budget_stage in {"repair", "report_explanation"}
                and selected not in {"repair", "report_explanation"}):
            mode, effort = "disabled", None
        if budget is None and (default_cap := _BAILIAN_OUTPUT_CAPS.get(budget_stage)):
            budget = min(int(call.get("llm_max_tokens") or default_cap), default_cap)
    if mode is not None:
        call[f"{provider}_thinking"] = mode
    if effort is not None:
        call[EFFORT_CONFIG_KEYS[provider][0]] = effort
    if budget is not None:
        call["llm_max_tokens"] = budget
    return call, model
