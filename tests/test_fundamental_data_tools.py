from __future__ import annotations

import json

import pytest

from tradingagents.agents.utils import fundamental_data_tools as tools
from tradingagents.research.fundamentals_prefetch import (
    fundamentals_from_prefetch_bundle,
)


def _bundle(*, statement_data: str = "Revenue,1\n", status: str = "ok") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "ticker": "603019.SS",
            "status": "complete" if status == "ok" else "partial",
            "results": [
                {
                    "capability": "fundamentals_quarterly",
                    "status": status,
                    "statements": [
                        {
                            "statement": "income_statement",
                            "status": status,
                            "data": statement_data,
                            "reason_code": None if status == "ok" else "provider_unavailable",
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.unit
def test_comprehensive_fundamentals_reuses_frozen_bundle(monkeypatch):
    def fail_route(*_args, **_kwargs):
        raise AssertionError("comprehensive fundamentals must not re-route")

    monkeypatch.setattr(tools, "route_to_vendor", fail_route)

    result = tools.get_fundamentals.func(
        "603019.SS",
        "2026-08-13",
        state={"fundamentals_prefetch_bundle": _bundle()},
    )

    assert result.startswith("PREFETCHED_FUNDAMENTALS_BUNDLE:")
    assert "Revenue,1" in result


@pytest.mark.unit
def test_unavailable_prefetched_fundamentals_does_not_fall_through(monkeypatch):
    def fail_route(*_args, **_kwargs):
        raise AssertionError("unavailable prefetch must remain unavailable")

    monkeypatch.setattr(tools, "route_to_vendor", fail_route)

    result = tools.get_fundamentals.func(
        "603019.SS",
        "2026-08-13",
        state={"fundamentals_prefetch_bundle": _bundle(statement_data="", status="unavailable")},
    )

    assert result == "PREFETCHED_FUNDAMENTALS_UNAVAILABLE: provider_unavailable"


@pytest.mark.unit
def test_malformed_or_missing_bundle_keeps_compatibility_fallback(monkeypatch):
    monkeypatch.setattr(tools, "route_to_vendor", lambda *args: "legacy route")

    assert fundamentals_from_prefetch_bundle(None) is None
    assert tools.get_fundamentals.func("603019.SS", "2026-08-13", state=None) == "legacy route"
