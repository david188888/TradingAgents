"""Pure parsing of bounded dated forecasts and named industry candidates."""

import hashlib
import re
from datetime import date, timedelta
from html.parser import HTMLParser

from pydantic import ValidationError

from tradingagents.agents.schemas._evidence_checks import (
    DatedForecastV1,
    PeerCandidateV1,
    PeerSelectionV1,
)
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable

FORECAST_SOURCES = frozenset({"ths.dated_forecast", "eastmoney.dated_forecast"})
PEER_SOURCES = frozenset({"eastmoney.peer_candidates", "tencent.peer_valuation"})
CAP_FORECAST = "dated_forecasts"
CAP_PEERS = "peer_context"


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif self.table is not None and tag == "tr":
            self.row = []
        elif self.row is not None and tag in {"th", "td"}:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _eligible_forecast(row, ts_code, cutoff):
    result = DatedForecastV1.model_validate(row)
    if (result.ts_code != ts_code or not cutoff-timedelta(days=180) <= result.published <= cutoff
            or result.forecast_year not in range(cutoff.year, cutoff.year+3)):
        raise NativeSourceUnavailable("forecast_identity_date_or_year_unqualified")
    return result.model_dump(mode="json")


def deduplicate_forecasts(rows, *, ts_code, cutoff):
    """Latest institution/year wins; wrappers do not increase analyst count."""
    eligible = []
    for raw in rows:
        try:
            eligible.append(_eligible_forecast(raw, ts_code, date.fromisoformat(cutoff)))
        except (NativeSourceUnavailable, ValidationError, ValueError, TypeError):
            continue
    eligible.sort(key=lambda r: (r["published"], r["institution"], r["report_id"]), reverse=True)
    selected, institutions = {}, set()
    for row in eligible:
        institution = re.sub(r"\s", "", row["institution"])
        if institution not in institutions and len(institutions) >= 8:
            continue
        institutions.add(institution)
        selected.setdefault((institution, row["forecast_year"]), row)
    return sorted(selected.values(), key=lambda r: (r["forecast_year"], r["institution"]))


def ths_forecasts(html, *, ts_code, cutoff):
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not title or not re.search(r"\("+re.escape(ts_code[:6])+r"\)", title[1]) or "盈利预测" not in title[1]:
        raise NativeSourceUnavailable("forecast_security_unqualified")
    parser = _Tables()
    parser.feed(html)
    rows = []
    for table in parser.tables:
        if len(table) < 3 or not all(any(word in cell for cell in table[0]) for word in ("机构名称", "预测年报每股收益", "报告日期")):
            continue
        # Admit the inspected nine-column individual table only. Aggregate
        # tables and positional guesses are deliberately not fallback inputs.
        years = [re.fullmatch(r"(20\d{2})预测", re.sub(r"\s", "", value)) for value in table[1]]
        if len(years) != 6 or not all(years) or [m[1] for m in years[:3]] != [m[1] for m in years[3:]]:
            continue
        for cells in table[2:]:
            if len(cells) != 9:
                continue
            institution, analyst, published = cells[0], cells[1], cells[-1]
            report_id = "ths."+hashlib.sha256(f"{institution}|{analyst}|{published}".encode()).hexdigest()[:24]
            for index, year in enumerate(years[:3]):
                rows.append({"ts_code": ts_code, "institution": institution, "analyst": analyst or None,
                    "report_id": report_id, "published": published, "forecast_year": int(year[1]),
                    "eps": cells[index+2], "year_basis": "explicit_header"})
    return deduplicate_forecasts(rows, ts_code=ts_code, cutoff=cutoff)


def eastmoney_forecasts(payload, *, ts_code, cutoff):
    rows = []
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise NativeSourceUnavailable("forecast_response_shape_invalid")
    for item in payload["data"][:20]:
        if not isinstance(item, dict) or item.get("stockCode") != ts_code[:6]:
            continue
        year = item.get("currentYear", payload.get("currentYear"))
        if isinstance(year, bool) or not re.fullmatch(r"20\d{2}", str(year)):
            continue
        for offset, field in enumerate(("predictThisYearEps", "predictNextYearEps", "predictNextTwoYearEps")):
            rows.append({"ts_code": ts_code, "institution": item.get("orgSName"), "analyst": item.get("researcher"),
                "report_id": item.get("infoCode"), "published": str(item.get("publishDate", ""))[:10],
                "forecast_year": int(year)+offset, "eps": str(item.get(field)), "year_basis": "response_currentYear"})
    return deduplicate_forecasts(rows, ts_code=ts_code, cutoff=cutoff)


def peer_candidates(payload, *, ts_code):
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("result"), dict):
        raise NativeSourceUnavailable("peer_response_shape_invalid")
    data = payload["result"].get("data")
    if not isinstance(data, list) or len(data) > 100:
        raise NativeSourceUnavailable("peer_response_shape_invalid")
    candidates, seen, population = [], set(), None
    for row in data:
        if not isinstance(row, dict) or row.get("SECUCODE") != ts_code:
            raise NativeSourceUnavailable("peer_target_security_mismatch")
        count = row.get("TOTAL_COUNT")
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            if population is not None and population != count:
                raise NativeSourceUnavailable("peer_population_conflict")
            population = count
        if len(candidates) == 5:
            continue
        code, name = row.get("CORRE_SECUCODE"), row.get("CORRE_SECURITY_NAME")
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code) or code == ts_code or code in seen:
            continue
        if row.get("CORRE_SECURITY_CODE") != code[:6] or not isinstance(name, str) or not name:
            continue
        seen.add(code)
        candidates.append(PeerCandidateV1(ts_code=code, name=name,
            financial_period=str(row["REPORT_DATE"])[:10] if row.get("REPORT_DATE") else None))
    return PeerSelectionV1(target_ts_code=ts_code, candidates=tuple(candidates), reported_population=population).model_dump(mode="json")
