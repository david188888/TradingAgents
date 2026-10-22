"""Bounded multi-source routing for the three evidence_v1 research modes."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import requests

from tradingagents.agents.schemas._verification_plan import VERIFIABLE_FIELDS
from tradingagents.dataflows.catalyst_events import CatalystEventV1, classify_earnings_title
from tradingagents.dataflows.catalyst_sources import CatalystSources
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.china_specialty import get_a_share_cninfo_announcements
from tradingagents.dataflows.native_qualification import (
    CALENDAR_INDEX_SYMBOL,
    NativeSourceUnavailable,
    api_date,
    calendar_disputes,
    calendar_gaps,
    index_session_dates,
    prepare_public_prices,
    qualify_identity,
    qualify_session_calendar,
    settle_calendar_disputes,
    sina_factors,
    sina_identity,
    sina_statement,
    szse_month,
)
from tradingagents.dataflows.tencent_kline import get_a_share_kline_df
from tradingagents.dataflows.ticker_utils import to_tushare_symbol
from tradingagents.dataflows.tushare_price_history import (
    PriceHistoryQualificationError,
    prepare_tushare_price_history,
    settled_sessions,
)
from tradingagents.execution.config_identity import SemanticConfigError
from tradingagents.research.evidence_freeze import (
    CAP_EVENT_COVERAGE,
    CAP_FUNDAMENTALS,
    CAP_IDENTITY,
    CAP_PRICE,
    CapabilityStatus,
    EvidenceFreezer,
    FreezeInputs,
    FrozenCapability,
    PriceObservation,
)
from tradingagents.research.native_versions import FINANCIAL_DETAIL_POLICY
from tradingagents.research.price_statistics import build_price_statistics
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

SOURCE_ROUTING_VERSION = "native-public-sources-v1"
DEFAULT_CHAINS = {
    "identity": ("eastmoney", "sina", "tushare"),
    "financial": ("sina", "tushare"),
    # The official SZSE month calendar is authoritative for every A-share
    # exchange (the three exchanges share one closure schedule) and carries no
    # quota.  The index bar dates are kept as an independent witness: they
    # cross-check settled official days, and lead only when SZSE is unreachable,
    # with TDX package existence confirming each weekday without a bar.  The
    # capped tushare trade_cal is the last resort, never a dispute tiebreaker.
    "calendar": ("szse", "tencent", "tushare"),
    "price": ("tencent", "tushare"),
    "events": ("cninfo",),
}
SINA_FINANCE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
SZSE_CALENDAR_URL = "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
TENCENT_CALENDAR_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
# The index walk only needs to reach `start`, at most 500 calendar days back.
# The endpoint caps a single response, so ask for a floor above that span.
TENCENT_CALENDAR_REQUEST_ROWS = 1000
# Published only for trading days (404 otherwise); existence is checked with
# HEAD, so the ~2.7MB package itself is never downloaded.
TDX_PACKAGE_URL = "https://www.tdx.com.cn/products/data/data/g4day/{ymd}.zip"
STATEMENT_FIELDS = {
    table: "ts_code,ann_date,f_ann_date,end_date,report_type," + ",".join(sorted(fields))
    for table, fields in VERIFIABLE_FIELDS.items()
}


def source_chains(config):
    overrides = config.get("evidence_source_vendors", {})
    excluded = config.get("evidence_source_exclusions", [])
    allowed = {vendor for chain in DEFAULT_CHAINS.values() for vendor in chain}
    if (not isinstance(overrides, dict) or set(overrides)-DEFAULT_CHAINS.keys()
        or not isinstance(excluded, list) or any(not isinstance(v, str) or v not in allowed for v in excluded)):
        raise SemanticConfigError("invalid_native_source_configuration")
    output = {}
    for key, defaults in DEFAULT_CHAINS.items():
        chain = overrides.get(key, list(defaults))
        if (not isinstance(chain, list) or any(not isinstance(v, str) or v not in defaults for v in chain)
            or len(set(chain)) != len(chain)):
            raise SemanticConfigError("invalid_native_source_configuration")
        output[key] = tuple(v for v in chain if v not in excluded)
    return output


class NativeSources(CatalystSources):
    def __init__(self, request, run_id, session, fetch):
        super().__init__(request, run_id, session, fetch)
        self.chains = source_chains(request.effective_config)
        self.excluded_vendors = frozenset(request.effective_config.get("evidence_source_exclusions", []))
        self.calendar_gaps, self.calendar_detail = [], {}
        self.attempts = {}
        self.tushare_limited = False

    def _get(self, url, *, params=None, referer=None, text=False):
        response = self.session.get(url, params=params, headers={
            "User-Agent": "Mozilla/5.0", "Referer": referer or url,
        }, timeout=12)
        if response.status_code != 200:
            raise NativeSourceUnavailable("source_http_unavailable")
        if text:
            # The labelled company page declares GB2312; the factor file is ASCII.
            return response.content.decode("gb18030" if "CorpInfo" in url else "utf-8")
        return response.json()

    def tushare(self, api_name, fields, **params):
        try:
            return super().tushare(api_name, fields, **params)
        except ValueError as exc:
            safe = str(exc)
            if safe == "tushare_rejected_40203":
                raise NativeSourceUnavailable("tushare_rate_limited") from None
            if safe == "tushare_not_configured":
                raise NativeSourceUnavailable("tushare_not_configured") from None
            raise NativeSourceUnavailable("tushare_source_unavailable") from None

    def _attempt(self, capability, vendor, key, operation):
        attempts = self.attempts.setdefault(capability, [])
        if vendor == "tushare" and self.tushare_limited:
            attempts.append({"vendor": vendor, "key": key, "status": "unavailable", "code": "tushare_run_cooldown"})
            return None
        try:
            result = self.fetch(SOURCE_ROUTING_VERSION+"."+key, operation)
        except CatalystCheckpointConflict:
            raise
        except (NativeSourceUnavailable, PriceHistoryQualificationError) as exc:
            code = exc.code
        except (requests.RequestException, ChinaDataUnavailableError):
            code = "source_transport_unavailable"
        except (ValueError, KeyError, TypeError):
            code = "source_response_unqualified"
        else:
            attempts.append({"vendor": vendor, "key": key, "status": "qualified"})
            return result
        if code == "tushare_rate_limited":
            self.tushare_limited = True
        attempts.append({"vendor": vendor, "key": key, "status": "unavailable", "code": code})
        return None

    def _cap(self, inputs, capability, sources=(), *, partial=False, gaps=(), detail=None):
        attempts = self.attempts.get(capability, [])
        available = bool(sources)
        status = CapabilityStatus.PARTIAL if available and partial else (
            CapabilityStatus.QUALIFIED if available else CapabilityStatus.UNAVAILABLE)
        inputs.capabilities.append(FrozenCapability(
            capability=capability, status=status, required=True, sources=tuple(sources),
            reason="qualified_source_fields_admitted" if available else "no_qualified_source_candidate",
            degradations=tuple(gaps) if available else (capability+"_unavailable",),
            detail={"routing_version": SOURCE_ROUTING_VERSION, "attempts": attempts, **(detail or {})},
        ))

    def _identity(self, inputs, ts_code):
        code, exchange = ts_code.split(".")
        for vendor in self.chains["identity"]:
            def query(vendor=vendor):
                if vendor == "sina":
                    text = self._get(f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{code}.phtml", text=True)
                    return sina_identity(text, ts_code=ts_code, cutoff=inputs.cutoff)
                if vendor == "eastmoney":
                    if exchange not in {"SH", "SZ"}:
                        raise NativeSourceUnavailable("identity_exchange_unsupported")
                    result = self._get("https://push2.eastmoney.com/api/qt/stock/get",
                        params={"secid": ("1." if exchange == "SH" else "0.")+code,
                                "fields": "f57,f58,f189", "fltt": "2"})
                    row = result.get("data") or {}
                    return qualify_identity({"ts_code": str(row.get("f57"))+"."+exchange,
                        "name": row.get("f58"), "list_date": str(row.get("f189"))},
                        ts_code=ts_code, cutoff=inputs.cutoff)
                rows = self.tushare("stock_basic", "ts_code,name,list_date,exchange,market", ts_code=ts_code)
                matches = [row for row in rows if row.get("ts_code") == ts_code]
                if len(matches) != 1:
                    raise NativeSourceUnavailable("identity_not_unique")
                return qualify_identity(matches[0], ts_code=ts_code, cutoff=inputs.cutoff)
            identity = self._attempt(CAP_IDENTITY, vendor, "identity."+vendor, query)
            if identity is not None:
                name = {"sina": "sina.company_profile", "eastmoney": "eastmoney.stock_profile", "tushare": "tushare.stock_basic"}[vendor]
                self.evidence(inputs, CAP_IDENTITY, name, identity)
                self._cap(inputs, CAP_IDENTITY, (name,))
                return identity
        self._cap(inputs, CAP_IDENTITY)
        return None

    def _events(self, inputs):
        start = (date.fromisoformat(inputs.cutoff)-timedelta(days=90)).isoformat()
        def query():
            rows = []
            report = get_a_share_cninfo_announcements(self.request.ticker, start, inputs.cutoff,
                session=self.session, records_sink=rows.extend)
            return {"records": rows, "coverage": report.coverage.model_dump(mode="json")}
        result = self._attempt(CAP_EVENT_COVERAGE, "cninfo", "events.cninfo", query) if self.chains["events"] else None
        if result is None:
            self._cap(inputs, CAP_EVENT_COVERAGE)
            return
        coverage = result["coverage"]
        for row in result["records"]:
            if not start <= row["Published"] <= inputs.cutoff:
                continue
            self.evidence(inputs, CAP_EVENT_COVERAGE, "cninfo", row,
                published=row["Published"], public_url=row["Detail URL"])
            digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            inputs.events.append(CatalystEventV1(security_id=self.request.ticker,
                kind=classify_earnings_title(row["Title"]), channel="official", title=row["Title"][:160],
                publication_date=row["Published"], state="point_in_time",
                announcement_id=row["Announcement ID"] or None,
                content_fingerprint=digest, source_family_id="cninfo:"+digest))
        complete = coverage["completeness"] == "complete" and coverage["pagination_exhausted"] is True
        self._cap(inputs, CAP_EVENT_COVERAGE, ("cninfo.announcements",), partial=not complete,
                  gaps=coverage["degradations"])

    def _financial(self, inputs, ts_code):
        bundles = {}
        selected, gaps = {}, []
        for table, fields in STATEMENT_FIELDS.items():
            for vendor in self.chains["financial"]:
                def query(vendor=vendor, table=table, fields=fields):
                    if vendor == "sina":
                        payload = self._get(SINA_FINANCE_URL, params={
                            "paperCode": ts_code.split(".")[1].lower()+ts_code[:6],
                            "source": {"income": "lrb", "balancesheet": "fzb", "cashflow": "llb"}[table],
                            "type": "0", "page": "1", "num": "8"})
                        return sina_statement(payload, table=table, ts_code=ts_code, cutoff=inputs.cutoff)
                    rows = self.tushare(table, fields, ts_code=ts_code,
                        start_date=(date.fromisoformat(inputs.cutoff)-timedelta(days=1100)).strftime("%Y%m%d"),
                        end_date=inputs.cutoff.replace("-", ""))
                    admitted = {}
                    for row in sorted(rows, key=lambda r: (str(r.get("end_date", "")), str(r.get("f_ann_date") or r.get("ann_date", ""))), reverse=True):
                        if row.get("ts_code") != ts_code or str(row.get("report_type")) != "1":
                            continue
                        end = api_date(row.get("end_date"))
                        disclosures = [api_date(row[key]) for key in ("ann_date", "f_ann_date") if row.get(key)]
                        if disclosures and end <= inputs.cutoff and all(end <= day <= inputs.cutoff for day in disclosures):
                            admitted.setdefault(row["end_date"], row)
                    if not admitted:
                        raise NativeSourceUnavailable("tushare_no_pit_rows")
                    return list(admitted.values())[:8]
                rows = self._attempt(CAP_FUNDAMENTALS, vendor, "financial."+vendor+"."+table, query)
                if rows is not None:
                    bundles.setdefault(vendor, {})[table] = rows
                    selected[table] = vendor
                    if len(rows) < 8:
                        gaps.append(table+"_eight_periods_not_covered")
                    break
            if table not in selected:
                gaps.append(table+"_unavailable")
        detail = getattr(self.request, "financial_detail_policy", None) == FINANCIAL_DETAIL_POLICY
        for vendor, bundle in bundles.items():
            self.evidence(inputs, CAP_FUNDAMENTALS, vendor+".financial_statements", bundle)
        if detail:
            # One additional record per statement table keeps every evidence
            # text under the 4,000-character SourceContentV1 limit. The baseline
            # records above are unchanged, so frozen checks and valuation read
            # exactly the same six fields they always did.
            for vendor, bundle in bundles.items():
                for table in STATEMENT_FIELDS:
                    if table in bundle:
                        self.evidence(inputs, CAP_FUNDAMENTALS, vendor+".financial_detail", {table: bundle[table]})
        sources = tuple(v+".financial_statements" for v in bundles)
        if detail:
            sources += tuple(v+".financial_detail" for v in bundles)
        self._cap(inputs, CAP_FUNDAMENTALS, sources,
                  partial=bool(gaps), gaps=gaps, detail={"selected_tables": selected})

    def _index_sessions(self):
        payload = self._get(TENCENT_CALENDAR_URL, params={
            "param": f"{CALENDAR_INDEX_SYMBOL},day,,,{TENCENT_CALENDAR_REQUEST_ROWS},",
        }, referer="https://gu.qq.com/")
        return index_session_dates(payload, index_symbol=CALENDAR_INDEX_SYMBOL)

    def _tdx_packages(self, days, control):
        """Whether TDX published a settled daily package for each day.

        TDX also answers 404 for days beyond its retention, so a 404 counts as a
        closure only when ``control`` -- a known session before every probed day
        -- still has its package.  Otherwise every day stays unwitnessed (None).
        """
        def published(day):
            response = self.session.head(TDX_PACKAGE_URL.format(ymd=day.replace("-", "")),
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
            return {200: True, 404: False}.get(response.status_code)
        if control is None or published(control) is not True:
            return dict.fromkeys(days)
        return {day: published(day) for day in days}

    @staticmethod
    def _tdx_key(days, control):
        return "calendar.tdx."+hashlib.sha256(",".join([control or "", *days]).encode()).hexdigest()[:16]

    def _calendar(self, inputs, ts_code, start):
        """Session calendar plus the cross-check degradations it carries.

        Sets ``self.calendar_gaps`` and ``self.calendar_detail`` for the price
        capability.  A two-vendor contradiction of the official calendar stops
        the chain: no later vendor is used to outvote the conflict.
        """
        self.calendar_gaps, self.calendar_detail = [], {}
        captured = datetime.now(timezone.utc)
        sessions_key = "calendar.tencent.sessions"
        for vendor in self.chains["calendar"]:
            def query(vendor=vendor):
                if vendor == "tushare":
                    rows = self.tushare("trade_cal", "cal_date,is_open", exchange={"SZ": "SZSE", "SH": "SSE", "BJ": "BSE"}[ts_code.split(".")[1]],
                        start_date=start.replace("-", ""), end_date=inputs.cutoff.replace("-", ""))
                elif vendor == "tencent":
                    sessions = self.fetch(SOURCE_ROUTING_VERSION+"."+sessions_key, self._index_sessions)
                    gaps = calendar_gaps(sessions, start=start, cutoff=inputs.cutoff, captured_at=captured)
                    closed = []
                    if gaps:
                        control = next((day for day in reversed(sessions) if day < gaps[0]), None)
                        verdicts = self.fetch(SOURCE_ROUTING_VERSION+"."+self._tdx_key(gaps, control),
                            lambda: self._tdx_packages(gaps, control))
                        if any(verdicts.get(day) is True for day in gaps):
                            raise NativeSourceUnavailable("calendar_index_session_missing")
                        closed = [day for day in gaps if verdicts.get(day) is False]
                    rows = qualify_session_calendar(sessions, closed, start=start,
                        cutoff=inputs.cutoff, captured_at=captured)
                else:
                    # One closure schedule applies to SSE, SZSE and BSE, so the
                    # official SZSE month calendar serves every A-share ticker.
                    begin, end = date.fromisoformat(start), date.fromisoformat(inputs.cutoff)
                    year, month = begin.year, begin.month
                    rows = []
                    while (year, month) <= (end.year, end.month):
                        rows.extend(szse_month(self._get(SZSE_CALENDAR_URL, params={"month": f"{year}-{month}"}), year, month))
                        year, month = (year+1, 1) if month == 12 else (year, month+1)
                    rows = [row for row in rows if start.replace("-", "") <= row["cal_date"] <= inputs.cutoff.replace("-", "")]
                settled_sessions(rows, start=start, cutoff=inputs.cutoff, captured_at=captured)
                return rows
            result = self._attempt(CAP_PRICE, vendor, "calendar."+vendor, query)
            if result is None:
                if self.attempts[CAP_PRICE][-1].get("code") == "calendar_sources_conflict":
                    return None
                continue
            if vendor == "szse" and not self._cross_check_calendar(result, start, inputs.cutoff, captured, sessions_key):
                return None
            return result
        return None

    def _cross_check_calendar(self, rows, start, cutoff, captured, sessions_key):
        """Witness settled official days with the index bar dates (and TDX on dispute).

        Returns False only when two independent vendors contradict the official
        calendar.  An unavailable witness accepts the official calendar with a
        recorded degradation; it never triggers a quota-limited fallback.
        """
        if "tencent" in self.excluded_vendors:
            return True
        sessions = self._attempt(CAP_PRICE, "tencent", sessions_key, self._index_sessions)
        try:
            disputes = None if sessions is None else calendar_disputes(
                rows, sessions, start=start, cutoff=cutoff, captured_at=captured)
        except NativeSourceUnavailable as exc:
            self.attempts[CAP_PRICE].append({"vendor": "tencent", "key": sessions_key,
                                             "status": "unavailable", "code": exc.code})
            disputes = None
        if disputes is None:
            self.calendar_gaps.append("calendar_cross_check_unavailable")
            return True
        if not disputes:
            return True
        official = {api_date(row["cal_date"]): row["is_open"] == "1" for row in rows}
        control = next((day for day in reversed(sessions) if day < disputes[0] and official.get(day)), None)
        verdicts = self._attempt(CAP_PRICE, "tdx", self._tdx_key(disputes, control),
                                 lambda: self._tdx_packages(disputes, control)) or {}
        try:
            unresolved = settle_calendar_disputes(rows, disputes, verdicts)
        except NativeSourceUnavailable as exc:
            self.attempts[CAP_PRICE].append({"vendor": "szse", "key": "calendar.szse.cross_check",
                                             "status": "unavailable", "code": exc.code})
            return False
        self.calendar_detail = {"calendar_disputes": disputes, "calendar_disputes_unresolved": unresolved}
        if unresolved:
            self.calendar_gaps.append("calendar_cross_check_unresolved")
        return True

    def _prices(self, inputs, ts_code, identity):
        if identity is None:
            self._cap(inputs, CAP_PRICE, gaps=("listing_date_unknown",))
            return
        start = max((date.fromisoformat(inputs.cutoff)-timedelta(days=500)).isoformat(), api_date(identity["list_date"]))
        calendar_rows = self._calendar(inputs, ts_code, start)
        if calendar_rows is None:
            self._cap(inputs, CAP_PRICE)
            return
        for vendor in self.chains["price"]:
            def query(vendor=vendor):
                captured = datetime.now(timezone.utc)
                end = settled_sessions(calendar_rows, start=start, cutoff=inputs.cutoff, captured_at=captured)[-1]
                if vendor == "tencent":
                    def raw_query():
                        frame, provenance = get_a_share_kline_df(self.request.ticker, start, end, session=self.session)
                        return {"bars": frame.to_dict("records"), "provenance": provenance}
                    raw = self.fetch(SOURCE_ROUTING_VERSION+".price.tencent.raw", raw_query)
                    symbol = ts_code.split(".")[1].lower()+ts_code[:6]
                    factors = self.fetch(SOURCE_ROUTING_VERSION+".price.sina.factors", lambda: sina_factors(
                        self._get(f"https://finance.sina.com.cn/realstock/company/{symbol}/qfq.js", text=True), symbol=symbol))
                    result = prepare_public_prices(raw, factors, calendar_rows, ts_code=ts_code,
                        start=start, cutoff=inputs.cutoff, captured_at=captured)
                else:
                    daily = self.fetch(SOURCE_ROUTING_VERSION+".price.tushare.daily", lambda: self.tushare(
                        "daily", "ts_code,trade_date,open,high,low,close", ts_code=ts_code,
                        start_date=start.replace("-", ""), end_date=end.replace("-", "")))
                    factors = self.fetch(SOURCE_ROUTING_VERSION+".price.tushare.factors", lambda: self.tushare(
                        "adj_factor", "ts_code,trade_date,adj_factor", ts_code=ts_code,
                        start_date=start.replace("-", ""), end_date=end.replace("-", "")))
                    result = prepare_tushare_price_history(daily, factors, calendar_rows,
                        ts_code=ts_code, start=start, cutoff=inputs.cutoff, captured_at=captured)
                if result["provenance"]["pit_status"] != "verified" or not result["provenance"]["window_covered"]:
                    raise NativeSourceUnavailable("price_window_or_vintage_unqualified")
                result["computed_statistics"] = build_price_statistics(result["bars"], result["provenance"])
                return result
            result = self._attempt(CAP_PRICE, vendor, "price."+vendor+".prepared", query)
            if result is not None:
                source = "tencent.sina_adjusted_daily" if vendor == "tencent" else "tushare.adjusted_daily"
                self.evidence(inputs, CAP_PRICE, source, result)
                inputs.prices.extend(PriceObservation(observed_on=row["Date"], close=row["Close"],
                    adjustment="qfq", source=vendor, pit_verified=True) for row in result["bars"])
                # A calendar accepted without a witness stays qualified but says so.
                self._cap(inputs, CAP_PRICE, (source,), gaps=self.calendar_gaps,
                          detail={**result["provenance"], **self.calendar_detail})
                return
        self._cap(inputs, CAP_PRICE)

    def collect(self):
        inputs = FreezeInputs(self.run_id, self.request.ticker, self.request.analysis_date, self.request.catalyst_policy)
        ts_code = to_tushare_symbol(self.request.ticker)
        identity = self._identity(inputs, ts_code)
        self._events(inputs)
        self._financial(inputs, ts_code)
        self._prices(inputs, ts_code, identity)
        draft = EvidenceFreezer(inputs).close()
        by_family = {row["source_family_id"]: row["evidence_id"] for row in draft.evidence if row["capability"] == CAP_EVENT_COVERAGE}
        return draft.model_copy(update={"events": tuple(event.model_copy(update={
            "evidence_ids": (by_family[event.source_family_id],) if event.source_family_id in by_family else (),
        }) for event in draft.events)}), self.context
