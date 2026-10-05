"""V5 collector: qualified official rows and optional valuation context."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas._evidence_checks import PeerQuoteV1
from tradingagents.dataflows.china_specialty import get_a_share_cninfo_announcements
from tradingagents.dataflows.disclosure_documents import BODY_SOURCE, MAX_PDF_BYTES, pdf_url
from tradingagents.dataflows.disclosure_documents_v2 import (
    NUMERIC_SOURCE,
    parse_document,
    select_documents,
    title_info,
)
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.native_sources import NativeSources
from tradingagents.dataflows.native_valuation import (
    CAP_VALUATION,
    HISTORY_SOURCE,
    SNAPSHOT_SOURCE,
    ValuationSources,
    qualify_history,
    qualify_snapshot,
)
from tradingagents.dataflows.supplemental_valuation import (
    CAP_FORECAST,
    CAP_PEERS,
    eastmoney_forecasts,
    peer_candidates,
    ths_forecasts,
)
from tradingagents.execution.budget import BudgetExhausted
from tradingagents.research.evidence_freeze import CapabilityStatus, FrozenCapability


class MinimumEvidenceSources(ValuationSources):
    def __init__(self, request, run_id, session, fetch):
        config = deepcopy(request.effective_config)
        overrides = config.get("evidence_source_vendors", {})
        if not isinstance(overrides, dict):
            raise ValueError("invalid_native_source_configuration")
        self.forecast_vendors = overrides.pop("forecasts", ["ths", "eastmoney"])
        self.peer_vendors = overrides.pop("peers", ["eastmoney", "tencent"])
        excluded = config.get("evidence_source_exclusions", [])
        if not isinstance(excluded, list):
            raise ValueError("invalid_native_source_configuration")
        for vendors, allowed in ((self.forecast_vendors, {"ths", "eastmoney"}), (self.peer_vendors, {"eastmoney", "tencent"})):
            if not isinstance(vendors, list) or any(not isinstance(v, str) or v not in allowed for v in vendors) or len(set(vendors)) != len(vendors):
                raise ValueError("invalid_native_source_configuration")
        self.forecast_vendors = [v for v in self.forecast_vendors if v not in excluded]
        self.peer_vendors = [v for v in self.peer_vendors if v not in excluded]
        config["evidence_source_exclusions"] = [v for v in excluded if v != "ths"]
        super().__init__(SimpleNamespace(**{**vars(request), "effective_config": config}), run_id, session, fetch)

    def _optional_cap(self, inputs, capability, sources, gaps=(), detail=None):
        inputs.capabilities.append(FrozenCapability(capability=capability, required=False,
            status=CapabilityStatus.PARTIAL if sources and gaps else CapabilityStatus.QUALIFIED if sources else CapabilityStatus.UNAVAILABLE,
            sources=tuple(dict.fromkeys(sources)), reason="qualified_selected_fields" if sources else "no_admitted_selected_fields",
            degradations=tuple(sorted(set(gaps))), detail={"attempts": self.attempts.get(capability, []), **(detail or {})}))

    def _document_get(self, row, ts_code, cutoff, issuer_name):
        response = self.session.get(pdf_url(row), headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}, timeout=12, stream=True)
        try:
            if response.status_code != 200:
                raise NativeSourceUnavailable("document_http_unavailable")
            content = bytearray()
            for chunk in response.iter_content(65536):
                self.session.ensure_active()
                content.extend(chunk)
                if len(content) > MAX_PDF_BYTES:
                    raise NativeSourceUnavailable("document_byte_limit")
            return parse_document(bytes(content), row, ts_code=ts_code, cutoff=cutoff,
                issuer_name=issuer_name, ensure_active=self.session.ensure_active)
        finally:
            response.close()

    def _documents(self, inputs, ts_code, identity):
        gaps, documents, selected = [], [], []
        catalogue = [p for p in self.context.values() if isinstance(p, dict) and "Announcement ID" in p]
        if identity is None or not self.chains["events"]:
            gaps.append("document_identity_unqualified" if identity is None else "document_source_disabled")
        elif inputs.cutoff != datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat():
            gaps.append("document_historical_vintage_unverified")
        else:
            if not any((info := title_info(r.get("Title", ""))) and info["kind"] == "report" for r in catalogue):
                def query():
                    rows = []
                    report = get_a_share_cninfo_announcements(self.request.ticker,
                        (date.fromisoformat(inputs.cutoff)-timedelta(days=550)).isoformat(), inputs.cutoff,
                        session=self.session, records_sink=rows.extend)
                    return {"records": rows, "coverage": report.coverage.model_dump(mode="json")}
                try:
                    result = self._attempt("announcement_bodies", "cninfo", "documents.catalogue.v5", query)
                except BudgetExhausted:
                    result = None
                    gaps.append("document_budget_exhausted")
                if result is not None:
                    catalogue = list({r["Announcement ID"]: r for r in (*catalogue, *result["records"])}.values())
                    if result["coverage"]["completeness"] != "complete":
                        gaps.append("document_catalogue_partial")
            selected = select_documents(catalogue, inputs.cutoff)
            for row in selected:
                if "document_budget_exhausted" in gaps:
                    break
                try:
                    document = self._attempt("announcement_bodies", "cninfo", "document.v5."+row["Announcement ID"],
                        lambda row=row: self._document_get(row, ts_code, inputs.cutoff, identity.get("name")))
                except BudgetExhausted:
                    gaps.append("document_budget_exhausted")
                    break
                if document is None:
                    gaps.append("document_selected_unavailable")
                else:
                    documents.append(document)
            if not selected:
                gaps.append("document_no_admitted_candidate")
        for doc in documents:
            metadata = {k: doc[k] for k in ("document_id", "title", "published", "ts_code", "url", "pdf_sha256",
                "page_count", "parser_version", "report_period", "document_kind", "body_coverage")}
            for excerpt in doc["excerpts"]:
                self.evidence(inputs, "announcement_bodies", BODY_SOURCE, {**metadata, **excerpt}, published=doc["published"], public_url=doc["url"])
            for row in doc["numeric_rows"]:
                self.evidence(inputs, "operating_detail", NUMERIC_SOURCE, {**metadata, "row": row}, published=doc["published"], public_url=doc["url"])
            gaps.extend(doc["gaps"])
        detail = {"selection_version": "official-documents-v2", "selected_ids": [r["Announcement ID"] for r in selected],
            "unselected_ids": sorted(r["Announcement ID"] for r in catalogue if r not in selected),
            "selected_unavailable_ids": [r["Announcement ID"] for r in selected if r["Announcement ID"] not in {d["document_id"] for d in documents}]}
        self._optional_cap(inputs, "announcement_bodies", [BODY_SOURCE] if any(d["excerpts"] for d in documents) else [],
            (*gaps, "document_selected_excerpts_only"), detail)
        self._optional_cap(inputs, "operating_detail", [NUMERIC_SOURCE] if any(d["numeric_rows"] for d in documents) else [], gaps, detail)
        inputs.evidence[:] = [{**e, "source_tier": "official"} if e["source_name"] in {BODY_SOURCE, NUMERIC_SOURCE} else e for e in inputs.evidence]

    def _forecasts(self, inputs, ts_code, identity):
        sources, gaps = [], ["sampled_institution_forecasts_not_complete_consensus"]
        if identity is None or inputs.cutoff != datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat():
            self._optional_cap(inputs, CAP_FORECAST, (), ("forecast_identity_or_vintage_unqualified",))
            return
        for vendor in self.forecast_vendors:
            def query(vendor=vendor):
                if vendor == "ths":
                    response = self.session.get(f"https://basic.10jqka.com.cn/new/{ts_code[:6]}/worth.html", headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
                    if response.status_code != 200:
                        raise NativeSourceUnavailable("forecast_http_unavailable")
                    html = response.content.decode("gb18030")
                    return ths_forecasts(html, ts_code=ts_code, cutoff=inputs.cutoff)
                response = self._get("https://reportapi.eastmoney.com/report/list", params={
                    "industryCode": "*", "pageSize": 20, "industry": "*", "rating": "*", "ratingChange": "*",
                    "beginTime": (date.fromisoformat(inputs.cutoff)-timedelta(days=180)).isoformat(), "endTime": inputs.cutoff,
                    "pageNo": 1, "fields": "", "qType": 0, "orgCode": "", "code": ts_code[:6], "rcode": ""})
                return eastmoney_forecasts(response, ts_code=ts_code, cutoff=inputs.cutoff)
            try:
                rows = self._attempt(CAP_FORECAST, vendor, "forecasts.v5."+vendor, query)
            except BudgetExhausted:
                gaps.append("forecast_budget_exhausted")
                break
            if not rows:
                gaps.append("forecast_source_no_admitted_rows:"+vendor)
                continue
            source = vendor+".dated_forecast"
            for row in rows:
                self.evidence(inputs, CAP_FORECAST, source, row, published=row["published"],
                    public_url=f"https://basic.10jqka.com.cn/new/{ts_code[:6]}/worth.html" if vendor == "ths" else "https://data.eastmoney.com/report/"+row["report_id"]+".html")
            sources.append(source)
            break  # One adequate dated feed is enough; no redundant crawl.
        self._optional_cap(inputs, CAP_FORECAST, sources, gaps)

    def _valuation(self, inputs, ts_code, identity):
        sources, peer_sources, gaps, peer_gaps = [], [], [], ["industry_candidates_not_business_equivalence", "selected_peers_not_full_industry_population"]
        eligible = identity is not None and self.last_session is not None and inputs.cutoff == datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        selection = None
        if eligible and "eastmoney" in self.peer_vendors:
            def candidates_query():
                payload = self._get("https://datacenter.eastmoney.com/securities/api/data/v1/get", params={
                    "reportName": "RPT_PCF10_INDUSTRY_CVALUE", "columns": "ALL", "filter": '(SECUCODE="'+ts_code+'")',
                    "pageNumber": 1, "pageSize": 20, "source": "WEB", "client": "WEB"})
                return peer_candidates(payload, ts_code=ts_code)
            try:
                selection = self._attempt(CAP_PEERS, "eastmoney", "peer_candidates.v5", candidates_query)
            except BudgetExhausted:
                peer_gaps.append("peer_budget_exhausted")
            if selection is not None:
                self.evidence(inputs, CAP_PEERS, "eastmoney.peer_candidates", selection, published=inputs.cutoff,
                    public_url="https://data.eastmoney.com/stockdata/"+ts_code[:6]+".html")
                peer_sources.append("eastmoney.peer_candidates")
        if eligible and "tencent" in self.valuation_vendors:
            codes = [ts_code] + ([r["ts_code"] for r in selection["candidates"]] if selection and "tencent" in self.peer_vendors else [])
            url = "https://qt.gtimg.cn/q="+",".join(c[-2:].lower()+c[:6] for c in codes)
            def quote_query():
                response = self.session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
                if response.status_code != 200:
                    raise NativeSourceUnavailable("valuation_http_unavailable")
                text = response.content.decode("gb18030")
                target = qualify_snapshot(text, ts_code=ts_code, last_session=self.last_session)
                peers = []
                for code in codes[1:]:
                    try:
                        peers.append(PeerQuoteV1(target_ts_code=ts_code, **qualify_snapshot(text, ts_code=code, last_session=self.last_session)).model_dump(mode="json"))
                    except (NativeSourceUnavailable, ValueError):
                        continue
                return {"target": target, "peers": peers}
            try:
                quotes = self._attempt(CAP_VALUATION, "tencent", "valuation.batch.v5", quote_query)
            except BudgetExhausted:
                quotes = None
                gaps.append("valuation_budget_exhausted")
            if quotes:
                self.evidence(inputs, CAP_VALUATION, SNAPSHOT_SOURCE, quotes["target"], published=self.last_session, public_url=url)
                sources.append(SNAPSHOT_SOURCE)
                for row in quotes["peers"]:
                    self.evidence(inputs, CAP_PEERS, "tencent.peer_valuation", row, published=self.last_session, public_url=url)
                if quotes["peers"]:
                    peer_sources.append("tencent.peer_valuation")
        if eligible and "tushare" in self.valuation_vendors:
            start = (date.fromisoformat(inputs.cutoff)-timedelta(days=1095)).isoformat()
            def history_query():
                rows = self.tushare("daily_basic", "ts_code,trade_date,pe_ttm,pb", ts_code=ts_code,
                    start_date=start.replace("-", ""), end_date=self.last_session.replace("-", ""))
                return {"ts_code": ts_code, "as_of": self.last_session, "currency": "CNY", "capture_scope": "current_cutoff_retrospective_history",
                    "rows": qualify_history(rows, ts_code=ts_code, start=start, end=self.last_session)}
            try:
                history = self._attempt(CAP_VALUATION, "tushare", "valuation.history.v5", history_query)
            except BudgetExhausted:
                history = None
                gaps.append("valuation_budget_exhausted")
            if history:
                self.evidence(inputs, CAP_VALUATION, HISTORY_SOURCE, history, published=self.last_session)
                sources.append(HISTORY_SOURCE)
        if not eligible:
            gaps.append("valuation_identity_calendar_or_vintage_unqualified")
            peer_gaps.append("peer_identity_calendar_or_vintage_unqualified")
        if SNAPSHOT_SOURCE not in sources:
            gaps.append("valuation_snapshot_unavailable")
        if HISTORY_SOURCE not in sources:
            gaps.append("valuation_history_unavailable")
        if "tencent.peer_valuation" not in peer_sources:
            peer_gaps.append("peer_quotes_unavailable")
        self._optional_cap(inputs, CAP_VALUATION, sources, gaps)
        self._optional_cap(inputs, CAP_PEERS, peer_sources, peer_gaps)

    def _prices(self, inputs, ts_code, identity):
        NativeSources._prices(self, inputs, ts_code, identity)
        self._documents(inputs, ts_code, identity)
        self._valuation(inputs, ts_code, identity)
        self._forecasts(inputs, ts_code, identity)
