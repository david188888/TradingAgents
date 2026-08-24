"""Regression tests for the bounded, keyless EastMoney capability adapters."""

from __future__ import annotations

import copy

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows import eastmoney, interface
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.errors import RateLimitError, VendorAccessDeniedError, VendorHTTPError


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, responses: list[object]) -> None:
        self.headers: dict[str, str] = {}
        self.responses = iter(responses)
        self.calls: list[dict] = []

    def get(self, url, *, params, timeout, headers=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout, "headers": headers})
        next_value = next(self.responses)
        if isinstance(next_value, Exception):
            raise next_value
        return next_value


def test_em_client_serializes_requests_with_minimum_pacing():
    now = [0.0]
    sleeps: list[float] = []
    session = _Session([_Response(200, {}), _Response(200, {})])
    client = eastmoney.EastMoneyHTTPClient(
        session=session,
        policy=eastmoney.EastMoneyRequestPolicy(jitter_seconds=0),
        clock=lambda: now[0],
        sleeper=lambda seconds: (sleeps.append(seconds), now.__setitem__(0, now[0] + seconds)),
        jitter=lambda _start, _end: 0.0,
    )

    client.get("https://example.test/first")
    client.get("https://example.test/second")

    assert sleeps == [1.0]
    assert session.headers["Connection"] == "keep-alive"
    assert len(session.calls) == 2


def test_em_client_retries_429_then_raises_typed_rate_limit():
    sleeps: list[float] = []
    session = _Session([_Response(429, {}), _Response(429, {}), _Response(429, {})])
    client = eastmoney.EastMoneyHTTPClient(
        session=session,
        policy=eastmoney.EastMoneyRequestPolicy(jitter_seconds=0),
        sleeper=sleeps.append,
        jitter=lambda _start, _end: 0.0,
    )

    with pytest.raises(RateLimitError):
        client.get("https://example.test/rate-limit")

    assert sleeps == [1.0, 2.0]


def test_em_client_does_not_retry_forbidden_response():
    session = _Session([_Response(403, {})])
    client = eastmoney.EastMoneyHTTPClient(session=session)

    with pytest.raises(VendorAccessDeniedError):
        client.get("https://example.test/forbidden")

    assert len(session.calls) == 1


def test_typed_http_failure_maps_to_router_cooldown_policy():
    assert interface._cooldown_for_exception(VendorHTTPError("eastmoney", 503)) == (20.0, "http_503")
    assert interface._cooldown_for_exception(VendorHTTPError("eastmoney", 0)) == (20.0, "network")
    assert interface._cooldown_for_exception(VendorAccessDeniedError("eastmoney", 403)) == (0.0, "forbidden")


def test_em_get_rejects_non_object_json():
    client = eastmoney.EastMoneyHTTPClient(session=_Session([_Response(200, [])]))

    with pytest.raises(VendorHTTPError, match="JSON root is not an object"):
        eastmoney.em_get("https://example.test/json", client=client)


def test_capital_flow_uses_shanghai_secid_and_reports_source(monkeypatch):
    observed: dict = {}

    def fake_em_get(url, *, params, **_kwargs):
        observed.update({"url": url, "params": params})
        return {"data": {"klines": ["2026-07-20,100,20,30,40,50,10.20,1.2"]}}

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    report = eastmoney.get_a_share_capital_flow("600519", "2026-07-01", "2026-07-20")

    assert observed["url"] == eastmoney.EASTMONEY_PUSH2_URL
    assert observed["params"]["secid"] == "1.600519"
    assert "Source: eastmoney" in report
    assert "Main Net Inflow" in report
    assert "2026-07-20" in report


def test_margin_financing_is_a_safe_empty_data_failure(monkeypatch):
    monkeypatch.setattr(eastmoney, "em_get", lambda *_args, **_kwargs: {"result": {"data": []}})

    with pytest.raises(ChinaDataUnavailableError, match="no margin-financing"):
        eastmoney.get_a_share_margin_financing("000001")


def test_margin_financing_filters_by_scode_and_renders_rows(monkeypatch):
    # RPTA_WEB_RZRQ_GGMX keys the security by SCODE; filtering on SECURITY_CODE
    # silently matches zero rows for every ticker (regression guard).
    captured = {}

    def fake_em_get(url, *, params, **_kwargs):
        captured["params"] = params
        return {"result": {"data": [{"DATE": "2026-08-03", "SCODE": "688825", "SECNAME": "x", "RZYE": 1}]}}

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    report = eastmoney.get_a_share_margin_financing("688825")

    flt = captured["params"]["filter"]
    assert 'SCODE="688825"' in flt
    assert "SECURITY_CODE" not in flt
    assert captured["params"]["sortColumns"] == "DATE"
    assert "688825" in report


def test_margin_financing_preserves_legacy_curr_date_keyword(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: {
            "result": {"data": [{"DATE": "2026-08-03", "SCODE": "688825", "RZYE": 1}]}
        },
    )

    report = eastmoney.get_a_share_margin_financing("688825", curr_date="2026-08-03")

    assert "# Actual window: 2026-08-03 to 2026-08-03" in report


def test_margin_financing_filters_requested_window_and_reports_actual_window(monkeypatch):
    def fake_em_get(url, *, params, **_kwargs):
        return {
            "result": {
                "data": [
                    {"DATE": "2026-07-31", "SCODE": "688825", "RZYE": 3},
                    {"DATE": "2026-07-15", "SCODE": "688825", "RZYE": 2},
                    {"DATE": "2026-06-30", "SCODE": "688825", "RZYE": 1},
                ]
            }
        }

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    report = eastmoney.get_a_share_margin_financing(
        "688825", "2026-07-01", "2026-07-31"
    )

    assert "# Requested window: 2026-07-01 to 2026-07-31" in report
    assert "# Actual window: 2026-07-15 to 2026-07-31" in report
    assert "# Coverage completeness: partial" in report
    assert "2026-06-30" not in report


def test_margin_financing_marks_unexhausted_first_page_partial(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: {
            "result": {
                "pages": 3,
                "data": [{"DATE": "2026-07-31", "SCODE": "688825", "RZYE": 3}],
            }
        },
    )

    report = eastmoney.get_a_share_margin_financing(
        "688825", "2026-07-01", "2026-07-31"
    )

    assert "# Coverage completeness: partial" in report
    assert "# Pagination: pages=1; exhausted=false" in report


def test_margin_financing_does_not_call_incomplete_end_window_complete(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: {
            "result": {
                "pages": 1,
                "data": [
                    {"DATE": "2026-07-01", "SCODE": "688825", "RZYE": 1},
                    {"DATE": "2026-07-30", "SCODE": "688825", "RZYE": 2},
                ],
            }
        },
    )

    report = eastmoney.get_a_share_margin_financing(
        "688825", "2026-07-01", "2026-07-31"
    )

    assert "# Coverage completeness: partial" in report
    assert "# Pagination: pages=1; exhausted=true" in report


def test_margin_financing_rejects_single_sided_new_window(monkeypatch):
    with pytest.raises(ValueError, match="start_date and end_date"):
        eastmoney.get_a_share_margin_financing("688825", end_date="2026-07-31")


def test_capital_flow_sina_backup_parses_and_labels_source(monkeypatch):
    class _FakeResp:
        text = '[{"opendate":"2026-07-20","trade":"10.5","netamount":"100000","turnover":"5000000"}]'

    monkeypatch.setattr(eastmoney.requests, "get", lambda *args, **kwargs: _FakeResp())

    report = eastmoney.get_a_share_capital_flow_sina("000001", "2026-07-01", "2026-07-20")

    assert "# Source: sina" in report
    assert "Sina backup" in report
    assert "2026-07-20" in report
    assert "100000" in report


def test_capital_flow_sina_filters_and_reports_observed_window(monkeypatch):
    class _FakeResp:
        text = (
            '[{"opendate":"2026-07-20","trade":"10.5","netamount":"100","turnover":"500"},'
            '{"opendate":"2026-06-30","trade":"9.5","netamount":"50","turnover":"400"}]'
        )

    monkeypatch.setattr(eastmoney.requests, "get", lambda *args, **kwargs: _FakeResp())

    report = eastmoney.get_a_share_capital_flow_sina(
        "000001", "2026-07-01", "2026-07-31"
    )

    assert "# Actual window: 2026-07-20 to 2026-07-20" in report
    assert "# Coverage completeness: partial" in report
    assert "2026-06-30" not in report


def test_capital_flow_sina_backup_raises_on_empty(monkeypatch):
    class _FakeResp:
        text = "[]"

    monkeypatch.setattr(eastmoney.requests, "get", lambda *args, **kwargs: _FakeResp())

    with pytest.raises(ChinaDataUnavailableError, match="no capital-flow rows"):
        eastmoney.get_a_share_capital_flow_sina("000001")


def test_capital_flow_falls_back_to_sina_when_eastmoney_fails(monkeypatch):
    """EastMoney failure degrades to the Sina backup via the router fallback chain."""
    monkeypatch.setattr(interface, "get_vendor", lambda _category, method=None: "default")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_a_share_capital_flow",
        {
            "eastmoney": lambda *_args, **_kwargs: (_ for _ in ()).throw(ChinaDataUnavailableError("eastmoney down")),
            "sina": lambda *_args, **_kwargs: "sina capital flow",
        },
    )

    assert interface.route_to_vendor("get_a_share_capital_flow", "600519") == "sina capital flow"


def test_a_share_capability_routes_through_eastmoney_and_non_a_share_skips(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(interface, "get_vendor", lambda _category, method=None: "eastmoney")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_a_share_capital_flow",
        {"eastmoney": lambda *_args, **_kwargs: calls.append("eastmoney") or "capital flow"},
    )

    assert interface.route_to_vendor("get_a_share_capital_flow", "600519") == "capital flow"
    assert calls == ["eastmoney"]

    with pytest.raises(RuntimeError, match="No available vendor"):
        interface.route_to_vendor("get_a_share_capital_flow", "AAPL")
    assert calls == ["eastmoney"]


@pytest.fixture(autouse=True)
def _reset_dataflow_config():
    # This module changes no config itself, but mirrors the router tests and
    # prevents an earlier test module's mutable global config from leaking in.
    import tradingagents.dataflows.config as config_module

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
