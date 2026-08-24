"""Contract tests for the keyless EastMoney company-news adapter."""

from __future__ import annotations

import pytest

from tradingagents.dataflows import eastmoney_news
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeClient:
    def __init__(self, text: str | list[str]):
        self._texts = [text] if isinstance(text, str) else list(text)
        self.calls: list[dict] = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers})
        return _FakeResponse(self._texts.pop(0))


def _jsonp(payload: str) -> str:
    return f"jQuery_news({payload})"


def test_eastmoney_news_parses_articles_and_strips_tags():
    import json

    payload = json.dumps(
        {
            "result": {
                "totalPage": 1,
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
    assert result["coverage"]["completeness"] == "unavailable"
    assert result["coverage"]["pagination_exhausted"] is True
    assert result["coverage"]["degradations"] == ["no_usable_items"]


def test_eastmoney_news_raises_on_malformed_jsonp():
    client = _FakeClient("not a jsonp response")

    with pytest.raises(ChinaDataUnavailableError):
        eastmoney_news.get_news_eastmoney("600519", "2026-01-01", "2026-02-01", client=client)


def test_eastmoney_news_paginates_filters_deduplicates_and_reports_coverage():
    import json

    page_one = {
        "result": {
            "totalPage": 2,
            "cmsArticleWebOld": [
                {
                    "title": "未来消息",
                    "date": "2026-08-05 09:00:00",
                    "url": "https://example.com/future",
                },
                {
                    "title": "窗口结束消息",
                    "date": "2026-08-04 09:00:00",
                    "url": "https://example.com/end",
                },
            ],
        }
    }
    page_two = {
        "result": {
            "totalPage": 2,
            "cmsArticleWebOld": [
                {
                    "title": "窗口内消息",
                    "date": "2026-07-20 09:00:00",
                    "url": "https://example.com/mid",
                },
                {
                    "title": "窗口内消息",
                    "date": "2026-07-20 09:00:00",
                    "url": "https://example.com/mid",
                },
                {
                    "title": "过旧消息",
                    "date": "2026-06-30 09:00:00",
                    "url": "https://example.com/old",
                },
            ],
        }
    }
    client = _FakeClient(
        [_jsonp(json.dumps(page_one)), _jsonp(json.dumps(page_two))]
    )

    result = eastmoney_news.get_news_eastmoney(
        "600519",
        "2026-07-01",
        "2026-08-04",
        client=client,
        max_pages=3,
    )

    assert [item["title"] for item in result["items"]] == [
        "窗口结束消息",
        "窗口内消息",
    ]
    requested_pages = [
        json.loads(call["params"]["param"])["param"]["cmsArticleWebOld"]["pageIndex"]
        for call in client.calls
    ]
    assert requested_pages == [1, 2]
    assert result["coverage"] == {
        "capability": "company_event_window",
        "source_id": "eastmoney.company_news",
        "requested_start": "2026-07-01",
        "requested_end": "2026-08-04",
        "actual_start": "2026-07-20",
        "actual_end": "2026-08-04",
        "item_count": 2,
        "page_count": 2,
        "pagination_exhausted": True,
        "completeness": "partial",
        "sources": ["eastmoney.company_news"],
        "degradations": ["requested_window_not_fully_observed"],
        "as_of": "2026-08-04",
    }


def test_eastmoney_news_marks_budget_truncation_partial():
    import json

    pages = []
    for page_number, published in ((1, "2026-08-04"), (2, "2026-07-01")):
        pages.append(
            _jsonp(
                json.dumps(
                    {
                        "result": {
                            "totalPage": 5,
                            "cmsArticleWebOld": [
                                {
                                    "title": f"消息{page_number}",
                                    "date": published,
                                    "url": f"https://example.com/{page_number}",
                                }
                            ],
                        }
                    }
                )
            )
        )
    client = _FakeClient(pages)

    result = eastmoney_news.get_news_eastmoney(
        "600519",
        "2026-07-01",
        "2026-08-04",
        client=client,
        max_pages=2,
    )

    coverage = result["coverage"]
    assert coverage["page_count"] == 2
    assert coverage["pagination_exhausted"] is False
    assert coverage["completeness"] == "partial"
    assert coverage["degradations"] == ["pagination_budget_exhausted"]


def test_eastmoney_news_is_complete_only_when_boundaries_are_observed():
    import json

    payload = json.dumps(
        {
            "result": {
                "totalPage": 1,
                "cmsArticleWebOld": [
                    {"title": "结束", "date": "2026-08-04", "url": "end"},
                    {"title": "开始", "date": "2026-07-01", "url": "start"},
                ],
            }
        }
    )

    result = eastmoney_news.get_news_eastmoney(
        "600519",
        "2026-07-01",
        "2026-08-04",
        client=_FakeClient(_jsonp(payload)),
    )

    assert result["coverage"]["completeness"] == "complete"
    assert result["coverage"]["degradations"] == []


def test_eastmoney_news_invalid_date_prevents_false_complete_coverage():
    import json

    payload = json.dumps(
        {
            "result": {
                "totalPage": 1,
                "cmsArticleWebOld": [
                    {"title": "结束", "date": "2026-08-04", "url": "end"},
                    {"title": "开始", "date": "2026-07-01", "url": "start"},
                    {"title": "日期未知", "date": "", "url": "unknown"},
                ],
            }
        }
    )

    result = eastmoney_news.get_news_eastmoney(
        "600519",
        "2026-07-01",
        "2026-08-04",
        client=_FakeClient(_jsonp(payload)),
    )

    assert [item["title"] for item in result["items"]] == ["结束", "开始"]
    assert result["coverage"]["completeness"] == "partial"
    assert result["coverage"]["degradations"] == [
        "invalid_or_missing_published_at"
    ]
