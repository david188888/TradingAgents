"""DeepSeek task effort stored in V9 runs created before stage model routing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEEPSEEK_EFFORT_TASKS = frozenset({
    "native.operating_quality", "native.event_context", "native.market_context",
    "native.challenge", "native.synthesis", "native.focus_response",
    "native.response_operating_quality", "native.response_event_context", "native.response_market_context",
    "aux.report_explanation",
})

def task_effort_overrides(config: Mapping[str, Any]) -> dict[str, str]:
    """Validate the complete optional policy, including unused task entries."""
    policy = config.get("deepseek_task_efforts", {})
    if not isinstance(policy, Mapping):
        raise ValueError("deepseek_task_efforts must be a mapping")
    for task, effort in policy.items():
        if task not in DEEPSEEK_EFFORT_TASKS:
            raise ValueError(f"deepseek_task_efforts: unknown task {task!r}")
        if not isinstance(effort, str) or effort not in {"low", "high", "max"}:
            raise ValueError(f"deepseek_task_efforts[{task!r}] must be low/high/max")
    if (policy and str(config.get("llm_provider", "")).lower() == "deepseek"
            and str(config.get("deepseek_thinking", "")).strip().lower() == "disabled"):
        raise ValueError("deepseek_task_efforts conflicts with disabled thinking")
    return dict(policy)


def resolve_task_effort(config: Mapping[str, Any], task: str | None = None) -> str | None:
    """Inherit global effort; active policies pin omitted globals to API high."""
    policy = task_effort_overrides(config)
    if task is not None and task not in DEEPSEEK_EFFORT_TASKS:
        raise ValueError(f"unknown effort task {task!r}")
    effort = policy.get(task) if task is not None else None
    effort = effort or config.get("deepseek_reasoning_effort")
    if effort:
        return str(effort).strip().lower()
    return "high" if policy else None
