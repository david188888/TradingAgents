"""Version-three native collector extension; v2 source topology stays intact."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradingagents.dataflows.china_specialty import get_a_share_cninfo_announcements
from tradingagents.dataflows.disclosure_documents import (
    BODY_SOURCE,
    MAX_PDF_BYTES,
    OPERATING_SOURCE,
    parse_document,
    pdf_url,
    report_period,
    select_documents,
)
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.native_sources import NativeSources
from tradingagents.execution.budget import BudgetExhausted
from tradingagents.research.evidence_freeze import CapabilityStatus, FrozenCapability

CAP_BODIES = "announcement_bodies"
CAP_OPERATING = "operating_detail"


class DisclosureSources(NativeSources):
    def _document_get(self, row, ts_code, cutoff, issuer_name):
        response = self.session.get(pdf_url(row), headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/",
        }, timeout=12, stream=True)
        try:
            if response.status_code != 200:
                raise NativeSourceUnavailable("document_http_unavailable")
            data = bytearray()
            for chunk in response.iter_content(65536):
                self.session.ensure_active()
                data.extend(chunk)
                if len(data) > MAX_PDF_BYTES:
                    raise NativeSourceUnavailable("document_byte_limit")
            return parse_document(bytes(data), row, ts_code=ts_code, cutoff=cutoff,
                                  issuer_name=issuer_name,
                                  ensure_active=self.session.ensure_active)
        finally:
            response.close()

    def _documents(self, inputs, ts_code, identity):
        gaps, documents, table_gaps = [], [], []
        catalogue = [payload for payload in self.context.values()
                     if isinstance(payload, dict) and "Announcement ID" in payload]
        reason = None
        if identity is None:
            reason = "document_identity_unqualified"
        elif not self.chains["events"]:
            reason = "document_source_disabled"
        elif inputs.cutoff != datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat():
            reason = "document_historical_vintage_unverified"
        if reason:
            gaps.append(reason)
        else:
            if not any(report_period(row.get("Title", "")) for row in catalogue):
                def query():
                    rows = []
                    report = get_a_share_cninfo_announcements(self.request.ticker,
                        (date.fromisoformat(inputs.cutoff)-timedelta(days=550)).isoformat(),
                        inputs.cutoff, session=self.session, records_sink=rows.extend)
                    return {"records": rows, "coverage": report.coverage.model_dump(mode="json")}
                try:
                    result = self._attempt(CAP_BODIES, "cninfo", "documents.catalogue.v1", query)
                except BudgetExhausted:
                    result = None
                    gaps.append("document_budget_exhausted")
                if result is not None:
                    if result["coverage"]["completeness"] != "complete":
                        gaps.append("document_catalogue_partial")
                    by_id = {row["Announcement ID"]: row for row in (*catalogue, *result["records"])}
                    catalogue = list(by_id.values())
            selected = select_documents(catalogue, inputs.cutoff)
            for row in selected:
                if "document_budget_exhausted" in gaps:
                    break
                try:
                    document = self._attempt(CAP_BODIES, "cninfo", "document.v1."+row["Announcement ID"],
                        lambda row=row: self._document_get(row, ts_code, inputs.cutoff, identity.get("name")))
                except BudgetExhausted:
                    gaps.append("document_budget_exhausted")
                    break
                if document is not None:
                    documents.append(document)
                else:
                    gaps.append("document_selected_unavailable")
            if not selected:
                gaps.append("document_no_admitted_candidate")
        for document in documents:
            metadata = {key: document[key] for key in (
                "document_id", "title", "published", "ts_code", "url", "pdf_sha256",
                "page_count", "parser_version", "report_period", "body_coverage")}
            for excerpt in document["excerpts"]:
                self.evidence(inputs, CAP_BODIES, BODY_SOURCE, {**metadata, **excerpt},
                    published=document["published"], public_url=document["url"])
            for row in document["operating_rows"]:
                self.evidence(inputs, CAP_OPERATING, OPERATING_SOURCE, {**metadata, "row": row},
                    published=document["published"], public_url=document["url"])
            table_gaps.extend(document["gaps"])
        # Record selection separately from list completeness and table coverage.
        bodies = any(doc["excerpts"] for doc in documents)
        operating = any(doc["operating_rows"] for doc in documents)
        for capability, available, sources in (
            (CAP_BODIES, bodies, (BODY_SOURCE,)), (CAP_OPERATING, operating, (OPERATING_SOURCE,))):
            cap_gaps = list(gaps)
            if capability == CAP_OPERATING:
                cap_gaps = [gap for gap in gaps if gap != "document_selected_unavailable"
                    and (not operating or gap != "document_budget_exhausted")]
                cap_gaps.extend(table_gaps)
            if capability == CAP_BODIES and bodies:
                cap_gaps.append("document_selected_excerpts_only")
            if capability == CAP_OPERATING and not operating:
                cap_gaps.append("operating_detail_not_admitted")
            status = CapabilityStatus.PARTIAL if available and cap_gaps else (
                CapabilityStatus.QUALIFIED if available else CapabilityStatus.UNAVAILABLE)
            inputs.capabilities.append(FrozenCapability(capability=capability, required=False,
                status=status, sources=sources if available else (),
                reason="selected_official_document_fields" if available else "no_admitted_document_fields",
                degradations=tuple(sorted(set(cap_gaps))), detail={
                    "selection_version": "official-documents-v1", "attempts": self.attempts.get(CAP_BODIES, []),
                    "selected_ids": [row["Announcement ID"] for row in selected] if not reason else [],
                    "unselected_ids": sorted(row["Announcement ID"] for row in catalogue
                        if reason or row not in selected),
                    "selected_unavailable_ids": [row["Announcement ID"] for row in selected
                        if row["Announcement ID"] not in {doc["document_id"] for doc in documents}] if not reason else [],
                }))
        # New families are explicitly official; never rename them as statements.
        inputs.evidence[:] = [{**item, "source_tier": "official"} if item["source_name"] in {
            BODY_SOURCE, OPERATING_SOURCE} else item for item in inputs.evidence]

    def _prices(self, inputs, ts_code, identity):
        super()._prices(inputs, ts_code, identity)
        self._documents(inputs, ts_code, identity)
