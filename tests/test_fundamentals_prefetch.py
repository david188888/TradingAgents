from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from tradingagents.dataflows.routing_trace import RouteAttemptTrace, RoutedVendorCall
from tradingagents.research.analysis_cutoff import resolve_analysis_cutoff
from tradingagents.research.evidence_registry import build_evidence_registry
from tradingagents.research.fundamentals_prefetch import (
    build_fundamentals_prefetch_bundle,
    statement_from_prefetch_bundle,
)

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _periods(count: int, *, annual: bool) -> list[str]:
    if annual:
        return [f"{year}-12-31" for year in range(2021, 2021 + count)]
    values = []
    for year in (2024, 2025):
        for month_day in ("03-31", "06-30", "09-30", "12-31"):
            values.append(f"{year}-{month_day}")
    return values[:count]


def _yfinance_fetch(
    method: str, symbol: str, frequency: str, analysis_date: str
) -> RoutedVendorCall:
    periods = _periods(5 if frequency == "annual" else 8, annual=frequency == "annual")
    result = "# Statement\n\nMetric," + ",".join(periods) + "\nRevenue," + ",".join(
        str(index + 1) for index in range(len(periods))
    )
    attempt = RouteAttemptTrace(
        vendor="yfinance",
        outcome="observed",
        reason_code="provider_payload_observed",
        recorded_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        vendor_call_id=f"{method}_call",
    )
    return RoutedVendorCall(result, None, (attempt,))


def test_medium_prefetch_builds_complete_quarterly_and_annual_results() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )
    bundle = build_fundamentals_prefetch_bundle(
        "AAPL",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_yfinance_fetch,
        recorded_at=NOW,
    )

    by_capability = {item["capability"]: item for item in bundle["results"]}
    quarterly = by_capability["fundamentals_quarterly"]["capability_result"]
    annual = by_capability["fundamentals_annual"]["capability_result"]
    assert quarterly["availability"] == "available"
    assert quarterly["coverage"]["bundle_completeness"] == "complete"
    assert annual["availability"] == "available"
    assert len(quarterly["attempts"]) == 6
    assert sum(item["outcome"] == "observed" for item in quarterly["attempts"]) == 3


def test_historical_unknown_filing_time_withholds_statement_and_limits_coverage() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2025-08-13", identity={"exchange": "NMS"}
    )
    bundle = build_fundamentals_prefetch_bundle(
        "AAPL",
        "2025-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_yfinance_fetch,
        recorded_at=NOW,
    )
    quarterly = next(
        item for item in bundle["results"] if item["capability"] == "fundamentals_quarterly"
    )

    assert quarterly["capability_result"]["availability"] == "partial"
    assert "historical_filing_time_unverified" in quarterly["capability_result"][
        "limitations"
    ]
    assert "withheld" in quarterly["statements"][0]["data"]


def test_prefetched_statement_is_reused_without_fetch() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )
    bundle = build_fundamentals_prefetch_bundle(
        "AAPL",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_yfinance_fetch,
        recorded_at=NOW,
    )

    statement = statement_from_prefetch_bundle(
        bundle, statement="income_statement", frequency="quarterly"
    )

    assert statement is not None
    assert "Revenue" in statement


def test_bundle_semantic_result_ids_are_stable() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )
    first = build_fundamentals_prefetch_bundle(
        "AAPL",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_yfinance_fetch,
        recorded_at=NOW,
    )
    second = build_fundamentals_prefetch_bundle(
        "AAPL",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_yfinance_fetch,
        recorded_at=NOW,
    )

    assert [item["capability_result_id"] for item in first["results"]] == [
        item["capability_result_id"] for item in second["results"]
    ]


def test_evidence_registry_registers_fundamentals_coverage() -> None:
    cutoff = resolve_analysis_cutoff(
        "AAPL", "2026-08-13", identity={"exchange": "NMS"}
    )
    bundle = build_fundamentals_prefetch_bundle(
        "AAPL",
        "2026-08-13",
        horizon="medium",
        cutoff=cutoff,
        fetch=_yfinance_fetch,
        recorded_at=NOW,
    )
    raw = json.dumps(bundle).encode("utf-8")
    event = SimpleNamespace(
        type="artifact.written",
        timestamp="2026-08-13T08:00:00Z",
        payload={
            "artifact_id": "artifact_fundamentals",
            "kind": "evidence-bundle",
            "media_type": "application/json",
            "locator": "artifacts/fundamentals.json",
            "state_key": "fundamentals_prefetch_bundle",
        },
    )

    class Store:
        def read_events(self, run_id):
            return [event]

        def read_artifact(self, run_id, artifact_id):
            return raw

    registry = build_evidence_registry(Store(), "run_test")

    assert registry.get_coverage("fundamentals_quarterly")[
        0
    ].envelope.bundle_completeness == "complete"
    assert registry.get_coverage("fundamentals_annual")[
        0
    ].envelope.bundle_completeness == "complete"
