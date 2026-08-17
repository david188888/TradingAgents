"""News curation: extraction, dedup, staleness, relevance marking, formatting.

Extracted from ``interface.py`` to keep the routing core focused on vendor
selection. These functions turn raw vendor news results into a single
source-labeled, deduplicated, relevance-marked package for downstream agents.

The module depends only on the target-ticker context, ticker normalization,
the news-consistency/credibility helpers, and config - it never imports the
routing core, so there is no circular dependency. ``_summarize_vendor_error``
stays in ``interface.py`` (it classifies vendor exception types); the news-side
wrapper here reaches it via a function-local import.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from .config import get_config
from .consistency import attach_cross_source_info, create_llm_from_config, cross_source_summary
from .coverage import CoveredText, SourceCoverageV1
from .credibility import attach_credibility, credibility_summary
from .target_context import get_target_ticker
from .ticker_utils import normalize_ticker_symbol, to_akshare_symbol


def _is_empty_news_result(result: Any) -> bool:
    if result is None:
        return True
    # Structured dict results (tavily/eastmoney/...) carry an explicit items list.
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return len(result["items"]) == 0
    text = str(result).strip()
    if not text:
        return True
    lowered = text.lower()
    return lowered.startswith("no news found") or lowered.startswith("no global news found")


def _is_error_news_result(result: Any) -> bool:
    if result is None or isinstance(result, (dict, list)):
        return False
    lowered = str(result).strip().lower()
    return lowered.startswith("error fetching news") or lowered.startswith("error fetching global news")


def _summarize_empty_news_result(result: Any) -> str:
    if isinstance(result, dict) and result.get("source") == "tavily":
        return "Tavily returned no results"
    if isinstance(result, dict) and result.get("source") == "doubao":
        return "Doubao returned no results"
    if isinstance(result, dict) and result.get("source") == "bocha":
        return "Bocha returned no results"
    return str(result).strip()[:300] or "empty result"


def _summarize_error_news_result(result: Any) -> str:
    return str(result).strip()[:300] or "source returned an error"


def _summarize_news_result(result: Any) -> str:
    count = len(_extract_news_items("unknown", result))
    return f"返回 {count} 条新闻"


def _summarize_vendor_error_for_news(err: Exception | str) -> str:
    if not isinstance(err, Exception):
        return str(err)
    # Function-local import: _summarize_vendor_error classifies vendor exception
    # types and lives in interface.py (routing core). Importing it at module level
    # would create a circular dependency.
    from .interface import _summarize_vendor_error

    return _summarize_vendor_error(err)


def _mark_news_relevance(items: list[dict[str, Any]]) -> int:
    """Soft-mark news items that do not mention the target ticker or company.

    Uses the run's target ticker (from the contextvar set at run start) and
    its resolved company name. Recall-first: any case-insensitive substring
    mention of a ticker form or the company name counts as relevant, so a
    genuinely relevant item is never falsely flagged. Items are not dropped -
    low-relevance ones are tagged so the downstream agent can weigh them
    accordingly. Returns the count of low-relevance items.

    When no target ticker is set (bare states, tests), no marking is applied.
    """
    target = get_target_ticker()
    if target is None:
        return 0
    target_ticker = target.ticker
    company_name = target.company_name
    low_count = 0
    for item in items:
        if _is_relevant_news_item(item, target_ticker, company_name):
            item["relevance"] = "high"
        else:
            item["relevance"] = "low"
            low_count += 1
    return low_count


def _company_short_form(company_name: str) -> str:
    """Return a common abbreviation of the company name for recall-first matching.

    English names with spaces use the first token (``"Apple"`` from
    ``"Apple Inc."``). Chinese names (no spaces, non-ASCII) use the last two
    characters as a typical abbreviation (``"茅台"`` from ``"贵州茅台"``). This
    may over-match (e.g. ``"银行"`` from ``"工商银行"``), which is acceptable
    because the relevance filter is recall-first: a genuinely relevant item
    must never be falsely flagged as low-relevance.
    """
    tokens = company_name.split()
    if len(tokens) > 1:
        return tokens[0].lower()
    if any(ord(ch) > 127 for ch in company_name) and len(company_name) >= 2:
        return company_name[-2:].lower()
    return ""


def _is_relevant_news_item(
    item: dict[str, Any],
    target_ticker: str,
    company_name: str | None,
) -> bool:
    """Return True when the item mentions the target ticker or company name.

    Recall-first matching against title + content. Ticker forms cover the
    bare code, the suffixed form, and the normalized form so ``600519``,
    ``600519.SH`` and ``600519.SS`` all match. Company matching tries the
    full name then a short form so items using a common abbreviation (e.g.
    ``"茅台"`` for ``"贵州茅台"``) are not falsely flagged. Matching is
    case-insensitive substring; an empty item body is treated as relevant
    (let the LLM judge) so it is not penalized for a missing content field.
    """
    text = " ".join(
        [str(item.get("title") or ""), str(item.get("content") or "")]
    ).lower()
    if not text.strip():
        return True

    ticker_forms: set[str] = set()
    for form in (
        target_ticker,
        to_akshare_symbol(target_ticker),
        normalize_ticker_symbol(target_ticker),
    ):
        if form:
            ticker_forms.add(form.lower())
    for form in ticker_forms:
        if form and form in text:
            return True

    if company_name:
        name_lower = company_name.lower()
        if name_lower and name_lower in text:
            return True
        short_form = _company_short_form(company_name)
        if short_form and short_form != name_lower and short_form in text:
            return True

    return False


def _extract_news_items(vendor: str, result: Any) -> list[dict[str, Any]]:
    if isinstance(result, dict) and result.get("source") == "tavily":
        return [dict(item, source="tavily") for item in result.get("items", [])]

    if isinstance(result, dict) and result.get("source") == "doubao":
        return [dict(item, source="doubao") for item in result.get("items", [])]

    if isinstance(result, dict) and result.get("source") == "bocha":
        return [dict(item, source="bocha") for item in result.get("items", [])]

    if isinstance(result, (dict, list)):
        return _extract_json_news_items(vendor, result)

    text = str(result)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None

    if parsed is not None:
        return _extract_json_news_items(vendor, parsed)

    return _extract_markdown_news_items(vendor, text)


def _extract_json_news_items(vendor: str, data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        records = data.get("feed") or data.get("results") or data.get("items") or []
    elif isinstance(data, list):
        records = data
    else:
        records = []

    items = []
    for record in records:
        if not isinstance(record, dict):
            continue
        title = record.get("title") or record.get("headline") or record.get("summary")
        if not title:
            continue
        items.append(
            {
                "title": title,
                "url": record.get("url") or record.get("link") or "",
                "content": record.get("summary") or record.get("content") or "",
                "published": record.get("time_published") or record.get("published") or "",
                "publisher": record.get("source") or record.get("publisher") or vendor,
                "score": record.get("overall_sentiment_score") or record.get("score"),
                "source": vendor,
            }
        )
    return items


def _extract_markdown_news_items(vendor: str, text: str) -> list[dict[str, Any]]:
    items = []
    blocks = re.split(r"\n(?=### )", text)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or not lines[0].startswith("### "):
            continue
        title_line = lines[0][4:].strip()
        publisher = vendor
        match = re.search(r"\(source:\s*([^)]+)\)", title_line, flags=re.IGNORECASE)
        if match:
            publisher = match.group(1).strip()
            title_line = re.sub(r"\s*\(source:\s*[^)]+\)", "", title_line, flags=re.IGNORECASE)
        link = ""
        content_lines = []
        for line in lines[1:]:
            if line.lower().startswith("link:"):
                link = line.split(":", 1)[1].strip()
            else:
                content_lines.append(line)
        items.append(
            {
                "title": title_line,
                "url": link,
                "content": " ".join(content_lines),
                "published": "",
                "publisher": publisher,
                "score": None,
                "source": vendor,
            }
        )
    return items


_STALE_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d",
    "%Y%m%dT%H%M%S",
    "%Y%m%d",
    "%b %d, %Y",
    "%B %d, %Y",
)


def _parse_date_best_effort(
    raw: str, *, default_timezone: tzinfo = timezone.utc
) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=default_timezone)
        return parsed.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        pass
    cleaned = re.sub(r"\s+[A-Z]{2,4}$", "", text)
    for fmt in _STALE_DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=default_timezone)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _filter_stale_items(
    items: list[dict[str, Any]], start_date: str, end_date: str
) -> tuple[list[dict[str, Any]], int]:
    """Remove items whose published date is outside the [start, end+1d] window.

    Returns (kept_items, stale_count).
    """
    try:
        market_timezone = _news_market_timezone()
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(
            tzinfo=market_timezone
        )
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            tzinfo=market_timezone
        )
    except ValueError:
        return items, 0

    start_utc = start.astimezone(timezone.utc)
    end_inclusive = (end + timedelta(days=1)).astimezone(timezone.utc)
    kept = []
    stale_count = 0
    for item in items:
        # Respect pre-computed stale flag from Tavily
        if item.get("stale"):
            stale_count += 1
            continue
        pub_dt = _parse_date_best_effort(
            item.get("published", ""), default_timezone=market_timezone
        )
        if pub_dt is None:
            item["published_time_status"] = "unknown"
            item.setdefault("limitations", []).append(
                "publication_time_unknown_excluded_from_window_coverage"
            )
        elif pub_dt < start_utc or pub_dt >= end_inclusive:
            stale_count += 1
            continue
        else:
            item["published_time_status"] = "verified"
            item["published_at_utc"] = pub_dt.isoformat()
        kept.append(item)
    return kept, stale_count


def _news_market_timezone() -> tzinfo:
    target = get_target_ticker()
    if target is not None:
        try:
            from .ticker_utils import is_a_share_ticker

            if is_a_share_ticker(target.ticker):
                return ZoneInfo("Asia/Shanghai")
        except ValueError:
            pass
    return timezone.utc


def _dedupe_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Two-layer deduplication: exact match first, then fuzzy title+time match.

    L1 (exact): URL normalised (strip query/hash); if no URL, exact title
    normalised.  O(n) and zero false positives.

    L2 (fuzzy, optional): character bigram Jaccard similarity on normalised
    titles, combined with a publication-time window so unrelated articles
    sharing some words are not falsely merged.  Runs *after* L1 so the
    comparison budget is already reduced.
    """
    ordered = sorted(items, key=lambda x: str(x.get("published") or ""), reverse=True)

    # ---- L1: exact dedup ----
    l1_deduped: list[dict[str, Any]] = []
    seen_l1: set[str] = set()
    for item in ordered:
        key = _news_dedupe_key(item)
        if key in seen_l1:
            continue
        seen_l1.add(key)
        l1_deduped.append(item)

    # ---- L2: fuzzy dedup (optional, config-gated) ----
    cfg = get_config()
    if not _config_bool(cfg.get("news_fuzzy_dedup_enabled", True)):
        return l1_deduped

    threshold = float(cfg.get("news_fuzzy_dedup_title_threshold", 0.5))
    time_window_days = int(cfg.get("news_fuzzy_dedup_time_window_days", 2))
    min_overlap = int(cfg.get("news_fuzzy_dedup_min_overlap_bigrams", 5))

    l2_deduped: list[dict[str, Any]] = []
    kept_bigrams: list[frozenset[str] | None] = []
    kept_times: list[datetime | None] = []

    for item in l1_deduped:
        bigrams = _title_bigrams(item.get("title"))
        pub_time = _parse_date_best_effort(item.get("published", ""))
        is_dup = False
        for i, kept_bg in enumerate(kept_bigrams):
            if kept_bg is None or bigrams is None:
                continue
            if not _within_time_window(pub_time, kept_times[i], time_window_days):
                continue
            sim = _title_similarity(bigrams, kept_bg, min_overlap)
            if sim >= threshold:
                is_dup = True
                break
        if is_dup:
            continue
        l2_deduped.append(item)
        kept_bigrams.append(bigrams)
        kept_times.append(pub_time)

    return l2_deduped


def _news_dedupe_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip().lower()
    if url:
        return re.sub(r"[?#].*$", "", url)
    title = str(item.get("title") or "").lower()
    return re.sub(r"[^a-z0-9一-鿿]+", "", title)[:120]


def _normalize_title_for_fuzzy(title: object) -> str:
    """Normalise a title for fuzzy comparison.

    Lowercase, strip punctuation/symbols, collapse whitespace.  Preserves
    CJK characters so Chinese titles still produce meaningful bigrams.
    """
    text = str(title or "").lower()
    text = re.sub(r"[^a-z0-9\s一-鿿]+", " ", text)
    return re.sub(r"\s+", "", text).strip()


def _title_bigrams(title: object) -> frozenset[str] | None:
    """Return character bigrams of a normalised title, or None if too short."""
    norm = _normalize_title_for_fuzzy(title)
    if len(norm) < 2:
        return None
    return frozenset(norm[i : i + 2] for i in range(len(norm) - 1))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _title_similarity(
    a: frozenset[str], b: frozenset[str], min_overlap: int = 5
) -> float:
    """Title similarity using bi-directional containment (max of both sides).

    Containment is more robust than Jaccard for republished articles where one
    site adds or removes a few words: it asks "what fraction of the shorter
    title's character pairs also appear in the longer one?" rather than
    penalising length asymmetry.

    Returns 0.0 when the overlap is below ``min_overlap`` bigrams so very
    short titles cannot coincidentally trigger a false merge.
    """
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter < min_overlap:
        return 0.0
    smaller = min(len(a), len(b))
    if smaller == 0:
        return 0.0
    return inter / smaller


def _within_time_window(
    a: datetime | None, b: datetime | None, window_days: int
) -> bool:
    """Two published times count as 'same event window' if both are known and
    within ``window_days`` of each other.  If either is unknown, we still let
    the fuzzy comparison run (safer to compare than to silently merge), but
    callers may choose a different strategy.
    """
    if a is None or b is None:
        return True
    return abs((a - b).days) <= window_days


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _format_curated_news(
    method: str,
    successes: list[tuple[str, Any]],
    errors: list[tuple[str, Exception | str]],
    start_date: str = "",
    end_date: str = "",
) -> str:
    cfg = get_config()
    max_items = int(cfg.get("news_curator_max_items", 10))
    items: list[dict[str, Any]] = []
    for vendor, result in successes:
        items.extend(_extract_news_items(vendor, result))

    # Timeliness: filter items whose published date is outside the query window
    stale_count = 0
    if start_date and end_date:
        items, stale_count = _filter_stale_items(items, start_date, end_date)

    # Cross-source consistency detection (before dedup to capture multi-source events)
    if len(successes) >= 2:
        llm = create_llm_from_config()
        attach_cross_source_info(items, llm)
    raw_count = len(items)
    curated = _dedupe_news_items(items)[:max_items]
    dedup_removed = raw_count - len(_dedupe_news_items(items))
    attach_credibility(curated)
    cred_summary = credibility_summary(curated)
    cs_summary = cross_source_summary(curated) if len(successes) >= 2 else {"confirmed": 0, "single_source": 0}
    # Relevance marking (recall-first): soft-mark items that do not mention the
    # target ticker or company name, so they stay available but are flagged for
    # the downstream agent rather than silently mixed into target analysis.
    low_relevance_count = _mark_news_relevance(curated)
    sections = [
        "## Curated News Package",
        f"Method: `{method}`",
        "Sources used: " + ", ".join(vendor for vendor, _ in successes),
        f"Credibility: {cred_summary['high']} high, {cred_summary['medium']} medium, {cred_summary['low']} low",
        f"Cross-source: {cs_summary['confirmed']} confirmed by multiple sources, {cs_summary['single_source']} single-source only",
    ]
    if stale_count:
        sections.append(f"Timeliness: {stale_count} item(s) filtered as outside the {start_date}~{end_date} window.")
    if dedup_removed:
        fuzzy_enabled = _config_bool(cfg.get("news_fuzzy_dedup_enabled", True))
        sections.append(
            f"Deduplication: {dedup_removed} item(s) removed "
            f"({'exact + fuzzy' if fuzzy_enabled else 'exact match only'}) "
            f"before curator cap."
        )
    if low_relevance_count:
        sections.append(
            f"Relevance: {low_relevance_count} item(s) marked low-relevance "
            f"(target ticker/company not detected in the item)."
        )
    unknown_date_count = sum(
        item.get("published_time_status") == "unknown" for item in curated
    )
    dated_item_count = sum(
        item.get("published_time_status") == "verified" for item in curated
    )
    if unknown_date_count:
        sections.append(
            f"Timeliness limitation: {unknown_date_count} retained item(s) have "
            "no verified publication time and do not contribute to window coverage."
        )

    if errors:
        sections.append(
            "Source status: "
            + "; ".join(f"{vendor}: {_summarize_vendor_error_for_news(err)}" for vendor, err in errors)
        )

    if not curated:
        sections.append("No parseable news items were found, but at least one source returned data.")
        for vendor, result in successes:
            sections.append(f"### Raw {vendor} result\n{str(result)[:2000]}")
        return _preserve_source_coverage(
            "\n\n".join(sections),
            successes,
            dated_item_count=0,
            unknown_date_count=0,
            curation_unverifiable=True,
        )

    sections.append(
        f"Curator retained {len(curated)} item(s) after source labeling, deduplication, and max item limiting."
    )
    for idx, item in enumerate(curated, start=1):
        title = item.get("title") or "Untitled"
        source = item.get("source") or "unknown"
        publisher = item.get("publisher") or source
        score = item.get("score")
        score_part = f", score: {score:.3f}" if isinstance(score, (float, int)) else ""
        credibility = item.get("credibility", "low")
        cs_tag = item.get("cross_source_tag", "")
        cs_part = f", {cs_tag}" if cs_tag else ""
        relevance = item.get("relevance")
        relevance_part = f", relevance: {relevance}" if relevance == "low" else ""
        body = [f"### {idx}. {title} (source: {source}, publisher: {publisher}{score_part}, credibility: {credibility}{cs_part}{relevance_part})"]
        if item.get("published"):
            body.append(f"Published: {item['published']}")
        elif item.get("published_time_status") == "unknown":
            body.append(
                "Publication time unavailable; excluded from recency/window coverage."
            )
        if item.get("content"):
            body.append(str(item["content"]).strip())
        if item.get("url"):
            body.append(f"Link: {item['url']}")
        sections.append("\n".join(body))

    return _preserve_source_coverage(
        "\n\n".join(sections),
        successes,
        dated_item_count=dated_item_count,
        unknown_date_count=unknown_date_count,
    )


def _preserve_source_coverage(
    rendered: str,
    successes: list[tuple[str, Any]],
    *,
    dated_item_count: int,
    unknown_date_count: int,
    curation_unverifiable: bool = False,
) -> str:
    """Keep provider-owned pagination proof through curation.

    Curation changes presentation, not what a provider fetched. When at least
    one successful source carries typed coverage, retain the strongest record
    on the curated string so deterministic prefetch can expose page counts and
    exhaustion without parsing rendered news.
    """
    rank = {"complete": 0, "partial": 1, "unknown": 2, "unavailable": 3}
    records: list[SourceCoverageV1] = []
    for _vendor, result in successes:
        if isinstance(result, CoveredText):
            records.append(result.coverage)
            continue
        if isinstance(result, dict) and isinstance(result.get("coverage"), dict):
            try:
                records.append(SourceCoverageV1.model_validate(result["coverage"]))
            except ValueError:
                continue
    if not records:
        return rendered
    strongest = min(
        records,
        key=lambda coverage: rank[coverage.completeness],
    )
    if strongest.completeness == "complete" and (
        unknown_date_count or curation_unverifiable
    ):
        downgraded = "partial" if dated_item_count else "unknown"
        strongest = SourceCoverageV1.model_validate(
            {
                **strongest.model_dump(mode="json"),
                "completeness": downgraded,
                "degradations": tuple(strongest.degradations)
                + (
                    "publication_time_unknown_excluded_from_window_coverage"
                    if unknown_date_count
                    else "curated_items_unverifiable",
                ),
            }
        )
    return CoveredText(rendered, strongest)
