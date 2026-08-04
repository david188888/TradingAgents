"""Contract tests for the keyless EastMoney company-news adapter."""

from __future__ import annotations

import pytest

from tradingagents.dataflows import eastmoney_news
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeClient:
    def __init__(self, text: str):
        self._text = text
        self.calls: list[dict] = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers})
        return _FakeResponse(self._text)


def _jsonp(payload: str) -> str:
    return f"jQuery_news({payload})"


def test_eastmoney_news_parses_articles_and_strips_tags():
    import json

    payload = json.dumps(
        {
            "result": {
                "cmsArticleWebOld": [
                    {
                        "title": "长鑫科技<b>上市</b>",
                        "content": "<p>今日上市交易</p>",
                        "date": "2026-07-27 16:31:00",
                        "mediaName": "上交所发布",
                        "url": "https://example.com/a",
                    }
                ]
            }
        },
        ensure_ascii=False,
    )
    client = _FakeClient(_jsonp(payload))

    result = eastmoney_news.get_news_eastmoney(
        "688825", "2026-07-01", "2026-08-04", client=client
    )

    assert result["source"] == "eastmoney"
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["title"] == "长鑫科技上市"
    assert item["content"] == "今日上市交易"
    assert item["publisher"] == "上交所发布"
    assert item["url"] == "https://example.com/a"
    # The search keyword must be the bare 6-digit code, not a suffixed form.
    inner = json.loads(client.calls[0]["params"]["param"])
    assert inner["keyword"] == "688825"
    assert inner["type"] == ["cmsArticleWebOld"]


def test_eastmoney_news_returns_empty_items_when_no_articles():
    import json

    payload = json.dumps({"result": {"cmsArticleWebOld": []}})
    client = _FakeClient(_jsonp(payload))

    result = eastmoney_news.get_news_eastmoney("600519", "2026-01-01", "2026-02-01", client=client)

    assert result["source"] == "eastmoney"
    assert result["items"] == []


def test_eastmoney_news_raises_on_malformed_jsonp():
    client = _FakeClient("not a jsonp response")

    with pytest.raises(ChinaDataUnavailableError):
        eastmoney_news.get_news_eastmoney("600519", "2026-01-01", "2026-02-01", client=client)
