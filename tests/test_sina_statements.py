"""Unit tests for the Sina direct financial-statement adapters.

The quotes.sina.cn HTTP call is monkeypatched with a synthetic payload shaped
like the real ``result.data.report_list`` response.
"""

from __future__ import annotations

import pytest

from tradingagents.dataflows import china_data
from tradingagents.dataflows.china_data import ChinaDataUnavailableError

# Shares the same result shape as a-stock-data §6.4.
_SINA_PAYLOAD = {
    "result": {
        "data": {
            "report_list": {
                "20260331": {
                    "data": [
                        {"item_title": "净利润", "item_value": "152.1"},
                        {"item_title": "营业总收入", "item_value": "1080.2"},
                    ]
                },
                "20251231": {
                    "data": [
                        {"item_title": "净利润", "item_value": "140.3"},
                        {"item_title": "营业总收入", "item_value": "990.1"},
                    ]
                },
            }
        }
    }
}


def _fake_sina_get(monkeypatch, payload=None):
    class _FakeResp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    calls = []
    monkeypatch.setattr(
        china_data.requests,
        "get",
        lambda *a, **kw: calls.append((a, kw)) or _FakeResp(payload or _SINA_PAYLOAD),
    )
    return calls


def test_income_statement_sina_parses_report_list(monkeypatch):
    _fake_sina_get(monkeypatch)
    report = china_data.get_income_statement_sina("600519", curr_date="2026-06-01")

    assert "# Source: sina direct" in report
    assert "Income Statement" in report
    assert "净利润" in report
    assert "152.1" in report  # newest period value present


def test_statement_respects_as_of_cutoff(monkeypatch):
    _fake_sina_get(monkeypatch)
    report = china_data.get_income_statement_sina("600519", curr_date="2026-01-01")

    # Only the 2025-12-31 period survives the as-of filter.
    assert "140.3" in report
    assert "152.1" not in report


def test_statement_empty_payload_raises(monkeypatch):
    _fake_sina_get(monkeypatch, payload={"result": {"data": {"report_list": {}}}})
    with pytest.raises(ChinaDataUnavailableError, match="no income statement data"):
        china_data.get_income_statement_sina("600519", curr_date="2026-06-01")


def test_statement_rejects_non_a_share():
    with pytest.raises(ChinaDataUnavailableError, match="not recognized as an A-share"):
        china_data.get_balance_sheet_sina("AAPL", curr_date="2026-06-01")


def test_all_three_statement_entry_points_hit_sina(monkeypatch):
    _fake_sina_get(monkeypatch)
    assert "Balance Sheet" in china_data.get_balance_sheet_sina("600519")
    assert "Cash Flow" in china_data.get_cashflow_sina("600519")
    assert "Income Statement" in china_data.get_income_statement_sina("600519")
