"""Prompt-local aliases; public proposals retain their canonical identifiers."""

from collections.abc import Mapping
from typing import Any

_KINDS = ("claim", "evidence", "hypothesis", "condition", "challenge", "response", "snapshot", "metric")


def reference_aliases(context: Mapping[str, Any]) -> dict[str, str]:
    """Build a deterministic bijection from saved identifier definitions only."""
    identifiers: dict[str, set[str]] = {kind: set() for kind in _KINDS}

    def collect(value):
        if isinstance(value, Mapping):
            for key, item in value.items():
                kind = key.removesuffix("_id") if key.endswith("_id") else None
                if kind in identifiers and isinstance(item, str):
                    identifiers[kind].add(item)
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect(context.get("record", {}))
    for key in ("facts", "sources", "metrics"):
        collect(context.get(key, []))
    aliases = {}
    for kind, values in identifiers.items():
        for index, identifier in enumerate(sorted(values), 1):
            if identifier in aliases:
                raise ValueError("native reference identifier has multiple kinds")
            aliases[identifier] = f"{kind}_{index:03d}"
    if set(aliases) & set(aliases.values()):
        raise ValueError("native reference alias collides with saved identifier")
    return aliases


def translate_references(value: Any, mapping: Mapping[str, str], *, references: bool = False) -> Any:
    """Translate exact reference fields, never prose, enum checks or substrings."""
    if isinstance(value, Mapping):
        return {key: translate_references(item, mapping, references=(
            references or (key.endswith(("_id", "_ids")) and key not in {"check_id", "check_ids"})
        )) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [translate_references(item, mapping, references=references) for item in value]
    if references and isinstance(value, str):
        return mapping.get(value, value)
    return value
