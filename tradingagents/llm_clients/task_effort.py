"""Code-owned DeepSeek task overrides; no dispatch, escalation or mutation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CLASSIC_ROLE_TASKS = {
    "market": "classic.market",
    "social": "classic.social",
    "news": "classic.news",
    "fundamentals": "classic.fundamentals",
    "bull": "classic.bull",
    "bear": "classic.bear",
    "research_manager": "classic.research_manager",
}
DEEPSEEK_EFFORT_TASKS = frozenset(CLASSIC_ROLE_TASKS.values()) | frozenset({
    "native.operating_quality", "native.event_context", "native.market_context",
    "native.challenge", "native.synthesis",
    "catalyst.catalyst_events", "catalyst.operating_delivery", "catalyst.market_reaction",
    "catalyst.independent_refutation", "catalyst.synthesis",
    "aux.news_cluster", "aux.news_coverage", "aux.news_sentiment",
    "aux.news_deep_review", "aux.context_compaction", "aux.debate_summary",
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


def bind_task_effort(llm: Any, config: Mapping[str, Any], task: str) -> Any:
    """Bind auxiliary invocation kwargs without modifying a shared client.

    Helpers must bind from their original client on each call, not chain task
    bindings. With no active policy return the exact legacy client unchanged.
    """
    policy = task_effort_overrides(config)
    if str(config.get("llm_provider", "")).lower() != "deepseek" or not policy:
        return llm
    return llm.bind(reasoning_effort=resolve_task_effort(config, task))
