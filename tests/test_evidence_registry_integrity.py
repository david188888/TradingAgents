from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.execution.output_publisher import (
    _extract_bundle_capabilities,
    _extract_bundle_result_ids,
    _extract_bundle_result_summaries,
)
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
from tradingagents.research.evidence_registry import build_evidence_registry
from tradingagents.research.integrity import ResearchIntegrityError
from tradingagents.research.official_disclosures import (
    build_official_disclosure_result,
)

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _bundle(ticker: str, *, horizon: str) -> bytes:
    cutoff = resolve_analysis_cutoff(
        ticker,
        "2026-08-13",
        identity={"exchange": "NMS"} if ticker == "AAPL" else None,
    )
    result = build_official_disclosure_result(
        ticker,
        "2026-08-13",
        horizon=horizon,
        cutoff=cutoff,
        recorded_at=NOW,
    )
    return json.dumps(
        {"ticker": ticker, "as_of": "2026-08-13", "results": [result]},
        sort_keys=True,
    ).encode()


def _event(raw: bytes, *, sequence: int, committed: int, artifact_id: str | None = None):
    digest = hashlib.sha256(raw).hexdigest()
    return SimpleNamespace(
        run_id="run_test",
        sequence=sequence,
        type="artifact.written",
        timestamp="2026-08-13T08:00:00Z",
        payload={
            "artifact_id": artifact_id or f"evidence-bundle:{digest}",
            "kind": "evidence-bundle",
            "media_type": "application/json",
            "content_sha256": digest,
            "locator": f"evidence/{digest}.json",
            "state_key": "news_window_bundle",
            "committed_sequence": committed,
        },
    )


class Store:
    def __init__(self, events, artifacts):
        self.events = events
        self.artifacts = artifacts

    def read_events(self, _run_id):
        return self.events

    def read_artifact(self, _run_id, artifact_id):
        return self.artifacts[artifact_id]


def test_later_committed_bundle_wins_deterministically() -> None:
    first_raw = _bundle("AAPL", horizon="medium")
    second_raw = _bundle("AAPL", horizon="long")
    first = _event(first_raw, sequence=2, committed=5)
    second = _event(second_raw, sequence=4, committed=8)
    store = Store(
        [first, second],
        {
            first.payload["artifact_id"]: first_raw,
            second.payload["artifact_id"]: second_raw,
        },
    )

    registry = build_evidence_registry(store, "run_test", expected_ticker="AAPL")

    selected = registry.evidence_by_state_key["news_window_bundle"]
    assert selected.artifact_id == second.payload["artifact_id"]
    assert registry.get_capability_results("official_disclosures")[0].effective_period == (
        "5_years"
    )


def test_corrupt_selected_retry_does_not_fall_back_to_older_bundle() -> None:
    first_raw = _bundle("AAPL", horizon="medium")
    corrupt_raw = b"not the declared artifact"
    first = _event(first_raw, sequence=2, committed=5)
    selected = _event(first_raw, sequence=4, committed=8, artifact_id="selected")
    store = Store(
        [first, selected],
        {
            first.payload["artifact_id"]: first_raw,
            selected.payload["artifact_id"]: corrupt_raw,
        },
    )

    with pytest.raises(
        ResearchIntegrityError, match="evidence_artifact_hash_mismatch"
    ):
        build_evidence_registry(store, "run_test", expected_ticker="AAPL")


def test_selected_bundle_identity_conflict_is_fatal() -> None:
    raw = _bundle("AAPL", horizon="medium")
    event = _event(raw, sequence=2, committed=5)
    store = Store([event], {event.payload["artifact_id"]: raw})

    with pytest.raises(
        ResearchIntegrityError, match="evidence_instrument_identity_conflict"
    ):
        build_evidence_registry(store, "run_test", expected_ticker="MSFT")


def test_news_publication_indexes_fixed_and_typed_capabilities() -> None:
    bundle = json.loads(_bundle("AAPL", horizon="medium"))

    assert _extract_bundle_capabilities("news_window_bundle", bundle) == (
        "company_event_window",
        "official_disclosures",
    )
    indexed = _extract_bundle_result_ids(bundle)
    assert indexed == {
        "official_disclosures": bundle["results"][0]["capability_result_id"]
    }
    summary = _extract_bundle_result_summaries(bundle)[0]
    assert summary["availability"] == "not_supported"
    assert summary["freshness"] == "unknown"
    assert summary["providers"] == ["sec"]
    assert summary["reason_codes"] == [
        "official_filings_provider_not_implemented"
    ]


def test_publication_rejects_duplicate_typed_capability() -> None:
    bundle = json.loads(_bundle("AAPL", horizon="medium"))
    bundle["results"].append(dict(bundle["results"][0]))

    with pytest.raises(ValueError, match="duplicate capability result"):
        _extract_bundle_result_ids(bundle)
