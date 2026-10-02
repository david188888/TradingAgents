"""Pure qualification of bounded Tushare daily/factor/calendar responses.

No SDK, I/O or retries live here. The execution adapter supplies responses
fetched through its durable capability and HTTP ledgers. A cutoff anchor is
not evidence of an archived historical factor vintage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

PRICE_PREPARATION_VERSION = "tushare-cutoff-qfq-v1"
SHANGHAI = ZoneInfo("Asia/Shanghai")


class PriceHistoryQualificationError(ValueError):
    """Safe code and audit detail; never includes vendor messages or tokens."""

    def __init__(self, code: str, **detail: Any):
        super().__init__(code)
        self.code, self.detail = code, detail


def _api_date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise PriceHistoryQualificationError("invalid_trade_date")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}").isoformat()
    except ValueError as exc:
        raise PriceHistoryQualificationError("invalid_trade_date") from exc


def settled_sessions(
    calendar: list[dict[str, Any]], *, start: str, cutoff: str, captured_at: datetime,
) -> tuple[str, ...]:
    if captured_at.tzinfo is None:
        raise PriceHistoryQualificationError("capture_timezone_required")
    local = captured_at.astimezone(SHANGHAI)
    begin, end = date.fromisoformat(start), date.fromisoformat(cutoff)
    if end < begin or (end - begin).days > 500 or end > local.date():
        raise PriceHistoryQualificationError("invalid_bounded_price_window")
    seen: dict[str, str] = {}
    for row in calendar:
        day = _api_date(row.get("cal_date"))
        status = str(row.get("is_open"))
        if not start <= day <= cutoff or day in seen or status not in {"0", "1"}:
            raise PriceHistoryQualificationError("invalid_calendar_row")
        seen[day] = status
    expected = {(begin + timedelta(days=i)).isoformat() for i in range((end - begin).days + 1)}
    if seen.keys() != expected:
        raise PriceHistoryQualificationError("calendar_window_not_complete")
    # Tushare daily ingestion is normally 15:00-16:00 local. Before that,
    # exclude the current session even if a provider has a provisional bar.
    days = tuple(sorted(day for day, status in seen.items() if status == "1"
        and (day < local.date().isoformat() or local.time() >= time(16))))
    if len(days) < 2:
        raise PriceHistoryQualificationError("insufficient_settled_sessions")
    return days


def _positive(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise PriceHistoryQualificationError(f"invalid_{field}")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise PriceHistoryQualificationError(f"invalid_{field}") from exc
    if not isfinite(result) or result <= 0:
        raise PriceHistoryQualificationError(f"invalid_{field}")
    return result


def prepare_tushare_price_history(
    daily: list[dict[str, Any]], factors: list[dict[str, Any]], calendar: list[dict[str, Any]],
    *, ts_code: str, start: str, cutoff: str, captured_at: datetime,
) -> dict[str, Any]:
    """Join exact dated factors and scale all OHLC to the last settled anchor.

    Gaps and unverified historical vintage remain explicit in provenance.
    This function does not promote either into qualified research evidence.
    """
    sessions = settled_sessions(calendar, start=start, cutoff=cutoff, captured_at=captured_at)
    expected = set(sessions)

    def index_rows(rows):
        indexed = {}
        for row in rows:
            day = _api_date(row.get("trade_date"))
            if row.get("ts_code") != ts_code or day not in expected or day in indexed:
                raise PriceHistoryQualificationError("price_identity_or_date_mismatch")
            indexed[day] = row
        return indexed

    prices, dated_factors = index_rows(daily), index_rows(factors)
    if len(prices) < 2:
        raise PriceHistoryQualificationError("insufficient_price_rows")
    if not prices.keys() <= dated_factors.keys():
        raise PriceHistoryQualificationError("missing_dated_adjustment_factor")
    # Never anchor to a future factor or to a session after the last price.
    anchor = max(prices)
    anchor_factor = _positive(dated_factors[anchor].get("adj_factor"), "adj_factor")
    bars = []
    for day, row in sorted(prices.items()):
        factor = _positive(dated_factors[day].get("adj_factor"), "adj_factor") / anchor_factor
        raw = {name: _positive(row.get(name), name) for name in ("open", "high", "low", "close")}
        if not raw["low"] <= min(raw["open"], raw["close"]) <= max(raw["open"], raw["close"]) <= raw["high"]:
            raise PriceHistoryQualificationError("inconsistent_ohlc")
        bar = {"Date": day, **{name.title(): value * factor for name, value in raw.items()}}
        if any(not isfinite(value) or value <= 0 for key, value in bar.items() if key != "Date"):
            raise PriceHistoryQualificationError("invalid_adjusted_ohlc")
        bars.append(bar)
    missing = sorted(expected - prices.keys())
    # Today's capture is eligible for today's end-of-day cutoff. Retrospective
    # retrieval needs an archive vintage, which these endpoints do not supply.
    pit_verified = cutoff == captured_at.astimezone(SHANGHAI).date().isoformat()
    degradations = (["missing_price_sessions"] if missing else []) + ([] if pit_verified else ["historical_factor_vintage_unverified"])
    fingerprint = hashlib.sha256(json.dumps({
        "daily": sorted(daily, key=lambda r: r["trade_date"]),
        "factors": sorted(factors, key=lambda r: r["trade_date"]),
        "calendar": sorted(calendar, key=lambda r: r["cal_date"]),
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"bars": bars, "provenance": {
        "source": "tushare.daily+adj_factor+trade_cal", "security_id": ts_code,
        "price_basis": "qfq", "currency": "CNY", "price_unit": "CNY/share",
        "adjustment_formula": "raw_ohlc * dated_adj_factor / anchor_adj_factor",
        "adjustment_anchor": anchor, "factor_vintage": "retrieved_at_capture",
        "captured_at": captured_at.isoformat(), "requested_start": start, "requested_end": cutoff,
        "actual_start": bars[0]["Date"], "actual_end": bars[-1]["Date"],
        "settled_through": sessions[-1], "expected_sessions": list(sessions),
        "missing_sessions": missing, "window_covered": not missing,
        "pit_status": "verified" if pit_verified else "unverified",
        "degradations": degradations, "input_sha256": fingerprint,
        "calculation_version": PRICE_PREPARATION_VERSION,
    }}
