"""Tests for expanded wrong-identity detection."""

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.evidence import (
    _find_wrong_identity_hits,
    _get_wrong_identity_hints,
    _names_are_related,
    evaluate_and_enrich_evidence,
)
from tradingagents.dataflows.news_advisor import NewsAdvisorResult


def _a_share_profile():
    return {
        "ticker": "000001.SZ",
        "symbol": "000001",
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "full_name": "平安银行股份有限公司",
        "industry": "银行",
        "exchange": "深圳证券交易所",
    }


def _yfinance_profile():
    return {
        "ticker": "002396.SZ",
        "symbol": "002396",
        "ts_code": "002396.SZ",
        "name": "FUJIAN STAR-NET COMMUNICATION C",
        "full_name": "Fujian Star-net Communication Co., LTD.",
        "industry": "Communication Equipment",
        "exchange": "深圳证券交易所",
        "profile_source": "yfinance",
    }


# ---------------------------------------------------------------------------
# _get_wrong_identity_hints
# ---------------------------------------------------------------------------


class TestGetWrongIdentityHints:
    def test_includes_built_in(self):
        hints = _get_wrong_identity_hints()
        assert "恒瑞医药" in hints
        assert "安洁科技" in hints

    def test_includes_config_additions(self):
        set_config({"wrong_identity_hints": ["中信证券", "招商银行"]})
        hints = _get_wrong_identity_hints()
        assert "中信证券" in hints
        assert "招商银行" in hints
        assert "恒瑞医药" in hints  # built-in still present
        set_config({"wrong_identity_hints": []})

    def test_comma_separated_string(self):
        set_config({"wrong_identity_hints": "中信证券,招商银行"})
        hints = _get_wrong_identity_hints()
        assert "中信证券" in hints
        set_config({"wrong_identity_hints": []})


# ---------------------------------------------------------------------------
# _names_are_related
# ---------------------------------------------------------------------------


class TestNamesAreRelated:
    def test_identical(self):
        assert _names_are_related("平安银行", {"平安银行"}) is True

    def test_substring(self):
        assert _names_are_related("平安", {"平安银行"}) is True

    def test_superset(self):
        assert _names_are_related("平安银行股份有限公司", {"平安银行"}) is True

    def test_unrelated(self):
        assert _names_are_related("中信证券", {"平安银行"}) is False

    def test_empty_profile_names(self):
        assert _names_are_related("中信证券", {""}) is False

    def test_cross_language_not_related(self):
        """Chinese vs English names should NOT be considered related."""
        assert _names_are_related("星网锐捷", {"FUJIAN STAR-NET"}) is False


# ---------------------------------------------------------------------------
# _find_wrong_identity_hits — expanded detection
# ---------------------------------------------------------------------------


class TestFindWrongIdentityHits:
    def test_detects_unrelated_name_in_explicit_identity_field(self):
        """An explicit stock-code/name pair must reject a mismatched target name."""
        profile = _a_share_profile()
        items = [
            {
                "title": "证券代码：000001.SZ；证券简称：中信证券",
                "source": "tavily",
            }
        ]
        hits = _find_wrong_identity_hits(items, profile)
        assert "中信证券" in hits

    def test_allows_correct_name_in_explicit_identity_field(self):
        """An explicit stock-code/name pair must allow the canonical name."""
        profile = _a_share_profile()
        items = [
            {
                "title": "证券代码：000001.SZ；证券简称：平安银行",
                "source": "tavily",
            }
        ]
        hits = _find_wrong_identity_hits(items, profile)
        assert "平安银行" not in hits

    def test_ignores_parenthetical_coverage_note_after_target_code(self):
        """Coverage notes are not company names or identity evidence."""
        profile = _a_share_profile()
        items = [
            {
                "title": "热门榜覆盖情况",
                "content": "前78名热门榜中未出现 000001（列表截断）。",
                "source": "report",
            }
        ]

        assert _find_wrong_identity_hits(items, profile) == set()

    def test_ignores_parenthetical_context_after_target_code(self):
        """A target ticker in narrative text is not a code/name binding."""
        profile = _a_share_profile()
        items = [
            {
                "title": "资金面观察",
                "content": "000001（部分覆盖）近期融资余额回落。",
                "source": "report",
            }
        ]

        assert _find_wrong_identity_hits(items, profile) == set()

    def test_explicit_identity_code_for_another_company_is_detected(self):
        """A labeled non-target stock code must stop the evidence gate."""
        profile = _a_share_profile()
        items = [
            {
                "title": "公司公告",
                "content": "证券代码：002320；证券简称：海峡股份。",
                "source": "report",
            }
        ]

        assert _find_wrong_identity_hits(items, profile) == {"002320"}

    def test_unbound_company_name_is_not_an_identity_conflict(self):
        """A peer or publisher name alone cannot prove target misidentification."""
        profile = _a_share_profile()
        items = [
            {
                "title": "中信证券研报",
                "content": "中信证券认为行业估值仍有修复空间。",
                "source": "report",
            }
        ]

        assert _find_wrong_identity_hits(items, profile) == set()

    def test_custom_hint_requires_explicit_identity_binding(self):
        """Configured names apply only within a labeled code/name pair."""
        set_config({"wrong_identity_hints": ["中信证券"]})
        profile = _a_share_profile()
        items = [
            {
                "title": "公司公告",
                "content": "证券代码：000001.SZ；证券简称：中信证券。",
                "source": "tavily",
            }
        ]
        hits = _find_wrong_identity_hits(items, profile)
        assert hits == {"中信证券"}
        set_config({"wrong_identity_hints": []})

    def test_yfinance_chinese_alias_not_flagged(self):
        """Chinese name for yfinance English profile should NOT be flagged."""
        profile = _yfinance_profile()
        items = [{"title": "002396.SZ（星网锐捷）发布公告", "source": "tavily"}]
        hits = _find_wrong_identity_hits(items, profile)
        assert "星网锐捷" not in hits

    def test_yfinance_profile_rejects_known_explicit_confusion_name(self):
        """A configured confusion name still rejects an explicit code/name pair."""
        profile = _yfinance_profile()
        items = [
            {
                "title": "公司公告",
                "content": "证券代码：002396.SZ；证券简称：恒瑞医药。",
                "source": "report",
            }
        ]
        hits = _find_wrong_identity_hits(items, profile)
        assert hits == {"恒瑞医药"}

    def test_empty_items(self):
        hits = _find_wrong_identity_hits([], _a_share_profile())
        assert hits == set()


# ---------------------------------------------------------------------------
# Integration: config-driven hints affect evaluate_and_enrich_evidence
# ---------------------------------------------------------------------------


class TestIdentityIntegration:
    def test_custom_hint_is_not_a_hard_identity_failure(self, monkeypatch):
        monkeypatch.setattr(
            "tradingagents.dataflows.evidence._run_tavily_enrichment",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr(
            "tradingagents.dataflows.evidence.analyze_news_coverage",
            lambda *args, **kwargs: NewsAdvisorResult(should_enrich=True),
        )
        set_config({
            "evidence_gate_enabled": True,
            "evidence_stop_on_fail": True,
            "wrong_identity_hints": ["中信证券"],
        })
        state = {
            "company_of_interest": "000001.SZ",
            "trade_date": "2026-05-07",
            "market_report": "market ok",
            "sentiment_report": "",
            "news_report": "### 中信证券研报\n000001.SZ 中信证券推荐买入\nLink: https://example.com/1\n",
            "fundamentals_report": "fundamentals ok",
            "canonical_company_profile": _a_share_profile(),
        }

        result = evaluate_and_enrich_evidence(state)

        assert result["evidence_status"] == "LOW_CONFIDENCE"
        assert "身份冲突" not in result["evidence_report"]
        set_config({"wrong_identity_hints": []})
