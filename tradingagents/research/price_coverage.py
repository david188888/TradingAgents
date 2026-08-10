"""Deterministic capability-level coverage status for adjusted price history.

This module is a pure, replayable abstraction over the adjusted-price bundle
produced by ``run_adjusted_price_prefetch``.  It is the single place where the
adjusted_price_history *capability* is collapsed into a public status that
eligibility and DataQuality policy can consume without re-parsing rendered CSV.

It deliberately never derives a trend conclusion from the raw audit series:
raw prices are audit metadata only.  ``has_usable_adjusted_trend`` is true only
when the provider returned a verified, complete adjusted series.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

ADJUSTED_PRICE_SOURCE_UNAVAILABLE = "adjusted_price_source_unavailable"
ADJUSTED_PRICE_COVERAGE_NOT_REPORTED = "adjusted_price_coverage_not_reported"


@dataclass(frozen=True)
class AdjustedPriceCapability:
    """Public capability status for the adjusted_price_history ability."""

    completeness: str  # complete | partial | unknown | unavailable
    reason_codes: tuple[str, ...]
    has_usable_adjusted_trend: bool


def _parse_bundle(bundle: object) -> Mapping[str, Any] | None:
    if isinstance(bundle, Mapping):
        return bundle
    if isinstance(bundle, str):
        try:
            payload = json.loads(bundle)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, Mapping) else None
    return None


def _reason_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


def assess_adjusted_price_capability(bundle: object) -> AdjustedPriceCapability:
    """Map an adjusted-price bundle to its deterministic capability status.

    Rules (applied in order, raw audit never authorises a trend):

    - ``adjusted.status == unavailable`` or an unparseable bundle -> unavailable
      with ``adjusted_price_source_unavailable``.
    - ``adjusted.status == ok`` with a ``complete`` coverage -> complete,
      usable trend.
    - otherwise the coverage (partial/unknown/unavailable) is passed through,
      and the public reason code comes from the coverage degradations.
    - a missing ``coverage`` record -> unknown with
      ``adjusted_price_coverage_not_reported``.
    """
    payload = _parse_bundle(bundle)
    adjusted = payload.get("adjusted") if payload is not None else None
    if not isinstance(adjusted, Mapping):
        return AdjustedPriceCapability(
            "unavailable", (ADJUSTED_PRICE_SOURCE_UNAVAILABLE,), False
        )

    status = adjusted.get("status")
    if status == "unavailable":
        reasons = _reason_tuple(adjusted.get("degradations")) or (
            ADJUSTED_PRICE_SOURCE_UNAVAILABLE,
        )
        return AdjustedPriceCapability("unavailable", reasons, False)

    coverage = adjusted.get("coverage")
    if not isinstance(coverage, Mapping):
        return AdjustedPriceCapability(
            "unknown", (ADJUSTED_PRICE_COVERAGE_NOT_REPORTED,), False
        )

    cov_completeness = coverage.get("completeness")
    if status == "ok" and cov_completeness == "complete":
        return AdjustedPriceCapability("complete", (), True)

    reasons = _reason_tuple(coverage.get("degradations")) or (
        ADJUSTED_PRICE_COVERAGE_NOT_REPORTED,
    )
    if cov_completeness in ("partial", "unknown", "unavailable"):
        return AdjustedPriceCapability(cov_completeness, reasons, False)
    # A degraded status, or an unexpected coverage value, cannot prove usability.
    return AdjustedPriceCapability("unknown", reasons, False)


def adjusted_price_capability_dict(bundle: object) -> dict[str, object]:
    """Return the JSON-safe capability status for embedding in a bundle."""
    capability = assess_adjusted_price_capability(bundle)
    return {
        "completeness": capability.completeness,
        "reason_codes": list(capability.reason_codes),
        "has_usable_adjusted_trend": capability.has_usable_adjusted_trend,
    }


def bundle_for_analyst(bundle: object) -> str:
    """Return an analyst-safe bundle with raw audit history rows removed.

    The raw audit series is audit metadata only and must never reach the model
    as a trend basis.  Its ``data`` field (rendered raw price rows) is dropped;
    its status / degradation / error metadata is preserved.
    """
    if isinstance(bundle, str):
        payload = _parse_bundle(bundle)
        if payload is None:
            return bundle
    else:
        payload = _parse_bundle(bundle)
        if payload is None:
            return "" if bundle is None else str(bundle)
    copy = dict(payload)
    raw = copy.get("raw_audit")
    if isinstance(raw, Mapping):
        copy["raw_audit"] = {key: value for key, value in raw.items() if key != "data"}
    return json.dumps(copy, ensure_ascii=False)
