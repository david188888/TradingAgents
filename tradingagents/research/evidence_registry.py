"""Deterministic, content-addressed evidence registry for ResearchCaseV2.

This module turns committed, durable artifacts into a closed set of public
evidence and coverage references that a later assembler can consume without
re-opening vendor connections or trusting in-memory graph state.  It is pure:
no LLM calls, no vendor routes, no network.  Every identifier is a stable
SHA-256 digest over canonical JSON, so the same artifact content always maps
to the same reference and replays are idempotent.

Two artifact families are registered:

* ``evidence-bundle`` artifacts produced by the deterministic prefetch nodes
  (adjusted price, news windows, A-share supplement).  Their content is stored
  as canonical JSON, so the stored ``content_sha256`` equals the ref_id.
* committed analyst report revisions (``report.updated`` with a recognized
  ``report_kind``).  Their ref_id is derived from a ``{"media_type", "content"}``
  canonical target so the reference is reproducible from the report text alone.

Coverage references are derived from each bundle's own coverage records and
wrapped with ``BundleCoverageV1`` so a consumer can reason about requested
versus observed coverage without re-deriving it from rendered text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from tradingagents.agents.schemas._research_case import CoverageRefV1, EvidenceRefV2
from tradingagents.dataflows.coverage import BundleCoverageV1, SourceCoverageV1

# Recognized analyst report kinds that carry durable evidence.
_REPORT_KINDS = frozenset({"market", "fundamentals", "news", "sentiment"})

# The deterministic prefetch state keys and the capability each one covers.
_EVIDENCE_BUNDLE_STATE_KEYS = (
    "adjusted_price_bundle",
    "news_window_bundle",
    "a_share_supplement_bundle",
    "fundamentals_prefetch_bundle",
)

_CAPABILITY_BY_STATE_KEY = {
    "adjusted_price_bundle": ("adjusted_price_history",),
    "news_window_bundle": ("company_event_window",),
}


def canonical_json_str(value: Any) -> str:
    """Return the product's canonical compact JSON for ``value``.

    Keys are sorted and no whitespace is inserted, matching the ref_id
    derivation used elsewhere in the codebase.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_json_sha256(value: Any) -> str:
    """Return the 64-hex SHA-256 of the canonical JSON of ``value``."""
    return hashlib.sha256(canonical_json_str(value).encode("utf-8")).hexdigest()


def _parse_event_time(timestamp: str) -> datetime:
    return (
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
    )


def _parse_source_date(value: Any) -> datetime | None:
    """Parse a bundle as_of/price_as_of date string into a naive datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            # A bare YYYY-MM-DD has no time component.
            from datetime import date

            parsed = datetime.combine(date.fromisoformat(value), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


_SOURCE_COVERAGE_FIELDS = (
    "capability",
    "source_id",
    "requested_start",
    "requested_end",
    "actual_start",
    "actual_end",
    "item_count",
    "page_count",
    "pagination_exhausted",
    "completeness",
    "sources",
    "degradations",
    "as_of",
)


def _coverage_record(coverage: Any, capability: str) -> SourceCoverageV1 | None:
    """Validate a bundle coverage dict as a single source record.

    Bundles may carry subclass-specific coverage fields (e.g.
    ``PriceSeriesCoverageV1`` price-basis fields).  ``SourceCoverageV1`` is
    ``extra="forbid"``, so project onto the base fields before validating;
    subclass-only metadata does not belong on the public coverage envelope.
    """
    if not isinstance(coverage, Mapping) or "source_id" not in coverage:
        return None
    projected = {key: coverage[key] for key in _SOURCE_COVERAGE_FIELDS if key in coverage}
    projected["capability"] = capability
    try:
        return SourceCoverageV1.model_validate(projected)
    except ValidationError:
        return None


def _bundle_coverage(
    bundle: Mapping[str, Any],
    artifact_id: str,
) -> list[CoverageRefV1]:
    """Derive bundle-level coverage refs for a persisted evidence bundle."""
    refs: list[CoverageRefV1] = []

    # Adjusted price: a single SourceCoverageV1 on the adjusted result.
    adjusted = bundle.get("adjusted")
    if isinstance(adjusted, Mapping):
        record = _coverage_record(adjusted.get("coverage"), "adjusted_price_history")
        if record is not None:
            envelope = BundleCoverageV1.build(
                capability="adjusted_price_history",
                records=[record],
                required_source_ids=(record.source_id,),
                optional_source_ids=(),
            )
            refs.append(
                CoverageRefV1(
                    coverage_ref_id=canonical_json_sha256(
                        {
                            "capability": "adjusted_price_history",
                            "artifact_id": artifact_id,
                            "source_id": record.source_id,
                        }
                    ),
                    capability="adjusted_price_history",
                    envelope=envelope,
                )
            )

    # News windows: a single company_event_window source record.
    windows = bundle.get("windows")
    if isinstance(windows, Mapping):
        company_events = windows.get("company_events")
        if isinstance(company_events, Mapping):
            for window in company_events.values():
                if not isinstance(window, Mapping):
                    continue
                record = _coverage_record(window.get("coverage"), "company_event_window")
                if record is None:
                    continue
                envelope = BundleCoverageV1.build(
                    capability="company_event_window",
                    records=[record],
                    required_source_ids=(record.source_id,),
                    optional_source_ids=(),
                )
                refs.append(
                    CoverageRefV1(
                        coverage_ref_id=canonical_json_sha256(
                            {
                                "capability": "company_event_window",
                                "artifact_id": artifact_id,
                                "source_id": record.source_id,
                            }
                        ),
                        capability="company_event_window",
                        envelope=envelope,
                    )
                )
                break

    # A-share supplement: one coverage ref per ok result capability.
    results = bundle.get("results")
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, Mapping) or result.get("status") != "ok":
                continue
            capability = result.get("capability")
            if not isinstance(capability, str) or not capability:
                continue
            record = _coverage_record(result.get("coverage"), capability)
            if record is None:
                continue
            envelope = BundleCoverageV1.build(
                capability=capability,
                records=[record],
                required_source_ids=(record.source_id,),
                optional_source_ids=(),
            )
            refs.append(
                CoverageRefV1(
                    coverage_ref_id=canonical_json_sha256(
                        {
                            "capability": capability,
                            "artifact_id": artifact_id,
                            "source_id": record.source_id,
                        }
                    ),
                    capability=capability,
                    envelope=envelope,
                )
            )

    # Fundamentals prefetch: typed capability results retain all positive and
    # negative source coverage, so missing providers remain visible on replay.
    for result in bundle.get("results", ()):
        if not isinstance(result, Mapping):
            continue
        semantic = result.get("capability_result")
        if not isinstance(semantic, Mapping):
            continue
        try:
            from tradingagents.dataflows.capability_result import CapabilityResultV1

            capability_result = CapabilityResultV1.model_validate(semantic)
        except (ImportError, ValidationError, ValueError):
            continue
        capability = capability_result.capability
        refs.append(
            CoverageRefV1(
                coverage_ref_id=canonical_json_sha256(
                    {
                        "capability": capability,
                        "artifact_id": artifact_id,
                        "capability_result_id": capability_result.capability_result_id,
                    }
                ),
                capability=capability,
                envelope=capability_result.coverage,
            )
        )

    return refs


def _bundle_source_observed_at(bundle: Mapping[str, Any]) -> datetime | None:
    quote = bundle.get("current_quote")
    if isinstance(quote, Mapping):
        price_as_of = _parse_source_date(quote.get("price_as_of"))
        if price_as_of is not None:
            return price_as_of
    return _parse_source_date(bundle.get("as_of"))


@dataclass(frozen=True)
class EvidenceRegistry:
    """An immutable, indexed view of a run's durable evidence and coverage."""

    evidence_refs: tuple[EvidenceRefV2, ...] = ()
    coverage_refs: tuple[CoverageRefV1, ...] = ()
    by_ref_id: Mapping[str, EvidenceRefV2] = field(default_factory=dict)
    by_artifact_id: Mapping[str, tuple[EvidenceRefV2, ...]] = field(default_factory=dict)
    coverage_by_capability: Mapping[str, tuple[CoverageRefV1, ...]] = field(
        default_factory=dict
    )
    # First evidence ref registered for each prefetch state_key (e.g.
    # ``adjusted_price_bundle``), so short ``evidence:`` keys can be resolved.
    evidence_by_state_key: Mapping[str, EvidenceRefV2] = field(default_factory=dict)
    # One evidence ref per recognised analyst report lens (market/fundamentals/
    # news/sentiment), so ``evidence:<lens>_report`` keys can be resolved.
    report_evidence_by_lens: Mapping[str, EvidenceRefV2] = field(default_factory=dict)

    #: Map a short ``evidence:<label>`` key to a real EvidenceRefV2, or None.
    _EVIDENCE_KEY_TO_STATE_KEY = {
        "evidence:price_bundle": "adjusted_price_bundle",
        "evidence:news_bundle": "news_window_bundle",
        "evidence:supplement_bundle": "a_share_supplement_bundle",
        "evidence:fundamentals_bundle": "fundamentals_prefetch_bundle",
    }
    _EVIDENCE_KEY_TO_LENS = {
        "evidence:market_report": "market",
        "evidence:fundamentals_report": "fundamentals",
        "evidence:news_report": "news",
        "evidence:sentiment_report": "sentiment",
    }

    def get_evidence(self, ref_id: str) -> EvidenceRefV2 | None:
        return self.by_ref_id.get(ref_id)

    def get_coverage(self, capability: str) -> tuple[CoverageRefV1, ...]:
        return self.coverage_by_capability.get(capability, ())

    def resolve_evidence_key(self, key: str) -> EvidenceRefV2 | None:
        """Resolve a short ``evidence:<label>`` key to a durable evidence ref."""
        state_key = self._EVIDENCE_KEY_TO_STATE_KEY.get(key)
        if state_key is not None:
            return self.evidence_by_state_key.get(state_key)
        lens = self._EVIDENCE_KEY_TO_LENS.get(key)
        if lens is not None:
            return self.report_evidence_by_lens.get(lens)
        return None

    def resolve_coverage_key(self, key: str) -> CoverageRefV1 | None:
        """Resolve a short ``coverage:<capability>`` key to a coverage ref."""
        if not isinstance(key, str) or not key.startswith("coverage:"):
            return None
        capability = key[len("coverage:"):]
        refs = self.coverage_by_capability.get(capability, ())
        return refs[0] if refs else None


def build_evidence_registry(
    store: Any,
    run_id: str,
) -> EvidenceRegistry:
    """Scan a run's artifact.written/report.updated events into a registry.

    Unreadable or malformed artifacts are skipped and never fail the run;
    only valid current-run artifacts are registered.
    """
    events = store.read_events(run_id)

    artifact_written = {
        str(event.payload["artifact_id"]): event
        for event in events
        if event.type == "artifact.written"
        and str(event.payload.get("artifact_id"))
    }

    evidence_refs: list[EvidenceRefV2] = []
    coverage_refs: list[CoverageRefV1] = []
    seen_ref_ids: set[str] = set()

    def register_evidence(
        ref_id: str,
        artifact_id: str,
        media_type: str,
        locator: str,
        source_observed_at: datetime | None,
        captured_at: datetime,
    ) -> EvidenceRefV2:
        if ref_id in seen_ref_ids:
            return EvidenceRefV2(
                ref_id=ref_id,
                run_id=run_id,
                artifact_id=artifact_id,
                media_type=media_type,
                locator=locator,
                source_observed_at=source_observed_at,
                captured_at=captured_at,
                resolution_status="available",
            )
        seen_ref_ids.add(ref_id)
        ref = EvidenceRefV2(
            ref_id=ref_id,
            run_id=run_id,
            artifact_id=artifact_id,
            media_type=media_type,
            locator=locator,
            source_observed_at=source_observed_at,
            captured_at=captured_at,
            resolution_status="available",
        )
        evidence_refs.append(ref)
        return ref

    # 1. Persisted evidence bundles.
    evidence_by_state_key: dict[str, EvidenceRefV2] = {}
    for event in events:
        if event.type != "artifact.written":
            continue
        payload = event.payload
        if payload.get("kind") != "evidence-bundle":
            continue
        artifact_id = str(payload["artifact_id"])
        try:
            raw = store.read_artifact(run_id, artifact_id)
            bundle = json.loads(raw.decode("utf-8"))
            if not isinstance(bundle, dict):
                raise ValueError("evidence bundle must be a JSON object")
        except Exception:
            continue
        ref = register_evidence(
            canonical_json_sha256(bundle),
            artifact_id,
            str(payload.get("media_type") or "application/json"),
            str(payload.get("locator") or ""),
            _bundle_source_observed_at(bundle),
            _parse_event_time(event.timestamp),
        )
        state_key = payload.get("state_key")
        if isinstance(state_key, str) and state_key:
            # First registered bundle wins for each state_key so a re-run
            # cannot silently replace an already-durable evidence reference.
            evidence_by_state_key.setdefault(state_key, ref)
        coverage_refs.extend(_bundle_coverage(bundle, artifact_id))

    # 2. Committed analyst report revisions.
    report_evidence_by_lens: dict[str, EvidenceRefV2] = {}
    for event in events:
        if event.type != "report.updated":
            continue
        report_kind = event.payload.get("report_kind")
        if report_kind not in _REPORT_KINDS:
            continue
        artifact_id = str(event.payload.get("artifact_id") or "")
        written = artifact_written.get(artifact_id)
        if written is None:
            continue
        try:
            content = store.read_artifact(run_id, artifact_id).decode("utf-8")
        except Exception:
            continue
        media_type = str(written.payload.get("media_type") or "text/markdown")
        locator = str(written.payload.get("locator") or "")
        ref = register_evidence(
            canonical_json_sha256({"media_type": media_type, "content": content}),
            artifact_id,
            media_type,
            locator,
            None,
            _parse_event_time(written.timestamp),
        )
        report_evidence_by_lens.setdefault(report_kind, ref)

    by_ref_id = {ref.ref_id: ref for ref in evidence_refs}
    by_artifact_id: dict[str, list[EvidenceRefV2]] = {}
    for ref in evidence_refs:
        by_artifact_id.setdefault(ref.artifact_id, []).append(ref)
    coverage_by_capability: dict[str, list[CoverageRefV1]] = {}
    for ref in coverage_refs:
        coverage_by_capability.setdefault(ref.capability, []).append(ref)

    return EvidenceRegistry(
        evidence_refs=tuple(evidence_refs),
        coverage_refs=tuple(coverage_refs),
        by_ref_id=by_ref_id,
        by_artifact_id={k: tuple(v) for k, v in by_artifact_id.items()},
        coverage_by_capability={
            k: tuple(v) for k, v in coverage_by_capability.items()
        },
        evidence_by_state_key=evidence_by_state_key,
        report_evidence_by_lens=report_evidence_by_lens,
    )
