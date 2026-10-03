"""Code-owned facts from a frozen, qualified source context; no I/O or LLMs."""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas._catalyst_research import CatalystEvidence
from tradingagents.agents.schemas._research_record import (
    RecordClaimV1,
    ResearchRecordV1,
    SourceContentV1,
    SourceEvidenceV1,
    make_evidence_snapshot,
)
from tradingagents.agents.schemas._verification_plan import FINANCIAL_FIELDS, FinancialOperandV1
from tradingagents.dataflows.ticker_utils import to_tushare_symbol
from tradingagents.research.evidence_freeze import (
    CAP_EVENT_COVERAGE,
    CAP_FUNDAMENTALS,
    CAP_IDENTITY,
    CAP_PRICE,
    CapabilityStatus,
    FrozenEvidenceDraft,
)
from tradingagents.research.record_assembly import _catalyst_content, _price_metrics, _safe_url
from tradingagents.research.verification_tools import (
    _date,
    _financial_operand,
    _number,
    _Unavailable,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
Mode = Literal["company_research", "catalyst_research", "holding_review"]
_SOURCE_CAPABILITIES = {
    "tushare.stock_basic": CAP_IDENTITY,
    "tushare.financial_statements": CAP_FUNDAMENTALS,
    "cninfo": CAP_EVENT_COVERAGE,
    "tushare.adjusted_daily": CAP_PRICE,
    "tencent.qfq": CAP_PRICE,
}


def _opaque_id(kind: str, *parts) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{kind}.{hashlib.sha256(encoded.encode()).hexdigest()[:32]}"


def _content(payload: dict, label: str) -> SourceContentV1 | None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if not payload or len(text) > 4000:
        return None
    return SourceContentV1(kind="source_fields", text=text, locator_label=label,
        content_sha256=hashlib.sha256(text.encode()).hexdigest())


def _financial_content(payload, ticker: str) -> SourceContentV1 | None:
    if not isinstance(payload, dict):
        return None
    selected = {}
    for table, fields in FINANCIAL_FIELDS.items():
        rows = payload.get(table)
        if not isinstance(rows, list):
            continue
        admitted = []
        for row in rows[:8]:
            if not isinstance(row, dict) or row.get("ts_code") != ticker:
                continue
            if isinstance(row.get("report_type"), bool) or str(row.get("report_type")) != "1":
                continue
            try:
                for key in ("end_date", "ann_date", "f_ann_date"):
                    if row.get(key) is not None:
                        _date(row[key])
            except _Unavailable:
                continue
            saved = {key: row[key] for key in ("end_date", "ann_date", "f_ann_date")
                if key in row and isinstance(row[key], str)}
            for key in sorted(fields):
                if key in row:
                    with suppress(_Unavailable):
                        saved[key] = str(_number(row[key]))
            admitted.append(saved)
        if admitted:
            selected[table] = admitted
    return _content(selected, "已保存各表最多八期合并财务字段；金额 CNY，日期为披露/报告日期")


def _source_content(item: CatalystEvidence, payload, ticker: str) -> SourceContentV1 | None:
    if item.source_name == "tushare.financial_statements":
        return _financial_content(payload, ticker)
    if item.source_name == "tencent.qfq":
        return _catalyst_content("tushare.adjusted_daily", payload)
    return _catalyst_content(item.source_name, payload)


def _source_record(item: CatalystEvidence, draft: FrozenEvidenceDraft, payload) -> SourceEvidenceV1:
    limitation = ["source_fields_are_not_full_document_text"]
    availability = item.availability
    capability = draft.capability(item.capability)
    expected = _SOURCE_CAPABILITIES.get(item.source_name)
    admitted_statuses = {CapabilityStatus.QUALIFIED, CapabilityStatus.PARTIAL}
    if item.capability in {CAP_IDENTITY, CAP_PRICE}:
        admitted_statuses = {CapabilityStatus.QUALIFIED}
    if capability is None or capability.status not in admitted_statuses or expected != item.capability:
        availability = "unavailable"
        limitation.append("source_capability_unqualified")
    elif capability.status is CapabilityStatus.PARTIAL:
        limitation.extend(("partial_source_coverage", *capability.degradations))
    usable_as_of = item.usable_as_of
    if usable_as_of is None or usable_as_of.tzinfo is None or usable_as_of.astimezone(SHANGHAI).date() > date.fromisoformat(draft.cutoff):
        availability = "unavailable"
        usable_as_of = None
        limitation.append("source_point_in_time_unqualified")
    if item.published_at is not None and (item.published_at.tzinfo is None or item.published_at.astimezone(SHANGHAI).date() > date.fromisoformat(draft.cutoff)):
        availability = "unavailable"
        limitation.append("source_publication_after_cutoff_or_unqualified")
    content = _source_content(item, payload, to_tushare_symbol(draft.ticker))
    if content is None:
        availability = "unavailable"
        limitation.append("source_fields_missing_invalid_or_exceed_public_limit")
    if item.source_name == "cninfo":
        limitation.append("announcement_list_title_not_body_or_implementation_proof")
        try:
            listed_date = _date(payload.get("Published"))
            if item.published_at is None or listed_date != item.published_at.astimezone(SHANGHAI).date():
                raise _Unavailable("disclosure_unqualified")
        except (_Unavailable, AttributeError):
            availability = "unavailable"
            limitation.append("announcement_publication_unqualified")
    public_url = _safe_url(item.public_url)
    if item.public_url and public_url is None:
        limitation.append("source_public_url_not_admitted")
    if item.source_name in {"tushare.adjusted_daily", "tencent.qfq"}:
        try:
            provenance = payload["provenance"]
            bars = payload["bars"]
            if (provenance.get("pit_status") != "verified" or not provenance.get("window_covered")
                or provenance.get("price_unit") != "CNY/share" or not bars
                or _date(provenance.get("adjustment_anchor")) > date.fromisoformat(draft.cutoff)
                or any(_date(row.get("Date")) > date.fromisoformat(draft.cutoff) for row in bars)):
                raise _Unavailable("source_unqualified")
        except (KeyError, TypeError, AttributeError, _Unavailable):
            availability = "unavailable"
            limitation.append("price_history_point_in_time_or_unit_unqualified")
    return SourceEvidenceV1(evidence_id=item.evidence_id,
        source_name="cninfo.announcements" if item.source_name == "cninfo" else item.source_name,
        source_kind=item.source_tier, source_family_id=item.source_family_id,
        availability=availability, public_url=public_url,
        published_at=item.published_at if item.published_at is None or item.published_at.tzinfo else None,
        usable_as_of=usable_as_of, captured_at=item.captured_at,
        content=content, limitations=tuple(dict.fromkeys(limitation)))


def _fact(source: SourceEvidenceV1, dimension: str, locator: str, statement: str) -> RecordClaimV1:
    return RecordClaimV1(claim_id=_opaque_id("f", source.evidence_id, locator, statement),
        kind="fact", statement=statement, evidence_ids=(source.evidence_id,),
        limitations=(*source.limitations, f"source_field:{locator}", f"native_dimension:{dimension}"))


def build_native_record(draft: FrozenEvidenceDraft, context: dict, *, mode: Mode,
                        original_thesis: str | None = None,
                        holding_facts_as_of: str | None = None) -> ResearchRecordV1:
    """Retain proven fields only; source coverage gaps never prove absence.

    Context bytes are bound to the collector's source-family digest before any
    fields are selected. Financial values use exactly the C1 operand parser.
    A user thesis is retained as a declaration, never as independently verified
    economic evidence. No holdings, value range or inference is invented.
    """
    if mode not in {"company_research", "catalyst_research", "holding_review"}:
        raise ValueError("unsupported native research mode")
    if mode != "holding_review" and (original_thesis is not None or holding_facts_as_of is not None):
        raise ValueError("holding inputs require holding_review")
    cutoff = date.fromisoformat(draft.cutoff)
    sources = []
    payloads = {}
    for raw in draft.evidence:
        item = CatalystEvidence.model_validate(raw)
        if (item.run_id, item.ticker) != (draft.run_id, draft.ticker):
            raise ValueError("frozen source identity does not match draft")
        payload = context.get(item.evidence_id)
        if payload is not None:
            digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if item.source_family_id != f"{item.source_name}:{digest}":
                raise ValueError("frozen source context changed from family digest")
        source = _source_record(item, draft, payload)
        sources.append(source)
        payloads[source.evidence_id] = payload
    if len({item.evidence_id for item in sources}) != len(sources):
        raise ValueError("duplicate frozen source evidence")

    identity_ok = draft.status_of(CAP_IDENTITY) is CapabilityStatus.QUALIFIED
    identities = [item for item in sources if item.source_name == "tushare.stock_basic" and item.availability == "available"]
    identity_ok = identity_ok and len(identities) == 1
    if identity_ok:
        identity_payload = payloads[identities[0].evidence_id]
        try:
            identity_ok = identity_payload.get("ts_code") == to_tushare_symbol(draft.ticker) and _date(identity_payload.get("list_date")) <= cutoff
        except _Unavailable:
            identity_ok = False

    # User declarations require a saved historical date, not an invented "now".
    if mode == "holding_review" and original_thesis:
        if not isinstance(original_thesis, str) or len(original_thesis) > 4000:
            raise ValueError("original thesis must fit saved public content")
        if holding_facts_as_of is None or date.fromisoformat(holding_facts_as_of) > cutoff:
            raise ValueError("original thesis requires a holding facts date at cutoff")
        thesis_time = datetime.combine(date.fromisoformat(holding_facts_as_of), time.min, SHANGHAI)
        sources.append(SourceEvidenceV1(evidence_id=_opaque_id("e", draft.run_id, "thesis", original_thesis, holding_facts_as_of),
            source_name="user.original_thesis", source_kind="unknown", availability="available",
            source_family_id=_opaque_id("user", draft.run_id, original_thesis),
            published_at=thesis_time, usable_as_of=thesis_time, captured_at=draft.frozen_at,
            content=SourceContentV1(kind="excerpt", text=original_thesis, locator_label="用户保存的原持仓论点（声明）",
                content_sha256=hashlib.sha256(original_thesis.encode()).hexdigest()),
            limitations=("user_declaration_not_independently_verified",)))

    evidence = tuple(sources)
    seed = ResearchRecordV1(run_id=draft.run_id, ticker=draft.ticker, mode=mode,
        analysis_date=cutoff, construction="native", evidence=evidence,
        snapshots=(make_evidence_snapshot(evidence),),
        limitations=() if identity_ok else ("security_identity_unqualified",))
    if not identity_ok:
        return seed
    facts = []
    metrics = []
    for source in sources:
        if source.availability != "available" or source.content is None:
            continue
        if source.source_name == "tushare.financial_statements":
            selected = json.loads(source.content.text)
            for table, rows in selected.items():
                for row in rows:
                    try:
                        period = _date(row.get("end_date")).isoformat()
                    except _Unavailable:
                        continue
                    for field in sorted(FINANCIAL_FIELDS[table]):
                        if field not in row:
                            continue
                        try:
                            value, _ = _financial_operand(seed, FinancialOperandV1(evidence_id=source.evidence_id,
                                table=table, field=field, report_period=period))
                        except _Unavailable:
                            continue
                        facts.append(_fact(source, "operating_quality", f"{table}[end_date={period}].{field}",
                            f"合并财务字段：报告期 {period}，{table}.{field} = {value} CNY。"))
        elif source.source_name == "cninfo.announcements":
            payload = payloads[source.evidence_id]
            title = payload.get("Title")
            if isinstance(title, str) and title and len(title) <= 1000 and source.published_at is not None:
                facts.append(_fact(source, "event_context", "Title;Published", f"{source.published_at.astimezone(SHANGHAI).date()} 的公告列表披露标题“{title}”；仅为标题，尚未核对正文或实施情况。"))
        elif source.source_name in {"tushare.adjusted_daily", "tencent.qfq"}:
            payload = payloads[source.evidence_id]
            last_bar = max(payload["bars"], key=lambda item: item["Date"])
            try:
                close = _number(last_bar.get("Close"))
                if close <= 0:
                    raise _Unavailable("invalid_fields")
                facts.append(_fact(source, "market_context", f"bars[Date={last_bar['Date']}].Close",
                    f"已保存行情：{last_bar['Date']} 收盘价 {close} CNY/share；这是价格观察，不是价值区间。"))
            except _Unavailable:
                pass
            try:
                qualified_metrics = _price_metrics(source.evidence_id, payload)
            except (KeyError, TypeError, ValueError):
                qualified_metrics = ()
            qualified_metrics = tuple(item for item in qualified_metrics if item.window_end is None or item.window_end <= cutoff)
            metrics.extend(qualified_metrics)
            for metric in qualified_metrics:
                if metric.availability == "available":
                    facts.append(_fact(source, "market_context", f"computed_statistics:{metric.metric_id}",
                        f"脚本计算 {metric.label} = {metric.value} {metric.unit}；样本 {metric.sample_size}，窗口 {metric.window_start} 至 {metric.window_end}；这是历史风险统计，不是价值区间。"))
        elif source.source_name == "user.original_thesis":
            facts.append(_fact(source, "holding_thesis", "original_thesis", "用户保存了原持仓论点；正文见证据摘录。这仅证明用户的原声明，不证明该论点为真。"))
    return ResearchRecordV1.model_validate({**seed.model_dump(mode="python"), "claims": tuple(facts), "metrics": tuple(metrics)})
