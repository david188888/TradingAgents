"""Contract tests for optional China capital-flow and macro source adapters."""

from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
from tradingagents.dataflows.china_capital_flow import ChinaCapitalFlowProvider
from tradingagents.dataflows.china_macro import ChinaMacroProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """Records requests and returns canned JSON for the direct-HTTP adapters."""

    def __init__(self, *, northbound=None, insider_rows=None):
        self.calls: list[tuple[str, dict]] = []
        self._northbound = northbound
        self._insider_rows = insider_rows or []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if "hexin" in url:
            return _FakeResponse(self._northbound or {"time": [], "hgt": [], "sgt": []})
        return _FakeResponse({"result": {"data": self._insider_rows}})


class _MacroApi:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def macro_china_gdp(self):
        self.calls.append("gdp")
        return pd.DataFrame([{"季度": "2026Q1", "国内生产总值": 1.0}])

    def macro_china_cpi(self):
        self.calls.append("cpi")
        return pd.DataFrame([{"月份": "2026-06", "同比": 0.1}])


def test_northbound_flow_uses_ths_series_and_keeps_scope_market_wide():
    session = _FakeSession(
        northbound={"time": ["09:30", "10:00"], "hgt": [1.5, 2.0], "sgt": [0.5, 0.8]}
    )

    report = ChinaCapitalFlowProvider(session).northbound_flow()

    assert report.ticker is None
    assert report.provider == "ths"
    assert report.data["time"].tolist() == ["09:30", "10:00"]
    assert report.data["hgt_net_buy_yi"].tolist() == [1.5, 2.0]
    assert "hexin" in session.calls[0][0]
    assert "Not a per-ticker attribution" in report.note


def test_insider_trades_filters_one_ticker_without_full_market_pagination():
    session = _FakeSession(
        insider_rows=[
            {"SECURITY_CODE": "600519", "HOLDER_NAME": "示例高管", "CHANGE_NUM": 100, "END_DATE": "2026-07-01 00:00:00"},
            {"SECURITY_CODE": "000001", "HOLDER_NAME": "他人", "CHANGE_NUM": 5, "END_DATE": "2026-07-01 00:00:00"},
        ]
    )

    report = ChinaCapitalFlowProvider(session).insider_trades("600519")

    assert report.ticker == "600519.SS"
    assert report.provider == "eastmoney"
    _, params = session.calls[0]
    assert 'SECURITY_CODE="600519"' in params["filter"]
    assert params["pageSize"] == "50"
    assert "must be verified against the source filing" in report.note


def test_capital_adapters_fail_closed_for_non_a_share_and_depleted_holdings():
    session = _FakeSession()
    provider = ChinaCapitalFlowProvider(session)

    with pytest.raises(AshareCapabilityUnavailableError, match="not an A-share ticker"):
        provider.insider_trades("AAPL")

    # Per-stock northbound holdings have had no usable upstream rows since the
    # 2024-08 disclosure cutoff; degrade fast instead of paginating the market.
    with pytest.raises(AshareCapabilityUnavailableError, match="disclosure cutoff"):
        provider.northbound_holdings("600519", "3日排行")

    assert session.calls == []


def test_china_macro_series_are_explicitly_labelled_and_partial_unavailability_is_visible():
    api = _MacroApi()

    report = ChinaMacroProvider(api).indicators("gdp,cpi,pmi")

    assert api.calls == ["gdp", "cpi"]
    assert set(report.data["indicator"]) == {"gdp", "cpi"}
    rendered = report.render()
    assert "Source: akshare" in rendered
    assert "no cycle stage is inferred" in rendered
    assert "Unavailable requested series: pmi:" in rendered


def test_china_macro_unknown_indicator_and_empty_provider_fail_closed():
    with pytest.raises(AshareCapabilityUnavailableError, match="unsupported indicator"):
        ChinaMacroProvider(_MacroApi()).indicators("gdp,imaginary")

    with pytest.raises(AshareCapabilityUnavailableError, match="has no macro_china_gdp adapter"):
        ChinaMacroProvider(object()).indicators("gdp")


def test_new_optional_capabilities_route_with_a_share_market_scope(monkeypatch):
    calls: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(interface, "get_vendor", lambda _category, method=None: "akshare")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_a_share_northbound_holdings",
        {"akshare": lambda *args: calls.append(("northbound", args)) or "holding rows"},
    )
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_china_macro_indicators",
        {"akshare": lambda *args: calls.append(("macro", args)) or "macro rows"},
    )

    assert interface.route_to_vendor("get_a_share_northbound_holdings", "600519") == "holding rows"
    assert interface.route_to_vendor("get_china_macro_indicators", "gdp,cpi") == "macro rows"
    assert interface._market_for_request(("gdp,cpi",), "get_china_macro_indicators") == "a_share"
    assert calls == [("northbound", ("600519",)), ("macro", ("gdp,cpi",))]
