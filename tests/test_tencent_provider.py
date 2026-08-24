"""Unit tests for the Tencent Finance realtime valuation provider."""

from __future__ import annotations

import pytest

from tradingagents.dataflows import tencent_provider
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


def _tencent_raw(code: str = "000001", name: str = "平安银行") -> str:
    """Build one synthetic Tencent quote line with fields at the verified indices."""
    vals = [""] * 55
    vals[1] = name
    vals[2] = code
    vals[3] = "10.50"
    vals[4] = "10.40"  # last close
    vals[32] = "0.96"
    vals[37] = "1234.5"  # amount (wan)
    vals[38] = "3.21"
    vals[39] = "5.23"
    vals[44] = "2345.6"  # float market cap (yi)
    vals[45] = "2100.0"  # total market cap (yi)
    vals[46] = "1.12"
    vals[47] = "11.55"
    vals[48] = "9.45"
    return f'v_sz{code}="{"~".join(vals)}";'


def _tencent_stale_line(code: str = "832982", name: str = "锦波生物") -> str:
    """Build a frozen quote line (volume 0, price == last close)."""
    vals = [""] * 55
    vals[1] = name
    vals[2] = code
    vals[3] = "112.60"
    vals[4] = "112.60"  # price == last close -> frozen
    vals[37] = "0"  # amount 0 -> stale
    vals[44] = "50.0"
    vals[45] = "50.0"
    vals[46] = "3.0"
    return f'v_bj{code}="{"~".join(vals)}";'


def test_parse_tencent_line_extracts_valuation_fields():
    line = _tencent_raw("000001", "平安银行")
    row = tencent_provider._parse_tencent_line(line)

    assert row is not None
    assert row["Code"] == "000001"
    assert row["Name"] == "平安银行"
    assert row["PE TTM"] == 5.23
    assert row["PB"] == 1.12
    # 44 = float market cap, 45 = total market cap (a-stock-data §1.2).
    assert row["Float Cap (yi)"] == 2345.6
    assert row["Market Cap (yi)"] == 2100.0
    assert row["Limit Up"] == 11.55
    assert row["Is Stale"] is False


def test_parse_tencent_line_flags_stale_quote():
    row = tencent_provider._parse_tencent_line(_tencent_stale_line())

    assert row is not None
    assert row["Is Stale"] is True
    assert row["Price"] == row["Last Close"]
    assert row["Amount (wan)"] == 0
    # Old BSE segment (43/83/87) gets the migration hint.
    assert "920" in (row["Stale Reason"] or "")


def test_valuation_parses_and_labels_source(monkeypatch):
    class _FakeResp:
        content = _tencent_raw("000001", "平安银行").encode("gbk")

    monkeypatch.setattr(tencent_provider.requests, "get", lambda *a, **kw: _FakeResp())

    report = tencent_provider.get_a_share_valuation("000001")

    assert "Source: tencent" in report
    assert "平安银行" in report
    assert "PE TTM" in report


def test_valuation_rejects_non_a_share():
    with pytest.raises(ChinaDataUnavailableError, match="not recognized as an A-share"):
        tencent_provider.get_a_share_valuation("AAPL")


def test_valuation_raises_on_empty(monkeypatch):
    class _FakeResp:
        content = b'v_sz000001="";'

    monkeypatch.setattr(tencent_provider.requests, "get", lambda *a, **kw: _FakeResp())

    with pytest.raises(ChinaDataUnavailableError, match="no quote"):
        tencent_provider.get_a_share_valuation("000001")
