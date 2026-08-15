"""Portable public export for an evidence-bound research conversation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .conversation_models import ConversationThreadV1

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


class ExportPrivacyError(ValueError):
    """Raised when a payload attempts to cross the public export boundary."""


def _as_public(value: Any, *, path: str = "root") -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(mode="json")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ExportPrivacyError(f"public export keys must be strings at {path}")
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if normalized in _PRIVATE_KEY_TOKENS:
                raise ExportPrivacyError(f"private field is not exportable: {path}.{key}")
            result[key] = _as_public(child, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_as_public(child, path=f"{path}[{index}]") for index, child in enumerate(value)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ExportPrivacyError(f"unsupported public export value at {path}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _as_public(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def package_sha256(package: Any) -> str:
    """Hash the public JSON projection used as the conversation anchor."""
    return hashlib.sha256(canonical_json_bytes(package)).hexdigest()


def _write_new(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    destination.write_bytes(content)


def _package_markdown(package: Any, thread: ConversationThreadV1) -> str:
    payload = json.loads(canonical_json_bytes(package).decode("utf-8"))
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "# Research Package\n\n"
        f"- Run ID: `{thread.run_id}`\n"
        f"- Package schema: `{thread.package_schema_version}`\n"
        f"- Package SHA-256: `{thread.package_sha256}`\n"
        "- Boundary: learning research only; not a trading instruction.\n\n"
        "## Public JSON\n\n"
        "```json\n"
        f"{encoded}\n"
        "```\n"
    )


def _conversation_jsonl(thread: ConversationThreadV1) -> bytes:
    records = [
        {"record_type": "thread", "thread": thread.model_dump(mode="json", exclude={"messages"})}
    ]
    records.extend(
        {"record_type": "message", "message": message.model_dump(mode="json")}
        for message in thread.messages
    )
    return b"".join(canonical_json_bytes(record) + b"\n" for record in records)


def export_research_bundle(
    destination: str | Path,
    *,
    package: Any,
    thread: ConversationThreadV1,
    metric_dictionary: Any = None,
    sources: Any = None,
    analysis_cutoff: str | None = None,
    language: str = "English",
    data_quality: str = "unknown",
) -> dict[str, Any]:
    """Write a non-destructive portable bundle and return its manifest.

    ``package`` is intentionally accepted as a Pydantic model or mapping so
    this module stays independent from the evolving ResearchPackage contract.
    Its canonical public hash must match the thread anchor.
    """
    actual_hash = package_sha256(package)
    if actual_hash != thread.package_sha256:
        raise ExportPrivacyError("package hash does not match conversation anchor")
    root = Path(destination)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"export destination is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    package_json = canonical_json_bytes(package) + b"\n"
    package_md = _package_markdown(package, thread).encode("utf-8")
    metric_json = canonical_json_bytes(metric_dictionary or {}) + b"\n"
    source_json = canonical_json_bytes(sources or {}) + b"\n"
    conversation_jsonl = _conversation_jsonl(thread)
    files = {
        "research-package.json": package_json,
        "research-package.md": package_md,
        "metric-dictionary.json": metric_json,
        "sources.json": source_json,
        "conversation.jsonl": conversation_jsonl,
    }
    metadata = {
        "schema_version": "research-export-manifest-v1",
        "run_id": thread.run_id,
        "thread_id": thread.thread_id,
        "package_schema_version": thread.package_schema_version,
        "package_sha256": thread.package_sha256,
        "analysis_cutoff": analysis_cutoff,
        "language": language,
        "data_quality": data_quality,
        "learning_research_only": True,
        "not_trading_instruction": True,
    }
    manifest = {
        **metadata,
        "files": {
            name: {
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
            }
            for name, content in files.items()
        },
    }
    for name, content in files.items():
        _write_new(root / name, content)
    _write_new(
        root / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n",
    )
    return manifest


__all__ = [
    "ExportPrivacyError",
    "canonical_json_bytes",
    "export_research_bundle",
    "package_sha256",
]
