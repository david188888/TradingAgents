"""Tests for the two-layer news dedup strategy (exact + fuzzy)."""

from __future__ import annotations

import pytest

from tradingagents.dataflows import news_curator
from tradingagents.dataflows.config import set_config


@pytest.fixture
def _default_cfg():
    """Apply a minimal config with fuzzy dedup enabled and no LLM fallbacks."""
    prev = news_curator.get_config()
    set_config(
        {
            "news_fuzzy_dedup_enabled": True,
            "news_fuzzy_dedup_title_threshold": 0.5,
            "news_fuzzy_dedup_time_window_days": 2,
            "news_fuzzy_dedup_min_overlap_bigrams": 5,
            "news_curator_max_items": 20,
            "news_layer1_enabled": False,
            "consistency_llm_model": "",
        }
    )
    yield
    set_config(prev)


# ---- helper ----

def _item(title, url="", published="", source="test"):
    return {
        "title": title,
        "url": url,
        "content": "body",
        "published": published,
        "source": source,
        "publisher": source,
    }


# ---- L1: exact dedup ----

class TestExactDedup:
    def test_same_url_merged(self, _default_cfg):
        items = [
            _item("A", "https://example.com/a?x=1", "2026-08-17"),
            _item("A different title", "https://example.com/a?y=2", "2026-08-17"),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 1

    def test_same_title_no_url_merged(self, _default_cfg):
        items = [
            _item("茅台发布半年报", published="2026-08-17"),
            _item("茅台发布半年报", published="2026-08-16"),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 1
        # keeps the newer one
        assert out[0]["published"] == "2026-08-17"

    def test_different_urls_both_kept(self, _default_cfg):
        items = [
            _item("A", "https://a.com/1", "2026-08-17"),
            _item("B", "https://b.com/1", "2026-08-17"),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 2


# ---- L2: fuzzy dedup ----

class TestFuzzyDedup:
    def test_same_article_different_title_merged(self, _default_cfg):
        """Sites A and B republish the same news with slightly rewritten titles."""
        items = [
            _item(
                "贵州茅台发布2026年半年报 营收增长15%",
                url="https://site-a.com/maotai-h1",
                published="2026-08-15T10:00:00+08:00",
                source="tavily",
            ),
            _item(
                "贵州茅台2026半年报出炉：营收同比增15%",
                url="https://site-b.com/maotai-2026",
                published="2026-08-15T14:30:00+08:00",
                source="doubao",
            ),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 1
        # keeps the newer published time
        assert "site-b.com" in out[0]["url"]

    def test_different_articles_not_merged(self, _default_cfg):
        items = [
            _item(
                "茅台发布半年报 营收增长15%",
                url="https://a.com/1",
                published="2026-08-15",
            ),
            _item(
                "五粮液上半年净利润同比增长12%",
                url="https://b.com/1",
                published="2026-08-15",
            ),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 2

    def test_same_title_far_apart_in_time_not_merged(self, _default_cfg):
        """Same event name but 30 days apart -> different events, keep both."""
        items = [
            _item(
                "公司召开股东大会审议分红方案",
                url="https://a.com/1",
                published="2026-06-01",
            ),
            _item(
                "公司召开临时股东大会 审议分红方案",
                url="https://b.com/1",
                published="2026-08-15",
            ),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 2

    def test_fuzzy_dedup_can_be_disabled(self, _default_cfg):
        from tradingagents.dataflows.config import set_config

        set_config(
            {
                "news_fuzzy_dedup_enabled": False,
                "news_fuzzy_dedup_title_threshold": 0.5,
                "news_fuzzy_dedup_time_window_days": 2,
                "news_fuzzy_dedup_min_overlap_bigrams": 5,
                "news_curator_max_items": 20,
                "news_layer1_enabled": False,
                "consistency_llm_model": "",
            }
        )
        items = [
            _item(
                "贵州茅台发布2026年半年报 营收增长15%",
                url="https://site-a.com/1",
                published="2026-08-15",
            ),
            _item(
                "贵州茅台2026半年报出炉：营收同比增15%",
                url="https://site-b.com/1",
                published="2026-08-15",
            ),
        ]
        out = news_curator._dedupe_news_items(items)
        # with fuzzy disabled, exact dedup only -> both kept (different URLs)
        assert len(out) == 2

    def test_threshold_is_configurable(self, _default_cfg):
        from tradingagents.dataflows.config import set_config

        # raise threshold so near-duplicates are no longer merged
        set_config(
            {
                "news_fuzzy_dedup_enabled": True,
                "news_fuzzy_dedup_title_threshold": 0.9,
                "news_fuzzy_dedup_time_window_days": 2,
                "news_fuzzy_dedup_min_overlap_bigrams": 5,
                "news_curator_max_items": 20,
                "news_layer1_enabled": False,
                "consistency_llm_model": "",
            }
        )
        items = [
            _item(
                "茅台半年报营收增长15%符合预期",
                url="https://a.com/1",
                published="2026-08-15",
            ),
            _item(
                "茅台发布半年报 营收增15%超市场预期",
                url="https://b.com/1",
                published="2026-08-15",
            ),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 2

    def test_short_titles_not_false_merged(self, _default_cfg):
        """Very short titles should not produce false fuzzy matches."""
        items = [
            _item("涨", url="https://a.com/1", published="2026-08-15"),
            _item("跌", url="https://b.com/1", published="2026-08-15"),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 2

    def test_three_sources_same_event_kept_once(self, _default_cfg):
        """Three near-identical reposts of the same article collapse to one."""
        items = [
            _item("贵州茅台发布2026年半年报 营收增长15%", url="https://a.com/1", published="2026-08-14"),
            _item("贵州茅台2026半年报出炉 营收同比增15%", url="https://b.com/1", published="2026-08-14"),
            _item("贵州茅台发布半年报 2026年营收增长15%", url="https://c.com/1", published="2026-08-14"),
        ]
        out = news_curator._dedupe_news_items(items)
        assert len(out) == 1


# ---- _title_bigrams / _jaccard unit tests ----

class TestBigramHelpers:
    def test_chinese_title_bigrams(self):
        bg = news_curator._title_bigrams("贵州茅台半年报")
        assert bg is not None
        assert "贵州" in bg
        assert "茅台" in bg

    def test_english_title_bigrams_ignore_case_and_punctuation(self):
        bg = news_curator._title_bigrams("Apple, Inc. Q3 Earnings!")
        assert bg is not None
        assert "ap" in bg
        assert "," not in bg

    def test_jaccard_identical_is_one(self):
        a = news_curator._title_bigrams("茅台半年报")
        b = news_curator._title_bigrams("茅台半年报")
        assert news_curator._jaccard(a, b) == pytest.approx(1.0)

    def test_jaccard_disjoint_is_zero(self):
        a = news_curator._title_bigrams("茅台")
        b = news_curator._title_bigrams("苹果")
        assert news_curator._jaccard(a, b) == 0.0
