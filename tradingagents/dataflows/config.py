from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

import tradingagents.default_config as default_config

# Use default config but allow it to be overridden
_config: dict | None = None
_run_config: ContextVar[dict | None] = ContextVar("tradingagents_run_config", default=None)


def _merge(base: dict, config: Mapping) -> dict:
    """Merge one config layer, copying nested values to avoid shared mutation."""
    merged = deepcopy(base)
    for key, value in deepcopy(dict(config)).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def merge_config(config: Mapping) -> dict:
    """Build a complete config from defaults and a caller's overrides."""
    return _merge(default_config.DEFAULT_CONFIG, config)


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = deepcopy(default_config.DEFAULT_CONFIG)


def set_config(config: dict):
    """Update the active run config, or the process config when unscoped.

    Dict-valued keys (e.g. ``data_vendors``) are merged one level deep so a
    partial update like ``{"data_vendors": {"core_stock_apis": "alpha_vantage"}}``
    keeps the other nested keys from the default; scalar keys are replaced.
    """
    global _config
    scoped = _run_config.get()
    if scoped is not None:
        _run_config.set(_merge(scoped, config))
        return
    initialize_config()
    _config = _merge(_config, config)


def replace_config(config: Mapping) -> None:
    """Replace the process-global configuration with an exact deep copy."""
    global _config
    _config = deepcopy(dict(config))


@contextmanager
def config_scope(config: Mapping) -> Iterator[None]:
    """Bind this exact config to the context without changing other workers."""
    token = _run_config.set(deepcopy(dict(config)))
    try:
        yield
    finally:
        _run_config.reset(token)


def get_config() -> dict:
    """Get this run's config, or the process-wide config outside a run."""
    scoped = _run_config.get()
    if scoped is not None:
        return deepcopy(scoped)
    if _config is None:
        initialize_config()
    return deepcopy(_config)


# Initialize with default config
initialize_config()
