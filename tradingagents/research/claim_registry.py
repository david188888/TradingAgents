"""Closed vocabulary and short-key conventions for evidence-bound research claims.

This module is pure: it carries no LLM calls and no analysis logic.  It exists
so the learning-mode Research Manager can, in a single structured turn, refer
to durable evidence and coverage by short, stable keys instead of by raw
sha256 refs or vendor locators.  A later assembler (separate from this task)
resolves those short keys into real ``EvidenceRefV2`` / ``CoverageRefV1``
objects and computes ``source_dates``.

Two families of short keys are recognised:

* ``coverage:<capability>`` — points at a coverage capability that was
  deterministically prefetched (e.g. ``coverage:adjusted_price_history``,
  ``coverage:company_event_window``, or an A-share supplement capability such
  as ``coverage:capital_flow``).
* ``evidence:<label>`` — points at a concrete evidence artifact.  Analyst
  reports use ``evidence:market_report``, ``evidence:fundamentals_report``,
  ``evidence:news_report``, ``evidence:sentiment_report``; deterministic data
  bundles use ``evidence:price_bundle``, ``evidence:news_bundle``,
  ``evidence:supplement_bundle``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from tradingagents.agents.schemas._research_case import (
    _CLAIM_LENSES,
    _CLAIM_PREDICATES,
    _CLAIM_TOPICS,
    CLAIM_KEY_PATTERN,
)

# Re-exported closed vocabularies so every consumer reads one source of truth.
CLAIM_LENSES = _CLAIM_LENSES
CLAIM_TOPICS = _CLAIM_TOPICS
CLAIM_PREDICATES = _CLAIM_PREDICATES

COVERAGE_KEY_PREFIX = "coverage:"
EVIDENCE_KEY_PREFIX = "evidence:"

# Recognised evidence short keys, split by origin for prompt listing.
REPORT_EVIDENCE_KEYS = frozenset(
    {
        "evidence:market_report",
        "evidence:fundamentals_report",
        "evidence:news_report",
        "evidence:sentiment_report",
    }
)
BUNDLE_EVIDENCE_KEYS = frozenset(
    {
        "evidence:price_bundle",
        "evidence:news_bundle",
        "evidence:supplement_bundle",
        "evidence:fundamentals_bundle",
    }
)
ALL_EVIDENCE_KEYS = REPORT_EVIDENCE_KEYS | BUNDLE_EVIDENCE_KEYS


def validate_claim_key(key: str) -> None:
    """Validate a four-segment claim key's shape and lens.

    A claim key has the shape ``lens.topic.subject.predicate``.  ``lens`` is
    code-controlled (it routes the claim to an analyst card and must be one
    of the registered lenses); the other three segments are stable snake_case
    identifiers chosen by the model and are only shape-checked.  This keeps
    evidence binding and the claim graph strict without demanding that the
    model hit a fixed topic/predicate ontology on the first try.
    """
    if re.fullmatch(CLAIM_KEY_PATTERN, key) is None:
        raise ValueError(f"invalid claim key: {key!r}")
    lens, _topic, subject, _predicate = key.split(".")
    if lens not in CLAIM_LENSES:
        raise ValueError(f"claim key lens is not registered: {lens}")
    if not subject:
        raise ValueError("claim key subject is required")
    return None


def available_candidate_keys(state: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return the coverage/evidence short keys actually available for this run.

    The judgement is based purely on which bundles and analyst reports are
    non-empty in ``state``.  Bundles are stored as canonical JSON strings.
    Returns ``{"coverage": [...], "evidence": [...]}`` for prompt listing and
    for tests.
    """
    coverage: list[str] = []
    evidence: list[str] = []

    price_capabilities = _available_typed_capabilities(
        state.get("adjusted_price_bundle")
    )
    if _nonempty(state.get("adjusted_price_bundle")):
        if not price_capabilities and not _has_typed_capability_results(
            state.get("adjusted_price_bundle")
        ):
            price_capabilities = ["adjusted_price_history"]
        if price_capabilities:
            coverage.extend(f"coverage:{item}" for item in price_capabilities)
            evidence.append("evidence:price_bundle")
    news_capabilities = _available_typed_capabilities(state.get("news_window_bundle"))
    if _nonempty(state.get("news_window_bundle")):
        if not news_capabilities and not _has_typed_capability_results(
            state.get("news_window_bundle")
        ):
            news_capabilities = ["company_event_window"]
        if news_capabilities:
            coverage.extend(f"coverage:{item}" for item in news_capabilities)
            evidence.append("evidence:news_bundle")

    fundamentals_capabilities = _available_typed_capabilities(
        state.get("fundamentals_prefetch_bundle")
    )
    if fundamentals_capabilities:
        coverage.extend(f"coverage:{item}" for item in fundamentals_capabilities)
        evidence.append("evidence:fundamentals_bundle")

    supplement_capabilities = _supplement_capabilities(state.get("a_share_supplement_bundle"))
    if supplement_capabilities:
        coverage.extend(f"coverage:{capability}" for capability in supplement_capabilities)
        evidence.append("evidence:supplement_bundle")

    if _nonempty(state.get("market_report")):
        evidence.append("evidence:market_report")
    if _nonempty(state.get("fundamentals_report")):
        evidence.append("evidence:fundamentals_report")
    if _nonempty(state.get("news_report")):
        evidence.append("evidence:news_report")
    if _nonempty(state.get("sentiment_report")):
        evidence.append("evidence:sentiment_report")

    return {
        "coverage": list(dict.fromkeys(coverage)),
        "evidence": list(dict.fromkeys(evidence)),
    }


def _nonempty(value: object) -> bool:
    """Return whether a state channel carries usable content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _parse_json_object(value: object) -> dict[str, Any] | None:
    """Parse a bundle that may be a JSON string or already a mapping."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _supplement_capabilities(bundle: object) -> list[str]:
    """Return the ok result capabilities of an A-share supplement bundle."""
    payload = _parse_json_object(bundle)
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    capabilities: list[str] = []
    for result in results:
        if not isinstance(result, Mapping):
            continue
        if result.get("status") != "ok":
            continue
        capability = result.get("capability")
        if isinstance(capability, str) and capability:
            capabilities.append(capability)
    return capabilities


def _available_typed_capabilities(bundle: object) -> list[str]:
    """Return typed capabilities with data available for factual claims."""

    payload = _parse_json_object(bundle)
    if payload is None:
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    capabilities: list[str] = []
    for wrapped in results:
        if not isinstance(wrapped, Mapping):
            continue
        semantic = wrapped.get("capability_result")
        if not isinstance(semantic, Mapping):
            continue
        capability = semantic.get("capability")
        if semantic.get("availability") == "available" and isinstance(
            capability, str
        ):
            capabilities.append(capability)
    return capabilities


def _has_typed_capability_results(bundle: object) -> bool:
    payload = _parse_json_object(bundle)
    if payload is None or not isinstance(payload.get("results"), list):
        return False
    return any(
        isinstance(wrapped, Mapping)
        and isinstance(wrapped.get("capability_result"), Mapping)
        for wrapped in payload["results"]
    )
