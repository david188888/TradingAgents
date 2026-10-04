"""Offline contracts for the Sina research-report adapter.

The HTTP layer is monkeypatched (including the module-level throttle clock) so
the suite covers the source's two traps without live traffic: the fake
``没有找到相关内容`` empty page served to rapid consecutive requests, and the
numbered-row count that must agree with the parsed rows.
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pandas as pd
import pytest

from tradingagents.dataflows import sina_research
from tradingagents.dataflows.china_data import ChinaDataUnavailableError

_UNTERMINATED_TABLE = '<table id="tb_01"><tr><th>序号</th><th>标题</th><th>研究员</th></tr>'
_EMPTY_PAGE = (
    '<html><body><table id="tb_01"><tr><th>研究员</th></tr></table>'
    "<p>没有找到相关内容</p></body></html>"
)


class _Response:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, content: bytes = b"", *, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


class _Clock:
    """Deterministic clock so the 6s throttle never actually sleeps."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _gbk(text: str, *, status_code: int = 200) -> _Response:
    return _Response(text.encode("gbk"), status_code=status_code)


def _report_frame(report: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(report.split("\n\n", 1)[1]))


def _row(
    index: int,
    *,
    title: str = "贵州茅台深度报告",
    report_id: str = "1234567",
    kind: str = "个股研报",
    day: str = "2026-09-18",
    org: str = "中信证券",
    author: str = "张三",
) -> str:
    href = (
        "//vip.stock.finance.sina.com.cn/q/go.php/vReport_Show/kind/lastest/"
        f"rptid/{report_id}/index.phtml"
    )
    return (
        f'<tr><td>{index}</td><td class="tal f14">'
        f'<a target="_blank" title="{title}" href="{href}">{title}</a></td>'
        f"<td>{kind}</td><td>{day}</td><td><a href='#'>{org}</a></td><td>{author}</td></tr>"
    )


def _page(*rows: str) -> str:
    return _UNTERMINATED_TABLE + "".join(rows) + "</table></body></html>"


def _install(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[str | _Response],
    *,
    clock: _Clock | None = None,
) -> tuple[_Clock, list[dict]]:
    """Serve one scripted page per request; the last page repeats."""
    fake_clock = clock or _Clock()
    calls: list[dict] = []
    monkeypatch.setattr(sina_research, "time", fake_clock)
    monkeypatch.setattr(sina_research, "_sina_report_last", [0.0])

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        page = pages[min(len(calls) - 1, len(pages) - 1)]
        return page if isinstance(page, _Response) else _gbk(page)

    monkeypatch.setattr(sina_research.requests, "get", fake_get)
    return fake_clock, calls


def test_sina_market_wide_uses_lastest_endpoint(monkeypatch):
    _clock, calls = _install(monkeypatch, [_page(_row(1))])

    report = sina_research.get_sina_research_reports(page=3)

    assert calls[0]["url"] == sina_research.SINA_REPORT_URL.format(kind="lastest")
    assert calls[0]["params"] == {"p": 3}
    assert calls[0]["timeout"][1] <= 20  # explicit bounded read timeout
    assert "# Total records: 1" in report
    frame = _report_frame(report)
    assert frame["title"].iloc[0] == "贵州茅台深度报告"
    assert frame["date"].iloc[0] == "2026-09-18"
    assert frame["org"].iloc[0] == "中信证券"  # HTML stripped from the cell
    assert frame["author"].iloc[0] == "张三"
    assert frame["report_id"].iloc[0] == 1234567
    assert frame["url"].iloc[0].startswith("https://vip.stock.finance.sina.com.cn/")
    assert report.coverage.completeness == "partial"
    assert report.coverage.query_complete is False
    assert report.coverage.degradations == ("no_source_reported_total",)


def test_sina_report_states_no_ratings_or_target_prices(monkeypatch):
    _install(monkeypatch, [_page(_row(1))])

    report = sina_research.get_sina_research_reports()

    assert "不含评级与目标价" in report


def test_sina_beijing_code_gets_the_bj_prefix(monkeypatch):
    _clock, calls = _install(monkeypatch, [_page(_row(1))], clock=_Clock())

    sina_research.get_sina_research_reports("920982")
    assert calls[0]["url"] == sina_research.SINA_REPORT_URL.format(kind="search")
    assert calls[0]["params"] == {"symbol": "bj920982", "t1": "all", "p": 1}

    # Both an explicit BJ form and a bare Beijing code resolve to the same symbol.
    _clock, calls = _install(monkeypatch, [_page(_row(1))])
    sina_research.get_sina_research_reports("BJ920982")
    assert calls[0]["params"]["symbol"] == "bj920982"


def test_sina_non_beijing_code_keeps_bare_symbol(monkeypatch):
    _clock, calls = _install(monkeypatch, [_page(_row(1))])

    sina_research.get_sina_research_reports("000001")

    assert calls[0]["params"] == {"symbol": "000001", "t1": "all", "p": 1}


def test_sina_validates_page(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("HTTP must not be attempted for an invalid page")

    monkeypatch.setattr(sina_research.requests, "get", explode)

    for page in (0, -3, "abc"):
        with pytest.raises(ValueError, match="page"):
            sina_research.get_sina_research_reports("600519", page=page)


def test_sina_retries_the_fake_empty_page_after_the_minimum_interval(monkeypatch):
    clock, calls = _install(monkeypatch, [_EMPTY_PAGE, _page(_row(1))])

    report = sina_research.get_sina_research_reports("600519")

    assert len(calls) == 2, "the bogus empty page must be retried exactly once"
    assert clock.sleeps == [sina_research.SINA_REPORT_MIN_INTERVAL]
    assert "# Total records: 1" in report


def test_sina_keeps_the_interval_between_consecutive_requests(monkeypatch):
    clock, calls = _install(monkeypatch, [_page(_row(1))])

    sina_research.get_sina_research_reports("600519")
    sina_research.get_sina_research_reports("600519", page=2)

    assert len(calls) == 2
    assert clock.sleeps == [sina_research.SINA_REPORT_MIN_INTERVAL]


def test_sina_repeated_empty_page_cannot_prove_absence(monkeypatch):
    clock, calls = _install(monkeypatch, [_EMPTY_PAGE])

    with pytest.raises(ChinaDataUnavailableError, match="ambiguous_empty_response"):
        sina_research.get_sina_research_reports("600519")

    # A persistent throttle can answer exactly like genuine absence both times.
    assert len(calls) == 2
    assert clock.sleeps == [sina_research.SINA_REPORT_MIN_INTERVAL]


def test_sina_parallel_calls_serialize_requests_and_spacing(monkeypatch):
    clock, _calls = _install(monkeypatch, [_page(_row(1))])
    first_http_entered = Event()
    release_first_http = Event()
    second_lock_attempted = Event()
    second_http_entered = Event()
    calls: list[dict] = []

    class ObservedLock:
        """Signal the second acquisition before it blocks on the real lock."""

        def __init__(self):
            self.lock = Lock()
            self.attempts = 0

        def __enter__(self):
            self.attempts += 1
            if self.attempts == 2:
                second_lock_attempted.set()
            self.lock.acquire()
            return self

        def __exit__(self, *args):
            self.lock.release()

    monkeypatch.setattr(sina_research, "_sina_report_lock", ObservedLock())

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            first_http_entered.set()
            assert release_first_http.wait(timeout=2)
        else:
            second_http_entered.set()
        return _gbk(_page(_row(1)))

    monkeypatch.setattr(sina_research.requests, "get", fake_get)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(sina_research.get_sina_research_reports, "600519")
        try:
            assert first_http_entered.wait(timeout=2)
            second = executor.submit(sina_research.get_sina_research_reports, "000001")
            assert second_lock_attempted.wait(timeout=2)
            assert not second_http_entered.is_set()
        finally:
            release_first_http.set()
        assert first.result(timeout=2).coverage.completeness == "partial"
        assert second.result(timeout=2).coverage.completeness == "partial"
    assert second_http_entered.is_set()
    assert len(calls) == 2
    # The fake monotonic clock advances without any real time.sleep call.
    assert clock.sleeps == [sina_research.SINA_REPORT_MIN_INTERVAL]


def test_sina_zero_rows_without_the_empty_marker_raises(monkeypatch):
    page = _UNTERMINATED_TABLE + "<tr><th>研究员</th></tr></table></body></html>"
    _install(monkeypatch, [page])

    with pytest.raises(ChinaDataUnavailableError, match="解析出 0 条"):
        sina_research.get_sina_research_reports()


def test_sina_row_count_must_match_numbered_rows(monkeypatch):
    broken_row = (
        '<tr><td>2</td><td class="tal f14">'
        '<a title="坏行" href="/q/go.php/vReport_Show/kind/lastest/index.phtml">坏行</a></td>'
        "<td>个股研报</td><td>2026-09-18</td><td>机构</td><td>李四</td></tr>"
    )
    _install(monkeypatch, [_page(_row(1), broken_row)])

    with pytest.raises(ChinaDataUnavailableError, match="2 行带序号、解析出 1 条"):
        sina_research.get_sina_research_reports()


def test_sina_missing_table_markers_raise(monkeypatch):
    _install(monkeypatch, ["<html><body><p>没有找到相关内容</p></body></html>"])

    with pytest.raises(ChinaDataUnavailableError, match="找不到研报表格"):
        sina_research.get_sina_research_reports()


def test_sina_unparseable_date_raises(monkeypatch):
    _install(monkeypatch, [_page(_row(1, day="昨天"))])

    with pytest.raises(ChinaDataUnavailableError, match="无法识别的日期"):
        sina_research.get_sina_research_reports()


def test_sina_http_failure_is_typed(monkeypatch):
    _install(monkeypatch, [_gbk("boom", status_code=500)])

    with pytest.raises(ChinaDataUnavailableError, match="HTTP 500"):
        sina_research.get_sina_research_reports()


def test_sina_transport_failure_is_typed(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(sina_research, "time", clock)
    monkeypatch.setattr(sina_research, "_sina_report_last", [0.0])

    def fake_get(url, **kwargs):
        raise sina_research.requests.ConnectionError("tls reset")

    monkeypatch.setattr(sina_research.requests, "get", fake_get)

    with pytest.raises(ChinaDataUnavailableError, match="ConnectionError"):
        sina_research.get_sina_research_reports()
    monkeypatch.setattr(
        sina_research.requests, "get", lambda *args, **kwargs: _gbk(_page(_row(1)))
    )
    assert sina_research.get_sina_research_reports().coverage.completeness == "partial"
    assert clock.sleeps == [sina_research.SINA_REPORT_MIN_INTERVAL]
