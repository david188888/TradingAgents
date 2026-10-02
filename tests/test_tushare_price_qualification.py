"""Offline adjustment, cutoff and source-admission counterexamples."""

from datetime import datetime, timezone

import pytest

from tradingagents.dataflows.tushare_price_history import (
    PriceHistoryQualificationError,
    prepare_tushare_price_history,
    settled_sessions,
)

NOW = datetime(2026, 9, 30, 9, tzinfo=timezone.utc)


def inputs():
    calendar = [{"cal_date": f"202609{day}", "is_open": 1} for day in (28, 29, 30)]
    daily = [{"ts_code": "600519.SH", "trade_date": f"202609{day}",
        "open": close, "high": close + 1, "low": close - 1, "close": close}
        for day, close in ((28, 100), (29, 102), (30, 51))]
    factors = [{"ts_code": "600519.SH", "trade_date": f"202609{day}", "adj_factor": factor}
        for day, factor in ((28, 2), (29, 2), (30, 4))]
    return daily, factors, calendar


def prepare(daily, factors, calendar, **kwargs):
    return prepare_tushare_price_history(daily, factors, calendar,
        ts_code="600519.SH", start="2026-09-28", cutoff="2026-09-30", captured_at=NOW, **kwargs)


def test_dated_factor_join_removes_split_without_future_anchor():
    daily, factors, calendar = inputs()
    result = prepare(daily[::-1], factors, calendar)
    assert [row["Close"] for row in result["bars"]] == [50, 51, 51]
    assert result["bars"][0]["High"] == 50.5
    assert result["provenance"]["adjustment_anchor"] == "2026-09-30"
    assert result["provenance"]["pit_status"] == "verified"
    assert result["provenance"]["window_covered"] is True
    assert result["provenance"]["input_sha256"] == prepare(daily, factors[::-1], calendar[::-1])["provenance"]["input_sha256"]


def test_retrospective_capture_does_not_prove_historical_vintage():
    daily, factors, calendar = inputs()
    result = prepare_tushare_price_history(daily[:2], factors[:2], calendar[:2],
        ts_code="600519.SH", start="2026-09-28", cutoff="2026-09-29", captured_at=NOW)
    assert result["provenance"]["window_covered"] is True
    assert result["provenance"]["pit_status"] == "unverified"
    assert result["provenance"]["degradations"] == ["historical_factor_vintage_unverified"]


def test_calendar_gap_is_retained_without_filled_price():
    daily, factors, calendar = inputs()
    result = prepare([daily[0], daily[2]], factors, calendar)
    assert len(result["bars"]) == 2
    assert result["provenance"]["missing_sessions"] == ["2026-09-29"]
    assert result["provenance"]["window_covered"] is False


@pytest.mark.parametrize("pollution", ["wrong_security", "future_factor", "duplicate_price", "missing_factor", "nan_close", "bad_ohlc", "truncated_calendar"])
def test_polluted_responses_fail_closed(pollution):
    daily, factors, calendar = inputs()
    if pollution == "wrong_security":
        daily[0]["ts_code"] = "000001.SZ"
    elif pollution == "future_factor":
        factors.append({"ts_code": "600519.SH", "trade_date": "20261001", "adj_factor": 99})
    elif pollution == "duplicate_price":
        daily.append(daily[0])
    elif pollution == "missing_factor":
        factors.pop(1)
    elif pollution == "nan_close":
        daily[0]["close"] = float("nan")
    elif pollution == "bad_ohlc":
        daily[0]["high"] = 80
    else:
        calendar.pop(1)
    with pytest.raises(PriceHistoryQualificationError):
        prepare(daily, factors, calendar)


def test_current_unsettled_session_excluded_before_request():
    _, _, calendar = inputs()
    before_close = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)
    assert settled_sessions(calendar, start="2026-09-28", cutoff="2026-09-30", captured_at=before_close) == ("2026-09-28", "2026-09-29")


@pytest.mark.parametrize("cutoff, capture", [("2026-10-01", NOW), ("2026-09-30", NOW.replace(tzinfo=None))])
def test_future_cutoff_or_timezone_ambiguity_rejected(cutoff, capture):
    _, _, calendar = inputs()
    with pytest.raises(PriceHistoryQualificationError):
        settled_sessions(calendar, start="2026-09-28", cutoff=cutoff, captured_at=capture)


def source_fixture(monkeypatch, *, cutoff="2026-09-30", vendors="wind,tushare", failure=None):
    import tradingagents.dataflows.catalyst_sources as module
    from tradingagents.execution.models import AnalysisRequest

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(module, "datetime", Clock)
    req = AnalysisRequest("600519", cutoff, research_profile="catalyst_v1", effective_config={
        "data_vendors": {"core_stock_apis": "tushare"},
        "tool_vendors": {"get_adjusted_price_history": vendors},
    })
    daily, factors, calendar = inputs()
    source = module.CatalystSources(req, "price-admission", object(), lambda key, op: op())
    calls = []
    def query(api, fields, **params):
        calls.append((api, params))
        if api == "stock_basic":
            return [{"ts_code": "600519.SH", "name": "fixture", "list_date": "20260928", "exchange": "SSE", "market": "主板"}]
        if api == "trade_cal":
            return [row for row in calendar if row["cal_date"] <= params["end_date"]]
        if api in {"daily", "adj_factor"}:
            if failure == api:
                raise ValueError("simulated entitlement rejection")
            rows = daily if api == "daily" else factors
            return [row for row in rows if row["trade_date"] <= params["end_date"]]
        raise ValueError("unselected fixture capability")
    monkeypatch.setattr(source, "tushare", query)
    # A Tencent fallback must not be called when it was not selected.
    monkeypatch.setattr(module, "get_a_share_kline_qfq_df", lambda *a, **k: pytest.fail("unselected Tencent call"))
    return source, calls


def test_default_chain_uses_bounded_tushare_and_binds_price_evidence(monkeypatch):
    from tradingagents.research.evidence_freeze import (
        CAP_PRICE,
        CapabilityStatus,
        build_specialist_view,
    )
    source, calls = source_fixture(monkeypatch)
    draft, context = source.collect()
    capability = draft.capability(CAP_PRICE)
    assert capability.status == CapabilityStatus.QUALIFIED
    assert capability.detail["bounded_adapter_selection"]["unsupported_before_selected"] == ["wind"]
    assert [row.close for row in draft.prices] == [50, 51, 51]
    view = build_specialist_view(draft, "market_reaction")
    assert len(view.prices) == 3
    assert len(view.citable_evidence_ids) == 2  # identity and prices
    assert any(context[eid].get("provenance", {}).get("input_sha256") for eid in view.citable_evidence_ids)
    price_payload = next(context[eid] for eid in view.citable_evidence_ids if "provenance" in context[eid])
    assert price_payload["computed_statistics"]["return_statistics"]["status"] == "unavailable"
    assert capability.status == CapabilityStatus.QUALIFIED  # short sample only limits statistics
    assert {api for api, _ in calls} == {"stock_basic", "trade_cal", "daily", "adj_factor"}


def test_historical_unverified_prices_do_not_reach_specialist(monkeypatch):
    from tradingagents.research.evidence_freeze import (
        CAP_PRICE,
        CapabilityStatus,
        build_specialist_view,
    )
    source, _ = source_fixture(monkeypatch, cutoff="2026-09-29")
    draft, _ = source.collect()
    assert draft.capability(CAP_PRICE).status == CapabilityStatus.UNAVAILABLE
    assert draft.capability(CAP_PRICE).detail["pit_status"] == "unverified"
    assert draft.prices == ()
    assert build_specialist_view(draft, "market_reaction").prices == ()


@pytest.mark.parametrize("failure", ["daily", "adj_factor"])
def test_endpoint_permission_failure_never_becomes_empty_history(monkeypatch, failure):
    from tradingagents.research.evidence_freeze import CAP_PRICE, CapabilityStatus
    source, _ = source_fixture(monkeypatch, failure=failure)
    draft, context = source.collect()
    assert draft.capability(CAP_PRICE).status == CapabilityStatus.UNAVAILABLE
    assert draft.prices == ()
    assert all(record["capability"] != CAP_PRICE for record in draft.evidence)


def test_explicit_wind_only_never_substitutes_tushare_prices(monkeypatch):
    from tradingagents.research.evidence_freeze import CAP_PRICE, CapabilityStatus
    source, calls = source_fixture(monkeypatch, vendors="wind")
    draft, _ = source.collect()
    assert draft.capability(CAP_PRICE).status == CapabilityStatus.UNAVAILABLE
    assert [api for api, _ in calls] == ["stock_basic"]


def test_real_rest_adapter_charges_every_attempt_and_preserves_resume_consumption(monkeypatch):
    import json

    import requests

    from tradingagents.dataflows.catalyst_sources import CatalystSources
    from tradingagents.dataflows.catalyst_transport import BudgetedSession
    from tradingagents.execution.budget import BudgetBucket, BudgetLedger
    from tradingagents.research.evidence_freeze import CAP_PRICE, CapabilityStatus

    fixture, _ = source_fixture(monkeypatch)
    monkeypatch.setenv("TUSHARE_TOKEN", "non-secret-test-token")
    dispatches = []
    def send(session, prepared, **kwargs):
        assert kwargs["allow_redirects"] is False
        payload = json.loads(prepared.body)
        rows = fixture.tushare(payload["api_name"], payload["fields"], **payload["params"])
        fields = payload["fields"].split(",")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"code": 0, "data": {"fields": fields,
            "items": [[row[field] for field in fields] for row in rows]}}).encode()
        dispatches.append(payload["api_name"])
        return response
    monkeypatch.setattr(requests.Session, "send", send)
    ledger = BudgetLedger("bounded-prices")
    def fetch(key, operation):
        grant = ledger.reserve_or_raise(BudgetBucket.DATA_CAPABILITY_CALLS, stage="evidence", logical_call_id="data." + key)
        ledger.mark_dispatched(grant)
        value = operation()
        ledger.settle(grant, ok=True, usage_available=False)
        return value
    with BudgetedSession(ledger, lambda: None, lambda: 300) as session:
        draft, context = CatalystSources(fixture.request, "bounded-prices", session, fetch).collect()
    assert draft.capability(CAP_PRICE).status == CapabilityStatus.QUALIFIED
    assert dispatches == ["stock_basic", "trade_cal", "daily", "adj_factor"]
    assert ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 4
    assert ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 4
    restored = BudgetLedger("bounded-prices", records=ledger.records())
    assert restored.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 4
    assert restored.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 4
    assert any("computed_statistics" in value for value in context.values())
