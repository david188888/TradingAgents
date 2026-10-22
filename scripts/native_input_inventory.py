"""Conservative content inventory; preserving bytes does not prove economics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

INVENTORY_VERSION = "native-input-inventory-v1"
ENTITY_IDS = (
    "observation_id", "anchor_id", "meta_id", "hypothesis_id", "challenge_id",
    "response_id", "verification_id", "metric_id", "claim_id", "evidence_id", "snapshot_id",
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def size(text):
    return {"characters": len(text), "utf8_bytes": len(text.encode())}


def category(path):
    if path and path[0] == "schema":
        return "schema_and_reference_contract"
    if "numeric_attribution" in path or "proof" in path:
        return "saved_receipts"
    if any(p.startswith("numeric_") for p in path):
        return "numeric_bindings"
    if any(p.startswith("factual_") for p in path):
        return "factual_observations"
    if any(p in {"sources", "evidence"} for p in path):
        return "sources_and_qualification"
    if any(p in {"challenges", "verifications", "challenge_outcomes", "local_checks",
                 "check_results", "evidence_checks", "local_check_assessments"} for p in path):
        return "challenges_and_checks"
    if any(p in {"facts", "claims", "assertions"} for p in path):
        return "claims"
    if any(p in {"hypotheses", "dialogue", "responses"} for p in path):
        return "hypotheses_and_replies"
    return "task_scope_and_limits"


def inventory(context):
    """All supplied content is a conservative floor, never a minimal evidence set.

    Entities stay atomic to retain ID/text/value/source bindings. Scope paths
    remain distinct: a fact in an unrelated saved receipt is not a replacement
    for that fact in the task's allowed facts. Exact duplicates within one
    scope share a requirement; array order of entity collections is not scored.
    """
    units = {}

    def add(value, path, identifier=None):
        scope = "/" + "/".join(path)
        key = (scope, digest(value))
        if key not in units:
            units[key] = {"scope": scope, "sha256": key[1], "category": category(path),
                          "entity_id": identifier, **size(encoded(value))}

    def walk(value, path):
        if isinstance(value, dict):
            identifier = next((value[k] for k in ENTITY_IDS
                               if isinstance(value.get(k), str)), None)
            if identifier is not None:
                add(value, path, identifier)
            elif not value:
                add(value, path)
            else:
                for key, item in sorted(value.items()):
                    walk(item, (*path, key.replace("~", "~0").replace("/", "~1")))
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            for item in value:
                walk(item, (*path, "*"))
        else:
            # Scalar lists retain order, including reference and condition lists.
            add(value, path)

    walk(context, ())
    return {"policy": INVENTORY_VERSION, "scope": "all_supplied_content_conservative_floor",
            "semantic_completeness": "not_assessed",
            "units": [units[k] for k in sorted(units)]}


def inventory_summary(value):
    counts = Counter(u["category"] for u in value["units"])
    return {"policy": value["policy"], "scope": value["scope"],
            "semantic_completeness": value["semantic_completeness"],
            "unit_count": len(value["units"]), "categories": dict(sorted(counts.items())),
            "sha256": digest(value)}


def compare_inventory(baseline, candidate):
    if baseline["policy"] != INVENTORY_VERSION or candidate["policy"] != INVENTORY_VERSION:
        raise ValueError("inventory_policy_mismatch")
    expected = {(u["scope"], u["sha256"]): u for u in baseline["units"]}
    actual = {(u["scope"], u["sha256"]) for u in candidate["units"]}
    missing = [expected[k] for k in sorted(expected.keys() - actual)]
    return {"required": len(expected), "retained": len(expected) - len(missing),
            "retention_ratio": (len(expected) - len(missing)) / len(expected) if expected else None,
            "missing": missing, "added": len(actual - expected.keys()),
            "semantic_completeness": "not_assessed"}


def composition(context):
    """Disjoint JSON value sizes; punctuation and container syntax stay separate."""
    parts = []

    def visit(value, path):
        if isinstance(value, dict) and (not path or path[-1] in {"record", "verification"}):
            for key, item in sorted(value.items()):
                visit(item, (*path, key))
        else:
            parts.append({"path": ".".join(path), "category": category(path),
                          **size(encoded(value))})

    visit(context, ())
    total = size(encoded(context))
    overhead = {k: total[k] - sum(p[k] for p in parts) for k in total}
    return {**total, "parts": parts, "container_syntax": overhead}


def repetitions(context, *, minimum_string_bytes=64):
    """Repeated whole strings, not removable information or a token estimate."""
    values = defaultdict(lambda: {"occurrences": 0, "serialized_bytes": 0})

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and len(value.encode()) >= minimum_string_bytes:
            item = values[digest(value)]
            item["occurrences"] += 1
            item["serialized_bytes"] = len(encoded(value).encode())

    walk(context)
    repeated = [{"sha256": key, **v, "repeated_payload_bytes": (v["occurrences"] - 1) * v["serialized_bytes"]}
                for key, v in values.items() if v["occurrences"] > 1]
    repeated.sort(key=lambda v: (-v["repeated_payload_bytes"], v["sha256"]))
    return {"minimum_string_utf8_bytes": minimum_string_bytes,
            "duplicate_string_groups": len(repeated),
            "repeated_payload_bytes": sum(v["repeated_payload_bytes"] for v in repeated),
            "interpretation": "exact_repeated_string_payload_not_removable_savings",
            "largest_groups": repeated[:10]}
