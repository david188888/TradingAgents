"""Typed source admission for the initial bounded A-share profile.

Only explicit transports are admitted here: an opaque SDK or subprocess with
unobservable retries cannot satisfy the profile's HTTP-attempt ceiling.
Failure is recorded as a missing capability, never as a proved empty window.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas import CatalystEvidence
from tradingagents.dataflows.catalyst_events import CatalystEventV1, classify_earnings_title
from tradingagents.dataflows.china_specialty import get_a_share_cninfo_announcements
from tradingagents.dataflows.tencent_kline import get_a_share_kline_qfq_df
from tradingagents.dataflows.ticker_utils import to_tushare_symbol
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


def _iso_api_date(value: str) -> str:
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}").isoformat()


class CatalystSources:
    def __init__(self, request: Any, run_id: str, session: Any, fetch: Any):
        self.request, self.run_id, self.session, self.fetch = request, run_id, session, fetch
        self.context: dict[str, Any] = {}

    def require_vendor(self, vendor: str, category: str, method: str = "") -> None:
        config = self.request.effective_config
        selected = config.get("tool_vendors", {}).get(method) or config.get("data_vendors", {}).get(category, "")
        if vendor not in {item.strip() for item in selected.split(",")}:
            raise ValueError("configured_source_has_no_bounded_adapter")

    def tushare(self, api_name: str, fields: str, **params) -> list[dict[str, Any]]:
        token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API_KEY")
        if not token:
            raise ValueError("tushare_not_configured")
        response = self.session.post("https://api.tushare.pro", json={
            "api_name": api_name, "token": token, "params": params, "fields": fields,
        }, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            # Vendor messages can echo request fields. Persist only a code.
            raise ValueError(f"tushare_rejected_{payload.get('code')}")
        data = payload.get("data") or {}
        columns, rows = data.get("fields"), data.get("items")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ValueError("tushare_invalid_shape")
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def evidence(self, inputs: FreezeInputs, capability: str, source: str, content: Any,
                 *, published: str | None = None, public_url: str | None = None) -> None:
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        evidence_id = f"e.{capability}.d{digest[:16]}"
        observed = min(datetime.now(timezone.utc), datetime.combine(
            date.fromisoformat(inputs.cutoff), time.max, ZoneInfo("Asia/Shanghai")))
        record = CatalystEvidence(
            evidence_id=evidence_id, run_id=self.run_id, ticker=inputs.ticker,
            capability=capability, source_tier="official" if source == "cninfo" else "vendor",
            source_name=source, source_family_id=f"{source}:{digest}", public_url=public_url,
            captured_at=datetime.now(timezone.utc), observed_at=observed,
            published_at=datetime.fromisoformat(published+"T00:00:00+08:00") if published else None,
            usable_as_of=observed, time_basis="known by research cutoff; publication date checked",
            value_basis="source-reported values; monetary fields CNY, prices CNY/share",
        )
        inputs.evidence.append(record.model_dump(mode="json"))
        self.context[evidence_id] = content

    def collect(self):
        request = self.request
        inputs = FreezeInputs(self.run_id, request.ticker, request.analysis_date, request.catalyst_policy)
        ts_code = to_tushare_symbol(request.ticker)
        compact_end = request.analysis_date.replace("-", "")
        history_start = (date.fromisoformat(request.analysis_date)-timedelta(days=500)).isoformat()
        identity = None

        def admit(capability, operation):
            try:
                operation()
            except Exception as exc:
                inputs.capabilities.append(FrozenCapability(
                    capability=capability, status=CapabilityStatus.UNAVAILABLE, required=True,
                    reason=f"{capability}_unavailable:{type(exc).__name__}",
                    degradations=(f"{capability}_unavailable",),
                ))

        def get_identity():
            nonlocal identity
            self.require_vendor("tushare", "core_stock_apis")
            rows = self.fetch("identity", lambda: self.tushare(
                "stock_basic", "ts_code,name,list_date,exchange,market", ts_code=ts_code))
            matches = [r for r in rows if r.get("ts_code") == ts_code and r.get("name")]
            if len(matches) != 1:
                raise ValueError("identity_not_unique")
            identity = matches[0]
            if _iso_api_date(identity["list_date"]) > inputs.cutoff:
                raise ValueError("not_listed_at_cutoff")
            self.evidence(inputs, CAP_IDENTITY, "tushare.stock_basic", {
                "ts_code": identity["ts_code"], "list_date": identity["list_date"],
            })
            inputs.capabilities.append(FrozenCapability(
                capability=CAP_IDENTITY, status=CapabilityStatus.QUALIFIED, required=True,
                sources=("tushare.stock_basic",), reason="exact security code and listing date verified",
            ))

        def get_events():
            self.require_vendor("cninfo", "a_share_official_data", "get_a_share_cninfo_announcements")
            start = (date.fromisoformat(inputs.cutoff)-timedelta(days=90)).isoformat()
            def query():
                rows = []
                text = get_a_share_cninfo_announcements(request.ticker, start, inputs.cutoff,
                    session=self.session, records_sink=rows.extend)
                return {"records": rows, "coverage": text.coverage.model_dump(mode="json")}
            result = self.fetch("events", query)
            coverage = result["coverage"]
            qualified = coverage["completeness"] == "complete" and coverage["pagination_exhausted"] is True
            for row in result["records"]:
                published = row["Published"]
                if not start <= published <= inputs.cutoff:
                    continue
                title = row["Title"]
                self.evidence(inputs, CAP_EVENT_COVERAGE, "cninfo", row, published=published,
                              public_url=row["Detail URL"])
                inputs.events.append(CatalystEventV1(
                    security_id=request.ticker, kind=classify_earnings_title(title), channel="official",
                    title=title[:160], publication_date=published, state="point_in_time",
                    announcement_id=row["Announcement ID"] or None,
                    content_fingerprint=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                    source_family_id="cninfo:" + hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                ))
            inputs.capabilities.append(FrozenCapability(
                capability=CAP_EVENT_COVERAGE,
                status=CapabilityStatus.QUALIFIED if qualified else CapabilityStatus.PARTIAL,
                required=True, sources=("cninfo.announcements",),
                reason="publication dates and requested window checked" if qualified else "coverage_not_proven",
                degradations=tuple(coverage["degradations"]),
            ))

        def get_fundamentals():
            collected = {}
            complete = True
            fields_by_api = {
                "income": "ts_code,ann_date,f_ann_date,end_date,report_type,revenue,n_income",
                "balancesheet": "ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,total_liab",
                "cashflow": "ts_code,ann_date,f_ann_date,end_date,report_type,n_cashflow_act",
            }
            for api, fields in fields_by_api.items():
                method = {"income": "get_income_statement", "balancesheet": "get_balance_sheet", "cashflow": "get_cashflow"}[api]
                self.require_vendor("tushare", "fundamental_data", method)
                financial_start = (date.fromisoformat(inputs.cutoff)-timedelta(days=1100)).strftime("%Y%m%d")
                rows = self.fetch(api, lambda api=api, fields=fields, financial_start=financial_start: self.tushare(
                    api, fields, ts_code=ts_code, start_date=financial_start, end_date=compact_end))
                admissible = []
                for row in rows:
                    announced = row.get("f_ann_date") or row.get("ann_date")
                    if row.get("ts_code") != ts_code or not announced or str(row.get("report_type")) != "1":
                        continue
                    if _iso_api_date(announced) <= inputs.cutoff and _iso_api_date(row["end_date"]) <= inputs.cutoff:
                        admissible.append(row)
                if not admissible:
                    raise ValueError(f"{api}_no_pit_rows")
                by_period = {}
                for row in sorted(admissible,key=lambda r:(r["end_date"],r.get("f_ann_date") or r["ann_date"]),reverse=True):
                    by_period.setdefault(row["end_date"], row)
                collected[api] = list(by_period.values())[:8]
                complete = complete and len(collected[api]) == 8
            self.evidence(inputs, CAP_FUNDAMENTALS, "tushare.financial_statements", collected)
            inputs.capabilities.append(FrozenCapability(
                capability=CAP_FUNDAMENTALS, status=CapabilityStatus.QUALIFIED if complete else CapabilityStatus.PARTIAL, required=True,
                sources=("tushare.income","tushare.balancesheet","tushare.cashflow"),
                reason="three statements checked against publication cutoff; CNY units",
                degradations=() if complete else ("eight_reporting_periods_not_covered",),
            ))

        def get_prices():
            self.require_vendor("tencent", "core_stock_apis", "get_adjusted_price_history")
            if identity is None:
                raise ValueError("listing_date_unknown")
            start = max(history_start, _iso_api_date(identity["list_date"]))
            exchange = {"SH":"SSE","SZ":"SZSE","BJ":"BSE"}[ts_code.rsplit(".",1)[1]]
            calendar = self.fetch("calendar", lambda: self.tushare("trade_cal", "cal_date,is_open",
                exchange=exchange, start_date=start.replace("-",""), end_date=compact_end))
            days = sorted(_iso_api_date(r["cal_date"]) for r in calendar if str(r["is_open"]) == "1")
            if len(days) < 2:
                raise ValueError("insufficient_verified_trading_days")
            def query():
                frame, provenance = get_a_share_kline_qfq_df(request.ticker, start, inputs.cutoff,session=self.session)
                return {"bars": frame.to_dict("records"), "provenance": provenance}
            result = self.fetch("prices", query)
            bars, provenance = result["bars"], result["provenance"]
            observed = {row["Date"] for row in bars}
            expected = {d for d in days if d <= provenance["settled_through"]}
            if len(observed) < 2 or observed != expected or not provenance.get("window_covered"):
                raise ValueError("price_window_not_qualified")
            # qfq-to-today is not qualified for a historical cutoff.
            if provenance.get("pit_status") != "verified":
                raise ValueError("qfq_factor_snapshot_unverified")
            self.evidence(inputs, CAP_PRICE, "tencent.qfq", result)
            inputs.prices.extend(PriceObservation(observed_on=row["Date"],close=row["Close"],
                adjustment="qfq",source="tencent",pit_verified=True) for row in bars)
            inputs.capabilities.append(FrozenCapability(
                capability=CAP_PRICE,status=CapabilityStatus.QUALIFIED,required=True,sources=("tencent.qfq",),
                reason="qfq column, units, complete calendar and current anchor verified",
            ))

        admit(CAP_IDENTITY, get_identity)
        admit(CAP_EVENT_COVERAGE, get_events)
        admit(CAP_FUNDAMENTALS, get_fundamentals)
        admit(CAP_PRICE, get_prices)
        draft = EvidenceFreezer(inputs).close()
        # A filing cites its own source record, never every filing in the window.
        by_family = {record["source_family_id"]: record["evidence_id"] for record in draft.evidence
            if record["capability"] == CAP_EVENT_COVERAGE}
        draft = draft.model_copy(update={"events": tuple(event.model_copy(update={
            "evidence_ids": (by_family[event.source_family_id],) if event.source_family_id in by_family else (),
        }) for event in draft.events)})
        return draft, self.context
