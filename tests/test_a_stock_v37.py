"""Unit tests for the a-stock-data v3.7.0 supplement adapters."""

from __future__ import annotations

import io
import sys
import types

import pandas as pd
import pytest

from tradingagents.dataflows import a_stock_v37
from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _TextResp:
    def __init__(self, text: str = "", content: bytes = b"", payload: dict | None = None) -> None:
        self.text = text
        self.content = content
        self._payload = payload
        self.apparent_encoding = "utf-8"
        self.encoding = None

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload or {}


class _BSResult:
    error_code = "0"

    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.fields = fields
        self._rows = rows
        self._i = 0

    def next(self) -> bool:
        if self._i < len(self._rows):
            self._i += 1
            return True
        return False

    def get_row_data(self) -> list[str]:
        return self._rows[self._i - 1]


def _install_baostock_mock(monkeypatch) -> None:
    """Inject a fake baostock module so lazy imports resolve in-process."""
    mod = types.ModuleType("baostock")
    mod.login = lambda: type("R", (), {"error_code": "0"})()
    mod.logout = lambda: None
    mod.query_history_k_data_plus = lambda *a, **kw: _BSResult(
        ["date", "code", "close", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "turn", "tradestatus", "isST"],
        [["2026-08-18", "sh.600519", "1500.0", "30.0", "8.0", "9.0", "20.0", "0.3", "1", "0"]],
    )
    mod.query_stock_basic = lambda *a, **kw: _BSResult(
        ["code", "code_name", "ipoDate", "outDate", "type", "status"],
        [["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"]],
    )
    monkeypatch.setitem(sys.modules, "baostock", mod)


# ---------------------------------------------------------------------------
# §1.4 复权因子
# ---------------------------------------------------------------------------

def test_adjust_factors_parses(monkeypatch):
    body = 'var sh600519qfq={"data":[{"d":"2026-08-18","f":"1.0"},{"d":"2026-06-26","f":"1.12"}]};'
    monkeypatch.setattr(a_stock_v37.requests, "get", lambda *a, **kw: _TextResp(text=body))
    report = a_stock_v37.get_a_share_adjust_factors("600519", "qfq")
    assert "Source: sina" in report
    assert "2026-08-18,1.0" in report


def test_adjust_factors_hfq_kind_validation():
    with pytest.raises(ValueError, match="kind 只能是"):
        a_stock_v37.get_a_share_adjust_factors("600519", "bad")


# ---------------------------------------------------------------------------
# §6.5 / §6.6 baostock endpoints
# ---------------------------------------------------------------------------

def test_valuation_history_renders(monkeypatch):
    _install_baostock_mock(monkeypatch)
    report = a_stock_v37.get_a_share_valuation_history("600519")
    assert "Source: baostock" in report
    assert "1500.0" in report


def test_listing_history_renders(monkeypatch):
    _install_baostock_mock(monkeypatch)
    report = a_stock_v37.get_a_share_listing_history("600519")
    assert "Source: baostock" in report
    assert "贵州茅台" in report


@pytest.mark.parametrize("ticker", ["920982", "832982", "430047"])
def test_baostock_endpoints_reject_bse(ticker, monkeypatch):
    """baostock rejects BSE segments server-side; we fail before login."""
    _install_baostock_mock(monkeypatch)
    with pytest.raises(AshareCapabilityUnavailableError, match="北交所"):
        a_stock_v37.get_a_share_valuation_history(ticker)
    with pytest.raises(AshareCapabilityUnavailableError, match="北交所"):
        a_stock_v37.get_a_share_chip_distribution(ticker)


# ---------------------------------------------------------------------------
# §4.6 筹码分布（本地推导）
# ---------------------------------------------------------------------------

def test_chip_distribution_basic():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]),
            "high": [101.0, 102.0, 101.5],
            "low": [99.0, 100.0, 100.5],
            "close": [100.0, 101.0, 101.0],
            "turn": [1.0, 1.0, 1.0],
        }
    )
    r = a_stock_v37.chip_distribution(df)
    assert 0.0 <= r["profit_ratio"] <= 1.0
    assert r["cost_90"][0] <= r["cost_70"][0] <= r["cost_70"][1] <= r["cost_90"][1]
    assert r["peak_price"] > 0


def test_chip_distribution_limit_board():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "high": [100.0, 100.0],
            "low": [100.0, 100.0],
            "close": [100.0, 100.0],
            "turn": [0.5, 0.5],
        }
    )
    r = a_stock_v37.chip_distribution(df)
    assert r["profit_ratio"] == 1.0


def test_chip_distribution_missing_column():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-05"]), "high": [1.0], "low": [1.0], "close": [1.0]})
    with pytest.raises(ValueError, match="缺少列"):
        a_stock_v37.chip_distribution(df)


# ---------------------------------------------------------------------------
# §6.7 申万行业变迁史
# ---------------------------------------------------------------------------

def test_sw_industry_history_parses(monkeypatch):
    xls = io.BytesIO()
    pd.DataFrame(
        {
            "股票代码": ["600519", "000001"],
            "行业代码": ["480101", "480101"],
            "计入日期": ["2001-08-27", "1991-04-03"],
            "更新日期": ["2026-01-01", "2026-01-01"],
        }
    ).to_excel(xls, index=False)
    monkeypatch.setattr(
        a_stock_v37.requests, "get", lambda *a, **kw: _TextResp(content=xls.getvalue())
    )
    report = a_stock_v37.get_sw_industry_history()
    assert "Source: swsresearch" in report
    assert "600519,480101" in report


# ---------------------------------------------------------------------------
# §11.1 / §11.2 宏观层
# ---------------------------------------------------------------------------

def test_china_pmi_parses(monkeypatch):
    payload = {
        "returndata": {
            "datanodes": [
                {"wds": [{"wdcode": "sj", "valuecode": "2026-07"}, {"wdcode": "zb", "valuecode": "A090201"}], "data": {"data": "49.2"}},
                {"wds": [{"wdcode": "sj", "valuecode": "2026-07"}, {"wdcode": "zb", "valuecode": "A090202"}], "data": {"data": "49.0"}},
            ]
        }
    }
    monkeypatch.setattr(a_stock_v37.requests, "get", lambda *a, **kw: _TextResp(payload=payload))
    report = a_stock_v37.get_china_pmi()
    assert "Source: nbs" in report
    assert "2026-07,A090201,49.2" in report


def test_china_social_financing_three_hop(monkeypatch):
    xls = io.BytesIO()
    pd.DataFrame({"月份": ["2026-01", "2026-02"], "社会融资规模增量(亿元)": [72185.0, 68000.0]}).to_excel(xls, index=False)

    def fake_get(url: str, **kw) -> _TextResp:
        if "index.html" in url and "2026" not in url:
            return _TextResp(text='<a href="/diaochatongjisi/116219/116319/2026/index.html">2026年统计数据</a>')
        if "2026/index.html" in url:
            return _TextResp(text='<a href="/pbc/2026/topic.html">社会融资规模</a>')
        if "topic.html" in url:
            return _TextResp(text='<a href="/pbc/2026/sf.xls">社会融资规模增量统计表.xls</a>')
        if "sf.xls" in url:
            return _TextResp(content=xls.getvalue())
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(a_stock_v37.requests, "get", fake_get)
    report = a_stock_v37.get_china_social_financing()
    assert "Source: pbc" in report
    assert "2026-01,72185" in report


# ---------------------------------------------------------------------------
# 北交所 / 非 A 股防护
# ---------------------------------------------------------------------------

def test_ticker_guard_rejects_non_a_share():
    with pytest.raises(ChinaDataUnavailableError, match="not recognized as an A-share"):
        a_stock_v37.get_a_share_adjust_factors("AAPL", "qfq")
