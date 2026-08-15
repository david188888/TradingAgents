"""Deterministic public hashing for research-package projections.

These helpers exist so an external Agent (Proma, Codex, etc.) can anchor a
conversation answer or a portable export to one canonical SHA-256 of the public
research package JSON.  The canonical form deliberately rejects private fields
(prompts, raw tool arguments, credentials, hidden reasoning) before hashing so
the digest never depends on non-public payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

PRIVATE_KEYS = frozenset(
    {
        "prompt",
        "prompts",
        "raw_tool_args",
        "raw_tool_arguments",
        "tool_args",
        "tool_arguments",
        "tool_trace",
        "private_reasoning",
        "chain_of_thought",
        "hidden_reasoning",
        "raw_payload",
        "source_locator",
        "content_sha256",
        "byte_size",
        "api_key",
        "authorization_token",
        "token",
        "secret",
        "password",
        "authorization",
    }
)
_PRIVATE_KEY_TOKENS = frozenset(re.sub(r"[^a-z0-9]", "", key.casefold()) for key in PRIVATE_KEYS)


class PublicHashError(ValueError):
    """Raised when a payload cannot cross the public hashing boundary."""


def _as_public(value: Any, *, path: str = "root") -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(mode="json")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise PublicHashError(f"public hash keys must be strings at {path}")
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized in _PRIVATE_KEY_TOKENS:
                raise PublicHashError(f"private field is not public: {path}.{key}")
            result[key] = _as_public(child, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_as_public(child, path=f"{path}[{index}]") for index, child in enumerate(value)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise PublicHashError(f"unsupported public hash value at {path}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a public projection to deterministic, sort-keyed JSON bytes."""
    return json.dumps(
        _as_public(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def package_sha256(package: Any) -> str:
    """Hash the public JSON projection used as the package anchor."""
    return hashlib.sha256(canonical_json_bytes(package)).hexdigest()


__all__ = ["PublicHashError", "canonical_json_bytes", "package_sha256"]
