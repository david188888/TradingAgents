import json

import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.tavily_news import get_global_news_tavily, get_news_tavily


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeStatusResponse(FakeResponse):
    def __init__(self, payload, status_code):
        super().__init__(payload)
        self.status_code = status_code


def test_tavily_news_uses_budget_defaults_and_logs_raw_response(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Apple earnings preview",
                        "url": "https://example.com/apple",
                        "content": "Apple earnings are in focus.",
                        "score": 0.91,
                    }
                ],
                "usage": {"credits": 1},
                "request_id": "req-123",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config(
        {
            "results_dir": str(tmp_path),
            "tavily_search_depth": "basic",
            "tavily_max_results": 5,
            "tavily_topic": "news",
            "tavily_include_raw_content": "false",
            "tavily_include_answer": False,
            "tavily_include_images": False,
            "tavily_auto_parameters": "false",
        }
    )

    result = get_news_tavily("AAPL", "2026-01-01", "2026-01-31")

    assert captured["json"]["search_depth"] == "basic"
    assert captured["json"]["query"] == '"AAPL" stock market news earnings revenue guidance analyst rating'
    assert captured["json"]["max_results"] == 5
    assert captured["json"]["topic"] == "news"
    assert captured["json"]["include_raw_content"] is False
    assert captured["json"]["include_answer"] is False
    assert captured["json"]["include_images"] is False
    assert captured["json"]["auto_parameters"] is False
    assert result["items"][0]["source"] == "tavily"
    assert result["items"][0]["publisher"] == "example.com"

    raw_files = list((tmp_path / "AAPL" / "2026-01-31" / "data").glob("tavily_get_news_*.json"))
    assert len(raw_files) == 1
    saved = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert saved["usage"] == {"credits": 1}
    assert saved["request_id"] == "req-123"


def test_tavily_news_builds_a_share_query_and_domain_filters(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "公告更新",
                        "url": "https://www.cninfo.com.cn/new/disclosure",
                        "content": "公司发布经营公告。",
                    }
                ],
                "request_id": "req-a-share",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config(
        {
            "results_dir": str(tmp_path),
            "tavily_include_domains": "cninfo.com.cn",
            "tavily_company_include_domains": ["szse.cn", "cninfo.com.cn"],
            "tavily_company_exclude_domains": ["example.com"],
        }
    )

    result = get_news_tavily("002396.SZ", "2026-01-01", "2026-01-31")

    assert '"002396.SZ"' in captured["json"]["query"]
    assert '"002396"' in captured["json"]["query"]
    assert "股票 公告 业绩 财报" in captured["json"]["query"]
    assert captured["json"]["include_domains"] == ["cninfo.com.cn", "szse.cn"]
    assert captured["json"]["exclude_domains"] == ["example.com"]
    assert result["items"][0]["title"] == "公告更新"


def test_tavily_news_falls_back_to_finance_topic_when_news_is_empty(monkeypatch, tmp_path):
    captured_topics = []

    def fake_post(url, headers, json, timeout):
        captured_topics.append(json["topic"])
        if json["topic"] == "news":
            return FakeResponse({"results": [], "request_id": "req-empty"})
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Apple analyst rating update",
                        "url": "https://example.com/rating",
                        "content": "Analyst sentiment shifted.",
                        "score": 0.72,
                    }
                ],
                "request_id": "req-finance",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config({"results_dir": str(tmp_path), "tavily_company_fallback_topic": "finance"})

    result = get_news_tavily("AAPL", "2026-01-01", "2026-01-31")

    assert captured_topics == ["news", "finance"]
    assert result["payload"]["topic"] == "finance"
    assert result["items"][0]["title"] == "Apple analyst rating update"


def test_tavily_news_falls_back_to_finance_topic_when_news_topic_is_invalid(monkeypatch, tmp_path):
    captured_topics = []

    def fake_post(url, headers, json, timeout):
        captured_topics.append(json["topic"])
        if json["topic"] == "news":
            return FakeStatusResponse({"error": "invalid topic"}, 400)
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Apple finance result",
                        "url": "https://example.com/finance",
                        "content": "Financial result.",
                    }
                ],
                "request_id": "req-finance-after-invalid",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config({"results_dir": str(tmp_path), "tavily_company_fallback_topic": "finance"})

    result = get_news_tavily("AAPL", "2026-01-01", "2026-01-31")

    assert captured_topics == ["news", "finance"]
    assert result["payload"]["topic"] == "finance"
    assert result["items"][0]["title"] == "Apple finance result"


def test_tavily_news_score_filter_discards_low_relevance_when_possible(monkeypatch, tmp_path):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Low relevance",
                        "url": "https://example.com/low",
                        "content": "Weak match.",
                        "score": 0.2,
                    },
                    {
                        "title": "High relevance",
                        "url": "https://example.com/high",
                        "content": "Strong match.",
                        "score": 0.81,
                    },
                ],
                "request_id": "req-score",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config({"results_dir": str(tmp_path), "tavily_min_score": 0.5})

    result = get_news_tavily("AAPL", "2026-01-01", "2026-01-31")

    assert [item["title"] for item in result["items"]] == ["High relevance"]


def test_tavily_global_news_uses_default_window_and_limit_when_omitted(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Fed policy update",
                        "url": "https://example.com/macro",
                        "content": "Markets track central bank policy.",
                    }
                ],
                "request_id": "req-global",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config({"results_dir": str(tmp_path)})

    result = get_global_news_tavily("2026-01-31")

    assert captured["json"]["topic"] == default_config.DEFAULT_CONFIG["tavily_global_news_topic"]
    assert captured["json"]["start_date"] == "2026-01-24"
    assert captured["json"]["end_date"] == "2026-01-31"
    assert captured["json"]["max_results"] == default_config.DEFAULT_CONFIG["tavily_max_results"]
    assert result["items"][0]["title"] == "Fed policy update"


def test_tavily_global_news_falls_back_to_finance_when_news_is_empty(monkeypatch, tmp_path):
    captured_topics = []

    def fake_post(url, headers, json, timeout):
        captured_topics.append(json["topic"])
        if json["topic"] == "news":
            return FakeResponse({"results": [], "request_id": "req-global-empty"})
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "Macro market update",
                        "url": "https://example.com/global",
                        "content": "Markets react to policy and earnings.",
                    }
                ],
                "request_id": "req-global-finance",
            }
        )

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr("tradingagents.dataflows.tavily_news.requests.post", fake_post)
    set_config({"results_dir": str(tmp_path), "tavily_global_fallback_topic": "finance"})

    result = get_global_news_tavily("2026-01-31")

    assert captured_topics == ["news", "finance"]
    assert result["payload"]["topic"] == "finance"
    assert result["items"][0]["title"] == "Macro market update"


def test_news_aggregation_curates_and_deduplicates_sources(monkeypatch):
    monkeypatch.setattr(
        interface,
        "get_vendor",
        lambda category, method=None: "tavily,yfinance,alpha_vantage",
    )
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "tavily": lambda *args, **kwargs: {
                "source": "tavily",
                "items": [
                    {
                        "title": "Apple earnings preview",
                        "url": "https://example.com/apple",
                        "content": "Tavily summary.",
                        "published": "2026-01-30",
                        "source": "tavily",
                    }
                ],
            },
            "yfinance": lambda *args, **kwargs: (
                "## AAPL News\n\n"
                "### Apple earnings preview (source: Yahoo Finance)\n"
                "Duplicate summary.\n"
                "Link: https://example.com/apple\n\n"
                "### Apple supplier update (source: Yahoo Finance)\n"
                "Supplier summary.\n"
                "Link: https://example.com/supplier\n"
            ),
            "alpha_vantage": lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("alpha unavailable")
            ),
        },
    )
    set_config({"news_curator_max_items": 10})

    result = interface.route_to_vendor("get_news", "AAPL", "2026-01-01", "2026-01-31")

    assert "Curated News Package" in result
    assert "Sources used: tavily, yfinance" in result
    assert result.count("Apple earnings preview") == 1
    assert "Apple supplier update" in result
    assert "alpha_vantage: alpha unavailable" in result


def test_news_aggregation_returns_readable_missing_status(monkeypatch):
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "tavily,yfinance")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "tavily": lambda *args, **kwargs: {"source": "tavily", "items": []},
            "yfinance": lambda *args, **kwargs: "No news found for AAPL",
        },
    )

    result = interface.route_to_vendor("get_news", "AAPL", "2026-01-01", "2026-01-31")

    assert "No curated news found" in result
    assert "Tavily returned no results" in result
    assert "No news found for AAPL" in result


def test_news_aggregation_treats_error_strings_as_source_failures(monkeypatch):
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "default")
    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "tavily": lambda *args, **kwargs: {
                "source": "tavily",
                "items": [
                    {
                        "title": "Apple AI investment",
                        "url": "https://example.com/apple-ai",
                        "content": "Tavily summary.",
                    }
                ],
            },
            "yfinance": lambda *args, **kwargs: "Error fetching news for AAPL: rate limited",
            "alpha_vantage": lambda *args, **kwargs: "No news found for AAPL",
        },
    )

    result = interface.route_to_vendor("get_news", "AAPL", "2026-01-01", "2026-01-31")

    assert "Sources used: tavily" in result
    assert "yfinance: Error fetching news for AAPL: rate limited" in result
    assert "alpha_vantage: No news found for AAPL" in result
    assert "source: yfinance" not in result
