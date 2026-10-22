"""Pure, conservative qualification of public native source responses."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from tradingagents.agents.schemas._verification_plan import SINA_FIELDS
from tradingagents.dataflows.tushare_price_history import (
    SHANGHAI,
    PriceHistoryQualificationError,
    _positive,
    settled_sessions,
)

# Keyless, quota-free session witness.  Only the SSE composite's bar dates are
# read; no index price enters research evidence.  A present bar proves a session
# traded, but a missing weekday bar cannot by itself distinguish a holiday from
# a vendor gap, so such a day is closed only when an independent witness agrees.
CALENDAR_INDEX_SYMBOL = "sh000001"
# A daily-bar witness can attest a session only once it settled.  The TDX
# after-market package is published around 16:10 local time.
_WITNESS_SETTLED_AT = time(16, 30)


class NativeSourceUnavailable(ValueError):
    """Controlled codes only; raw provider messages never enter checkpoints."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def api_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise NativeSourceUnavailable("invalid_source_date")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}").isoformat()
    except ValueError:
        raise NativeSourceUnavailable("invalid_source_date") from None


def qualify_identity(row, *, ts_code, cutoff):
    if not isinstance(row, dict) or row.get("ts_code") != ts_code:
        raise NativeSourceUnavailable("identity_code_mismatch")
    if not isinstance(row.get("name"), str) or not row["name"].strip():
        raise NativeSourceUnavailable("identity_name_missing")
    if api_date(row.get("list_date")) > cutoff:
        raise NativeSourceUnavailable("not_listed_at_cutoff")
    return {key: row[key] for key in ("ts_code", "name", "list_date")}


class _ProfileParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.table = False
        self.cell = None
        self.cells = []
        self.title = False
        self.title_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "comInfo1":
            self.table = True
        if tag == "td" and self.table:
            self.cell = ""
        if tag == "title":
            self.title = True

    def handle_endtag(self, tag):
        if tag == "table":
            self.table = False
        if tag == "td" and self.cell is not None:
            self.cells.append(self.cell.strip())
            self.cell = None
        if tag == "title":
            self.title = False

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data
        if self.title:
            self.title_text += data


def sina_identity(text, *, ts_code, cutoff):
    parser = _ProfileParser()
    parser.feed(text)
    code, exchange = ts_code.split(".")
    title = re.fullmatch(r"(.+)\((\d{6})\)公司资料_新浪财经_新浪网", parser.title_text.strip())
    if not title or title[2] != code:
        raise NativeSourceUnavailable("identity_code_mismatch")
    cells = parser.cells
    fields = {cells[i].rstrip("：:"): cells[i+1] for i in range(len(cells)-1)
              if cells[i].endswith(("：", ":"))}
    expected = {"SZ": "深圳证券交易所", "SH": "上海证券交易所", "BJ": "北京证券交易所"}[exchange]
    if fields.get("上市市场") != expected:
        raise NativeSourceUnavailable("identity_exchange_mismatch")
    listed = fields.get("上市日期", "").replace("-", "")
    return qualify_identity({"ts_code": ts_code, "name": title[1], "list_date": listed},
                            ts_code=ts_code, cutoff=cutoff)


def sina_statement(payload, *, table, ts_code, cutoff):
    try:
        if payload["result"]["status"]["code"] != 0:
            raise NativeSourceUnavailable("sina_statement_rejected")
        reports = payload["result"]["data"]["report_list"]
    except (KeyError, TypeError):
        raise NativeSourceUnavailable("sina_statement_invalid_shape") from None
    if not isinstance(reports, dict):
        raise NativeSourceUnavailable("sina_statement_invalid_shape")
    rows = []
    for period, report in sorted(reports.items(), reverse=True):
        if not isinstance(report, dict):
            raise NativeSourceUnavailable("sina_statement_invalid_shape")
        if report.get("rType") != "合并期末" or report.get("rCurrency") != "CNY":
            raise NativeSourceUnavailable("sina_statement_scope_or_unit_unqualified")
        # This endpoint's CNY item_value is in yuan, not the legacy adapter's
        # assumed 100-million-yuan display scale. Never multiply these values.
        for key in ("unit", "rUnit"):
            if key in report and (isinstance(report[key], bool) or report[key] not in ("元", "CNY", "yuan", 1)):
                raise NativeSourceUnavailable("sina_statement_scope_or_unit_unqualified")
        announced = report.get("publish_date")
        end, published = api_date(period), api_date(announced)
        if published < end:
            raise NativeSourceUnavailable("sina_disclosure_before_period")
        if published > cutoff or end > cutoff:
            continue
        updated = report.get("update_time")
        if updated is not None:
            try:
                if isinstance(updated, bool):
                    raise ValueError
                update_day = datetime.fromtimestamp(int(updated), SHANGHAI).date().isoformat()
            except (TypeError, ValueError, OverflowError, OSError):
                raise NativeSourceUnavailable("sina_invalid_update_time") from None
            if update_day > cutoff:
                continue
        row = {"ts_code": ts_code, "end_date": period, "ann_date": announced, "report_type": "1"}
        row["provider_metadata"] = {key: report[key] for key in (
            "rType", "rCurrency", "publish_date", "update_time", "data_source", "unit", "rUnit") if key in report}
        items = report.get("data")
        if not isinstance(items, list):
            raise NativeSourceUnavailable("sina_statement_invalid_shape")
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise NativeSourceUnavailable("sina_statement_invalid_shape")
            field = SINA_FIELDS[table].get(item.get("item_field"))
            if field is None:
                continue
            if field in seen:
                raise NativeSourceUnavailable("sina_duplicate_financial_field")
            seen.add(field)
            value = item.get("item_value")
            if value is None:
                continue
            try:
                number = Decimal(str(value))
                if isinstance(value, bool) or not number.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                raise NativeSourceUnavailable("sina_invalid_financial_value") from None
            row[field] = str(number)
        if seen and any(field in row for field in SINA_FIELDS[table].values()):
            rows.append(row)
    if not rows:
        raise NativeSourceUnavailable("sina_no_qualified_statement_rows")
    return rows[:8]


def szse_month(payload, year, month):
    expected = {date(year, month, day).isoformat() for day in range(1, calendar.monthrange(year, month)[1]+1)}
    rows, seen = [], set()
    records = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise NativeSourceUnavailable("calendar_invalid_shape")
    for row in records:
        day = row.get("jyrq") if isinstance(row, dict) else None
        flag = str(row.get("jybz")) if isinstance(row, dict) else ""
        if day not in expected or day in seen or flag not in {"0", "1"}:
            raise NativeSourceUnavailable("calendar_invalid_row")
        seen.add(day)
        rows.append({"cal_date": day.replace("-", ""), "is_open": flag})
    if seen != expected:
        raise NativeSourceUnavailable("calendar_window_not_complete")
    return rows


def _calendar_window(start, cutoff):
    try:
        begin, end = date.fromisoformat(start), date.fromisoformat(cutoff)
    except (TypeError, ValueError):
        raise NativeSourceUnavailable("calendar_window_invalid") from None
    if end < begin or (end - begin).days > 500:
        raise NativeSourceUnavailable("calendar_window_invalid")
    return begin, end


def _window_days(begin, end):
    return [(begin + timedelta(days=offset)).isoformat() for offset in range((end - begin).days + 1)]


def index_session_dates(payload, *, index_symbol):
    """Read only the bar dates of one index daily-bar response."""
    data = payload.get("data") if isinstance(payload, dict) else None
    node = data.get(index_symbol) if isinstance(data, dict) else None
    if not isinstance(node, dict):
        raise NativeSourceUnavailable("calendar_invalid_shape")
    bars = node.get("day")
    if bars is None:
        bars = node.get("qfqday")
    if not isinstance(bars, list) or not bars:
        raise NativeSourceUnavailable("calendar_invalid_shape")
    sessions = set()
    for bar in bars:
        day = bar[0] if isinstance(bar, (list, tuple)) and bar else None
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise NativeSourceUnavailable("calendar_invalid_row")
        try:
            weekday = date.fromisoformat(day).weekday()
        except ValueError:
            raise NativeSourceUnavailable("calendar_invalid_row") from None
        if day in sessions:
            raise NativeSourceUnavailable("calendar_duplicate_row")
        # A-share exchanges never trade on Saturday or Sunday, including the
        # weekend make-up workdays, so a weekend bar is a malformed series.
        if weekday >= 5:
            raise NativeSourceUnavailable("calendar_invalid_row")
        sessions.add(day)
    return sorted(sessions)


def witness_horizon(captured_at: datetime) -> str:
    """Last day a settled daily-bar witness can attest at capture time."""
    if captured_at.tzinfo is None:
        raise NativeSourceUnavailable("calendar_capture_timezone_required")
    local = captured_at.astimezone(SHANGHAI)
    day = local.date() if local.time() >= _WITNESS_SETTLED_AT else local.date() - timedelta(days=1)
    return day.isoformat()


def calendar_gaps(sessions, *, start, cutoff, captured_at: datetime):
    """Weekdays with no index bar that need an independent closure witness.

    The index series must reach ``start``; a truncated walk would otherwise
    turn real sessions into gaps.  Weekends are closed by exchange rule.  A
    capture day that has not settled yet is not a gap: it stays unconfirmed.
    """
    begin, end = _calendar_window(start, cutoff)
    if not sessions or min(sessions) > start:
        raise NativeSourceUnavailable("calendar_window_not_complete")
    present, horizon = set(sessions), witness_horizon(captured_at)
    return [day for day in _window_days(begin, end) if day <= horizon
            and date.fromisoformat(day).weekday() < 5 and day not in present]


def qualify_session_calendar(sessions, closed, *, start, cutoff, captured_at: datetime):
    """Build the ``szse_month`` row shape from index sessions plus witnessed closures.

    ``closed`` must cover every gap from :func:`calendar_gaps`: an index bar
    proves a session, and only an independent witness may prove a missing
    weekday was a holiday rather than a vendor omission.  The unsettled capture
    day without a bar is written as closed, so it is never a settled session.
    """
    gaps = calendar_gaps(sessions, start=start, cutoff=cutoff, captured_at=captured_at)
    if set(gaps) - set(closed):
        raise NativeSourceUnavailable("calendar_gap_unwitnessed")
    present = set(sessions)
    return [{"cal_date": day.replace("-", ""), "is_open": "1" if day in present else "0"}
            for day in _window_days(*_calendar_window(start, cutoff))]


def calendar_disputes(rows, sessions, *, start, cutoff, captured_at: datetime):
    """Settled days where an official calendar and the index bar dates disagree."""
    begin, end = _calendar_window(start, cutoff)
    if not sessions or min(sessions) > start:
        raise NativeSourceUnavailable("calendar_window_not_complete")
    official = {api_date(row.get("cal_date")): str(row.get("is_open")) == "1" for row in rows}
    present, horizon = set(sessions), witness_horizon(captured_at)
    return [day for day in _window_days(begin, end)
            if day <= horizon and day in official and official[day] != (day in present)]


def settle_calendar_disputes(rows, disputes, verdicts):
    """Resolve official-vs-index disputes with a third, independent witness.

    ``verdicts`` maps a day to True (session), False (closed) or None (not
    witnessed).  The official calendar stands when the witness agrees with it.
    When two independent vendors both contradict it the calendar is rejected
    rather than repaired.  Returns the days that stayed unwitnessed.
    """
    official = {api_date(row.get("cal_date")): str(row.get("is_open")) == "1" for row in rows}
    unresolved = []
    for day in disputes:
        verdict = verdicts.get(day)
        if verdict is None:
            unresolved.append(day)
        elif verdict != official[day]:
            raise NativeSourceUnavailable("calendar_sources_conflict")
    return unresolved


def sina_factors(text, *, symbol):
    prefix = re.match(r"\s*var\s+(\w+)\s*=", text)
    if not prefix or prefix[1] != symbol+"qfq":
        raise NativeSourceUnavailable("factor_identity_mismatch")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[prefix.end():].lstrip())
        rows = payload["data"]
    except (ValueError, KeyError, TypeError):
        raise NativeSourceUnavailable("factor_invalid_shape") from None
    if not isinstance(rows, list) or type(payload.get("total")) is not int or payload["total"] != len(rows):
        raise NativeSourceUnavailable("factor_incomplete_snapshot")
    seen = set()
    for row in rows:
        day = row.get("d") if isinstance(row, dict) else None
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError
            _positive(row.get("f"), "factor")
        except (TypeError, ValueError):
            raise NativeSourceUnavailable("factor_invalid_row") from None
        if day in seen:
            raise NativeSourceUnavailable("factor_duplicate_date")
        seen.add(day)
    return sorted(rows, key=lambda row: row["d"])


def prepare_public_prices(raw, factors, calendar_rows, *, ts_code, start, cutoff, captured_at: datetime):
    """Apply Sina's dated qfq DIVISOR and re-anchor to the last settled bar."""
    sessions = settled_sessions(calendar_rows, start=start, cutoff=cutoff, captured_at=captured_at)
    code, exchange = ts_code.split(".")
    if raw.get("provenance", {}).get("code") != exchange.lower()+code:
        raise NativeSourceUnavailable("price_identity_mismatch")
    indexed = {}
    for row in raw.get("bars", []):
        day = row.get("Date")
        if day not in sessions or day in indexed:
            raise NativeSourceUnavailable("price_identity_or_date_mismatch")
        indexed[day] = row
    if set(indexed) != set(sessions):
        raise NativeSourceUnavailable("price_window_not_complete")
    if not factors or any(row["d"] > cutoff for row in factors):
        raise NativeSourceUnavailable("factor_future_or_missing")
    def factor(day):
        eligible = [row for row in factors if row["d"] <= day]
        if not eligible:
            raise NativeSourceUnavailable("missing_dated_adjustment_factor")
        return _positive(eligible[-1]["f"], "factor")
    anchor = sessions[-1]
    anchor_factor = factor(anchor)
    bars = []
    for day, row in sorted(indexed.items()):
        values = {key: _positive(row.get(key), key) for key in ("Open", "High", "Low", "Close")}
        if not values["Low"] <= min(values["Open"], values["Close"]) <= max(values["Open"], values["Close"]) <= values["High"]:
            raise PriceHistoryQualificationError("inconsistent_ohlc")
        scale = anchor_factor/factor(day)
        bars.append({"Date": day, **{key: _positive(value*scale, key) for key, value in values.items()}})
    pit = cutoff == captured_at.astimezone(SHANGHAI).date().isoformat()
    digest = hashlib.sha256(json.dumps({"raw": raw, "factors": factors, "calendar": calendar_rows},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"bars": bars, "provenance": {
        "source": "tencent.raw+sina.qfq_factors", "security_id": ts_code,
        "price_basis": "qfq", "currency": "CNY", "price_unit": "CNY/share",
        "adjustment_formula": "raw_ohlc * anchor_sina_qfq_divisor / dated_sina_qfq_divisor",
        "adjustment_anchor": anchor, "factor_vintage": "retrieved_at_capture",
        "captured_at": captured_at.isoformat(), "requested_start": start, "requested_end": cutoff,
        "actual_start": bars[0]["Date"], "actual_end": anchor, "settled_through": anchor,
        "expected_sessions": list(sessions), "missing_sessions": [], "window_covered": True,
        "pit_status": "verified" if pit else "unverified",
        "degradations": [] if pit else ["historical_factor_vintage_unverified"],
        "input_sha256": digest, "calculation_version": "tencent-sina-cutoff-qfq-v1",
    }}
