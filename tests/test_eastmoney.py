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


def _envelope(data, *, pages=1, count=None, code=0, message=""):
    """The real EastMoney datacenter envelope the strict pager requires.

    The old single-page call accepted ``{"result": {"data": []}}``; that shape
    cannot distinguish a throttle from "no records", so every fake datacenter
    answer now carries ``code``/``pages``/``count``.
    """
    return {
        "code": code,
        "message": message,
        "result": {
            "pages": pages,
            "count": len(data) if count is None else count,
            "data": data,
        },
    }


def test_margin_financing_completed_empty_result_is_coverage_not_failure(monkeypatch):
    monkeypatch.setattr(eastmoney, "em_get", lambda *_args, **_kwargs: _envelope([], count=0))

    report = eastmoney.get_a_share_margin_financing("000001")

    assert isinstance(report, str)
    assert "# Coverage: complete (0 matching records)" in report
    assert "# Note:" in report
    assert "not a fetch failure" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 0


def test_margin_financing_page_one_9201_is_a_completed_empty_query(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: {"code": 9201, "message": "数据为空"},
    )

    report = eastmoney.get_a_share_margin_financing("000001")

    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 0


def test_margin_financing_nonzero_provider_code_raises(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: _envelope([], code=9501, message="sortTypes 个数不一致"),
    )

    with pytest.raises(ChinaDataUnavailableError, match="9501"):
        eastmoney.get_a_share_margin_financing("000001")


def test_margin_financing_filters_by_scode_and_renders_rows(monkeypatch):
    # RPTA_WEB_RZRQ_GGMX keys the security by SCODE; filtering on SECURITY_CODE
    # silently matches zero rows for every ticker (regression guard).
    captured = {}

    def fake_em_get(url, *, params, **_kwargs):
        captured["params"] = params
        return _envelope([{"DATE": "2026-08-03", "SCODE": "688825", "SECNAME": "x", "RZYE": 1}])

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    report = eastmoney.get_a_share_margin_financing("688825")

    flt = captured["params"]["filter"]
    assert 'SCODE="688825"' in flt
    assert "SECURITY_CODE" not in flt
    assert captured["params"]["sortColumns"] == "DATE"
    assert "688825" in report
    assert isinstance(report, str)
    assert report.coverage.completeness == "complete"
    assert report.coverage.requested_scope == "ticker=688825.SH window=*..*"


def test_margin_financing_rejects_rows_for_another_instrument(monkeypatch):
    # A filter the interface ignored must raise, never render another
    # instrument's margin balance as this ticker's.
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: _envelope(
            [{"DATE": "2026-08-03", "SCODE": "600519", "RZYE": 1}]
        ),
    )

    with pytest.raises(ChinaDataUnavailableError, match="结果不可信"):
        eastmoney.get_a_share_margin_financing("688825")


def test_margin_financing_preserves_legacy_curr_date_keyword(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: _envelope(
            [{"DATE": "2026-08-03", "SCODE": "688825", "RZYE": 1}]
        ),
    )

    report = eastmoney.get_a_share_margin_financing("688825", curr_date="2026-08-03")

    assert "# Actual window: 2026-08-03 to 2026-08-03" in report
    assert "# Requested as-of: 2026-08-03" in report


def test_margin_financing_filters_requested_window_and_reports_actual_window(monkeypatch):
    captured = {}

    def fake_em_get(_url, *, params, **_kwargs):
        captured["params"] = params
        return _envelope(
            [
                {"DATE": "2026-07-31", "SCODE": "688825", "RZYE": 3},
                {"DATE": "2026-07-15", "SCODE": "688825", "RZYE": 2},
            ]
        )

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    report = eastmoney.get_a_share_margin_financing(
        "688825", "2026-07-01", "2026-07-31"
    )

    assert "(DATE>='2026-07-01')" in captured["params"]["filter"]
    assert "(DATE<='2026-07-31')" in captured["params"]["filter"]
    assert "# Requested window: 2026-07-01 to 2026-07-31" in report
    assert "# Actual window: 2026-07-15 to 2026-07-31" in report
    assert "# Coverage: complete (2 matching records)" in report
    assert "# Coverage completeness: complete" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.degradations == ()


def test_margin_financing_rejects_out_of_window_rows(monkeypatch):
    # A server that ignored the DATE filter returns another window's row; the
    # adapter must not silently keep it (that is the old loose path's bug in
    # reverse: filtering client-side hid the provider's behavior).
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: _envelope(
            [{"DATE": "2026-06-30", "SCODE": "688825", "RZYE": 1}]
        ),
    )

    with pytest.raises(ChinaDataUnavailableError, match="结果不可信"):
        eastmoney.get_a_share_margin_financing("688825", "2026-07-01", "2026-07-31")


def test_margin_financing_completed_query_with_mid_window_rows_is_complete(monkeypatch):
    # A completed query is decided by pagination exhaustion and the reconciled
    # count, not by whether the rows touch both window edges: an instrument with
    # no record on the first/last day simply has no such row.  Marking this
    # `partial` would contradict `query_complete=True`.
    monkeypatch.setattr(
        eastmoney,
        "em_get",
        lambda *_args, **_kwargs: _envelope(
            [
                {
                    "DATE": "2026-09-18 00:00:00",
                    "SCODE": "600519",
                    "SECURITY_NAME_ABBR": "贵州茅台",
                    "RZYE": 100.0,
                }
            ]
        ),
    )

    report = eastmoney.get_a_share_margin_financing("600519.SH", "2026-09-01", "2026-09-30")

    assert "# Requested window: 2026-09-01 to 2026-09-30" in report
    assert "# Actual window: 2026-09-18 to 2026-09-18" in report
    assert report.coverage.completeness == "complete"
    assert report.coverage.item_count == 1
    assert report.coverage.query_complete is True
    assert report.coverage.degradations == ()
    assert "# Coverage completeness: partial" not in report


def test_margin_financing_row_cap_truncation_is_partial(monkeypatch):
    rows = [
        {"DATE": "2026-08-03", "SCODE": "688825", "RZYE": index}
        for index in range(2000)
    ]

    def fake_em_get(_url, *, params, **_kwargs):
        page = int(params["pageNumber"])
        start = (page - 1) * 500
        return _envelope(rows[start : start + 500], pages=5, count=2500)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)

    report = eastmoney.get_a_share_margin_financing("688825")

    assert "# Coverage: partial (2000 matching records)" in report
    assert report.coverage.completeness == "partial"
    assert report.coverage.pagination_exhausted is False
    assert report.coverage.page_count == 4
    assert report.coverage.item_count == 2000
    assert "row_cap_truncated" in report.coverage.degradations


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
