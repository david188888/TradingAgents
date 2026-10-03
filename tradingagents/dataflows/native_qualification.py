"""Pure, conservative qualification of public native source responses."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from tradingagents.dataflows.tushare_price_history import (
    SHANGHAI,
    PriceHistoryQualificationError,
    _positive,
    settled_sessions,
)


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


SINA_FIELDS = {
    "income": {"BIZINCO": "revenue", "NETPROFIT": "n_income", "PARENETP": "n_income_attr_p"},
    "balancesheet": {"TOTASSET": "total_assets", "TOTLIAB": "total_liab"},
    "cashflow": {"MANANETR": "n_cashflow_act"},
}


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
