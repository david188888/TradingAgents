from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.config import config_scope
from tradingagents.dataflows.errors import VendorNotConfiguredError
from tradingagents.dataflows.index_provider import (
    EastMoneyIndexProvider,
    IndexDataUnavailableError,
    normalize_index_code,
)
from tradingagents.dataflows.risk_metrics import (
    RiskMetricsUnavailableError,
    calculate_local_risk_metrics,
)


def _snapshot_payload():
    return {
        "data": {
            "f43": 345678,
            "f44": 350000,
            "f45": 340000,
            "f46": 342000,
            "f47": 123456789,
            "f48": 987654321,
            "f60": 344000,
        }
    }


def _history_payload():
    return {
        "data": {
            "klines": [
                "2026-08-11,3400.00,3420.00,3430.00,3390.00,100,200",
                "2026-08-12,3420.00,3450.00,3460.00,3410.00,110,220",
            ]
        }
    }


def test_index_capability_falls_back_when_wind_is_unavailable(monkeypatch):
    calls = []

    def wind_impl(*args, **kwargs):
        calls.append("wind")
        raise VendorNotConfiguredError("Wind is disabled")

    def eastmoney_impl(*args, **kwargs):
        calls.append("eastmoney")
        return "eastmoney index fallback"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_index_snapshot",
        {"wind": wind_impl, "eastmoney": eastmoney_impl},
    )
    with config_scope(
        {
            "wind_enabled": False,
            "data_vendors": {"wind_index_data": "wind,eastmoney"},
        }
    ):
        result = interface.route_to_vendor("get_index_snapshot", "000300.SH")

    assert result == "eastmoney index fallback"
    assert calls == ["wind", "eastmoney"]


def test_index_code_requires_explicit_registered_identity():
    assert normalize_index_code("CSI300").canonical_code == "000300.SH"
    with pytest.raises(ValueError, match="unsupported or ambiguous"):
        normalize_index_code("000300")


def test_eastmoney_snapshot_scales_prices_and_renders_unknown_coverage(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "tradingagents.dataflows.index_provider.capture_vendor_raw",
        lambda payload, metadata: captured.append((payload, metadata)),
    )
    provider = EastMoneyIndexProvider(fetch_json=lambda params: _snapshot_payload())

    result = provider.snapshot("CSI300")
    rendered = result.render()

    assert result.identity.canonical_code == "000300.SH"
    assert result.last_price == Decimal("3456.78")
    assert result.previous_close == Decimal("3440")
    assert rendered.coverage.capability == "index_snapshot"
    assert rendered.coverage.completeness == "unknown"
    assert "Price unit: index points" in rendered
    assert captured[0][1]["dataset"] == "index_snapshot"


def test_eastmoney_history_validates_window_and_preserves_actual_dates(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.index_provider.capture_vendor_raw",
        lambda payload, metadata: None,
    )
    calls = []
    provider = EastMoneyIndexProvider(
        fetch_history_json=lambda params: calls.append(params) or _history_payload()
    )

    result = provider.history("000300.SH", "2026-08-01", "2026-08-12")
    rendered = result.render()

    assert len(result.rows) == 2
    assert calls[0]["beg"] == "20260801"
    assert calls[0]["end"] == "20260812"
    assert rendered.coverage.actual_start == "2026-08-11"
    assert rendered.coverage.actual_end == "2026-08-12"
    assert rendered.coverage.completeness == "unknown"

    with pytest.raises(ValueError, match="cannot be after"):
        provider.history("000300.SH", "2026-08-12", "2026-08-01")


def test_eastmoney_history_rejects_empty_rows():
    provider = EastMoneyIndexProvider(fetch_history_json=lambda params: {"data": {"klines": []}})
    with pytest.raises(IndexDataUnavailableError, match="no index history"):
        provider.history("CSI300", "2026-08-01", "2026-08-12")


def _series(values):
    start = date(2026, 1, 1)
    return pd.Series(
        values,
        index=[start + timedelta(days=offset) for offset in range(len(values))],
    )


def test_local_risk_metrics_are_deterministic_for_aligned_adjusted_prices():
    benchmark = _series([100 + 0.4 * i for i in range(25)])
    asset = _series([100 + 0.8 * i for i in range(25)])

    result = calculate_local_risk_metrics(
        asset,
        benchmark,
        benchmark_name="CSI300",
        minimum_returns=20,
    )

    assert result.observation_count == 24
    assert result.benchmark_name == "CSI300"
    assert result.annualized_volatility > 0
    assert result.sharpe_ratio > 0
    assert result.max_drawdown <= 0


def test_local_risk_metrics_fail_closed_for_insufficient_or_invalid_inputs():
    short = _series([100 + i for i in range(5)])
    with pytest.raises(RiskMetricsUnavailableError, match="at least 20"):
        calculate_local_risk_metrics(short, short, benchmark_name="CSI300")

    duplicate = pd.Series([100, 101], index=["2026-01-01", "2026-01-01"])
    with pytest.raises(RiskMetricsUnavailableError, match="duplicate"):
        calculate_local_risk_metrics(duplicate, duplicate, benchmark_name="CSI300")

    with pytest.raises(ValueError, match="benchmark_name"):
        calculate_local_risk_metrics(short, short, benchmark_name=" ")
