"""Offline contract tests for the shared EastMoney datacenter pager."""

from __future__ import annotations

from typing import Any

import pytest

from tradingagents.dataflows import eastmoney
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.eastmoney import (
    DatacenterPage,
    em_datacenter_strict,
    strict_date_arg,
    strict_limit,
    strict_number,
    strict_source_day,
)
from tradingagents.dataflows.errors import VendorHTTPError

# ---------------------------------------------------------------------------
# Offline gateway helpers
# ---------------------------------------------------------------------------


def _payload(
    data: list[dict[str, Any]],
    *,
    pages: int = 1,
    count: int | None = None,
    code: int = 0,
    message: str = "ok",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "result": {"pages": pages, "count": len(data) if count is None else count, "data": data},
    }


def _install(monkeypatch, responder):
    """Replace the EastMoney gateway with an offline responder and return its call log."""
    calls: list[dict[str, Any]] = []

    def fake_em_get(url, **kwargs):
        call = {"url": url, "params": dict(kwargs.get("params") or {})}
        calls.append(call)
        return responder(call)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    return calls


_SOURCE_ROW = {"SECURITY_CODE": "600519"}


def test_datacenter_9201_on_first_page_returns_empty(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 9201, "message": "返回数据为空"})
    page = em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")
    assert page == DatacenterPage(rows=[], pages=1, count=0, pages_fetched=1, truncated=False)
    assert page.pagination_exhausted is True


def test_datacenter_9201_after_first_page_raises(monkeypatch):
    def responder(call):
        if call["params"]["pageNumber"] == "1":
            return _payload([dict(_SOURCE_ROW), {**_SOURCE_ROW, "SECURITY_CODE": "000001"}],
                            pages=2, count=4)
        return {"code": 9201, "message": "返回数据为空"}

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="数据为空"):
        em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=2, max_rows=4
        )


def test_datacenter_non_zero_error_code_raises_with_code_and_message(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 9501, "message": "排序字段和顺序数量不一致",
                                        "result": None})
    with pytest.raises(ChinaDataUnavailableError, match=r"9501 排序字段和顺序数量不一致"):
        em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_short_non_final_page_raises(monkeypatch):
    def responder(call):
        return _payload([dict(_SOURCE_ROW), {**_SOURCE_ROW, "SECURITY_CODE": "000001"}],
                        pages=2, count=6)

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="非末页应为 3 条"):
        em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=3, max_rows=6
        )


def test_datacenter_empty_non_final_page_raises(monkeypatch):
    def responder(call):
        if call["params"]["pageNumber"] == "1":
            return _payload([dict(_SOURCE_ROW)], pages=2, count=2)
        return _payload([], pages=2, count=2)

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="页是空的"):
        em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=1, max_rows=2
        )


def test_datacenter_page_or_count_change_across_pages_raises(monkeypatch):
    def responder(call):
        if call["params"]["pageNumber"] == "1":
            return _payload([dict(_SOURCE_ROW), {**_SOURCE_ROW, "SECURITY_CODE": "000001"}],
                            pages=2, count=4)
        return _payload([dict(_SOURCE_ROW), {**_SOURCE_ROW, "SECURITY_CODE": "000002"}],
                        pages=3, count=6)

    _install(monkeypatch, responder)
    with pytest.raises(ChinaDataUnavailableError, match="翻页时总页数"):
        em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=2, max_rows=6
        )


def test_datacenter_final_total_mismatch_raises(monkeypatch):
    _install(monkeypatch, lambda call: _payload([dict(_SOURCE_ROW)], pages=1, count=3))
    with pytest.raises(ChinaDataUnavailableError, match="与总数 3 不符"):
        em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_never_truncates_when_count_is_within_cap(monkeypatch):
    rows = [dict(_SOURCE_ROW), {**_SOURCE_ROW, "SECURITY_CODE": "000001"}]
    _install(monkeypatch, lambda call: _payload(rows, pages=1, count=1))
    with pytest.raises(ChinaDataUnavailableError, match="与总数 1 不符"):
        em_datacenter_strict(
            "RPT_X", sort_columns="A", sort_types="-1", page_size=10, max_rows=10
        )


def test_datacenter_truncates_only_when_count_exceeds_cap(monkeypatch):
    rows = [dict(_SOURCE_ROW), {**_SOURCE_ROW, "SECURITY_CODE": "000001"}]
    _install(monkeypatch, lambda call: _payload(rows, pages=2, count=2212))
    page = em_datacenter_strict(
        "RPT_X", sort_columns="A", sort_types="-1", page_size=2, max_rows=2
    )
    assert len(page.rows) == 2
    assert page.truncated is True
    assert page.pagination_exhausted is False
    assert page.count == 2212


def test_datacenter_validates_sort_columns_and_types_before_request(monkeypatch):
    calls = _install(monkeypatch, lambda call: _payload([dict(_SOURCE_ROW)]))
    with pytest.raises(ValueError, match="个数不一致"):
        em_datacenter_strict("RPT_X", sort_columns="A,B", sort_types="-1")
    assert calls == []


def test_datacenter_rejects_non_object_data(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 0, "result": {"pages": 1, "count": 1,
                                                             "data": ["not-a-dict"]}})
    with pytest.raises(ChinaDataUnavailableError, match="不是由对象组成的列表"):
        em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_missing_pagination_info_raises(monkeypatch):
    _install(monkeypatch, lambda call: {"code": 0, "result": {"data": [dict(_SOURCE_ROW)]}})
    with pytest.raises(ChinaDataUnavailableError, match="不是非负整数"):
        em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_datacenter_provider_error_is_typed(monkeypatch):
    def fake_em_get(url, **kwargs):
        raise VendorHTTPError("eastmoney", 503)

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    with pytest.raises(ChinaDataUnavailableError, match="请求失败"):
        em_datacenter_strict("RPT_X", sort_columns="A", sort_types="-1")


def test_strict_number_normalizes_and_rejects_bad_values():
    assert strict_number(None) is None
    assert strict_number("") is None
    assert strict_number("-") is None
    assert strict_number("--") is None
    assert strict_number("None") is None
    assert strict_number("1,234.50") == 1234.5
    assert strict_number(7) == 7.0
    assert strict_number(float("nan")) is None
    assert strict_number(float("inf")) is None
    with pytest.raises(ChinaDataUnavailableError, match="布尔值"):
        strict_number(True)
    with pytest.raises(ChinaDataUnavailableError, match="无法识别的数值"):
        strict_number("garbage")


def test_strict_date_arg_accepts_supported_forms_and_rejects_others():
    assert strict_date_arg("20260918") == "2026-09-18"
    assert strict_date_arg("2026-09-18") == "2026-09-18"
    with pytest.raises(ValueError):
        strict_date_arg("2026/09/18")
    with pytest.raises(ValueError):
        strict_date_arg("2026-13-40")


def test_strict_source_day_rejects_non_iso_spelling():
    assert strict_source_day(None) is None
    assert strict_source_day("2026-09-18 00:00:00") == "2026-09-18"
    with pytest.raises(ChinaDataUnavailableError, match="无法识别的日期"):
        strict_source_day("18/09/2026")


def test_strict_limit_validates_range():
    assert strict_limit(1) == 1
    assert strict_limit("5000") == 5000
    for bad in (0, 5001, -1):
        with pytest.raises(ValueError, match="limit 范围"):
            strict_limit(bad)
    with pytest.raises(ValueError, match="必须是整数"):
        strict_limit("abc")
