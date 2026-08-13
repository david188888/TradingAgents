from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.dataflows.capability_result import parse_capability_result
from tradingagents.execution.output_publisher import (
    _extract_bundle_capabilities,
    _extract_bundle_result_ids,
    _extract_bundle_result_summaries,
)
from tradingagents.observability.events import RunEventDraft
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
from tradingagents.research.case_assembly import assemble_partial_research_case
from tradingagents.research.evidence_registry import build_evidence_registry
from tradingagents.research.integrity import ResearchIntegrityError
from tradingagents.research.official_disclosures import (
    build_official_disclosure_result,
)
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.reader_projection import project_reader

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


def test_registry_rejects_typed_result_without_declared_id() -> None:
    bundle = json.loads(_bundle("AAPL", horizon="medium"))
    bundle["results"][0].pop("capability_result_id")
    raw = json.dumps(bundle, sort_keys=True).encode()
    event = _event(raw, sequence=2, committed=5)
    store = Store([event], {event.payload["artifact_id"]: raw})

    with pytest.raises(
        ResearchIntegrityError, match="capability_result_contract_invalid"
    ):
        build_evidence_registry(store, "run_test", expected_ticker="AAPL")


def test_registry_rejects_half_typed_wrapper() -> None:
    bundle = json.loads(_bundle("AAPL", horizon="medium"))
    bundle["results"][0].pop("capability_result")
    raw = json.dumps(bundle, sort_keys=True).encode()
    event = _event(raw, sequence=2, committed=5)
    store = Store([event], {event.payload["artifact_id"]: raw})

    with pytest.raises(
        ResearchIntegrityError, match="capability_result_contract_invalid"
    ):
        build_evidence_registry(store, "run_test", expected_ticker="AAPL")


def test_registry_rejects_inner_typed_result_identity_conflict() -> None:
    bundle = json.loads(_bundle("AAPL", horizon="medium"))
    semantic = dict(bundle["results"][0]["capability_result"])
    semantic["symbol"] = "MSFT"
    result = parse_capability_result(semantic)
    bundle["results"][0]["capability_result"] = result.semantic_payload()
    bundle["results"][0]["capability_result_id"] = result.capability_result_id
    raw = json.dumps(bundle, sort_keys=True).encode()
    event = _event(raw, sequence=2, committed=5)
    store = Store([event], {event.payload["artifact_id"]: raw})

    with pytest.raises(
        ResearchIntegrityError, match="evidence_instrument_identity_conflict"
    ):
        build_evidence_registry(store, "run_test", expected_ticker="AAPL")


def _frozen_pre_s1_v2_bundle() -> dict:
    """Legacy v2 fixture captured before discriminated S1 result contracts."""

    result = {
        "schema_version": 1,
        "capability": "official_disclosures",
        "symbol": "AAPL",
        "market": "global",
        "analysis_date": "2026-08-13",
        "analysis_cutoff_at": "2026-08-14T03:59:59.999999+00:00",
        "availability": "not_supported",
        "freshness": "unknown",
        "coverage": {
            "capability": "official_disclosures",
            "records": [
                {
                    "capability": "official_disclosures",
                    "source_id": "sec.company_filings",
                    "requested_start": "2022-08-13",
                    "requested_end": "2026-08-13",
                    "actual_start": None,
                    "actual_end": None,
                    "item_count": 0,
                    "page_count": None,
                    "pagination_exhausted": None,
                    "completeness": "unavailable",
                    "sources": ["sec.company_filings"],
                    "degradations": [
                        "official_filings_provider_not_implemented"
                    ],
                    "as_of": "2026-08-13",
                }
            ],
            "required_source_ids": ["sec.company_filings"],
            "required_source_groups": [],
            "optional_source_ids": [],
            "bundle_completeness": "unavailable",
        },
        "source_ids": ["sec.company_filings"],
        "attempts": [
            {
                "source_id": "sec.company_filings",
                "provider": "sec",
                "outcome": "not_supported",
                "reason_code": "official_filings_provider_not_implemented",
                "recorded_at": "2026-08-13T08:00:00+00:00",
                "started_at": None,
                "ended_at": None,
                "vendor_call_id": None,
                "provenance_artifact_id": None,
            }
        ],
        "fallback_from": [],
        "effective_period": "4_years",
        "published_at_or_filing_at": None,
        "source_observed_at": None,
        "fetched_at": None,
        "degradation_codes": ["official_filings_provider_not_implemented"],
        "limitations": ["official_filings_provider_not_implemented"],
    }
    result_id = "f66ea73278757807c8431ccb03db576680730f56458cd961444b7e99238e2c32"
    return {
        "ticker": "AAPL",
        "as_of": "2026-08-13",
        "results": [
            {
                "capability": "official_disclosures",
                "status": "unavailable",
                "requirement": "required",
                "data": "",
                "error_type": None,
                "capability_result_id": result_id,
                "capability_result": result,
            }
        ],
    }


class _ReadOnlyReplayStore:
    """Expose only the three read operations used by Registry and Reader."""

    def __init__(self, store: RunStore) -> None:
        self._store = store

    def read_snapshot(self, run_id: str):
        return self._store.read_snapshot(run_id)

    def read_events(self, run_id: str):
        return self._store.read_events(run_id)

    def read_artifact(self, run_id: str, artifact_id: str):
        return self._store.read_artifact(run_id, artifact_id)


def test_frozen_pre_s1_v2_registry_case_and_reader_replay_without_writes(
    tmp_path,
) -> None:
    run_id = "run_20260813T080000000000Z_1234abcd"
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(
        run_id=run_id,
        ticker="AAPL",
        analysis_date="2026-08-13",
        horizon="medium",
        mode="company_research",
    )
    store.create_run(snapshot)
    bundle = _frozen_pre_s1_v2_bundle()
    evidence = store.store_artifact(
        run_id,
        kind="evidence-bundle",
        value=json.dumps(bundle, sort_keys=True),
        media_type="application/json",
    )
    frozen_result_id = bundle["results"][0]["capability_result_id"]
    store.append_event(
        RunEventDraft(
            run_id,
            "artifact.written",
            {
                "artifact_id": evidence.artifact_id,
                "kind": evidence.kind,
                "media_type": evidence.media_type,
                "content_sha256": evidence.content_sha256,
                "byte_size": evidence.byte_size,
                "locator": evidence.locator,
                "state_key": "news_window_bundle",
                "capability_result_ids": {
                    "official_disclosures": frozen_result_id
                },
                "committed_sequence": 7,
            },
            status="committed",
        )
    )

    replay_store = _ReadOnlyReplayStore(store)
    registry = build_evidence_registry(
        replay_store, run_id, expected_ticker="AAPL"
    )
    assert registry.evidence_by_state_key["news_window_bundle"].artifact_id == (
        evidence.artifact_id
    )
    assert (
        registry.get_capability_results("official_disclosures")[0]
        .capability_result_id
        == frozen_result_id
    )

    case = assemble_partial_research_case(
        snapshot,
        source_sequence=7,
        evidence_verdict="PASS",
    )
    case_artifact = store.store_artifact(
        run_id,
        kind="research-case-v2",
        value=case.model_dump(mode="json"),
    )
    store.append_event(
        RunEventDraft(
            run_id,
            "artifact.written",
            {
                "artifact_id": case_artifact.artifact_id,
                "kind": case_artifact.kind,
                "media_type": case_artifact.media_type,
                "content_sha256": case_artifact.content_sha256,
                "byte_size": case_artifact.byte_size,
                "locator": case_artifact.locator,
                "public_contract": "research-case-v2",
                "committed_sequence": 8,
            },
            status="committed",
        )
    )
    events_before = store.read_events(run_id)

    reader = project_reader(replay_store, run_id)

    assert reader["kind"] == "typed"
    assert reader["run_id"] == run_id
    assert reader["ticker"] == "AAPL"
    assert store.read_events(run_id) == events_before
