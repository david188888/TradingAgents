"""Offline-only, reversible numeric metadata representation; no runtime activation."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.schemas._numeric_narrative import NumericCatalogV1
from tradingagents.research.native_versions import NUMERIC_NARRATIVE_POLICY

VIEW_POLICY = "lossless-numeric-metadata-v1"
VIEW_GUIDANCE = (
    "Numeric metadata are defined once in numeric_meta. "
    "numeric_catalog.metadata_aliases preserves their order; each entry names that exact m_ alias. "
    "Use the existing {{meta:m_alias}} tokens unchanged."
)
_COMPONENTS = {"numeric_narrative_policy", "numeric_catalog", "numeric_meta", "numeric_aliases",
               "prompt_context_view", "metadata_aliases"}


class PromptViewError(ValueError):
    """Closed diagnostic code only; never embed source material in exceptions."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EncodedContext:
    context: dict[str, Any]
    status: str
    reason: str | None = None


def _json(value):
    def check(item):
        if type(item) is dict:
            if any(type(k) is not str for k in item):
                raise PromptViewError("invalid_json")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise PromptViewError("invalid_json")

    try:
        check(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise PromptViewError("invalid_json") from None


def _context(value):
    if type(value) is not dict:
        raise PromptViewError("invalid_context")
    _json(value)


def _validate_original(context):
    if context.get("numeric_narrative_policy") != NUMERIC_NARRATIVE_POLICY:
        raise PromptViewError("numeric_policy_invalid")
    catalog = context.get("numeric_catalog")
    meta, aliases = context.get("numeric_meta"), context.get("numeric_aliases")
    if (type(catalog) is not dict or type(meta) is not dict or type(aliases) is not dict
            or type(catalog.get("metadata")) is not list or type(catalog.get("anchors")) is not list):
        raise PromptViewError("numeric_components_invalid")
    try:
        # JSON strict mode permits JSON arrays for tuple fields without coercing
        # string/number/bool types. Validation never replaces the original data.
        NumericCatalogV1.model_validate_json(_json(catalog), strict=True)
    except ValueError:
        raise PromptViewError("numeric_catalog_invalid") from None
    expected = {f"m_{i:04d}": item for i, item in enumerate(catalog["metadata"])}
    if set(meta) != set(expected):
        raise PromptViewError("metadata_alias_mismatch")
    if _json(meta) != _json(expected):
        raise PromptViewError("metadata_content_mismatch")
    expected = {f"n_{i:04d}": item["anchor_id"] for i, item in enumerate(catalog["anchors"])}
    if _json(aliases) != _json(expected):
        raise PromptViewError("numeric_alias_mismatch")


def decode_context(candidate: dict) -> dict:
    """Validate the closed alias protocol; authenticity requires the original."""
    _context(candidate)
    if candidate.get("prompt_context_view") != VIEW_POLICY:
        raise PromptViewError("view_policy_invalid")
    catalog, meta = candidate.get("numeric_catalog"), candidate.get("numeric_meta")
    if type(catalog) is not dict or type(meta) is not dict or "metadata" in catalog:
        raise PromptViewError("candidate_shape_invalid")
    refs = catalog.get("metadata_aliases")
    if (type(refs) is not list or any(type(ref) is not str for ref in refs)
            or refs != [f"m_{i:04d}" for i in range(len(meta))] or set(refs) != set(meta)):
        raise PromptViewError("metadata_alias_mismatch")
    if "metadata_aliases" in candidate:
        raise PromptViewError("view_field_conflict")
    restored = deepcopy(candidate)
    restored.pop("prompt_context_view")
    restored["numeric_catalog"].pop("metadata_aliases")
    restored["numeric_catalog"]["metadata"] = [deepcopy(meta[key]) for key in refs]
    _validate_original(restored)
    return restored


def verify_roundtrip(original: dict, candidate: dict) -> dict:
    """Return restored data only after exact JSON equality with the original."""
    _context(original)
    restored = decode_context(candidate)
    if _json(original) != _json(restored):
        raise PromptViewError("roundtrip_mismatch")
    return restored


def encode_context(context: dict) -> EncodedContext:
    """Create a candidate regardless of size; the full-prompt owner decides use."""
    _context(context)
    if not (_COMPONENTS & context.keys()):
        return EncodedContext(deepcopy(context), "identity_noop", "not_applicable")
    catalog = context.get("numeric_catalog")
    if ("prompt_context_view" in context or "metadata_aliases" in context
            or isinstance(catalog, dict) and "metadata_aliases" in catalog):
        raise PromptViewError("view_field_conflict")
    _validate_original(context)
    if not catalog["metadata"]:
        return EncodedContext(deepcopy(context), "identity_noop", "empty_metadata")
    candidate = deepcopy(context)
    candidate["prompt_context_view"] = VIEW_POLICY
    candidate["numeric_catalog"].pop("metadata")
    candidate["numeric_catalog"]["metadata_aliases"] = [f"m_{i:04d}" for i in range(len(catalog["metadata"]))]
    verify_roundtrip(context, candidate)
    return EncodedContext(candidate, "candidate")
