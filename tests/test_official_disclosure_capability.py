from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from tradingagents.agents.utils.news_data_tools import run_news_windows
from tradingagents.dataflows.coverage import CoveredText, SourceCoverageV1
from tradingagents.dataflows.routing_trace import RouteAttemptTrace, RoutedVendorCall
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
from tradingagents.research.evidence_registry import build_evidence_registry
from tradingagents.research.official_disclosures import (
    build_official_disclosure_result,
)

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _cninfo_fetch(_symbol: str, start_date: str, _max_pages: int) -> RoutedVendorCall:
    coverage = SourceCoverageV1(
        capability="official_disclosures",
        source_id="cninfo.announcements",
        requested_start=start_date,
        requested_end="2026-08-13",
        actual_start=start_date,
        actual_end="2026-08-13",
        item_count=3,
        page_count=1,
        pagination_exhausted=True,
        completeness="complete",
        sources=("cninfo.announcements",),
        as_of="2026-08-13",
    )
    attempt = RouteAttemptTrace(
        vendor="cninfo",
        outcome="observed",
        reason_code="provider_payload_observed",
        recorded_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        vendor_call_id="cninfo_call",
    )
    return RoutedVendorCall(CoveredText("official records", coverage), None, (attempt,))


def test_a_share_official_disclosure_is_typed_and_complete() -> None:
    cutoff = resolve_analysis_cutoff("000338.SZ", "2026-08-13")

    wrapped = build_official_disclosure_result(
        "000338.SZ",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_cninfo_fetch,
        recorded_at=NOW,
    )

    result = wrapped["capability_result"]
    assert wrapped["status"] == "ok"
    assert result["availability"] == "available"
    assert result["coverage"]["bundle_completeness"] == "complete"
    assert [item["source_id"] for item in result["attempts"]] == [
        "cninfo.announcements",
        "exchange.announcements",
    ]
    assert result["attempts"][1]["outcome"] == "skipped_unobserved"


def test_global_official_disclosure_is_explicitly_not_supported() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )

    wrapped = build_official_disclosure_result(
        "AAPL",
        "2026-08-13",
        horizon="long",
        cutoff=cutoff,
        recorded_at=NOW,
    )

    result = wrapped["capability_result"]
    assert wrapped["status"] == "unavailable"
    assert result["availability"] == "not_supported"
    assert result["fetched_at"] is None
    assert result["attempts"][0]["reason_code"] == (
        "official_filings_provider_not_implemented"
    )


def test_eastmoney_fallback_cannot_satisfy_official_source_group() -> None:
    cutoff = resolve_analysis_cutoff("000338.SZ", "2026-08-13")

    def fetch(_symbol: str, _start: str, _pages: int) -> RoutedVendorCall:
        cninfo = RouteAttemptTrace(
            vendor="cninfo",
            outcome="provider_failed",
            reason_code="provider_request_failed",
            recorded_at=NOW,
            started_at=NOW,
            ended_at=NOW,
        )
        fallback = RouteAttemptTrace(
            vendor="china_exchange",
            outcome="observed",
            reason_code="provider_payload_observed",
            recorded_at=NOW,
            started_at=NOW,
            ended_at=NOW,
        )
        return RoutedVendorCall(
            "# Source: eastmoney\npublic fallback records",
            None,
            (cninfo, fallback),
        )

    wrapped = build_official_disclosure_result(
        "000338.SZ",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=fetch,
        recorded_at=NOW,
    )

    result = wrapped["capability_result"]
    assert result["availability"] == "invalid"
    assert result["attempts"][1]["outcome"] == "invalid_payload"
    assert result["attempts"][1]["reason_code"] == (
        "non_official_fallback_not_eligible"
    )


def test_news_bundle_persists_typed_global_negative_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "tradingagents.agents.utils.news_data_tools.route_to_vendor",
        lambda *_args, **_kwargs: "company news",
    )
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )

    bundle = json.loads(
        run_news_windows(
            "AAPL",
            "2026-08-13",
            horizon="medium",
            analysis_cutoff=cutoff,
        )
    )

    assert bundle["windows"]["official"]["status"] == "unavailable"
    official = next(
        item for item in bundle["results"] if item["capability"] == "official_disclosures"
    )
    assert official["capability_result"]["availability"] == (
        "not_supported"
    )


def test_registry_registers_negative_official_coverage() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )
    bundle = {
        "as_of": "2026-08-13",
        "results": [
            build_official_disclosure_result(
                "AAPL",
                "2026-08-13",
                horizon="medium",
                cutoff=cutoff,
                recorded_at=NOW,
            )
        ],
    }
    raw = json.dumps(bundle).encode("utf-8")
    event = SimpleNamespace(
        type="artifact.written",
        timestamp="2026-08-13T08:00:00Z",
        payload={
            "artifact_id": "artifact_news",
            "kind": "evidence-bundle",
            "media_type": "application/json",
            "locator": "artifacts/news.json",
            "state_key": "news_window_bundle",
        },
    )

    class Store:
        def read_events(self, _run_id):
            return [event]

        def read_artifact(self, _run_id, _artifact_id):
            return raw

    registry = build_evidence_registry(Store(), "run_test")

    official = registry.get_coverage("official_disclosures")
    assert official[0].envelope.bundle_completeness == "unavailable"
