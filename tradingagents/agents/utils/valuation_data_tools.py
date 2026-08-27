"""Code-owned valuation prefetch bundle for the learning research chain.

Fetches the two deterministic inputs the valuation decision chain needs:

* ``valuation_snapshot`` -- Tencent realtime quote row (price, PE-TTM, PB,
  market cap) for the current position labels;
* ``valuation_history`` -- baostock daily PE/PB/PS history over a ~3 year
  window for the own-history percentile bands.

Both failures degrade independently inside one canonical JSON bundle stored
under the ``valuation_bundle`` state key.  Non-A-share tickers produce an
explicit ``not_applicable`` bundle, mirroring a_share_supplement_tools.

Point-in-time discipline: history is fetched only up to the analysis date, so
replaying a historical run cannot observe future multiples.  The realtime
snapshot is inherently "now" and is dated with its retrieval day.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.dataflows.errors import DataSourceUnavailableError, VendorError
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.ticker_utils import is_a_share_ticker

_HISTORY_LOOKBACK_DAYS = 1100  # ~3 trading years of calendar window


def _current_shanghai_date() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _coverage(
    capability: str,
    route_method: str,
    completeness: str,
    as_of: str,
    degradations: tuple[str, ...],
) -> dict[str, object]:
    """Uniform coverage envelope so evidence registry can track each result."""
    return {
        "capability": capability,
        "source_id": route_method,
        "requested_start": "",
        "requested_end": as_of,
        "actual_start": "",
        "actual_end": as_of,
        "item_count": 0,
        "completeness": completeness,
        "sources": [route_method],
        "degradations": list(degradations),
        "as_of": as_of,
    }


def _fetch_result(
    capability: str,
    route_method: str,
    invoke: object,
    as_of: str,
) -> dict[str, object]:
    try:
        raw = invoke()
    except Exception as exc:
        public_type = (
            "source_unavailable"
            if isinstance(exc, (DataSourceUnavailableError, VendorError))
            else "source_failed"
        )
        return {
            "capability": capability,
            "route_method": route_method,
            "status": "unavailable",
            "degradations": ["capability_unavailable"],
            "error_type": public_type,
            "coverage": _coverage(capability, route_method, "unavailable", as_of, ("source_unavailable",)),
        }
    rendered = str(raw)
    if not rendered or rendered.startswith(("NO_DATA_AVAILABLE:", "Data unavailable")):
        return {
            "capability": capability,
            "route_method": route_method,
            "status": "unavailable",
            "degradations": ["no_usable_data"],
            "coverage": _coverage(capability, route_method, "unavailable", as_of, ("no_usable_data",)),
        }
    return {
        "capability": capability,
        "route_method": route_method,
        "status": "ok",
        "data": rendered,
        "coverage": _coverage(capability, route_method, "complete", as_of, ()),
    }


def run_valuation_prefetch(ticker: str, analysis_date: str) -> str:
    """Return the canonical ``valuation_bundle`` JSON string."""
    if not is_a_share_ticker(ticker):
        return json.dumps(
            {
                "schema_version": 1,
                "ticker": ticker,
                "as_of": analysis_date,
                "status": "not_applicable",
                "results": [],
            },
            ensure_ascii=False,
        )

    # Point-in-time discipline: never fetch valuation history beyond the
    # analysis date, so replaying a historical run cannot see future multiples.
    try:
        requested_end = date.fromisoformat(analysis_date[:10])
    except ValueError:
        requested_end = None
    today = date.fromisoformat(_current_shanghai_date())
    end_date = (
        min(requested_end, today).isoformat() if requested_end is not None else today.isoformat()
    )
    start_date = (date.fromisoformat(end_date) - timedelta(days=_HISTORY_LOOKBACK_DAYS)).isoformat()
    results = [
        _fetch_result(
            "valuation_snapshot",
            "get_a_share_valuation",
            lambda: route_to_vendor("get_a_share_valuation", ticker),
            end_date,
        ),
        _fetch_result(
            "valuation_history",
            "get_a_share_valuation_history",
            lambda: route_to_vendor(
                "get_a_share_valuation_history", ticker, start_date, end_date
            ),
            end_date,
        ),
    ]
    ok_count = sum(item["status"] == "ok" for item in results)
    status = "ok" if ok_count == len(results) else ("partial" if ok_count else "unavailable")
    return json.dumps(
        {
            "schema_version": 1,
            "ticker": ticker,
            "as_of": analysis_date,
            "history_start": start_date,
            "status": status,
            "results": results,
        },
        ensure_ascii=False,
    )


def create_valuation_prefetch_node():
    """Create the graph task that owns valuation evidence prefetching."""

    def prefetch(state: Mapping[str, Any]) -> dict[str, str]:
        return {
            "valuation_bundle": run_valuation_prefetch(
                str(state["company_of_interest"]),
                str(state["trade_date"]),
            )
        }

    return prefetch
