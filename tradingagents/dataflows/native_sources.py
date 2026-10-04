"""Bounded multi-source routing for the three evidence_v1 research modes."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import requests

from tradingagents.dataflows.catalyst_events import CatalystEventV1, classify_earnings_title
from tradingagents.dataflows.catalyst_sources import CatalystSources
from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.china_specialty import get_a_share_cninfo_announcements
from tradingagents.dataflows.native_qualification import (
    NativeSourceUnavailable,
    api_date,
    prepare_public_prices,
    qualify_identity,
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
from tradingagents.research.price_statistics import build_price_statistics
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

SOURCE_ROUTING_VERSION = "native-public-sources-v1"
DEFAULT_CHAINS = {
    "identity": ("eastmoney", "sina", "tushare"),
    "financial": ("sina", "tushare"),
    "calendar": ("szse", "tushare"),
    "price": ("tencent", "tushare"),
    "events": ("cninfo",),
}
SINA_FINANCE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
SZSE_CALENDAR_URL = "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
STATEMENT_FIELDS = {
    "income": "ts_code,ann_date,f_ann_date,end_date,report_type,revenue,n_income,n_income_attr_p",
    "balancesheet": "ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,total_liab",
    "cashflow": "ts_code,ann_date,f_ann_date,end_date,report_type,n_cashflow_act",
}


def source_chains(config):
    overrides = config.get("evidence_source_vendors", {})
    excluded = config.get("evidence_source_exclusions", [])
    allowed = {vendor for chain in DEFAULT_CHAINS.values() for vendor in chain}
    if (not isinstance(overrides, dict) or set(overrides)-DEFAULT_CHAINS.keys()
        or not isinstance(excluded, list) or any(not isinstance(v, str) or v not in allowed for v in excluded)):
        raise ValueError("invalid_native_source_configuration")
    output = {}
    for key, defaults in DEFAULT_CHAINS.items():
        chain = overrides.get(key, list(defaults))
        if (not isinstance(chain, list) or any(not isinstance(v, str) or v not in defaults for v in chain)
            or len(set(chain)) != len(chain)):
            raise ValueError("invalid_native_source_configuration")
        output[key] = tuple(v for v in chain if v not in excluded)
    return output


class NativeSources(CatalystSources):
    def __init__(self, request, run_id, session, fetch):
        super().__init__(request, run_id, session, fetch)
        self.chains = source_chains(request.effective_config)
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
        for vendor, bundle in bundles.items():
            self.evidence(inputs, CAP_FUNDAMENTALS, vendor+".financial_statements", bundle)
        self._cap(inputs, CAP_FUNDAMENTALS, tuple(v+".financial_statements" for v in bundles),
                  partial=bool(gaps), gaps=gaps, detail={"selected_tables": selected})

    def _calendar(self, inputs, ts_code, start):
        for vendor in self.chains["calendar"]:
            def query(vendor=vendor):
                if vendor == "tushare":
                    rows = self.tushare("trade_cal", "cal_date,is_open", exchange={"SZ": "SZSE", "SH": "SSE", "BJ": "BSE"}[ts_code.split(".")[1]],
                        start_date=start.replace("-", ""), end_date=inputs.cutoff.replace("-", ""))
                else:
                    if not ts_code.endswith(".SZ"):
                        raise NativeSourceUnavailable("calendar_exchange_unsupported")
                    begin, end = date.fromisoformat(start), date.fromisoformat(inputs.cutoff)
                    year, month = begin.year, begin.month
                    rows = []
                    while (year, month) <= (end.year, end.month):
                        rows.extend(szse_month(self._get(SZSE_CALENDAR_URL, params={"month": f"{year}-{month}"}), year, month))
                        year, month = (year+1, 1) if month == 12 else (year, month+1)
                    rows = [row for row in rows if start.replace("-", "") <= row["cal_date"] <= inputs.cutoff.replace("-", "")]
                settled_sessions(rows, start=start, cutoff=inputs.cutoff, captured_at=datetime.now(timezone.utc))
                return rows
            result = self._attempt(CAP_PRICE, vendor, "calendar."+vendor, query)
            if result is not None:
                return result
        return None

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
                self._cap(inputs, CAP_PRICE, (source,), detail=result["provenance"])
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
