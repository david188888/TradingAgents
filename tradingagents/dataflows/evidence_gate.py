"""Evidence gate orchestration and Tavily enrichment.

Verdict contract: PASS / LOW_CONFIDENCE / FAIL_STOP / GATE_ERROR. The gate
orchestrates company identity, news relevance and rendering; the four
monkeypatched names (``create_llm_from_config``, ``analyze_news_coverage``,
``_complete_profile``, ``_run_tavily_enrichment``) are looked up through the
``evidence`` facade at call time so tests that patch the facade path keep
working.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import requests

from tradingagents.observability.provenance import (
    capture_direct_call_with_origin,
    capture_vendor_raw,
)

from .config import get_config
from .consistency import attach_cross_source_info
from .credibility import attach_credibility
from .evidence_ledger import build_evidence_ledger, persist_evidence_ledger
from .evidence_news import (
    _annotate_entity_roles,
    _dedupe_news_items,
    _extract_news_items_from_reports,
    _find_wrong_identity_hits,
    _is_company_relevant,
    _is_industry_relevant,
    _is_official_item,
)
from .evidence_render import (
    _format_evidence_news_package,
    _format_evidence_report,
    format_company_profile,
)
from .news_layers import Layer1Sentiment
from .ticker_utils import is_a_share_ticker, normalize_ticker_symbol


class EvidenceStatus(str, Enum):
    PASS = "PASS"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NEEDS_ENRICHMENT = "NEEDS_ENRICHMENT"
    FAIL_STOP = "FAIL_STOP"
    GATE_ERROR = "GATE_ERROR"


class EvidenceGateError(RuntimeError):
    """Raised when evidence is too weak or contradictory for downstream debate."""


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _configured_tavily_keys() -> tuple[str, ...]:
    """Read Tavily API keys from env, matching tavily_news.py's convention.

    Supports both ``TAVILY_API_KEYS`` (comma-separated, preferred) and
    ``TAVILY_API_KEY`` (legacy single-key). Returns an empty tuple when
    neither is set.
    """
    multi = os.getenv("TAVILY_API_KEYS", "")
    values = [part.strip() for part in multi.split(",") if part.strip()]
    legacy = os.getenv("TAVILY_API_KEY", "").strip()
    if legacy:
        values.append(legacy)
    return tuple(dict.fromkeys(values))


_LAYER1_DIRECTION_SCORES: Mapping[str, float] = {
    "+": 0.6,
    "-": -0.6,
    "0": 0.0,
}


def _layer1_direction_scores(
    layer1_sentiment: list[Layer1Sentiment],
) -> dict[str, float]:
    """Map Layer 1 per-item sentiment codes to normalized direction scores.

    The Layer 1 pass is a directional classification (+/-/0/?), not a strength
    measurement, so the scores are nominal magnitudes rather than inferred
    precision. ``?`` (unknown) is excluded so it neither counts as neutral nor
    skews the source-alignment projection.
    """
    scores: dict[str, float] = {}
    for entry in layer1_sentiment:
        score = _LAYER1_DIRECTION_SCORES.get(entry.sentiment)
        if score is None:
            continue
        scores[entry.item_id] = score
    return scores


def evaluate_and_enrich_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Validate evidence quality and optionally enrich weak news context."""
    from tradingagents.dataflows import evidence as _evidence
    cfg = get_config()
    if not cfg.get("evidence_gate_enabled", True):
        ledger = build_evidence_ledger(
            profile={},
            assessment={"status": EvidenceStatus.PASS, "items": []},
            trade_date=str(state.get("trade_date") or ""),
            enrichment_rounds=0,
        )
        return {
            "evidence_status": EvidenceStatus.PASS.value,
            "evidence_report": "Evidence gate disabled by configuration.",
            "evidence_ledger": ledger,
            "evidence_ledger_artifact_id": persist_evidence_ledger(ledger),
        }

    ticker = normalize_ticker_symbol(str(state.get("company_of_interest") or ""))
    profile = _evidence._complete_profile(state.get("canonical_company_profile"), ticker)
    if is_a_share_ticker(ticker) and not profile.get("name"):
        assessment = {
            "status": EvidenceStatus.LOW_CONFIDENCE,
            "reasons": ["无法解析 A 股 canonical company profile，身份信息不完整"],
            "items": [],
            "company_count": 0,
            "mixed_count": 0,
            "weighted_company": 0.0,
            "weighted_mixed": 0.0,
            "low_coverage": False,
            "limitations": ["unresolved_a_share_profile"],
        }
        return _low_confidence_with_ledger(
            profile,
            assessment,
            trade_date=str(state.get("trade_date") or ""),
            enrichment_rounds=0,
        )

    core_warning = _assert_no_core_data_warnings(state, profile)
    if core_warning:
        # _assert_no_core_data_warnings delegates to _fail_or_return, which
        # already emits exactly one failed ledger when fail-open is configured.
        return core_warning

    original_items = _dedupe_news_items(
        _extract_news_items_from_reports(
            state.get("news_report", ""),
            state.get("sentiment_report", ""),
        )
    )
    assessment = _assess_news_items(original_items, profile)
    if assessment["status"] == EvidenceStatus.PASS:
        return _pass_with_ledger(
            profile,
            assessment,
            trade_date=str(state.get("trade_date") or ""),
            enrichment_rounds=0,
        )
    if assessment["status"] == EvidenceStatus.FAIL_STOP:
        reason = "; ".join(assessment.get("reasons", [])) or "证据门控未通过"
        return _fail_or_return(
            reason,
            profile,
            assessment=assessment,
            trade_date=str(state.get("trade_date") or ""),
            hard_fail=True,
        )

    max_rounds = int(cfg.get("evidence_max_enrichment_rounds", 3))
    deadline = time.monotonic() + float(cfg.get("evidence_max_enrichment_seconds", 90))

    # Use LLM-based advisor to get targeted enrichment queries
    llm = _evidence.create_llm_from_config()
    advisor = _evidence.analyze_news_coverage(original_items, profile, llm)
    # The advisor's Layer 1 pass classifies each original news item's
    # direction; persist it as the ledger's direction_score so downstream
    # source alignment reflects real evidence rather than being always empty.
    direction_scores = _layer1_direction_scores(advisor.layer1_sentiment)
    if advisor.should_enrich and advisor.queries:
        enriched_items = _evidence._run_tavily_enrichment_with_queries(
            advisor.queries,
            profile,
            str(state.get("trade_date") or ""),
            max_rounds,
            deadline,
        )
    else:
        enriched_items = _evidence._run_tavily_enrichment(
            profile, str(state.get("trade_date") or ""), max_rounds, deadline
        )
    all_items = _dedupe_news_items([*original_items, *enriched_items])
    enriched_assessment = _assess_news_items(all_items, profile)

    if enriched_assessment["status"] == EvidenceStatus.PASS:
        evidence_report = _format_evidence_report(
            profile,
            enriched_assessment,
            enrichment_rounds=max_rounds,
        )
        result = _pass_with_ledger(
            profile,
            enriched_assessment,
            trade_date=str(state.get("trade_date") or ""),
            enrichment_rounds=max_rounds,
            direction_scores=direction_scores,
        )
        result.update(
            {
                "canonical_company_profile": profile,
                "evidence_report": evidence_report,
                "news_report": _format_evidence_news_package(profile, all_items, evidence_report),
            }
        )
        return result

    if enriched_assessment["status"] == EvidenceStatus.FAIL_STOP:
        reason = (
            f"Tavily 补充 {max_rounds} 轮后仍为致命问题："
            f"{'; '.join(enriched_assessment['reasons']) or '未知原因'}。"
        )
        return _fail_or_return(
            reason,
            profile,
            assessment=enriched_assessment,
            trade_date=str(state.get("trade_date") or ""),
            enrichment_rounds=max_rounds,
            direction_scores=direction_scores,
            hard_fail=True,
        )

    # NEEDS_ENRICHMENT after enrichment rounds exhausted → LOW_CONFIDENCE
    low_conf_assessment = {
        **enriched_assessment,
        "status": EvidenceStatus.LOW_CONFIDENCE,
    }
    evidence_report = _format_evidence_report(
        profile,
        low_conf_assessment,
        enrichment_rounds=max_rounds,
    )
    result = _low_confidence_with_ledger(
        profile,
        low_conf_assessment,
        trade_date=str(state.get("trade_date") or ""),
        enrichment_rounds=max_rounds,
        direction_scores=direction_scores,
    )
    result.update(
        {
            "canonical_company_profile": profile,
            "evidence_report": evidence_report,
            "news_report": _format_evidence_news_package(
                profile, all_items, evidence_report
            ),
        }
    )
    return result


def _pass_with_ledger(
    profile: dict[str, Any],
    assessment: dict[str, Any],
    *,
    trade_date: str,
    enrichment_rounds: int,
    direction_scores: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    result = {
        "canonical_company_profile": profile,
        "evidence_status": EvidenceStatus.PASS.value,
        "evidence_report": _format_evidence_report(
            profile,
            assessment,
            enrichment_rounds=enrichment_rounds,
        ),
    }
    return _with_ledger(
        result,
        profile=profile,
        assessment=assessment,
        trade_date=trade_date,
        enrichment_rounds=enrichment_rounds,
        direction_scores=direction_scores,
    )


def _low_confidence_with_ledger(
    profile: dict[str, Any],
    assessment: dict[str, Any],
    *,
    trade_date: str,
    enrichment_rounds: int,
    direction_scores: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    result = {
        "canonical_company_profile": profile,
        "evidence_status": EvidenceStatus.LOW_CONFIDENCE.value,
        "evidence_report": _format_evidence_report(
            profile,
            assessment,
            enrichment_rounds=enrichment_rounds,
        ),
    }
    return _with_ledger(
        result,
        profile=profile,
        assessment=assessment,
        trade_date=trade_date,
        enrichment_rounds=enrichment_rounds,
        direction_scores=direction_scores,
    )


def _with_ledger(
    result: dict[str, Any],
    *,
    profile: dict[str, Any],
    assessment: dict[str, Any],
    trade_date: str,
    enrichment_rounds: int,
    direction_scores: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    ledger = build_evidence_ledger(
        profile=profile,
        assessment=assessment,
        trade_date=trade_date,
        enrichment_rounds=enrichment_rounds,
        direction_scores=direction_scores,
    )
    result["evidence_ledger"] = ledger
    result["evidence_ledger_artifact_id"] = persist_evidence_ledger(ledger)
    return result


FATAL_DATA_PATTERNS: tuple[str, ...] = (
    "no usable financial statement",
)


DEGRADED_DATA_PATTERNS: tuple[str, ...] = (
    "Supplemental source: unavailable",
    "Warning: Yahoo Finance",
    "暂未获取",
    "未获取到完整",
    "Data unavailable",
)


def _assert_no_core_data_warnings(
    state: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    text = "\n\n".join(
        str(state.get(key) or "") for key in ("market_report", "fundamentals_report")
    )
    fatal_hits = [p for p in FATAL_DATA_PATTERNS if p.lower() in text.lower()]
    degraded_hits = [p for p in DEGRADED_DATA_PATTERNS if p.lower() in text.lower()]

    if fatal_hits:
        return _fail_or_return(
            "核心财务数据缺失，已触发证据门控：" + ", ".join(fatal_hits),
            profile,
            trade_date=str(state.get("trade_date") or ""),
            hard_fail=True,
        )

    if degraded_hits:
        assessment = {
            "status": EvidenceStatus.LOW_CONFIDENCE,
            "reasons": ["数据质量降级：" + ", ".join(degraded_hits)],
            "items": [],
            "company_count": 0,
            "mixed_count": 0,
            "weighted_company": 0.0,
            "weighted_mixed": 0.0,
            "low_coverage": False,
            "limitations": degraded_hits,
        }
        return _low_confidence_with_ledger(
            profile,
            assessment,
            trade_date=str(state.get("trade_date") or ""),
            enrichment_rounds=0,
        )

    return None


_CREDIBILITY_WEIGHTS = {"high": 1.5, "medium": 1.0, "low": 0.5}


_CROSS_SOURCE_BONUS = 1.5  # confirmed items get 50% extra weight


def _credibility_weighted_count(items: list[dict[str, Any]]) -> float:
    """Sum credibility weights for *items*, with cross-source confirmation bonus."""
    total = 0.0
    for item in items:
        weight = _CREDIBILITY_WEIGHTS.get(item.get("credibility", "low"), 0.5)
        if item.get("cross_source_tag") == "confirmed":
            weight *= _CROSS_SOURCE_BONUS
        total += weight
    return total


def _assess_news_items(items: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    from tradingagents.dataflows import evidence as _evidence
    cfg = get_config()
    llm = _evidence.create_llm_from_config()
    attach_cross_source_info(items, llm)
    attach_credibility(items)
    _annotate_entity_roles(items, profile)

    wrong_hits = _find_wrong_identity_hits(items, profile)
    if wrong_hits:
        return {
            "status": EvidenceStatus.FAIL_STOP,
            "reasons": ["身份冲突：" + ", ".join(sorted(wrong_hits))],
            "items": items,
            "company_count": 0,
            "mixed_count": 0,
            "low_coverage": False,
        }

    company_items = [item for item in items if _is_company_relevant(item, profile)]
    official_items = [
        item
        for item in items
        if item.get("entity_role") == "subject" and _is_official_item(item)
    ]
    industry_items = [
        item
        for item in items
        if item.get("entity_role") in {"subject", "comparable"}
        and _is_industry_relevant(item, profile)
    ]
    mixed = _dedupe_news_items([*company_items, *official_items, *industry_items])

    min_company = int(cfg.get("news_min_company_items", 3))
    min_mixed = int(cfg.get("news_min_mixed_items", 5))

    weighted_company = _credibility_weighted_count(company_items)
    weighted_mixed = _credibility_weighted_count(mixed)

    if weighted_company >= min_company:
        return _assessment_pass(
            items, company_items, mixed,
            low_coverage=False,
            weighted_company=weighted_company,
            weighted_mixed=weighted_mixed,
        )
    if weighted_mixed >= min_mixed and (company_items or official_items):
        return _assessment_pass(
            items, company_items, mixed,
            low_coverage=True,
            weighted_company=weighted_company,
            weighted_mixed=weighted_mixed,
        )

    reasons = []
    if not items:
        reasons.append("未找到可解析新闻条目")
    if weighted_company < min_company:
        reasons.append(
            f"公司直相关新闻加权 {weighted_company:.1f}/{min_company} "
            f"(原始 {len(company_items)} 条)"
        )
    if weighted_mixed < min_mixed:
        reasons.append(
            f"混合证据加权 {weighted_mixed:.1f}/{min_mixed} "
            f"(原始 {len(mixed)} 条)"
        )
    return {
        "status": EvidenceStatus.NEEDS_ENRICHMENT,
        "reasons": reasons,
        "items": items,
        "company_count": len(company_items),
        "mixed_count": len(mixed),
        "weighted_company": weighted_company,
        "weighted_mixed": weighted_mixed,
        "low_coverage": False,
    }


def _assessment_pass(
    items: list[dict[str, Any]],
    company_items: list[dict[str, Any]],
    mixed_items: list[dict[str, Any]],
    *,
    low_coverage: bool,
    weighted_company: float | None = None,
    weighted_mixed: float | None = None,
) -> dict[str, Any]:
    if weighted_company is None:
        weighted_company = _credibility_weighted_count(company_items)
    if weighted_mixed is None:
        weighted_mixed = _credibility_weighted_count(mixed_items)
    return {
        "status": EvidenceStatus.PASS,
        "reasons": [],
        "items": items,
        "company_count": len(company_items),
        "mixed_count": len(mixed_items),
        "weighted_company": weighted_company,
        "weighted_mixed": weighted_mixed,
        "low_coverage": low_coverage,
    }


def _run_tavily_enrichment(
    profile: dict[str, Any],
    trade_date: str,
    rounds: int,
    deadline: float,
) -> list[dict[str, Any]]:
    from tradingagents.dataflows import evidence as _evidence
    api_keys = _configured_tavily_keys()
    if not api_keys:
        return []
    api_key = api_keys[0]
    queries = _evidence._build_enrichment_queries(profile)
    if not queries:
        return []

    items: list[dict[str, Any]] = []
    for index, spec in enumerate(queries[:rounds], start=1):
        if time.monotonic() >= deadline:
            break
        payload = _build_tavily_payload(spec, trade_date)
        try:
            result, origin = capture_direct_call_with_origin(
                invocation_path=f"evidence.enrichment.fallback.{index}",
                method="evidence_tavily_enrichment",
                vendor="tavily",
                function=_request_tavily_enrichment,
                kwargs={
                    "payload": payload,
                    "api_key": api_key,
                    "timeout": min(30, max(1, int(deadline - time.monotonic()))),
                    "metadata": {"mode": "fallback", "round": index},
                },
                normalize=lambda value: _items_from_tavily_response(value["data"]),
            )
        except Exception:
            continue
        response_status = result["status_code"]
        data = result["data"]
        _evidence._save_enrichment_raw_response(profile, trade_date, index, payload, data)
        if response_status >= 400:
            continue
        items.extend(
            _attach_provenance_artifact_ids(
                _items_from_tavily_response(data),
                origin.artifact_ids if origin is not None else (),
            )
        )
    return _dedupe_news_items(items)


def _run_tavily_enrichment_with_queries(
    queries: list[dict[str, Any]],
    profile: dict[str, Any],
    trade_date: str,
    rounds: int,
    deadline: float,
) -> list[dict[str, Any]]:
    """Run Tavily enrichment with pre-built queries (e.g. from news advisor)."""
    from tradingagents.dataflows import evidence as _evidence
    api_keys = _configured_tavily_keys()
    if not api_keys or not queries:
        return []
    api_key = api_keys[0]

    items: list[dict[str, Any]] = []
    for index, spec in enumerate(queries[:rounds], start=1):
        if time.monotonic() >= deadline:
            break
        payload = _build_tavily_payload(spec, trade_date)
        try:
            result, origin = capture_direct_call_with_origin(
                invocation_path=f"evidence.enrichment.advisor.{index}",
                method="evidence_tavily_enrichment",
                vendor="tavily",
                function=_request_tavily_enrichment,
                kwargs={
                    "payload": payload,
                    "api_key": api_key,
                    "timeout": min(30, max(1, int(deadline - time.monotonic()))),
                    "metadata": {"mode": "advisor", "round": index},
                },
                normalize=lambda value: _items_from_tavily_response(value["data"]),
            )
        except Exception:
            continue
        response_status = result["status_code"]
        data = result["data"]
        _evidence._save_enrichment_raw_response(profile, trade_date, index, payload, data)
        if response_status >= 400:
            continue
        items.extend(
            _attach_provenance_artifact_ids(
                _items_from_tavily_response(data),
                origin.artifact_ids if origin is not None else (),
            )
        )
    return _dedupe_news_items(items)


def _request_tavily_enrichment(
    *,
    payload: dict[str, Any],
    api_key: str,
    timeout: int,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """One direct Tavily request with a true pre-normalization capture point."""
    response = requests.post(
        TAVILY_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    data = response.json()
    capture_vendor_raw(
        data,
        metadata={"provider": "tavily", **metadata},
    )
    return {"status_code": response.status_code, "data": data}


def _build_enrichment_queries(profile: dict[str, Any]) -> list[dict[str, Any]]:
    ticker = str(profile.get("ticker") or profile.get("ts_code") or "")
    name = str(profile.get("name") or "")
    full_name = str(profile.get("full_name") or name)
    industry = str(profile.get("industry") or "")
    query_base = " ".join(part for part in (ticker, name) if part)

    from .ticker_utils import is_a_share_ticker

    if is_a_share_ticker(ticker):
        return [
            {
                "query": f"{query_base} 公告 业绩 新闻 舆情",
                "include_domains": [],
                "include_raw_content": False,
            },
            {
                "query": f"{full_name} {ticker} 巨潮资讯 深交所 公告",
                "include_domains": ["cninfo.com.cn", "szse.cn"],
                "include_raw_content": True,
            },
            {
                "query": f"{name} {industry} 行业 订单 经营 市场 情绪",
                "include_domains": [],
                "include_raw_content": False,
            },
        ]

    # US / international stocks: English queries with relevant domains
    return [
        {
            "query": f"{ticker} {name} earnings news press release",
            "include_domains": [],
            "include_raw_content": False,
        },
        {
            "query": f"{full_name} SEC filing investor relations",
            "include_domains": ["sec.gov", "prnewswire.com", "businesswire.com"],
            "include_raw_content": True,
        },
        {
            "query": f"{name} {industry} industry outlook market analysis",
            "include_domains": [],
            "include_raw_content": False,
        },
    ]


def _build_tavily_payload(spec: dict[str, Any], trade_date: str) -> dict[str, Any]:
    start_date, end_date = _date_window(trade_date)
    payload = {
        "query": spec["query"][:380],
        "search_depth": "advanced",
        "max_results": 10,
        "topic": "general",
        "start_date": start_date,
        "end_date": end_date,
        "include_raw_content": bool(spec.get("include_raw_content")),
        "include_answer": False,
        "include_images": False,
        "auto_parameters": False,
        "include_favicon": True,
    }
    if spec.get("include_domains"):
        payload["include_domains"] = spec["include_domains"]
    return payload


def _date_window(trade_date: str) -> tuple[str, str]:
    try:
        end = datetime.strptime(trade_date, "%Y-%m-%d")
    except Exception:
        end = datetime.now()
    start = end - timedelta(days=120)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _items_from_tavily_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for result in data.get("results") or []:
        if not isinstance(result, dict):
            continue
        items.append(
            {
                "title": result.get("title") or "Untitled",
                "url": result.get("url") or "",
                "content": result.get("raw_content") or result.get("content") or "",
                "published": result.get("published_date") or result.get("published_time") or "",
                "score": result.get("score"),
                "publisher": _publisher_from_url(result.get("url") or ""),
                "source": "tavily_enrichment",
            }
        )
    return items


def _attach_provenance_artifact_ids(
    items: list[dict[str, Any]],
    artifact_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Carry direct-call lineage into the compact ledger, never raw payloads."""
    if not artifact_ids:
        return items
    for item in items:
        item["provenance_artifact_ids"] = list(artifact_ids)
    return items


def _save_enrichment_raw_response(
    profile: dict[str, Any],
    trade_date: str,
    round_index: int,
    payload: dict[str, Any],
    data: dict[str, Any],
) -> None:
    try:
        from .tavily_news import _save_raw_response

        _save_raw_response(
            str(profile.get("ticker") or profile.get("symbol") or "UNKNOWN"),
            trade_date or datetime.now().strftime("%Y-%m-%d"),
            f"evidence_enrichment_round_{round_index}",
            payload,
            data,
        )
    except Exception:
        return


def _publisher_from_url(url: str) -> str:
    domain = urlparse(str(url or "")).netloc.lower()
    if "cninfo.com.cn" in domain:
        return "巨潮资讯"
    if "szse.cn" in domain:
        return "深交所"
    return domain or "unknown"


def _fail_or_return(
    reason: str,
    profile: dict[str, Any],
    assessment: dict[str, Any] | None = None,
    *,
    trade_date: str = "",
    enrichment_rounds: int = 0,
    direction_scores: Mapping[str, float] | None = None,
    hard_fail: bool = False,
) -> dict[str, Any]:
    cfg = get_config()
    report = "\n".join(
        [
            "## Evidence Steward Report",
            format_company_profile(profile),
            f"Status: {EvidenceStatus.FAIL_STOP.value}",
            f"Reason: {reason}",
        ]
    )
    ledger_assessment = assessment or {
        "status": EvidenceStatus.FAIL_STOP,
        "items": [],
        "reasons": [reason],
    }
    result = _with_ledger(
        {
            "canonical_company_profile": profile,
            "evidence_status": EvidenceStatus.FAIL_STOP.value,
            "evidence_report": report,
        },
        profile=profile,
        assessment=ledger_assessment,
        trade_date=trade_date,
        enrichment_rounds=enrichment_rounds,
        direction_scores=direction_scores,
    )
    if hard_fail or cfg.get("evidence_stop_on_fail", False):
        raise EvidenceGateError(f"{reason}\n\n{report}")
    return result

