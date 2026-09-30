"""T-D2 regression guard: Tencent kline columns are ``[date, OPEN, CLOSE, HIGH, LOW, VOL]``.

Live probe 2026-09-29 (capability-probe-2026-09-29.md §2.1) proved the layout
twice: a max/min invariant over 4 tickers x 28 sessions, and a field-by-field
match against the live ``qt.gtimg.cn`` snapshot.  Reading the row as the
intuitive ``[O, H, L, C]`` swaps high and low and raises nothing.

``test_ohlc_invariant_catches_the_ohlc_column_order_bug`` is the test the task
plan requires to fail before the fix; it parses the same fixture both ways and
asserts the naive OHLC reading violates the invariant on essentially every bar.

Fixtures are synthetic, minimal, and carry only a date plus numbers.  They are
shaped like the real response (6-element rows, ``data[code][key]``) but the
values are invented, not captured vendor output.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from tradingagents.dataflows import tencent_kline
from tradingagents.dataflows.china_data import ChinaDataUnavailableError


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    """Serves a fixed page per requested end date and records the requests.

    ``default`` answers any end date not explicitly mapped, so a multi-segment
    walk can be exercised without enumerating every cursor the adapter computes.
    """

    def __init__(self, pages_by_end: dict[str, object], default: object | None = None) -> None:
        self.pages_by_end = pages_by_end
        self.default = default
        self.requests: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        param = params["param"]
        end = param.split(",")[3]
        self.requests.append(param)
        page = self.pages_by_end.get(end, self.default)
        if page is None:
            return _FakeResponse({"code": 0, "msg": "", "data": {}})
        return _FakeResponse(page)


def _row(day: str, open_: float, close: float, high: float, low: float, vol: int):
    """One real-layout row: index 2 is the close, index 3 the high."""
    return [day, str(open_), str(close), str(high), str(low), str(vol)]


def _page(code: str, key: str, rows):
    return {"code": 0, "msg": "", "data": {code: {key: rows}}}


# Six sessions of invented data where high > both body values and low < both.
# Any bar where the two interpretations coincide would weaken the guard, so
# every row here has high != max(open, close) and low != min(open, close).
_TDX2_ROWS = [
    _row("2026-09-21", 10.00, 10.80, 11.50, 9.60, 12000),
    _row("2026-09-22", 10.80, 10.10, 11.20, 9.90, 13000),
    _row("2026-09-23", 10.10, 10.95, 11.80, 9.80, 14000),
    _row("2026-09-24", 10.95, 10.20, 11.40, 10.05, 15000),
    _row("2026-09-25", 10.20, 11.10, 11.60, 10.00, 16000),
    _row("2026-09-28", 11.10, 10.60, 11.70, 10.30, 17000),
]


# ---------------------------------------------------------------- T-D2 guard


def test_ohlc_invariant_catches_the_ohlc_column_order_bug():
    """The invariant must reject the naive OHLC reading of a Tencent row.

    This is the acceptance item the plan states must fail *before* the fix.  It
    reconstructs the defect directly from the fixture: parse indices 1-4 as
    (open, high, low, close) and the invariant breaks on every bar, with no
    exception raised by the parse itself.  Parsing the same rows by the real
    layout satisfies it.
    """
    parsed_correct = pd.DataFrame(
        [tencent_kline._parse_kline_row(row) for row in _TDX2_ROWS]
    )
    # The correct layout passes.
    tencent_kline.assert_ohlc_invariant(parsed_correct, context="real layout")

    # The buggy layout: index 2 read as High, index 3 read as Low, index 4 as Close.
    parsed_buggy = pd.DataFrame(
        [
            {
                "Date": row[0],
                "Open": float(row[1]),
                "High": float(row[2]),  # actually the CLOSE
                "Low": float(row[3]),  # actually the HIGH
                "Close": float(row[4]),  # actually the LOW
            }
            for row in _TDX2_ROWS
        ]
    )
    with pytest.raises(ChinaDataUnavailableError, match="OHLC invariant violated"):
        tencent_kline.assert_ohlc_invariant(parsed_buggy, context="OHLC reading")

    # The parse itself never raised -- the data is silently wrong, which is the
    # whole reason an explicit invariant is required.
    assert len(parsed_buggy) == len(_TDX2_ROWS)
    assert parsed_buggy["High"].tolist() != parsed_correct["High"].tolist()


def test_parse_kline_row_maps_the_real_column_order():
    row = _row("2026-09-28", 11.10, 10.60, 11.70, 10.30, 17000)

    parsed = tencent_kline._parse_kline_row(row)

    assert parsed == {
        "Date": "2026-09-28",
        "Open": 11.10,
        "Close": 10.60,
        "High": 11.70,
        "Low": 10.30,
        "Volume": 17000.0,
    }
    # Explicitly pin the two indices that are the defect.
    assert parsed["Close"] == 10.60, "index 2 is the close, not the high"
    assert parsed["High"] == 11.70, "index 3 is the high, not the low"
    assert parsed["Low"] == 10.30, "index 4 is the low, not the close"


def test_parse_kline_row_rejects_short_and_malformed_rows():
    assert tencent_kline._parse_kline_row(["2026-09-28", "1", "2"]) is None
    assert tencent_kline._parse_kline_row(None) is None
    assert tencent_kline._parse_kline_row(["2026-09-28", "1", "2", "3", "x", "5"]) is None


# ------------------------------------------------------- qfq masquerade guard


def test_qfq_answering_with_day_bars_is_unavailable_not_raw():
    """Probe §2.3: some symbols answer ``fq=qfq`` with unadjusted ``day`` bars.

    Serving those as "forward adjusted" is the masquerade design §8.2 forbids.
    """
    session = _FakeSession(
        {"2026-09-28": _page("sh688981", "day", _TDX2_ROWS)}
    )
    with pytest.raises(ChinaDataUnavailableError) as ctx:
        tencent_kline.get_a_share_kline_qfq_df(
            "688981.SH", "2026-09-01", "2026-09-28", session=session
        )

    assert "unadjusted" in str(ctx.value)
    assert "qfqday" in str(ctx.value)


def test_raw_and_qfq_are_separate_entry_points():
    """A raw request must never pick up adjustment, and vice versa."""
    raw_session = _FakeSession({"2026-09-28": _page("sh600519", "day", _TDX2_ROWS)})
    frame, provenance = tencent_kline.get_a_share_kline_df(
        "600519.SH", "2026-09-01", "2026-09-28", session=raw_session
    )

    assert provenance["price_basis"] == "raw"
    assert provenance["adjust_requested"] == "none"
    assert "pit_status" not in provenance
    assert list(frame.columns) == ["Date", "Open", "Close", "High", "Low", "Volume"]

    qfq_session = _FakeSession({"2026-09-28": _page("sh600519", "qfqday", _TDX2_ROWS)})
    qfq_frame, qfq_provenance = tencent_kline.get_a_share_kline_qfq_df(
        "600519.SH", "2026-09-01", "2026-09-28", session=qfq_session
    )

    assert qfq_provenance["price_basis"] == "qfq"
    assert qfq_provenance["pit_status"] == "unverified"
    assert "NOT point-in-time verified" in qfq_provenance["adjustment_note"]
    # Same shape, independently fetched -- the two paths never share a frame.
    assert qfq_frame is not frame


# ---------------------------------------------------- truncation / pagination


def test_silent_640_row_cap_is_segmented_not_treated_as_complete(monkeypatch):
    """Probe §2.4: no total/count/more marker, real cap 640 rows.

    A full first page must trigger a second backward segment rather than being
    accepted as the whole window.
    """
    monkeypatch.setattr(tencent_kline, "TENCENT_MAX_ROWS_PER_REQUEST", 6)
    older = [
        _row(f"2026-08-{day:02d}", 9.0, 9.5, 9.9, 8.8, 1000)
        for day in range(1, 7)
    ]

    class _TwoPageSession:
        """Serves the recent page for a current end, the older page for any past end.

        This models the real endpoint, which answers "the most recent N rows at
        or before this end" -- so an end date inside the older range returns the
        older rows, and an end older than everything returns nothing.
        """

        def __init__(self) -> None:
            self.requests: list[str] = []

        def get(self, url, params=None, headers=None, timeout=None):
            param = params["param"]
            end = param.split(",")[3]
            self.requests.append(param)
            if end >= "2026-09-21":
                return _FakeResponse(_page("sh600519", "day", _TDX2_ROWS))
            if end >= "2026-08-01":
                return _FakeResponse(_page("sh600519", "day", older))
            return _FakeResponse({"code": 0, "msg": "", "data": {}})

    session = _TwoPageSession()

    frame, provenance = tencent_kline.get_a_share_kline_df(
        "600519.SH", "2026-08-01", "2026-09-28", session=session
    )

    assert len(frame) == 12
    assert provenance["segments"] == 2
    assert provenance["truncated_by_provider"] is True
    # The second segment must be requested with an end date strictly before the
    # oldest row of the first, or it would loop forever.
    assert len(session.requests) == 2
    assert session.requests[1].split(",")[3] == "2026-09-20"


def test_truncation_is_reported_not_silently_accepted(monkeypatch):
    """A walk that stops short of the start must raise, not return a short frame.

    Probe §2.4 records sh600000 at 0.225 trading-day density over 20 calls:
    systematic vendor-side missing rows.  Reporting that as a complete window
    would be a silent coverage lie.
    """
    monkeypatch.setattr(tencent_kline, "TENCENT_MAX_ROWS_PER_REQUEST", 6)

    class _NeverReachesStartSession:
        def get(self, url, params=None, headers=None, timeout=None):
            # Always the same recent page: the walk advances the cursor but
            # never observes an older row.
            return _FakeResponse(_page("sh600519", "day", _TDX2_ROWS))

    with pytest.raises(tencent_kline.TencentKlineTruncated):
        tencent_kline.get_a_share_kline_df(
            "600519.SH", "2001-01-01", "2026-09-28", session=_NeverReachesStartSession()
        )

def test_short_page_ends_the_walk(monkeypatch):
    """Fewer rows than the requested count means the provider has nothing older."""
    monkeypatch.setattr(tencent_kline, "TENCENT_MAX_ROWS_PER_REQUEST", 20)
    session = _FakeSession({"2026-09-28": _page("sh600519", "day", _TDX2_ROWS)})

    frame, provenance = tencent_kline.get_a_share_kline_df(
        "600519.SH", "2026-08-01", "2026-09-28", session=session
    )

    assert len(frame) == 6
    assert provenance["segments"] == 1
    assert provenance["truncated_by_provider"] is False
    assert len(session.requests) == 1


def test_segment_budget_exhaustion_raises_instead_of_reporting_complete(monkeypatch):
    """A window older than the segment budget must be an error, not a short frame.

    Probe §2.4: 20 calls took 600519 back only to 2003-05-16, so a 2001 start
    date is genuinely unreachable.  Reporting the 6 rows we did get as the
    window would be a silent coverage lie.
    """
    monkeypatch.setattr(tencent_kline, "TENCENT_MAX_ROWS_PER_REQUEST", 6)
    monkeypatch.setattr(tencent_kline, "TENCENT_MAX_SEGMENTS", 3)

    class _AlwaysFullSession:
        """Advances the cursor every call but never reaches the window start.

        The oldest row tracks the requested end, so the walk can go forever --
        which is exactly the 600519 case the probe measured at 0.225 trading-day
        density after 20 calls.
        """

        def __init__(self) -> None:
            self.requests = 0

        def get(self, url, params=None, headers=None, timeout=None):
            self.requests += 1
            end = datetime.strptime(params["param"].split(",")[3], "%Y-%m-%d")
            rows = [
                _row(
                    (end - timedelta(days=offset)).strftime("%Y-%m-%d"),
                    10.0,
                    10.5,
                    11.0,
                    9.5,
                    100,
                )
                for offset in range(6)
            ]
            return _FakeResponse(_page("sh600519", "day", rows))

    session = _AlwaysFullSession()

    with pytest.raises(tencent_kline.TencentKlineTruncated) as ctx:
        tencent_kline.get_a_share_kline_df(
            "600519.SH", "2001-01-01", "2026-09-28", session=session
        )
    assert "2001-01-01" in str(ctx.value)
    assert session.requests == 3


def test_empty_data_node_with_code_zero_is_not_success(monkeypatch):
    """``count >= 2100`` returns ``{"code":0,"msg":"param error","data":[]}``."""
    session = _FakeSession({})
    monkeypatch.setattr(tencent_kline, "TENCENT_MAX_ROWS_PER_REQUEST", 5000)

    with pytest.raises(ChinaDataUnavailableError, match="no kline data node"):
        tencent_kline.get_a_share_kline_df(
            "600519.SH", "2001-01-01", "2026-09-28", session=session
        )


# ----------------------------------------------- unsettled / settled sessions


def test_raw_drops_the_in_progress_session():
    """Probe §2.6: ``day`` includes today's unfinished bar; qfq does not.

    Both paths must align on the last *settled* session, otherwise raw and qfq
    disagree on the final bar for a reason that has nothing to do with
    adjustment.  The clock is injected so the boundary is testable at any hour.
    """
    today = "2026-09-29"
    yesterday = "2026-09-28"

    def _fetch(now, key="day"):
        intraday = _row(today, 100.0, 101.0, 102.0, 99.0, 5000)
        settled = _row(yesterday, 99.0, 99.5, 100.0, 98.0, 4000)
        # The adapter requests the *settled-through* end date, which before the
        # 15:00 close is yesterday, not today.
        session = _FakeSession(
            {
                today: _page("sh600519", key, [intraday, settled]),
                yesterday: _page("sh600519", key, [intraday, settled]),
            },
            default=_page("sh600519", key, []),
        )
        return tencent_kline.get_a_share_kline_df(
            "600519.SH", "2026-09-01", today, session=session, now=now
        )

    # 11:00, mid-session: today's bar is not a closed bar and must be dropped.
    morning, morning_prov = _fetch(datetime(2026, 9, 29, 11, 0))
    assert today not in set(morning["Date"])
    assert morning_prov["settled_through"] == yesterday
    assert list(morning["Date"]) == [yesterday]

    # 15:30, after the close: the same bar is a legitimate observation.
    evening, evening_prov = _fetch(datetime(2026, 9, 29, 15, 30))
    assert list(evening["Date"]) == [yesterday, today]
    assert evening_prov["settled_through"] == today

    # A window that ends before today is never truncated, whatever the hour.
    early, early_prov = _fetch(datetime(2026, 9, 29, 9, 0))
    assert early_prov["settled_through"] == yesterday


def test_qfq_and_raw_agree_on_the_last_settled_session():
    """The two paths must not disagree about which session is complete."""
    today = "2026-09-29"
    yesterday = "2026-09-28"
    raw_bar = _row(today, 100.0, 101.0, 102.0, 99.0, 5000)
    shared = _row(yesterday, 99.0, 99.5, 100.0, 98.0, 4000)
    now = datetime(2026, 9, 29, 11, 0)

    raw_session = _FakeSession(
        {
            today: _page("sh600519", "day", [raw_bar, shared]),
            yesterday: _page("sh600519", "day", [raw_bar, shared]),
        },
        default=_page("sh600519", "day", []),
    )
    qfq_session = _FakeSession(
        {
            today: _page("sh600519", "qfqday", [raw_bar, shared]),
            yesterday: _page("sh600519", "qfqday", [raw_bar, shared]),
        },
        default=_page("sh600519", "qfqday", []),
    )

    raw_frame, raw_prov = tencent_kline.get_a_share_kline_df(
        "600519.SH", "2026-09-01", today, session=raw_session, now=now
    )
    qfq_frame, qfq_prov = tencent_kline.get_a_share_kline_qfq_df(
        "600519.SH", "2026-09-01", today, session=qfq_session, now=now
    )

    assert raw_prov["settled_through"] == qfq_prov["settled_through"] == yesterday
    assert list(raw_frame["Date"]) == list(qfq_frame["Date"])


# ------------------------------------------------------ provenance / units


def test_provenance_records_units_convention_and_source():
    session = _FakeSession({"2026-09-28": _page("sh600519", "day", _TDX2_ROWS)})

    frame, provenance = tencent_kline.get_a_share_kline_df(
        "600519.SH", "2026-09-01", "2026-09-28", session=session
    )

    assert provenance["provider"] == "tencent"
    assert provenance["volume_unit"] == "lots (100 shares)"
    assert provenance["column_order"] == "[date, OPEN, CLOSE, HIGH, LOW, VOLUME]"
    assert provenance["code"] == "sh600519"
    assert provenance["requested_start"] == "2026-09-01"
    assert provenance["requested_end"] == "2026-09-28"
    # No silent truncation flag when the walk terminated naturally.
    assert provenance["segment_budget_exhausted"] is False
    assert frame["Volume"].tolist() == [12000.0, 13000.0, 14000.0, 15000.0, 16000.0, 17000.0]


def test_rendered_report_carries_the_ohlc_map_and_pit_status(monkeypatch):
    qfq_session = _FakeSession({"2026-09-28": _page("sh600519", "qfqday", _TDX2_ROWS)})
    monkeypatch.setattr(tencent_kline, "_capture_vendor_raw", lambda *a, **k: None)

    report = tencent_kline.get_a_share_kline_qfq(
        "600519.SH", "2026-09-01", "2026-09-28", session=qfq_session
    )

    assert "# Price basis: qfq" in report
    assert "# PIT status: unverified" in report
    assert "NOT point-in-time verified" in report
    assert "[date, OPEN, CLOSE, HIGH, LOW, VOLUME]" in report
    # The rendered CSV must show the close in its own column, not as the high.
    assert "2026-09-28,11.1,10.6,11.7,10.3,17000.0" in report
    tencent_kline.assert_ohlc_invariant(
        pd.read_csv(
            pd.io.common.StringIO(report.split("\n\n", 1)[1])
        ),
        context="rendered report",
    )


def test_raw_rendered_report_declares_the_unadjusted_basis(monkeypatch):
    session = _FakeSession({"2026-09-28": _page("sh600519", "day", _TDX2_ROWS)})
    monkeypatch.setattr(tencent_kline, "_capture_vendor_raw", lambda *a, **k: None)

    report = tencent_kline.get_a_share_kline(
        "600519.SH", "2026-09-01", "2026-09-28", session=session
    )

    assert "# Price basis: raw" in report
    assert "Unadjusted prices" in report
    assert "PIT status" not in report


def test_non_a_share_ticker_is_rejected():
    with pytest.raises(ChinaDataUnavailableError, match="not recognized as an A-share"):
        tencent_kline._tencent_code("AAPL")
