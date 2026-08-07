"""Evidence report / news package / company profile formatting."""

from __future__ import annotations

from typing import Any

from .config import get_config


def format_company_profile(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    parts = [
        f"canonical ticker: `{profile.get('ticker') or profile.get('ts_code')}`",
        f"company short name: `{profile.get('name') or 'unknown'}`",
    ]
    if profile.get("full_name"):
        parts.append(f"full company name: `{profile['full_name']}`")
    if profile.get("industry"):
        parts.append(f"industry: `{profile['industry']}`")
    if profile.get("exchange"):
        parts.append(f"exchange: `{profile['exchange']}`")
    return "Canonical company profile: " + "; ".join(parts) + "."


def _format_evidence_report(
    profile: dict[str, Any],
    assessment: dict[str, Any],
    *,
    enrichment_rounds: int,
) -> str:
    from .evidence_gate import EvidenceStatus
    status = assessment.get("status")
    if status == EvidenceStatus.LOW_CONFIDENCE:
        status_label = "低信心通过"
    elif assessment.get("low_coverage"):
        status_label = "低覆盖通过"
    else:
        status_label = "通过"

    weighted_company = assessment.get("weighted_company", assessment.get("company_count", 0))
    weighted_mixed = assessment.get("weighted_mixed", assessment.get("mixed_count", 0))
    cfg = get_config()
    min_company = int(cfg.get("news_min_company_items", 3))
    min_mixed = int(cfg.get("news_min_mixed_items", 5))

    lines = [
        "## Evidence Steward Report",
        format_company_profile(profile),
        f"Status: {status_label}",
        f"Evidence confidence: {status.value if hasattr(status, 'value') else status} "
        f"(company {weighted_company:.1f}/{min_company}, mixed {weighted_mixed:.1f}/{min_mixed})",
        f"Company evidence items: {assessment.get('company_count', 0)}",
        f"Mixed evidence items after deduplication: {assessment.get('mixed_count', 0)}",
        f"Tavily enrichment rounds used: {enrichment_rounds}",
        "Deduplication: URL query strings and repeated titles are collapsed before downstream context injection.",
    ]
    if assessment.get("reasons"):
        lines.append("Limitations:")
        for reason in assessment["reasons"]:
            lines.append(f"- {reason}")
    return "\n".join(lines)


def _format_evidence_news_package(
    profile: dict[str, Any],
    items: list[dict[str, Any]],
    evidence_report: str,
) -> str:
    cfg = get_config()
    max_items = int(cfg.get("news_curator_max_items", 10))
    sections = [
        "## Evidence-Gated News Package",
        evidence_report,
        "The following items are deduplicated and identity-filtered before downstream debate.",
    ]
    for idx, item in enumerate(items[:max_items], start=1):
        sections.append(_format_item(idx, item, profile))
    return "\n\n".join(sections)


def _format_item(idx: int, item: dict[str, Any], profile: dict[str, Any]) -> str:
    title = str(item.get("title") or "Untitled").strip()
    publisher = str(item.get("publisher") or item.get("source") or "unknown").strip()
    credibility = item.get("credibility", "low")
    parts = [f"### {idx}. {title} (publisher: {publisher}, credibility: {credibility})"]
    if item.get("published"):
        parts.append(f"Published: {item['published']}")
    content = str(item.get("content") or "").strip()
    if content:
        parts.append(content[:1200])
    if item.get("url"):
        parts.append(f"Link: {item['url']}")
    parts.append(f"Identity check: matched {profile.get('ticker')} / {profile.get('name')}.")
    return "\n".join(parts)

