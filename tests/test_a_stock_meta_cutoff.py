"""Offline cutoff regression for newly exposed live A-share source snapshots."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from tradingagents.agents.utils import data_meta_tools as meta
from tradingagents.dataflows.errors import VendorRequestError

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 2)
TICKER = "600519.SH"
LIVE_CAPABILITIES = (
    ("earnings_forecast", "eastmoney", "get_a_share_earnings_forecast", (TICKER,)),
    ("share_buyback", "eastmoney", "get_a_share_share_buyback", (TICKER,)),
    ("equity_pledge", "eastmoney", "get_a_share_equity_pledge", (TICKER,)),
    ("ipo_calendar", "eastmoney", "get_a_share_ipo_calendar", (30,)),
    ("sse_e_interaction", "sse_e", "get_a_share_sse_e_interaction", (TICKER, "questions")),
    ("sina_research_reports", "sina", "get_a_share_research_reports_sina", (TICKER,)),
)


@pytest.fixture
def routes(monkeypatch):
    calls = []
    monkeypatch.setattr(meta, "_current_a_share_date", lambda: TODAY)

    def route(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        return "source snapshot captured today"

    monkeypatch.setattr(meta, "route_to_vendor", route)
    return calls


@pytest.fixture(params=LIVE_CAPABILITIES, ids=lambda item: item[0])
def live(request):
    identity, source, method, args = request.param
    capability = next(item for item in meta._CAPABILITIES if item.id == identity)
    return capability, source, method, args


@pytest.mark.parametrize("cutoff", ["2020-01-01", "2026-10-03", "invalid", "20261002", None])
def test_live_wrapper_rejects_unqualified_cutoff_before_source_dispatch(routes, live, cutoff):
    capability, source, _, _ = live
    with pytest.raises(VendorRequestError) as caught:
        capability.runner(TICKER, cutoff, "research")
    assert caught.value.provider == source
    assert caught.value.detail in {"live_snapshot_cutoff_invalid", "live_snapshot_vintage_unavailable"}
    assert routes == []


def test_live_wrapper_preserves_current_day_source_contract(routes, live):
    capability, _, method, args = live
    assert capability.runner(TICKER, TODAY.isoformat(), "research") == "source snapshot captured today"
    assert routes == [(method, args, {})]


@pytest.mark.parametrize("model_cutoff", ["2020-01-01", "2026-10-03", "invalid"])
def test_historical_bundle_cannot_expose_live_snapshot_after_run_cutoff_clamp(
    monkeypatch, routes, live, model_cutoff
):
    capability, _, method, _ = live
    # Isolate this approved capability; unrelated defaults have separate tests.
    monkeypatch.setattr(meta, "select_capabilities", lambda *_: [capability])
    payload = json.loads(meta.run_data_bundle(
        capability.focus, TICKER, model_cutoff, "research", {"trade_date": "2020-01-01"}
    ))
    assert payload["as_of"] == "2020-01-01"
    assert payload["status"] == "degraded"
    assert payload["results"] == [{
        "capability": capability.id,
        "route_method": method,
        "status": "error",
        "error_type": "source_unavailable",
        "message": "The requested data capability is currently unavailable.",
    }]
    assert routes == []


def test_current_bundle_keeps_existing_scalar_cutoff_clamp(monkeypatch, routes, live):
    capability, _, method, args = live
    monkeypatch.setattr(meta, "select_capabilities", lambda *_: [capability])
    payload = json.loads(meta.run_data_bundle(
        capability.focus, TICKER, "2026-10-03", "research", {"trade_date": TODAY.isoformat()}
    ))
    assert payload["as_of"] == TODAY.isoformat()
    assert payload["status"] == "ok"
    assert payload["results"][0]["data"] == "source snapshot captured today"
    assert routes == [(method, args, {})]


def test_institution_survey_keeps_historical_notice_date_window(routes):
    assert meta._institution_survey(TICKER, "2020-01-01", "research") == "source snapshot captured today"
    assert routes == [(
        "get_a_share_institution_survey", (TICKER,), {"start": "2019-07-05", "end": "2020-01-01"}
    )]


def test_current_a_share_date_uses_shanghai_boundary(monkeypatch):
    class Clock:
        @staticmethod
        def now(zone):
            assert str(zone) == "Asia/Shanghai"
            return datetime(2026, 10, 1, 16, 1, tzinfo=timezone.utc).astimezone(zone)

    monkeypatch.setattr(meta, "datetime", Clock)
    assert meta._current_a_share_date() == date(2026, 10, 2)
