"""News item extraction, entity relevance and wrong-identity detection."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from .config import get_config

OFFICIAL_A_SHARE_DOMAINS = ("cninfo.com.cn", "szse.cn", "sse.com.cn", "bse.cn")


WRONG_IDENTITY_HINTS: tuple[str, ...] = ("恒瑞医药", "安洁科技")


def _get_wrong_identity_hints() -> tuple[str, ...]:
    """Return wrong-identity hints: built-in + user-configured additions."""
    cfg = get_config()
    extra = cfg.get("wrong_identity_hints") or []
    if isinstance(extra, str):
        extra = [s.strip() for s in extra.split(",") if s.strip()]
    return WRONG_IDENTITY_HINTS + tuple(extra)


def _extract_news_items_from_reports(*reports: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for report in reports:
        text = str(report or "").strip()
        if not text or text.lower().startswith("no curated news found"):
            continue
        blocks = re.split(r"\n(?=###\s+)", text)
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines or not lines[0].startswith("###"):
                continue
            title = re.sub(r"^###\s+\d*\.?\s*", "", lines[0]).strip()
            url = ""
            content_lines = []
            publisher = ""
            published = ""
            for line in lines[1:]:
                lower = line.lower()
                if lower.startswith("link:"):
                    url = line.split(":", 1)[1].strip()
                elif lower.startswith("published:"):
                    published = line.split(":", 1)[1].strip()
                else:
                    content_lines.append(line)
            match = re.search(r"publisher:\s*([^,)]+)", title, flags=re.IGNORECASE)
            if match:
                publisher = match.group(1).strip()
            items.append(
                {
                    "title": title,
                    "url": url,
                    "content": " ".join(content_lines),
                    "publisher": publisher,
                    "published": published,
                    "source": "report",
                }
            )
    return items


def _dedupe_news_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in items:
        key = _news_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(item))
    return deduped


def _news_dedupe_key(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip().lower()
    if url:
        parsed = urlparse(url)
        return f"{parsed.netloc}{parsed.path}".rstrip("/")
    title = str(item.get("title") or "").lower()
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title)
    return normalized[:160]


def _annotate_entity_roles(items: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    """Classify evidence without treating every non-target code as contamination.

    Explicit roles from an upstream curator win. Otherwise, target identity is
    a subject; a non-target code in an industry context is a comparable; all
    remaining unbound material is noise. Only an explicitly target-bound
    identity conflict can be a hard stop.
    """
    profile_codes = _profile_code_aliases(profile)
    profile_names = _profile_name_aliases(profile)
    for item in items:
        explicit = str(item.get("entity_role") or "").strip().lower()
        if explicit in {"subject", "comparable", "noise"}:
            continue
        text = _item_text(item)
        codes = _explicit_stock_codes(text)
        if any(code in text for code in profile_codes) or any(
            name and name in text for name in profile_names
        ):
            item["entity_role"] = "subject"
        elif codes and _is_industry_relevant(item, profile):
            item["entity_role"] = "comparable"
        else:
            item["entity_role"] = "noise"


def _is_primary_identity_binding(text: str, profile: dict[str, Any]) -> bool:
    """Return true only when a labeled identity pair names another code."""
    return bool(_explicit_identity_codes(text) - _profile_code_aliases(profile))


def _explicit_identity_codes(text: str) -> set[str]:
    """Return codes that occur in a complete labeled code/name pair."""
    return {code for code, _name in _explicit_identity_bindings(text)}


def _find_wrong_identity_hits(items: list[dict[str, Any]], profile: dict[str, Any]) -> set[str]:
    profile_names = _profile_name_aliases(profile)
    profile_codes = _profile_code_aliases(profile)
    hits: set[str] = set()

    # A FAIL_STOP must be supported by a source-level identity assertion. A
    # report that merely names a peer, publisher, or data-status note is not
    # evidence of target misidentification.
    for item in items:
        text = _item_text(item)
        identity_codes = _explicit_identity_codes(text)
        hits.update(code for code in identity_codes if code not in profile_codes)
        if profile_names:
            hits.update(_wrong_names_bound_to_profile_code(text, profile, profile_names))
    return hits


def _profile_name_aliases(profile: dict[str, Any]) -> set[str]:
    aliases = {str(profile.get("name") or ""), str(profile.get("full_name") or "")}
    return {alias for alias in aliases if alias}


def _profile_code_aliases(profile: dict[str, Any]) -> set[str]:
    aliases = {
        str(profile.get("ticker") or "").upper(),
        str(profile.get("ts_code") or "").upper(),
        str(profile.get("symbol") or ""),
    }
    return {alias for alias in aliases if alias}


def _explicit_stock_codes(text: str) -> set[str]:
    hits = {
        match.group(0).upper()
        for match in re.finditer(r"(?<!\w)\d{6}\.(?:SZ|SH|SS|BJ)(?!\w)", text, re.IGNORECASE)
    }
    for match in re.finditer(
        r"(?:证券代码|股票代码|stock\s+code|ticker)[：:\s]*([0-9]{6})", text, re.IGNORECASE
    ):
        hits.add(match.group(1))
    return hits


def _explicit_identity_bindings(text: str) -> list[tuple[str, str]]:
    """Extract code/name pairs only from labeled security identity fields.

    A hard stop discards an entire research run, so a ticker adjacent to prose,
    a parenthetical note, or an analyst's interpretation must never be treated
    as a company-name assertion. The pair must be explicitly labeled as a
    security code followed by a security short name, company name, or issuer.
    """
    code_pattern = r"(?<!\w)([0-9]{6}(?:\.(?:SZ|SH|SS|BJ))?)(?!\w)"
    code_label = r"(?:证券代码|股票代码|stock\s+code|ticker)"
    name_label = r"(?:证券简称|股票简称|公司名称|公告主体|security\s+name|company\s+name)"
    bindings: list[tuple[str, str]] = []
    pattern = re.compile(
        rf"{code_label}\s*[：:]?\s*{code_pattern}"
        rf"[\s,，;；|/]*{name_label}\s*[：:]?\s*"
        rf"([^\n，,;；。()（）]{{2,80}})",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        bindings.append((match.group(1).upper(), match.group(2).strip()))
    return bindings


def _wrong_names_bound_to_profile_code(
    text: str,
    profile: dict[str, Any],
    profile_names: set[str],
) -> set[str]:
    """Return conflicting names from explicit security identity bindings only."""
    hits: set[str] = set()
    profile_codes = _profile_code_aliases(profile)
    for code, candidate in _explicit_identity_bindings(text):
        if code not in profile_codes or _is_profile_alias(candidate, profile_names):
            continue
        # Hints identify known cross-company collisions, but only after the
        # source has made an explicit code/name identity assertion.
        if candidate in _get_wrong_identity_hints():
            hits.add(candidate)
            continue
        # A Chinese alias may be correct when the canonical profile came from
        # yfinance in English. Without a local name mapping, abstain.
        if profile.get("profile_source") == "yfinance":
            continue
        if not _names_are_related(candidate, profile_names):
            hits.add(candidate)
    return hits


def _names_are_related(candidate: str, profile_names: set[str]) -> bool:
    """Check if candidate name has any substring relationship with profile names."""
    for name in profile_names:
        if not name:
            continue
        if candidate in name or name in candidate:
            return True
        # Check for significant character overlap (handles abbreviations)
        common = set(candidate) & set(name)
        if len(common) >= min(len(candidate), len(name)) * 0.6:
            return True
    return False


def _is_profile_alias(candidate: str, profile_names: set[str]) -> bool:
    return any(candidate in name or name in candidate for name in profile_names)


def _is_company_relevant(item: dict[str, Any], profile: dict[str, Any]) -> bool:
    if item.get("entity_role") in {"comparable", "noise"}:
        return False
    text = _item_text(item)
    candidates = {
        str(profile.get("ticker") or ""),
        str(profile.get("ts_code") or ""),
        str(profile.get("symbol") or ""),
        str(profile.get("name") or ""),
        str(profile.get("full_name") or ""),
    }
    return any(candidate and candidate in text for candidate in candidates)


def _is_official_item(item: dict[str, Any]) -> bool:
    domain = urlparse(str(item.get("url") or "")).netloc.lower()
    return any(official in domain for official in OFFICIAL_A_SHARE_DOMAINS)


def _is_industry_relevant(item: dict[str, Any], profile: dict[str, Any]) -> bool:
    industry = str(profile.get("industry") or "")
    return bool(industry and industry in _item_text(item))


def _item_text(item: dict[str, Any]) -> str:
    return "\n".join(str(item.get(key) or "") for key in ("title", "content", "publisher", "url"))

