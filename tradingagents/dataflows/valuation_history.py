"""Bounded daily valuation history: baostock primary, Tushare daily_basic fallback."""

from __future__ import annotations

import csv
import io
import os
from datetime import date

import requests

from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
from tradingagents.dataflows.ticker_utils import is_a_share_ticker, normalize_ticker_symbol

_TUSHARE_URL = "https://api.tushare.pro"
_FIELDS = "ts_code,trade_date,close,pe_ttm,pb"


def _num(value):
    if value in (None, ""):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _csv_rows(text):
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line and not line.startswith("#")), None)
    return [] if start is None else list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def _baostock_rows(ticker, start_date, end_date):
    from tradingagents.dataflows.a_stock_v37 import get_a_share_valuation_history

    rows = []
    for row in _csv_rows(str(get_a_share_valuation_history(ticker, start_date, end_date))):
        published = str(row.get("date") or "")[:10]
        if not published:
            continue
        rows.append({"published": published, "close": _num(row.get("close")),
                     "pe_ttm": _num(row.get("peTTM")),
                     "pb_mrq": _num(row.get("pbMRQ")), "ps_ttm": _num(row.get("psTTM")),
                     "pcf": _num(row.get("pcfNcfTTM")), "turnover": _num(row.get("turn")),
                     "is_st": str(row.get("isST") or ""), "source_name": "baostock.valuation_history"})
    return rows


def _tushare_token():
    token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API_KEY")
    if not token:
        raise AshareCapabilityUnavailableError(
            "valuation_history", "tushare", "tushare_not_configured")
    return token


def _tushare_rows(ticker, start_date, end_date, *, session):
    token = _tushare_token()
    response = (session or requests).post(_TUSHARE_URL, json={
        "api_name": "daily_basic", "token": token,
        "params": {"ts_code": normalize_ticker_symbol(ticker),
                   "start_date": start_date.replace("-", ""), "end_date": end_date.replace("-", "")},
        "fields": _FIELDS,
    }, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise AshareCapabilityUnavailableError(
            "valuation_history", "tushare", f"tushare_rejected_{payload.get('code')}")
    data = payload.get("data") or {}
    columns, items = data.get("fields"), data.get("items")
    if not isinstance(columns, list) or not isinstance(items, list):
        raise AshareCapabilityUnavailableError("valuation_history", "tushare", "tushare_invalid_shape")
    rows = []
    for item in items:
        row = dict(zip(columns, item, strict=True))
        raw = str(row.get("trade_date") or "")
        if len(raw) != 8:
            continue
        rows.append({"published": f"{raw[:4]}-{raw[4:6]}-{raw[6:]}",
                     "close": _num(row.get("close")),
                     "pe_ttm": _num(row.get("pe_ttm")), "pb_mrq": _num(row.get("pb")),
                     "ps_ttm": None, "pcf": None, "turnover": None, "is_st": "",
                     "source_name": "tushare.valuation_history"})
    return rows


def get_a_share_valuation_history_rows(ticker, start_date, end_date, *, session=None):
    """Newest-first bounded PE/PB rows; baostock first, Tushare fallback.

    baostock serves richer fields but needs its own TCP session; when it cannot
    log in, Tushare daily_basic supplies PE/PB only. Both are source-reported
    snapshots, not fair-value conclusions, and the caller applies the row cap.
    """
    code = normalize_ticker_symbol(ticker)
    if not is_a_share_ticker(code):
        raise AshareCapabilityUnavailableError("valuation_history", "baostock", f"{ticker} is not an A-share")
    if date.fromisoformat(end_date) < date.fromisoformat(start_date):
        raise ValueError("valuation_history_window_invalid")
    try:
        rows = _baostock_rows(code, start_date, end_date)
    except AshareCapabilityUnavailableError:
        rows = _tushare_rows(code, start_date, end_date, session=session)
    if not rows:
        raise AshareCapabilityUnavailableError("valuation_history", "baostock", "no rows in window")
    rows = list(rows)
    rows.sort(key=lambda item: item["published"], reverse=True)
    return tuple(rows)
