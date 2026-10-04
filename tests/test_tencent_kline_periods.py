"""Weekly and monthly Tencent bars (a-stock-data v3.9.0 §1.2).

The daily path was already segmented, settled-session-filtered and guarded
against a qfq request being answered with raw bars.  Moving to weekly/monthly
bars breaks two things that are invisible at daily granularity:

* the response key is ``week``/``qfqweek`` (``month``/``qfqmonth``), so a
  hardcoded ``day`` lookup finds nothing;
* the backward walk stepped the cursor by one *day*, which lands inside the same
  weekly bar, stops the cursor advancing, and reports a false truncation on a
  window that was in fact covered.

These tests pin both, plus the settled-period boundary: a weekly bar is
unfinished for the whole of its week, so clamping it to "yesterday" would hand
the caller a partial bar it was told was settled.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from tradingagents.dataflows import tencent_kline as tk
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    """Serves a fixed page per requested end date and records every request."""

    def __init__(self, pages_by_end: dict[str, object], default: object | None = None) -> None:
        self.pages_by_end = pages_by_end
        self.default = default
        self.requests: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        param = params["param"]
        self.requests.append(param)
        end = param.split(",")[3]
        page = self.pages_by_end.get(end, self.default)
        if page is None:
            return _FakeResponse({"code": 0, "msg": "", "data": {}})
        return _FakeResponse(page)

    @property
    def periods(self) -> list[str]:
        return [request.split(",")[1] for request in self.requests]

    @property
    def ends(self) -> list[str]:
        return [request.split(",")[3] for request in self.requests]


def _row(day: str, close: float):
    """One real-layout row: index 2 is the close, index 3 the high."""
    return [day, str(close - 0.5), str(close), str(close + 1.0), str(close - 1.0), "1000"]


def _page(code: str, key: str, rows):
    return {"code": 0, "msg": "", "data": {code: {key: rows}}}


_WEEK_ROWS = [_row("2026-09-04", 11.0), _row("2026-09-11", 12.0), _row("2026-09-18", 13.0)]


def _settled(end: str, period: str, now: datetime) -> str:
    """The end date the adapter actually requests after settlement clamping."""
    return tk._settled_through(end, period=period, now=now)


_NOW = datetime(2026, 9, 30, 16, 0)


def test_weekly_request_asks_for_week_and_reads_the_week_key(monkeypatch):
    session = _FakeSession(
        {_settled("2026-09-30", "week", _NOW): _page("sh600519", "week", _WEEK_ROWS)}
    )
    frame, provenance = tk.get_a_share_kline_df(
        "600519.SH", "2026-09-01", "2026-09-30", period="week", session=session,
        now=datetime(2026, 9, 30, 16, 0),
    )

    assert session.periods == ["week"]
    assert provenance["period"] == "week"
    assert provenance["granularity"] == "weekly"
    # All three weeks fall inside 2026-09-01..2026-09-25 (the settled boundary).
    assert frame["Date"].tolist() == ["2026-09-04", "2026-09-11", "2026-09-18"]


def test_monthly_qfq_reads_the_qfqmonth_key(monkeypatch):
    session = _FakeSession(
        {_settled("2026-09-30", "month", _NOW): _page("sh600519", "qfqmonth", [_row("2026-08-31", 9.0)])}
    )
    frame, provenance = tk.get_a_share_kline_qfq_df(
        "600519.SH", "2026-08-01", "2026-09-30", period="month", session=session,
        now=datetime(2026, 9, 30, 16, 0),
    )

    assert session.periods == ["month"]
    assert provenance["period"] == "month"
    assert provenance["granularity"] == "monthly"
    assert frame["Date"].tolist() == ["2026-08-31"]


def test_qfq_weekly_answered_with_raw_week_bars_is_unavailable(monkeypatch):
    """The qfq masquerade guard must work for every period, not just `day`."""
    session = _FakeSession(
        {_settled("2026-09-30", "week", _NOW): _page("sh600519", "week", _WEEK_ROWS)}
    )

    with pytest.raises(ChinaDataUnavailableError, match="unadjusted `week` bars"):
        tk.get_a_share_kline_qfq_df(
            "600519.SH", "2026-09-01", "2026-09-30", period="week", session=session,
            now=datetime(2026, 9, 30, 16, 0),
        )


def test_weekly_walk_ends_before_the_oldest_calendar_week(monkeypatch):
    """A full weekly page must move the cursor by the bar width.

    With a one-day step the next request lands inside the same weekly bar, the
    cursor stops advancing, and the walk raises a truncation error for a window
    it had actually reached.
    """
    first_end = _settled("2026-09-30", "week", _NOW)
    count = tk.TENCENT_MAX_ROWS_PER_REQUEST
    oldest = date.fromisoformat(first_end) - timedelta(days=7 * (count - 1))
    full_page_rows = [
        _row((oldest + timedelta(days=7 * i)).isoformat(), 10.0 + (i % 50))
        for i in range(count)
    ]
    second_end = (oldest - timedelta(days=oldest.weekday() + 1)).isoformat()
    session = _FakeSession(
        {
            first_end: _page("sh600519", "week", full_page_rows),
            second_end: _page("sh600519", "week", [_row("2005-01-07", 5.0)]),
        }
    )

    # The start is deliberately older than the first page, so a second segment
    # is required and the cursor has to move.
    frame, _ = tk.get_a_share_kline_df(
        "600519.SH", "2000-01-01", "2026-09-30", period="week", session=session,
        now=_NOW,
    )

    assert session.ends == [first_end, second_end]
    assert date.fromisoformat(second_end).weekday() == 6
    assert "2005-01-07" in frame["Date"].tolist()


@pytest.mark.parametrize("period,dates,end,now,expected_ends", [
    ("week", ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25", "2026-09-30", "2026-10-09"],
     "2026-10-09", datetime(2026, 10, 15, 16), ["2026-10-09", "2026-09-27", "2026-09-13"]),
    ("month", ["2026-01-30", "2026-02-27", "2026-03-31", "2026-04-30", "2026-05-29", "2026-06-30"],
     "2026-06-30", datetime(2026, 7, 15, 16), ["2026-06-30", "2026-04-30", "2026-02-28"]),
])
@pytest.mark.parametrize("adjust", [None, "qfq"])
def test_calendar_paging_preserves_shortened_periods(monkeypatch, period, dates, end, now, expected_ends, adjust):
    monkeypatch.setattr(tk, "TENCENT_REQUEST_ROW_CAP", 2)
    key = f"qfq{period}" if adjust else period

    class WindowSession(_FakeSession):
        def get(self, url, params=None, headers=None, timeout=None):
            param = params["param"]
            self.requests.append(param)
            cursor = param.split(",")[3]
            rows = [_row(day, 10.0) for day in dates if day <= cursor][-2:]
            return _FakeResponse(_page("sh600519", key, rows))

    session = WindowSession({})
    getter = tk.get_a_share_kline_qfq_df if adjust else tk.get_a_share_kline_df
    frame, provenance = getter("600519.SH", dates[0], end, period=period, session=session, now=now)
    assert frame["Date"].tolist() == dates
    assert session.ends == expected_ends
    assert provenance["window_covered"] is True


def test_settled_boundary_uses_the_last_closed_period():
    """A week/month bar is unsettled until its own period ends."""
    now = datetime(2026, 9, 30, 10, 0)  # Wednesday morning, before the close
    settled_day = date(2026, 9, 29)  # yesterday

    daily = tk._settled_through("2026-12-31", period="day", now=now)
    weekly = tk._settled_through("2026-12-31", period="week", now=now)
    monthly = tk._settled_through("2026-12-31", period="month", now=now)

    assert daily == settled_day.isoformat()
    # The latest Friday on or before the settled day.
    assert weekly == (settled_day - timedelta(days=(settled_day.weekday() - 4) % 7)).isoformat()
    assert date.fromisoformat(weekly).weekday() == 4
    # The end of the previous calendar month.
    assert monthly == (settled_day.replace(day=1) - timedelta(days=1)).isoformat()
    assert monthly == "2026-08-31"


def test_settled_boundary_never_moves_the_end_forwards():
    now = datetime(2026, 9, 30, 10, 0)
    for period in ("day", "week", "month"):
        assert tk._settled_through("2026-01-05", period=period, now=now) == "2026-01-05"


def test_router_wrappers_pin_both_period_and_adjustment(monkeypatch):
    """A weekly capability must never be served by the daily path."""
    calls: list[tuple[str, str]] = []

    def _fake_raw(ticker, start, end, *, period="day", session=None):
        calls.append(("raw", period))
        return "raw"

    def _fake_qfq(ticker, start, end, *, period="day", session=None):
        calls.append(("qfq", period))
        return "qfq"

    monkeypatch.setattr(tk, "get_a_share_kline", _fake_raw)
    monkeypatch.setattr(tk, "get_a_share_kline_qfq", _fake_qfq)

    assert tk.get_a_share_kline_weekly("600519.SH", "a", "b") == "raw"
    assert tk.get_a_share_kline_weekly_qfq("600519.SH", "a", "b") == "qfq"
    assert tk.get_a_share_kline_monthly("600519.SH", "a", "b") == "raw"
    assert tk.get_a_share_kline_monthly_qfq("600519.SH", "a", "b") == "qfq"

    assert calls == [("raw", "week"), ("qfq", "week"), ("raw", "month"), ("qfq", "month")]


def test_unknown_period_is_a_caller_error():
    with pytest.raises(ValueError, match="period must be one of"):
        tk.get_a_share_kline_df("600519.SH", "2026-01-01", "2026-09-30", period="quarter")
