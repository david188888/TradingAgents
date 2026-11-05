"""Bounded capability supplements: validate, fetch, admit; models never see backends."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas._evidence import RecordClaimV1, SourceContentV1, SourceEvidenceV1
from tradingagents.agents.schemas._insight import CapabilityRequest
from tradingagents.agents.schemas._search import AdmissionBatchV1, AdmittedObservationV1
from tradingagents.dataflows.capability_catalog import load_capability_catalog
from tradingagents.execution.budget import BudgetBucket, BudgetLimitHit
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.observability.canonical import canonical_sha256
from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict

SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_REQUESTS = 2
_MAX_ROWS = {"disclosure_search": 8, "shareholder_count": 8, "ir_qa": 8, "longhubang": 8,
             "holder_change": 8, "consensus_eps": 5}


@dataclass(frozen=True)
class GatewayResult:
    admitted: AdmissionBatchV1
    gaps: tuple[str, ...]
    executed: tuple[str, ...]
    rejected: tuple[str, ...]


def execute_capability_requests(requests, *, role, ticker, cutoff, ledger, ensure_active,
                                session=None, available_requirements=frozenset()):
    """Validate and execute structured capability requests for one specialist role."""
    visible = {card.id: card for card in load_capability_catalog(
        role=role, available_requirements=available_requirements)}
    normalized, rejected = [], []
    incoming = tuple(requests or ())
    if len(incoming) > _MAX_REQUESTS:
        rejected.append("capability_request_truncated")
    for raw in incoming:
        try:
            request = raw if isinstance(raw, CapabilityRequest) else CapabilityRequest.model_validate(raw)
        except Exception:
            rejected.append("capability_request_invalid")
            continue
        card = visible.get(request.capability_id)
        if card is None:
            rejected.append(f"capability_not_visible:{request.capability_id}")
            continue
        if request.capability_id == "news_search":
            rejected.append("capability_use_search_path:news_search")
            continue
        if request.capability_id == "disclosure_search" and not request.query.strip():
            rejected.append("capability_query_required:disclosure_search")
            continue
        if len(normalized) >= _MAX_REQUESTS:
            continue
        normalized.append(request)
    if not normalized:
        empty = tuple(dict.fromkeys(rejected))
        return GatewayResult(AdmissionBatchV1(batch_id="capability.empty"), empty, (), empty)

    identity = canonical_sha256({"role": role, "ticker": ticker, "cutoff": str(cutoff),
                                 "requests": [r.model_dump(mode="json") for r in normalized]})
    key = "capability.batch." + identity
    cached = ledger.cached_result(key)
    if cached is not None:
        if cached["input"] != identity:
            raise ResearchCheckpointConflict("capability gateway input changed")
        return GatewayResult(AdmissionBatchV1.model_validate(cached["admitted"]),
                             tuple(cached["gaps"]), tuple(cached["executed"]), tuple(cached["rejected"]))

    # Card limits are per run, so they count durable attempts instead of this call's
    # request list; a resumed run cannot spend a card its saved journal already used.
    allowed = []
    for request in normalized:
        card = visible[request.capability_id]
        used = _card_calls_this_run(ledger, role, request.capability_id) + sum(
            1 for item in allowed if item.capability_id == request.capability_id)
        if used >= card.max_calls_per_run:
            rejected.append(f"capability_card_limit:{request.capability_id}")
            continue
        allowed.append(request)
    normalized = allowed

    observations, gaps, executed = [], list(dict.fromkeys(rejected)), []
    for request in normalized:
        ensure_active()
        token = ledger.reserve(BudgetBucket.SUPPLEMENT_CAPABILITIES,
                               stage=f"capability.{role}.{request.capability_id}",
                               logical_call_id=f"{key}.{request.capability_id}")
        if isinstance(token, BudgetLimitHit):
            gaps.append("capability_budget_exhausted")
            break
        ledger.mark_dispatched(token)
        try:
            rows = _fetch(request, ticker=ticker, cutoff=cutoff, session=session, ensure_active=ensure_active)
            for index, row in enumerate(rows):
                observations.append(_observation(request, role=role, ticker=ticker, row=row, index=index))
            executed.append(request.capability_id)
            if not rows:
                gaps.append(f"capability_empty:{request.capability_id}")
            ledger.settle(token, ok=True, usage_available=False, detail=request.capability_id)
        except AnalysisCancelled:
            ledger.settle(token, ok=False, usage_available=False, detail="cancelled")
            raise
        except Exception as exc:
            reason = str(exc).strip()[:80] if isinstance(exc, ValueError) else type(exc).__name__
            gaps.append(f"capability_unavailable:{request.capability_id}:{reason}")
            ledger.settle(token, ok=False, usage_available=False, detail=reason)

    admitted = AdmissionBatchV1(batch_id="capability." + identity[:16], observations=tuple(observations),
                                rejections=tuple(dict.fromkeys(gaps)))
    ledger.record_result(key, {"input": identity, "admitted": admitted.model_dump(mode="json"),
                               "gaps": list(admitted.rejections), "executed": list(executed),
                               "rejected": list(dict.fromkeys(rejected))})
    return GatewayResult(admitted, admitted.rejections, tuple(executed), tuple(dict.fromkeys(rejected)))


def _card_calls_this_run(ledger, role, capability_id):
    """Durable card usage for this role; a released reservation never spent quota."""
    stage = f"capability.{role}.{capability_id}"
    return sum(1 for record in ledger.records()
               if record.bucket == BudgetBucket.SUPPLEMENT_CAPABILITIES
               and record.stage == stage and record.counts_against_budget())


def _fetch(request, *, ticker, cutoff, session, ensure_active):
    cutoff = date.fromisoformat(cutoff) if isinstance(cutoff, str) else cutoff
    if request.capability_id == "disclosure_search":
        return _disclosure_rows(ticker, cutoff, request.query.strip(), session=session, ensure_active=ensure_active)
    if request.capability_id == "shareholder_count":
        ensure_active()
        return _shareholder_rows(ticker, cutoff)
    if request.capability_id == "ir_qa":
        ensure_active()
        return _ir_rows(ticker, cutoff)
    if request.capability_id == "longhubang":
        ensure_active()
        return _dragon_tiger_rows(ticker, cutoff)
    if request.capability_id == "holder_change":
        ensure_active()
        return _holder_change_rows(ticker, cutoff)
    if request.capability_id == "consensus_eps":
        ensure_active()
        return _consensus_rows(ticker, cutoff)
    raise ValueError(f"capability_not_implemented:{request.capability_id}")


def _disclosure_rows(ticker, cutoff, query, *, session, ensure_active):
    from tradingagents.dataflows.china_specialty import get_a_share_cninfo_announcements

    records = []
    ensure_active()
    get_a_share_cninfo_announcements(
        ticker, (cutoff - timedelta(days=400)).isoformat(), cutoff.isoformat(),
        page_size=30, max_pages=2, session=session, records_sink=records.extend)
    needle, end, rows = query.casefold(), cutoff.isoformat(), []
    for record in records:
        title, published = str(record.get("Title") or ""), str(record.get("Published") or "")
        if needle not in title.casefold() or not published or published > end:
            continue
        detail = str(record.get("Detail URL") or "")
        rows.append({"published": published, "title": title[:200],
                     "url": detail if detail.startswith(("http://", "https://")) else "",
                     "announcement_id": str(record.get("Announcement ID") or ""),
                     "kind": str(record.get("Type") or ""), "source_name": "cninfo.announcements"})
        if len(rows) >= _MAX_ROWS["disclosure_search"]:
            break
    return rows


def _shareholder_rows(ticker, cutoff):
    from tradingagents.dataflows.china_specialty_em import get_a_share_shareholder_counts_em

    text = str(get_a_share_shareholder_counts_em(ticker))
    rows = []
    for row in _csv_rows(text):
        day = str(row.get("Date") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day > cutoff.isoformat():
            continue
        rows.append({"published": day, "holder_num": row.get("Holder Num"),
                     "change_num": row.get("Change Num"), "change_pct": row.get("Change %"),
                     "avg_hold": row.get("Avg Hold Num"), "source_name": "eastmoney.shareholder_counts"})
        if len(rows) >= _MAX_ROWS["shareholder_count"]:
            break
    return rows


def _dragon_tiger_rows(ticker, cutoff):
    from tradingagents.dataflows.china_specialty_em import get_a_share_dragon_tiger_em

    # Appearance records only; the adapter's TOP5 seat section starts at "## ".
    text = str(get_a_share_dragon_tiger_em(ticker, cutoff.isoformat())).split("\n\n## ", 1)[0]
    rows = []
    for row in _csv_rows(text):
        day = str(row.get("Date") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day > cutoff.isoformat():
            continue
        rows.append({"published": day, "reason": str(row.get("Reason") or "")[:120],
                     "net_buy_wan": row.get("Net Buy (wan)"), "turnover_pct": row.get("Turnover %"),
                     "source_name": "eastmoney.dragon_tiger"})
        if len(rows) >= _MAX_ROWS["longhubang"]:
            break
    return rows


def _holder_change_rows(ticker, cutoff):
    from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError
    from tradingagents.dataflows.china_capital_flow import get_a_share_insider_trades

    try:
        text = str(get_a_share_insider_trades(
            ticker, (cutoff - timedelta(days=365)).isoformat(), cutoff.isoformat()))
    except AshareCapabilityUnavailableError as exc:
        if exc.capability == "date_window":
            return []
        raise
    rows = []
    for row in _csv_rows(text):
        notice = str(row.get("NOTICE_DATE") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", notice) or notice > cutoff.isoformat():
            continue
        rows.append({"published": notice, "holder": str(row.get("HOLDER_NAME") or "")[:80],
                     "direction": str(row.get("DIRECTION") or ""), "change_num": row.get("CHANGE_NUM"),
                     "change_symbol": row.get("CHANGE_NUM_SYMBOL"),
                     "after_change_rate": row.get("AFTER_CHANGE_RATE"), "avg_price": row.get("TRADE_AVERAGE_PRICE"),
                     "end_date": str(row.get("END_DATE") or "")[:10], "source_name": "eastmoney.insider_trades"})
        if len(rows) >= _MAX_ROWS["holder_change"]:
            break
    return rows


def _consensus_rows(ticker, cutoff):
    from tradingagents.dataflows.china_specialty_em import get_a_share_eps_forecast

    # The adapter reads a live snapshot with no archived vintage, so a historical
    # cutoff would silently present today's forecast as of that date.
    if cutoff != datetime.now(SHANGHAI).date():
        raise ValueError("capability_not_point_in_time")
    text = str(get_a_share_eps_forecast(ticker, as_of=cutoff.isoformat()))
    rows = []
    for row in _csv_rows(text):
        year = str(row.get("年度") or "").strip()
        if not re.fullmatch(r"\d{4}", year):
            continue
        rows.append({"published": cutoff.isoformat(), "year": year,
                     "institutions": row.get("预测机构数"), "eps_low": row.get("最小值"),
                     "eps_mean": row.get("均值"), "eps_high": row.get("最大值"),
                     "industry_mean": row.get("行业平均数"), "source_name": "ths.eps_forecast"})
        if len(rows) >= _MAX_ROWS["consensus_eps"]:
            break
    return rows


def _ir_rows(ticker, cutoff):
    from tradingagents.dataflows.ticker_utils import (
        infer_a_share_exchange,
        normalize_ticker_symbol,
        strict_ticker_code,
        to_akshare_symbol,
    )

    code = to_akshare_symbol(normalize_ticker_symbol(ticker))
    exchange = infer_a_share_exchange(code)
    if exchange == "SH":
        return _sse_ir_rows(strict_ticker_code(ticker, stock_only=True), cutoff)
    if exchange == "SZ":
        return _cninfo_irm_rows(code, cutoff)
    raise ValueError("ir_qa_exchange_unsupported")


def _sse_ir_rows(code, cutoff):
    from tradingagents.dataflows.a_share_official import get_a_share_sse_e_interaction

    rows = []
    for row in _csv_rows(str(get_a_share_sse_e_interaction(code, kind="answered", page=1, page_size=10))):
        stamp = str(row.get("answer_time") or "")
        day = stamp[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day > cutoff.isoformat():
            continue
        rows.append({"published": day, "question": row.get("question", ""), "answer": row.get("answer", ""),
                     "question_time": row.get("question_time", ""), "source_name": "sse.e_interaction"})
        if len(rows) >= _MAX_ROWS["ir_qa"]:
            break
    return rows


def _cninfo_irm_rows(code, cutoff):
    """Bounded CNINFO IRM (a-stock-data §10.1); one page only, never AKShare's 10×1000 crawl."""
    import requests

    from tradingagents.dataflows.china_specialty import _cninfo_orgid

    response = requests.post(
        "https://irm.cninfo.com.cn/newircs/company/question",
        params={"_t": 1, "stockcode": code, "orgId": _cninfo_orgid(code), "pageSize": 30, "pageNum": 1,
                "keyWord": "", "startDay": "", "endDay": ""},
        headers={"User-Agent": "TradingAgents/1.0"}, timeout=15)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("rows") or []
    if not isinstance(items, list):
        raise ValueError("cninfo_irm_shape")
    rows = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("pubDate"), (int, float)):
            continue
        published = datetime.fromtimestamp(item["pubDate"] / 1000, SHANGHAI).date()
        if published > cutoff:
            continue
        rows.append({"published": published.isoformat(),
                     "question": str(item.get("mainContent") or "")[:500],
                     "answer": str(item.get("attachedContent") or "")[:800],
                     "answerer": str(item.get("attachedAuthor") or ""),
                     "source_name": "cninfo.irm"})
        if len(rows) >= _MAX_ROWS["ir_qa"]:
            break
    return rows


def _csv_rows(text):
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line and not line.startswith("#")), None)
    return [] if start is None else list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def _observation(request, *, role, ticker, row, index):
    source_name = row["source_name"]
    source_kind = "vendor" if source_name.startswith(("eastmoney.", "ths.")) else "official"
    if request.capability_id == "disclosure_search":
        text = f"{row['published']} 《{row['title']}》" + (f" 类型:{row['kind']}" if row.get("kind") else "")
        statement = f"巨潮公告目录载明：{text}"
        url = row.get("url") or None
        locator = "公告目录标题"
    elif request.capability_id == "shareholder_count":
        text = (f"{row['published']} 股东户数={row.get('holder_num')} 变化={row.get('change_num')} "
                f"环比%={row.get('change_pct')} 户均={row.get('avg_hold')}")
        statement = f"东财股东户数披露：{text}"
        url, locator = None, "股东户数序列"
    elif request.capability_id == "longhubang":
        text = (f"{row['published']} 龙虎榜 原因={row.get('reason')} 净买入={row.get('net_buy_wan')}万元 "
                f"换手率={row.get('turnover_pct')}%")
        statement = f"东财龙虎榜记录：{text}"
        url, locator = None, "个股龙虎榜上榜记录"
    elif request.capability_id == "holder_change":
        text = (f"公告日={row['published']} 变动截止={row.get('end_date')} 方向={row.get('direction')} "
                f"变动数量={row.get('change_symbol') or row.get('change_num')} 均价={row.get('avg_price')} "
                f"变动后持股比例={row.get('after_change_rate')} 主体={row.get('holder')}")
        statement = f"东财增减持披露：{text[:1000]}"
        url, locator = None, "股东增减持公告摘录"
    elif request.capability_id == "consensus_eps":
        text = (f"{row['year']}年 预测机构数={row.get('institutions')} EPS均值={row.get('eps_mean')} "
                f"区间={row.get('eps_low')}~{row.get('eps_high')} 行业平均={row.get('industry_mean')}")
        statement = f"同花顺一致预期样本：{text}"
        url, locator = None, "机构一致预期表"
    else:
        text = f"问：{row.get('question', '')}\n答：{row.get('answer') or '（尚未回复）'}"
        statement = f"投资者互动问答：{text[:1000]}"
        url, locator = None, "互动问答摘录"
    text = text[:4000]
    extra_limitations = {"consensus_eps": ("forecast_snapshot_not_reported_eps",),
                         "longhubang": ("market_record_not_motive",),
                         "holder_change": ("disclosure_record_not_motive",)}.get(request.capability_id, ())
    digest = hashlib.sha256(text.encode()).hexdigest()
    identity = hashlib.sha256(
        f"{request.capability_id}|{ticker}|{role}|{row['published']}|{text}|{index}".encode()).hexdigest()
    published = date.fromisoformat(row["published"])
    published_at = datetime(published.year, published.month, published.day, tzinfo=SHANGHAI)
    source = SourceEvidenceV1(
        evidence_id="capability." + identity, source_name=source_name, source_kind=source_kind,
        source_family_id="capability:" + request.capability_id, availability="available",
        public_url=url, published_at=published_at, usable_as_of=published_at,
        captured_at=datetime.now(timezone.utc),
        content=SourceContentV1(kind="excerpt", text=text, locator_label=locator, content_sha256=digest),
        limitations=("capability_supplement", "native_dimension:" + role,
                     "source_reported_not_independently_verified", "selected_capability_excerpt",
                     *extra_limitations))
    fact = RecordClaimV1(
        claim_id="fact." + identity, kind="fact", statement=statement[:1200],
        evidence_ids=(source.evidence_id,),
        limitations=("capability_supplement", "native_dimension:" + role, "source_reported_observation"))
    return AdmittedObservationV1(source=source, fact=fact, role=role, capability=request.capability_id)
