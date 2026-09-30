"""Offline contracts for the official-exchange A-share adapters.

Every test monkeypatches the HTTP layer: no live network, no real exchange.
The contracts under test are the *degradation* rules -- an unpublished month, a
short page, a changed row structure, or a drifted uid mapping must raise a typed
``ChinaDataUnavailableError`` rather than produce an empty/partial table.
"""

from __future__ import annotations

import calendar
import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from tradingagents.dataflows import a_share_official
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _Response:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(
        self,
        payload: object = None,
        *,
        content: bytes = b"",
        status_code: int = 200,
        url: str = "https://example.invalid/",
    ) -> None:
        self._payload = payload
        self.content = content
        self.status_code = status_code
        self.url = url

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _report_frame(report: str) -> pd.DataFrame:
    """Parse the CSV body out of a rendered adapter report."""
    return pd.read_csv(io.StringIO(report.split("\n\n", 1)[1]))


def _calendar_payload(
    year: int = 2026,
    month: int = 9,
    *,
    drop_day: int | None = None,
    bad_flag_day: int | None = None,
    omit_jyrq_day: int | None = None,
) -> dict:
    last = calendar.monthrange(year, month)[1]
    data = []
    for day in range(1, last + 1):
        if day == drop_day:
            continue
        current = date(year, month, day)
        record: dict[str, object] = {
            "jyrq": current.isoformat(),
            "jybz": "1" if current.weekday() < 5 else "0",
        }
        if day == bad_flag_day:
            record["jybz"] = "2"
        if day == omit_jyrq_day:
            record.pop("jyrq")
        data.append(record)
    return {"data": data}


def _patch_get(monkeypatch: pytest.MonkeyPatch, response, calls: list | None = None):
    def fake_get(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        return response if not callable(response) else response(url, **kwargs)

    monkeypatch.setattr(a_share_official.requests, "get", fake_get)


# --------------------------------------------------------------------------- #
# Trading calendar
# --------------------------------------------------------------------------- #
def test_trading_calendar_covers_every_calendar_day(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, _Response(_calendar_payload()), calls)

    report = a_share_official.get_a_share_trading_calendar(2026, 9)

    url, kwargs = calls[0]
    assert url == a_share_official.SZSE_CALENDAR_URL
    assert kwargs["params"] == {"month": "2026-9"}
    assert kwargs["timeout"][1] <= 20  # explicit bounded read timeout

    frame = _report_frame(report)
    expected = {
        date(2026, 9, day).isoformat() for day in range(1, calendar.monthrange(2026, 9)[1] + 1)
    }
    assert set(frame["date"]) == expected
    assert len(frame) == 30
    assert "# Total records: 30" in report
    # jybz is carried through as a real session flag, not inferred from the weekday.
    assert set(frame["is_open"]) == {True, False}


def test_trading_calendar_missing_day_raises(monkeypatch):
    _patch_get(monkeypatch, _Response(_calendar_payload(drop_day=15)))

    with pytest.raises(ChinaDataUnavailableError, match="日期不完整"):
        a_share_official.get_a_share_trading_calendar(2026, 9)


def test_trading_calendar_misaligned_month_raises(monkeypatch):
    _patch_get(monkeypatch, _Response(_calendar_payload(year=2026, month=8)))

    with pytest.raises(ChinaDataUnavailableError, match="月份错位或日期不完整"):
        a_share_official.get_a_share_trading_calendar(2026, 9)


def test_trading_calendar_rejects_non_binary_jybz(monkeypatch):
    _patch_get(monkeypatch, _Response(_calendar_payload(bad_flag_day=3)))

    with pytest.raises(ChinaDataUnavailableError, match="日历字段异常"):
        a_share_official.get_a_share_trading_calendar(2026, 9)


def test_trading_calendar_rejects_missing_jyrq(monkeypatch):
    _patch_get(monkeypatch, _Response(_calendar_payload(omit_jyrq_day=4)))

    with pytest.raises(ChinaDataUnavailableError, match="日历字段异常"):
        a_share_official.get_a_share_trading_calendar(2026, 9)


def test_trading_calendar_unpublished_month_raises(monkeypatch):
    _patch_get(monkeypatch, _Response({"data": []}))

    with pytest.raises(ChinaDataUnavailableError, match="尚未返回该月日历"):
        a_share_official.get_a_share_trading_calendar(2026, 12)


def test_trading_calendar_rejects_bad_arguments(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("HTTP must not be attempted for invalid arguments")

    monkeypatch.setattr(a_share_official.requests, "get", explode)

    for year, month in (("2026", 9), (2026, 0), (2026, 13), (True, 9), (2026, None)):
        with pytest.raises(ValueError):
            a_share_official.get_a_share_trading_calendar(year, month)


def test_trading_calendar_http_and_body_failures_are_typed(monkeypatch):
    _patch_get(monkeypatch, _Response(None, status_code=502))
    with pytest.raises(ChinaDataUnavailableError, match="HTTP 502"):
        a_share_official.get_a_share_trading_calendar(2026, 9)

    _patch_get(monkeypatch, _Response(None, content=b"<html>error</html>"))
    with pytest.raises(ChinaDataUnavailableError, match="不是 JSON"):
        a_share_official.get_a_share_trading_calendar(2026, 9)


# --------------------------------------------------------------------------- #
# Margin trading (exchange whitelist, page totals, code segments)
# --------------------------------------------------------------------------- #
def _sh_payload(day: str = "20260918", rows: list | None = None, total: str | None = None) -> dict:
    if rows is None:
        rows = [
            {
                "opDate": day,
                "stockCode": "600519",
                "securityAbbr": "贵州茅台",
                "rzye": "1,234.50",
                "rzmre": "100",
                "rqylje": "",
                "rqyl": "50",
                "rqmcl": "10",
            },
            {
                "opDate": day,
                "stockCode": "601318",
                "securityAbbr": "中国平安",
                "rzye": "2000",
                "rzmre": "200",
                "rqylje": "300.5",
                "rqyl": "60",
                "rqmcl": "20",
            },
        ]
    return {"pageHelp": {"data": rows, "total": total if total is not None else str(len(rows))}}


def test_margin_sh_happy_path(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, _Response(_sh_payload()), calls)

    report = a_share_official.get_a_share_margin_trading_backup("2026-09-18", "sh")

    url, kwargs = calls[0]
    assert url == a_share_official.SSE_MARGIN_URL
    assert kwargs["params"]["detailsDate"] == "20260918"
    assert kwargs["params"]["pageHelp.pageSize"] == 5000
    assert kwargs["timeout"][1] <= 20

    frame = _report_frame(report)
    assert set(frame["code"]) == {600519, 601318}
    assert frame.loc[frame["code"] == 600519, "margin_balance"].iloc[0] == 1234.5
    # A blank 融券余额 is absent data, not a fabricated zero.
    assert pd.isna(frame.loc[frame["code"] == 600519, "short_balance"].iloc[0])
    assert frame.loc[frame["code"] == 601318, "short_balance"].iloc[0] == 300.5
    assert "# Total records: 2" in report


def test_margin_sh_page_total_must_match_rows(monkeypatch):
    _patch_get(monkeypatch, _Response(_sh_payload(total="5000")))

    with pytest.raises(ChinaDataUnavailableError, match="分页不完整"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH")


def test_margin_sh_rejects_non_numeric_total(monkeypatch):
    _patch_get(monkeypatch, _Response(_sh_payload(total="2 rows")))

    with pytest.raises(ChinaDataUnavailableError, match="分页总数"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH")


def test_margin_sh_rejects_date_mismatch(monkeypatch):
    _patch_get(monkeypatch, _Response(_sh_payload(day="20260917")))

    with pytest.raises(ChinaDataUnavailableError, match="日期不符"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH")


def test_margin_sh_rejects_changed_fields(monkeypatch):
    rows = _sh_payload()["pageHelp"]["data"]
    for row in rows:
        row.pop("rzye")
    _patch_get(monkeypatch, _Response(_sh_payload(rows=rows)))

    with pytest.raises(ChinaDataUnavailableError, match="字段发生变化"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH")


def test_margin_sh_rejects_unparseable_number(monkeypatch):
    rows = _sh_payload()["pageHelp"]["data"]
    rows[0]["rzye"] = "--"
    _patch_get(monkeypatch, _Response(_sh_payload(rows=rows)))

    with pytest.raises(ChinaDataUnavailableError, match="缺少必需数值"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH")


def test_margin_row_code_segment_must_match_exchange(monkeypatch):
    rows = _sh_payload()["pageHelp"]["data"]
    rows[0]["stockCode"] = "000001"  # a Shenzhen code inside the Shanghai file
    _patch_get(monkeypatch, _Response(_sh_payload(rows=rows)))

    with pytest.raises(ChinaDataUnavailableError, match="不符的证券代码"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH")


def test_margin_rejects_unsupported_exchange_and_bad_date(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("HTTP must not be attempted for invalid arguments")

    monkeypatch.setattr(a_share_official.requests, "get", explode)

    for exchange in ("BJ", "BSE", "", "SHZ"):
        with pytest.raises(ValueError, match="SH 或 SZ"):
            a_share_official.get_a_share_margin_trading_backup("2026-09-18", exchange)
    with pytest.raises(ValueError, match="trade_date"):
        a_share_official.get_a_share_margin_trading_backup("2026/09/18", "SH")


def test_margin_rejects_ticker_exchange_mismatch(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must not reach the network
        raise AssertionError("HTTP must not be attempted for an invalid ticker")

    monkeypatch.setattr(a_share_official.requests, "get", explode)

    with pytest.raises(ValueError, match="与请求的交易所不符"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH", "000001")
    with pytest.raises(ValueError, match="与请求的交易所不符"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ", "600519")
    with pytest.raises(ValueError, match="与请求的交易所不符"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ", "920982")


def test_margin_ticker_filters_the_complete_frame(monkeypatch):
    _patch_get(monkeypatch, _Response(_sh_payload()))

    report = a_share_official.get_a_share_margin_trading_backup("20260918", "SH", "600519.SH")

    frame = _report_frame(report)
    assert list(frame["code"]) == [600519]
    assert "# Total records: 1" in report
    assert "601318" not in report.split("\n\n", 1)[1]
    assert "已从完整快照中按 600519 过滤" in report


def test_margin_ticker_absent_from_complete_frame_raises(monkeypatch):
    _patch_get(monkeypatch, _Response(_sh_payload()))

    with pytest.raises(ChinaDataUnavailableError, match="不在 2026-09-18 SH 官方两融完整名单中"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SH", "600000")


def _sz_frame(*, codes: tuple[str, ...] = ("000001", "000002")) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "证券代码": list(codes),
            "证券简称": ["平安银行", "万科A"][: len(codes)],
            "融资余额(元)": ["1000", "2000"][: len(codes)],
            "融资买入额(元)": ["10", "20"][: len(codes)],
            "融券余额(元)": ["30", "40"][: len(codes)],
            "融券余量(股/份)": ["5", "6"][: len(codes)],
            "融券卖出量(股/份)": ["1", "2"][: len(codes)],
        }
    )


def _patch_excel(monkeypatch: pytest.MonkeyPatch, frame_or_error):
    def fake_read_excel(*args, **kwargs):
        if isinstance(frame_or_error, Exception):
            raise frame_or_error
        return frame_or_error.copy()

    monkeypatch.setattr(a_share_official.pd, "read_excel", fake_read_excel)


def test_margin_sz_reads_the_official_xlsx(monkeypatch):
    calls: list = []
    _patch_get(monkeypatch, _Response(content=b"xlsx-bytes"), calls)
    _patch_excel(monkeypatch, _sz_frame())

    report = a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ")

    url, kwargs = calls[0]
    assert url == a_share_official.SZSE_MARGIN_URL
    assert kwargs["params"] == {
        "SHOWTYPE": "xlsx",
        "CATALOGID": "1837_xxpl",
        "TABKEY": "tab2",
        "txtDate": "2026-09-18",
    }
    frame = _report_frame(report)
    assert set(frame["code"]) == {1, 2}
    assert frame.loc[frame["code"] == 1, "margin_balance"].iloc[0] == 1000
    assert "# Total records: 2" in report


def test_margin_sz_tolerates_header_whitespace(monkeypatch):
    frame = _sz_frame()
    frame.columns = [column.replace("(元)", " (元)") for column in frame.columns]
    _patch_get(monkeypatch, _Response(content=b"xlsx-bytes"))
    _patch_excel(monkeypatch, frame)

    report = a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ")

    assert "# Total records: 2" in report


def test_margin_sz_missing_column_raises(monkeypatch):
    _patch_get(monkeypatch, _Response(content=b"xlsx-bytes"))
    _patch_excel(monkeypatch, _sz_frame().drop(columns=["融资余额(元)"]))

    with pytest.raises(ChinaDataUnavailableError, match="官方数据列缺失"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ")


def test_margin_sz_unparseable_excel_raises(monkeypatch):
    _patch_get(monkeypatch, _Response(content=b"<html>not xlsx</html>"))
    _patch_excel(monkeypatch, ValueError("bad zip"))

    with pytest.raises(ChinaDataUnavailableError, match="可解析的 Excel"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ")


def test_margin_sz_non_valueerror_parse_failure_is_typed(monkeypatch):
    # openpyxl/zipfile raise BadZipFile, which is not an OSError: the adapter
    # must still degrade to a typed error instead of leaking it.
    _patch_get(monkeypatch, _Response(content=b"<html>not xlsx</html>"))
    _patch_excel(monkeypatch, zipfile.BadZipFile("file is not a zip file"))

    with pytest.raises(ChinaDataUnavailableError, match="可解析的 Excel"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ")


def test_margin_sz_row_code_segment_must_match_exchange(monkeypatch):
    _patch_get(monkeypatch, _Response(content=b"xlsx-bytes"))
    _patch_excel(monkeypatch, _sz_frame(codes=("600519",)))

    with pytest.raises(ChinaDataUnavailableError, match="不符的证券代码"):
        a_share_official.get_a_share_margin_trading_backup("2026-09-18", "SZ")


# --------------------------------------------------------------------------- #
# 上证e互动 (SSE e-interaction)
# --------------------------------------------------------------------------- #
_QUESTION_BLOCK = (
    '<div class="m_feed_detail m_qa_detail">\n'
    '  <div class="m_feed_txt"><a href="/company/600519">:{name}({code})</a>{question}</div>\n'
    '  <div class="m_feed_from"><span>{ask_time}</span></div>\n'
    '  <span rel="face" title="{asker}"></span>\n'
    "</div>\n"
)
_ANSWER_BLOCK = (
    '<div class="m_feed_detail m_qa">\n'
    '  <div class="m_feed_txt">{answer}</div>\n'
    '  <div class="m_feed_from"><span>{answer_time}</span></div>\n'
    "</div>\n"
)


def _feed_item(
    item_id: str,
    *,
    code: str = "600519",
    name: str = "贵州茅台",
    question: str = "分红政策如何？",
    asker: str = "投资者A",
    ask_time: str = "2026年09月18日 10:30",
    answer: str | None = "详见公告。",
    answer_time: str = "2026年09月18日 15:00",
) -> str:
    body = (
        f'<div class="m_feed_item" id="item-{item_id}">\n'
        + _QUESTION_BLOCK.format(
            name=name,
            code=code,
            question=question,
            ask_time=ask_time,
            asker=asker,
        )
    )
    if answer is not None:
        body += _ANSWER_BLOCK.format(answer=answer, answer_time=answer_time)
    return body + "</div>\n"


def _feed(*items: str, note: str | None = None) -> str:
    body = "<html><body>" + "".join(items)
    if note:
        body += f'<div class="m_feed_note">{note}</div>'
    return body + "</body></html>"


_COMPANY_PAGES: dict[int, list[tuple[str, str]]] = {
    1: [(f"6000{index:02d}", str(index)) for index in range(0, 32)],
    2: [(f"6005{index:02d}", str(index)) for index in range(0, 32)],
}


def _company_content(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return f"<html><body>{a_share_official._SSE_COMPANY_END}</body></html>"
    return "<html><body>" + "".join(
        f'<a href="/company/{uid}" uid="{uid}">'
        f'<img src="/images/company/{code}.png"></a>'
        for code, uid in pairs
    ) + "</body></html>"


class _SseSite:
    """Fake platform: company list plus a scripted feed response."""

    def __init__(self, feed_text: str) -> None:
        self.feed_text = feed_text
        self.company_calls: list[int] = []
        self.feed_calls: list[dict] = []

    def get(self, url, **kwargs):
        self.feed_calls.append({"url": url, **kwargs})
        return _Response(None, content=self.feed_text.encode("utf-8"))

    def post(self, url, **kwargs):
        if url.endswith("/allcompany.do"):
            page = int(kwargs["data"]["page"])
            self.company_calls.append(page)
            content = _company_content(_COMPANY_PAGES.get(page, []))
            return _Response({"content": content}, url=url)
        self.feed_calls.append({"url": url, **kwargs})
        return _Response(None, content=self.feed_text.encode("utf-8"))


def _install_sse(monkeypatch: pytest.MonkeyPatch, site: _SseSite) -> _SseSite:
    monkeypatch.setattr(a_share_official.requests, "get", site.get)
    monkeypatch.setattr(a_share_official.requests, "post", site.post)
    monkeypatch.setattr(a_share_official, "_SSE_UID_CACHE", {})
    monkeypatch.setattr(a_share_official, "_SSE_COMPANY_PAGES", {})
    return site


def test_sse_e_interaction_validates_kind_and_paging(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("HTTP must not be attempted for invalid arguments")

    monkeypatch.setattr(a_share_official.requests, "get", explode)
    monkeypatch.setattr(a_share_official.requests, "post", explode)

    with pytest.raises(ValueError, match="kind"):
        a_share_official.get_a_share_sse_e_interaction(kind="latest")
    for page, page_size in ((0, 10), (1, 0), (1, 51), (1, -1)):
        with pytest.raises(ValueError, match="page"):
            a_share_official.get_a_share_sse_e_interaction(page=page, page_size=page_size)


def test_sse_e_interaction_rejects_non_shanghai_codes(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("HTTP must not be attempted for a non-Shanghai code")

    monkeypatch.setattr(a_share_official.requests, "get", explode)
    monkeypatch.setattr(a_share_official.requests, "post", explode)

    for ticker in ("000001", "000001.SZ", "920982", "430047"):
        with pytest.raises(ValueError, match="巨潮互动易 cninfo"):
            a_share_official.get_a_share_sse_e_interaction(ticker=ticker)


def test_sse_e_interaction_market_wide(monkeypatch):
    site = _install_sse(monkeypatch, _SseSite(_feed(_feed_item("1"), _feed_item("2", code="600000"))))

    report = a_share_official.get_a_share_sse_e_interaction(kind="questions", page=2, page_size=5)

    call = site.feed_calls[0]
    assert call["url"] == a_share_official.SSE_E_BASE + "/ajax/feeds.do"
    assert call["params"] == {"type": 10, "pageSize": 5, "lastid": -1, "show": 1, "page": 2}
    assert call["timeout"][1] <= 20
    assert "# Total records: 2" in report
    frame = _report_frame(report)
    assert list(frame["id"]) == [1, 2]
    assert frame["question_time"].iloc[0] == "2026-09-18 10:30"
    assert frame["answer_time"].iloc[0] == "2026-09-18 15:00"
    assert frame["answer"].iloc[0] == "详见公告。"


def test_sse_e_interaction_company_query_uses_cached_uid(monkeypatch):
    site = _install_sse(monkeypatch, _SseSite(_feed(_feed_item("9"))))

    report = a_share_official.get_a_share_sse_e_interaction(ticker="600519.SH")
    first_company_calls = list(site.company_calls)
    assert first_company_calls, "the company uid must be resolved from the company list"
    assert "# Total records: 1" in report

    post_call = [call for call in site.feed_calls if str(call["url"]).endswith("userfeeds.do")][0]
    assert post_call["data"]["typeCode"] == "company"
    assert post_call["data"]["type"] == 11
    assert post_call["data"]["uid"] == a_share_official._SSE_UID_CACHE["600519"]
    assert post_call["data"]["page"] == 1

    # Second call: the uid (and every visited company page) is cached.
    a_share_official.get_a_share_sse_e_interaction(ticker="600519")
    assert site.company_calls == first_company_calls


def test_sse_e_interaction_uid_missing_raises(monkeypatch):
    site = _install_sse(monkeypatch, _SseSite(_feed(_feed_item("9"))))

    with pytest.raises(ChinaDataUnavailableError, match="没有 600999"):
        a_share_official.get_a_share_sse_e_interaction(ticker="600999")
    assert site.company_calls


def test_sse_e_interaction_zero_rows_without_empty_marker_raises(monkeypatch):
    _install_sse(monkeypatch, _SseSite(_feed()))

    with pytest.raises(ChinaDataUnavailableError, match="没有问答也没有「暂无」提示"):
        a_share_official.get_a_share_sse_e_interaction()


def test_sse_e_interaction_zero_rows_with_empty_marker_is_a_fact(monkeypatch):
    _install_sse(monkeypatch, _SseSite(_feed(note="暂时没有问答内容")))

    report = a_share_official.get_a_share_sse_e_interaction(page=9)

    assert "# Total records: 0" in report
    assert "本页确认没有数据" in report
    frame = _report_frame(report)
    assert frame.empty


def test_sse_e_interaction_wrong_company_guard(monkeypatch):
    _install_sse(monkeypatch, _SseSite(_feed(_feed_item("3", code="600000"))))

    with pytest.raises(ChinaDataUnavailableError, match="其他公司的问答"):
        a_share_official.get_a_share_sse_e_interaction(ticker="600519")


def test_sse_e_interaction_structure_changes_raise(monkeypatch):
    broken_id = _feed('<div class="m_feed_item" id="item-abc"></div>')
    _install_sse(monkeypatch, _SseSite(broken_id))
    with pytest.raises(ChinaDataUnavailableError, match="不是数字"):
        a_share_official.get_a_share_sse_e_interaction()

    item = _feed_item("4").replace("2026年09月18日 10:30", "昨天")
    _install_sse(monkeypatch, _SseSite(_feed(item)))
    with pytest.raises(ChinaDataUnavailableError, match="无法解析问题或时间|提问时间认不出"):
        a_share_official.get_a_share_sse_e_interaction()


def test_sse_e_interaction_company_list_schema_change_raises(monkeypatch):
    site = _install_sse(monkeypatch, _SseSite(_feed(_feed_item("9"))))

    def fake_post(url, **kwargs):
        if url.endswith("/allcompany.do"):
            site.company_calls.append(int(kwargs["data"]["page"]))
            return _Response({"unexpected": "shape"}, url=url)
        return site.post(url, **kwargs)

    monkeypatch.setattr(a_share_official.requests, "post", fake_post)

    with pytest.raises(ChinaDataUnavailableError, match="没有 content 字符串"):
        a_share_official.get_a_share_sse_e_interaction(ticker="600519")


def test_sse_e_interaction_http_failure_is_typed(monkeypatch):
    def fake_post(url, **kwargs):
        return _Response(None, status_code=503, url=url)

    monkeypatch.setattr(a_share_official.requests, "post", fake_post)
    monkeypatch.setattr(a_share_official, "_SSE_UID_CACHE", {})
    monkeypatch.setattr(a_share_official, "_SSE_COMPANY_PAGES", {})

    with pytest.raises(ChinaDataUnavailableError, match="HTTP 503"):
        a_share_official.get_a_share_sse_e_interaction(ticker="600519")
