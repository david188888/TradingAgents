"""Source credibility scoring for news items.

Assigns a credibility tier (high / medium / low) to each news item based on
its publisher domain.  The mapping is intentionally small (~30 domains) to
keep maintenance overhead low; unknown domains default to ``"low"``.

Domain assignments are evidence-based — see SOURCES section below.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .config import get_config

# ---------------------------------------------------------------------------
# Built-in domain → tier mapping
# ---------------------------------------------------------------------------
#
# SOURCES — evidence for domain assignments:
#
# [CSRC] 中国证监会官方指定信息披露渠道:
#   https://www.csrc.gov.cn/csrc/c100028/c7433195/content.shtml
#   指定平台: 巨潮资讯网(cninfo.com.cn), 中证网(cs.com.cn),
#   深交所(szse.cn), 上交所(sse.com.cn), 北交所(bse.cn)
#
# [Hurun] 2020中国财经媒体排行 Top10:
#   财联社、证券时报、第一财经、21世纪经济报道、每日经济新闻等
#
# [CSRC-Media] 财联社(cls.cn): 持有《互联网新闻信息服务许可证》的主流财经新闻集团和财经通讯社
#   500+记者团队, 由上海报业集团主管
#
# [SEC] SEC.gov: 美国证监会官方, 所有上市公司法定披露渠道
#   prnewswire.com / businesswire.com: SEC 8-K filing 常用官方新闻稿发布渠道
#
# [MediaRank] 国际财经媒体 Tier-1: Reuters, Bloomberg, WSJ, FT, AP, CNBC
#   基于引用率、新闻质量、编辑标准的行业共识

# High: official regulatory sources + state media + top-tier newswires
_HIGH_DOMAINS: set[str] = {
    # ── A股 官方监管 / 指定披露平台 (CSRC-designated) ──
    "cninfo.com.cn",    # 巨潮资讯网 — CSRC 指定信息披露平台 [CSRC]
    "szse.cn",          # 深圳证券交易所 [CSRC]
    "sse.com.cn",       # 上海证券交易所 [CSRC]
    "bse.cn",           # 北京证券交易所 [CSRC]
    "cs.com.cn",        # 中证网 — CSRC 指定信息披露平台 [CSRC]
    "csrc.gov.cn",      # 中国证监会官网 [CSRC]
    # ── US / global regulatory ──
    "sec.gov",          # SEC — 美国证监会 [SEC]
    "investor.gov",     # SEC 投资者教育
    # ── 国际通讯社 / Tier-1 财经媒体 [MediaRank] ──
    "reuters.com",      # 路透社
    "bloomberg.com",    # 彭博社
    "apnews.com",       # 美联社
    "wsj.com",          # 华尔街日报
    "ft.com",           # 金融时报
    "barrons.com",      # Barron's
    "cnbc.com",         # CNBC
    # ── 国际官方新闻稿发布渠道 [SEC] ──
    "prnewswire.com",   # PR Newswire — SEC 8-K filing 常用渠道
    "businesswire.com", # Business Wire — SEC 8-K filing 常用渠道
    # ── 中国 Tier-1 财经媒体 [CSRC-Media][Hurun] ──
    "cls.cn",           # 财联社 — 持有互联网新闻信息服务许可证, 500+记者 [CSRC-Media]
    "xinhuanet.com",    # 新华社 — 国家通讯社
    "yicai.com",        # 第一财经 — Hurun Top10 财经媒体 [Hurun]
    "caixin.com",       # 财新 — 深度调查报道
    "stcn.com",         # 证券时报 — CSRC 指定信息披露媒体 [CSRC][Hurun]
    "21jingji.com",     # 21世纪经济报道 — Hurun Top10 [Hurun]
}

# Medium: mainstream financial platforms / data aggregators
_MEDIUM_DOMAINS: set[str] = {
    # ── 国际主流财经平台 ──
    "finance.yahoo.com",    # Yahoo Finance
    "marketwatch.com",      # MarketWatch
    "investing.com",        # Investing.com
    "seekingalpha.com",     # Seeking Alpha
    "fool.com",             # The Motley Fool
    # ── 中国主流财经平台 [Hurun] ──
    "eastmoney.com",        # 东方财富
    "10jqka.com.cn",        # 同花顺
    "stockstar.com",        # 证券之星
    "nbd.com.cn",           # 每日经济新闻 — Hurun Top10 [Hurun]
    "jiemian.com",          # 界面新闻 — Hurun Top10 [Hurun]
}


def _domain_from_url(url: str) -> str:
    """Extract the lowercased netloc (without ``www.`` prefix) from *url*.

    Also handles bare domain strings (e.g. ``"reuters.com"``) that are stored
    in the ``publisher`` field — these have no scheme so ``urlparse`` puts them
    into ``path`` rather than ``netloc``.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    netloc = (parsed.netloc or parsed.path).lower()
    return netloc.removeprefix("www.")


def _matches_domain(domain: str, target: str) -> bool:
    """Return True when *domain* equals *target* or is a subdomain of it."""
    return domain == target or domain.endswith("." + target)


def score_credibility(item: dict[str, Any]) -> str:
    """Return the credibility tier for a single news *item*.

    Resolution order:
    1. ``credibility_domain_overrides`` from config (user custom mappings)
    2. Built-in ``_HIGH_DOMAINS`` / ``_MEDIUM_DOMAINS``
    3. Default ``"low"``
    """
    cfg = get_config()

    # User overrides take highest priority
    overrides = cfg.get("credibility_domain_overrides") or {}
    url_domain = _domain_from_url(item.get("url") or "")
    publisher_domain = _domain_from_url(item.get("publisher") or "")

    for domain in (url_domain, publisher_domain):
        if not domain:
            continue
        for pattern, tier in overrides.items():
            if _matches_domain(domain, str(pattern).lower()):
                return str(tier).lower()

    # Built-in mappings
    for domain in (url_domain, publisher_domain):
        if not domain:
            continue
        if any(_matches_domain(domain, hd) for hd in _HIGH_DOMAINS):
            return "high"
        if any(_matches_domain(domain, md) for md in _MEDIUM_DOMAINS):
            return "medium"

    return "low"


def attach_credibility(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score and attach ``credibility`` to each item in *items* (in-place).

    Returns the same list for chaining convenience.
    """
    cfg = get_config()
    if not cfg.get("credibility_enabled", True):
        return items

    for item in items:
        item["credibility"] = score_credibility(item)
    return items


def credibility_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    """Return a count of items per credibility tier."""
    summary: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for item in items:
        tier = item.get("credibility", "low")
        summary[tier] = summary.get(tier, 0) + 1
    return summary
