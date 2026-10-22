"""Offline proposals for the explicit factual-premise contract, never runtime fallback."""

from copy import deepcopy

from tradingagents.research.factual_premises import premise_path
from tradingagents.research.numeric_narrative import _field_scope, _fields


def bind(stage, value, context):
    value = deepcopy(value)
    value["premises"] = []
    for path, _ in _fields(value["proposal"]):
        if not premise_path(path):
            continue
        scope = _field_scope(stage, path, value["proposal"], context)
        candidates = [o for o in context["factual_observations"] if set(o["fact_ids"]) <= scope]
        value["premises"].append({"field_path": path,
            "observation_ids": [o["observation_id"] for o in candidates[:1]], "pending_questions": []})
    return value
