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
    }
)
ALL_EVIDENCE_KEYS = REPORT_EVIDENCE_KEYS | BUNDLE_EVIDENCE_KEYS


def validate_claim_key(key: str) -> None:
    """Validate a four-segment claim key against the registered vocabulary.

    A claim key has the shape ``lens.topic.subject.predicate`` where ``lens``,
    ``topic`` and ``predicate`` must be registered and ``subject`` is a stable
    snake_case metric/entity name.  Raises ``ValueError`` on any violation.
    """
    if re.fullmatch(CLAIM_KEY_PATTERN, key) is None:
        raise ValueError(f"invalid claim key: {key!r}")
    lens, topic, subject, predicate = key.split(".")
    if lens not in CLAIM_LENSES:
        raise ValueError(f"claim key lens is not registered: {lens}")
    if topic not in CLAIM_TOPICS:
        raise ValueError(f"claim key topic is not registered: {topic}")
    if predicate not in CLAIM_PREDICATES:
        raise ValueError(f"claim key predicate is not registered: {predicate}")
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

    if _nonempty(state.get("adjusted_price_bundle")):
        coverage.append("coverage:adjusted_price_history")
        evidence.append("evidence:price_bundle")
    if _nonempty(state.get("news_window_bundle")):
        coverage.append("coverage:company_event_window")
        evidence.append("evidence:news_bundle")

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

    return {"coverage": coverage, "evidence": evidence}


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
