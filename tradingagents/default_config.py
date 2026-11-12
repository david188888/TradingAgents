import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LLM_MAX_RETRIES":      "llm_max_retries",
    "TRADINGAGENTS_GOOGLE_THINKING_LEVEL":   "google_thinking_level",
    "TRADINGAGENTS_OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
    "TRADINGAGENTS_ANTHROPIC_EFFORT":        "anthropic_effort",
    "TRADINGAGENTS_DEEPSEEK_THINKING":       "deepseek_thinking",
    "TRADINGAGENTS_DEEPSEEK_REASONING_EFFORT": "deepseek_reasoning_effort",
    "TRADINGAGENTS_LLM_MAX_TOKENS":          "llm_max_tokens",
    "TRADINGAGENTS_EVIDENCE_SEARCH_ENABLED": "evidence_search_enabled",
    "TRADINGAGENTS_WIND_ENABLED":            "wind_enabled",
    "TRADINGAGENTS_WIND_MAX_CONCURRENCY":    "wind_max_concurrency",
    "TRADINGAGENTS_WIND_REQUEST_TIMEOUT_SECONDS": "wind_request_timeout_seconds",
    "TRADINGAGENTS_WIND_STRICT_EDB_ALLOWLIST": "wind_strict_edb_allowlist",
}


_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value.

    Invalid values raise ValueError rather than silently falling back.
    """
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


def _path_from_env(env_var: str, default: str) -> str:
    """Use the fallback path when an optional path variable is unset or blank."""
    return os.getenv(env_var) or default


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": _path_from_env(
        "TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")
    ),
    "data_cache_dir": _path_from_env(
        "TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")
    ),
    # Independent Search/Fetch is separate from the configured research LLM.
    "evidence_search_enabled": True,
    # LLM settings
    # This fork is A-share-first and defaults to DeepSeek (no OpenAI key needed).
    # Override per-environment via TRADINGAGENTS_LLM_PROVIDER / TRADINGAGENTS_*_LLM.
    "llm_provider": "deepseek",
    "deep_think_llm": "deepseek-flash",
    "quick_think_llm": "deepseek-flash",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # DeepSeek thinking mode: "enabled" or "disabled", default enabled/high.
    # Thinking ignores temperature. Requests with tools must echo prior
    # reasoning_content (handled by the client); forced tool choices require
    # non-thinking mode. A disabled toggle suppresses reasoning_effort so the
    # effort does not re-enable thinking at the API.
    "deepseek_thinking": "enabled",
    # DeepSeek reasoning effort: "low", "high", or "max" (medium/xhigh are
    # mapped to high by the API). Defaults to "high" (the API default) for
    # reasoning on the official Flash path.
    "deepseek_reasoning_effort": "high",
    # Upper bound for a single model response (output tokens). None leaves
    # each provider at its default; DeepSeek V4 supports up to 384K output
    # and recommends a sane max_tokens to avoid truncated JSON reports.
    "llm_max_tokens": None,
    # Sampling temperature forwarded to every provider when set. None leaves
    # each provider at its own default.
    "temperature": None,
    # SDK retry budget forwarded to every provider chat client. None leaves
    # each provider/SDK at its own default (usually 2).
    "llm_max_retries": None,
    # Cap on output tokens forwarded to every provider chat client. None leaves
    # each provider at its own default. Set it to bound a model that emits
    # unbounded reasoning/output and hangs or trips a gateway idle timeout
    # (e.g. some deepseek-v4-flash deployments, #1204).
    "max_tokens": None,
    "output_language": "Chinese",
    # Wind AIFin Market (https://aifinmarket.wind.com.cn) premium data.
    # Enabled by default for this local research workspace. Set
    # wind_enabled=False to disable Wind capabilities without affecting core
    # A-share OHLCV/fundamentals/news paths.
    "wind_enabled": True,
    "wind_max_concurrency": 1,
    "wind_request_timeout_seconds": 120,
    "wind_strict_edb_allowlist": False,
})


def validate_config(config: dict) -> list[str]:
    """Return a list of configuration problems; [] means the config is usable.

    Check provider/model presence and supported option values. The LLM
    client layer validates model availability.
    """
    problems: list[str] = []
    from tradingagents.llm_clients.stage_models import stage_model_overrides

    try:
        stage_model_overrides(config)
    except ValueError as exc:
        problems.append(str(exc))
    provider = str(config.get("llm_provider", "")).strip().lower()
    if not provider:
        problems.append("llm_provider is required")
    for key in ("deep_think_llm", "quick_think_llm"):
        if not str(config.get(key, "")).strip():
            problems.append(f"{key} is required")
    search_enabled = config.get("evidence_search_enabled")
    if not isinstance(search_enabled, bool):
        problems.append(f"evidence_search_enabled must be a boolean, got {search_enabled!r}")
    temperature = config.get("temperature")
    if temperature is not None and temperature != "":
        try:
            float(temperature)
        except (TypeError, ValueError):
            problems.append(f"temperature must be numeric, got {temperature!r}")
    for key in (
        "llm_max_retries",
        "llm_max_tokens",
    ):
        value = config.get(key)
        if value is None or value == "":
            continue
        try:
            if int(value) < 0:
                problems.append(f"{key} must be non-negative")
        except (TypeError, ValueError):
            problems.append(f"{key} must be an integer, got {value!r}")
    thinking = config.get("deepseek_thinking")
    if thinking is not None and str(thinking).strip().lower() not in (
        "enabled",
        "disabled",
        "",
    ):
        problems.append(
            f"deepseek_thinking must be 'enabled' or 'disabled', got {thinking!r}"
        )
    effort = config.get("deepseek_reasoning_effort")
    if effort is not None and str(effort).strip().lower() not in (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "",
    ):
        problems.append(
            "deepseek_reasoning_effort must be one of low/medium/high/xhigh/max, "
            f"got {effort!r}"
        )
    return problems
