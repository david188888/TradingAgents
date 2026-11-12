"""Contract tests for the A-share capital-flow adapters."""

from __future__ import annotations

import pytest

from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
from tradingagents.dataflows.china_capital_flow import ChinaCapitalFlowProvider


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
