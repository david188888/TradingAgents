"""Contracts for safe, source-labelled A-share specialty capabilities."""

from __future__ import annotations

import pytest

from tradingagents.dataflows.china_data import ChinaDataUnavailableError
from tradingagents.dataflows.china_specialty import (
    AnnouncementRecord,
    EastMoneyAnnouncementFallback,
    SSEAnnouncementProvider,
    get_a_share_exchange_announcements,
)


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return self.response


class _Provider:
    def __init__(self, name: str, records: list[AnnouncementRecord] | Exception) -> None:
        self.name = name
        self.records = records
        self.calls = 0

    def fetch(self, *_args, **_kwargs):
        self.calls += 1
        if isinstance(self.records, Exception):
            raise self.records
        return self.records


def test_sse_contract_uses_official_endpoint_and_returns_source_labelled_records():
    session = _Session(
        _Response(200, {"result": [{"TITLE": "关于董事会决议的公告", "SSEDATE": "2026-07-20", "URL": "https://sse.test/a.pdf", "ARTICLE_CODE": "x1"}]})
    )
    provider = SSEAnnouncementProvider(session=session)

    records = provider.fetch("600519", start_date="2026-07-01", end_date="2026-07-20")

    assert records == [
        AnnouncementRecord(
            title="关于董事会决议的公告",
            published_at="2026-07-20",
            source_provider="sse",
            source_uri="https://sse.test/a.pdf",
            announcement_id="x1",
        )
    ]
    assert session.calls[0]["params"]["productId"] == "600519"
    assert "sse.com.cn" in str(session.calls[0]["url"])


def test_exchange_failure_uses_explicit_keyless_public_fallback():
    official = _Provider("sse", ChinaDataUnavailableError("endpoint changed"))
    fallback = _Provider(
        "eastmoney",
        [AnnouncementRecord("补充公告", "2026-07-19", "eastmoney", announcement_id="em-1")],
    )

    report = get_a_share_exchange_announcements("600519", providers=(official, fallback))

    assert official.calls == 1
    assert fallback.calls == 1
    assert "# Source: eastmoney" in report
    assert "补充公告" in report
    assert "em-1" in report


def test_all_announcement_providers_fail_with_typed_degradable_error():
    with pytest.raises(ChinaDataUnavailableError, match="No announcement source available"):
        get_a_share_exchange_announcements(
            "600519",
            providers=(
                _Provider("sse", ChinaDataUnavailableError("gone")),
                _Provider("eastmoney", ChinaDataUnavailableError("empty")),
            ),
        )


def test_eastmoney_public_fallback_preserves_absent_uri_instead_of_constructing_one(monkeypatch):
    import tradingagents.dataflows.china_specialty as specialty

    monkeypatch.setattr(
        specialty,
        "em_get",
        lambda *_args, **_kwargs: {"result": {"data": [{"TITLE": "无链接公告", "NOTICE_DATE": "2026-07-18", "ARTICLE_CODE": "a-1"}]}},
    )

    records = EastMoneyAnnouncementFallback().fetch("000001")

    assert records[0].source_uri is None
    assert records[0].announcement_id == "a-1"


def test_szse_announcement_prepends_cdn_prefix_to_attach_path():
    from tradingagents.dataflows.china_specialty import _record_from_mapping

    record = _record_from_mapping(
        {"title": "关于股份回购的公告", "publishTime": "2026-07-20", "attachPath": "/disc/123/ann.pdf"},
        "szse",
    )

    assert record.source_uri == "https://disc.static.szse.cn/download/disc/123/ann.pdf"
    assert record.title == "关于股份回购的公告"
    assert record.source_provider == "szse"


def test_eastmoney_announcement_does_not_prepend_szse_cdn_prefix():
    from tradingagents.dataflows.china_specialty import _record_from_mapping

    # EastMoney rows carry their own absolute URL; the SZSE CDN prefix must
    # not apply to a non-szse provider even when a URL field is present.
    record = _record_from_mapping(
        {"TITLE": "公告", "NOTICE_DATE": "2026-07-20", "URL": "https://pdf.dfcfw.com/x.pdf"},
        "eastmoney",
    )

    assert record.source_uri == "https://pdf.dfcfw.com/x.pdf"


def test_cninfo_announcement_searchkey_uses_server_side_title_search_without_highlight(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from tradingagents.dataflows import china_specialty

    published_ms = int(datetime(2026, 10, 9, 12, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)
    payload = {
        "announcements": [{
            "secCode": "002130",
            "announcementTitle": "关于控股子公司增资扩股暨关联交易的进展公告",
            "announcementTime": published_ms,
            "announcementId": "a1",
            "announcementTypeName": "重大事项",
            "adjunctUrl": "",
        }],
        "totalpages": 1,
        "hasMore": False,
    }
    calls = []

    class _PostResponse:
        status_code = 200

        @staticmethod
        def json():
            return payload

    def fake_post(url, *, data, headers, timeout):
        calls.append(dict(data))
        return _PostResponse()

    monkeypatch.setattr(china_specialty.requests, "post", fake_post)
    monkeypatch.setattr(china_specialty, "_cninfo_orgid", lambda code, *, session=None: "org-x")
    text = china_specialty.get_a_share_cninfo_announcements(
        "002130.SZ", "2025-10-01", "2026-11-05", searchkey="增资扩股 进展公告")
    assert calls[0]["searchkey"] == "增资扩股 进展公告"
    assert calls[0]["isHLtitle"] == "false"
    assert "增资扩股暨关联交易的进展公告" in text
