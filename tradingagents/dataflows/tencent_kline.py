"""Tencent bars (fqkline) -- daily/weekly/monthly, raw and forward-adjusted.

Endpoints (no credentials, not IP-banned, not rate-limited):
  raw  -> https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=<code>,day,,,<n>
  qfq  -> ...&fq=qfq

**Column order is NOT OHLC.**  Each row is
``[date, OPEN, CLOSE, HIGH, LOW, VOLUME, ...]`` -- index 2 is the *close* and
index 3 is the *high*.  Reading it as the intuitive ``[O, H, L, C]`` produces
silently wrong high/low values with no error raised.  Proven twice on
2026-09-29 (capability-probe-2026-09-29.md §2.1): a max/min invariant over 4
tickers x 28 sessions (``max(idx1..idx4) == idx3`` and ``min == idx4``) and a
field-by-field match against the live ``qt.gtimg.cn`` snapshot (4/4 exact on
open/now/high/low).  :func:`_parse_kline_row` encodes that map and
``tests/test_tencent_kline_tdx2.py`` re-asserts the invariant.

Three further behaviours are load-bearing and are *not* self-evident from the
payload:

* ``fq=qfq`` can come back as an unadjusted ``day`` key with HTTP 200 and an
  empty ``msg``.  That is a **silent downgrade to raw**, so the qfq path treats
  a missing ``qfqday`` key as ``unavailable`` rather than falling back.
* There is no ``total``/``count``/``more`` marker, and the effective per-request
  cap is 640 rows (larger ``count`` values silently return 640; >= 2100 returns
  ``param error`` with ``code: 0``).  Truncation must be detected locally.
* ``day`` requests include today's *unfinished* bar while ``qfq`` requests do
  not, so the two paths disagree on "last complete session".  Both are filtered
  to the last *settled* session and the caller's ``end_date`` is honoured.

Tencent qfq is anchored to the present, so its most recent bar equals the raw
bar.  That is a property of the anchor, **not** evidence that the series is
point-in-time correct: a later corporate action silently rewrites history.
Series therefore carry ``adjustment_verified=False`` and must not feed a
historical cutoff (design §8.5).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Literal

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .ticker_utils import is_a_share_ticker, normalize_ticker_symbol, to_akshare_symbol

logger = logging.getLogger(__name__)

TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# Bar periods the fqkline endpoint serves.  The response key is the period name
# itself, or ``qfq<period>`` on the adjusted series, so both the request and the
# key are derived from this tuple rather than written out per call site.
TENCENT_KLINE_PERIODS = ("day", "week", "month")
KlinePeriod = Literal["day", "week", "month"]

# How far back to step the window cursor when a full page did not reach the
# requested start.  Stepping one *day* back from a weekly bar's date re-requests
# the same week, the cursor stops advancing, and the walk reports a false
# truncation -- so the step has to match the bar width.

# Coverage granularity per bar period (PriceSeriesCoverageV1 vocabulary).
_PERIOD_GRANULARITY = {"day": "daily", "week": "weekly", "month": "monthly"}

# Human label used in the rendered title.
_PERIOD_LABEL = {"day": "daily", "week": "weekly", "month": "monthly"}

# Probe 2026-09-29 §2.4: count=1000/1500/2000 all return exactly 640 rows, and
# >=2100 returns {"code":0,"msg":"param error","data":[]} -- i.e. the endpoint
# reports success while dropping the request.  640 is the real ceiling.
TENCENT_MAX_ROWS_PER_REQUEST = 640
# Sending a larger count earns a `param error` instead of more rows.
TENCENT_REQUEST_ROW_CAP = 2000
# How many backward-walking segments one logical request may spend.
TENCENT_MAX_SEGMENTS = 20

# A-share close is 15:00 Asia/Shanghai.  A `day` response fetched after that
# instant is assumed settled; fetched before it, the trailing bar is an
# in-progress session and is dropped.
TENCENT_SETTLED_BAR_CUTOFF_HOUR = 15

_ADJUSTMENT_NOTE = (
    "Tencent qfq is anchored to the present, so a later corporate action "
    "silently rewrites earlier bars. This series is NOT point-in-time verified "
    "and must not back a historical cutoff."
)


class TencentKlineTruncated(RuntimeError):
    """Raised when the endpoint silently dropped rows we asked for."""


def _tencent_prefix(ticker: str) -> str:
    """Pick Tencent's exchange prefix for a canonical A-share ticker."""
    canonical = normalize_ticker_symbol(ticker)
    if canonical.endswith((".SS", ".SH")):
        return "sh"
    if canonical.endswith(".BJ"):
        return "bj"
    return "sz"


def _tencent_code(ticker: str) -> str:
    canonical = normalize_ticker_symbol(ticker)
    if not is_a_share_ticker(canonical):
        raise ChinaDataUnavailableError(
            f"{ticker} is not recognized as an A-share ticker."
        )
    return f"{_tencent_prefix(ticker)}{to_akshare_symbol(canonical)}"


def _parse_kline_row(row: list[Any]) -> dict[str, Any] | None:
    """Map one Tencent kline row onto the local OHLCV schema.

    The positional layout is ``[date, OPEN, CLOSE, HIGH, LOW, VOLUME, ...]``.
    Getting this wrong is silent, so the mapping is spelled out rather than
    zipped and the OHLC ordering is validated in
    :func:`assert_ohlc_invariant`.
    """
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        return None
    try:
        return {
            "Date": str(row[0]),
            "Open": float(row[1]),
            "Close": float(row[2]),
            "High": float(row[3]),
            "Low": float(row[4]),
            "Volume": float(row[5]),
        }
    except (TypeError, ValueError):
        return None


def assert_ohlc_invariant(frame: pd.DataFrame, *, context: str = "") -> None:
    """Require ``high >= max(open, close) >= min(open, close) >= low`` per row.

    The regression guard for T-D2: reading the Tencent layout as OHLC swaps
    high and low, which violates this on essentially every real bar while
    raising nothing.
    """
    if frame.empty:
        return
    upper = frame[["Open", "Close"]].max(axis=1)
    lower = frame[["Open", "Close"]].min(axis=1)
    violations = (frame["High"] < upper) | (frame["Low"] > lower) | (
        frame["High"] < frame["Low"]
    )
    if bool(violations.any()):
        bad = frame.loc[violations].head(3)
        raise ChinaDataUnavailableError(
            "Tencent kline OHLC invariant violated"
            f"{f' for {context}' if context else ''}: high >= max(open, close) "
            f">= min(open, close) >= low does not hold on {int(violations.sum())} "
            f"of {len(frame)} rows. First offending rows:\n{bad.to_csv(index=False)}"
            " This indicates the provider column order was misread, not that the "
            "market produced impossible bars."
        )


def _request_page(
    code: str,
    *,
    start: str,
    end: str,
    count: int,
    adjust: Literal["none", "qfq"],
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch one raw Tencent kline page and return the decoded JSON body."""
    if period not in TENCENT_KLINE_PERIODS:
        raise ValueError(f"period must be one of {TENCENT_KLINE_PERIODS!r}")
    param = f"{code},{period},{start},{end},{count}"
    if adjust == "qfq":
        param += ",qfq"
    http = session or requests
    try:
        resp = http.get(
            TENCENT_KLINE_URL,
            params={"param": param},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise ChinaDataUnavailableError(
            f"Tencent kline request failed for {code}: {type(exc).__name__}"
        ) from exc
    if resp.status_code != 200:
        raise ChinaDataUnavailableError(
            f"Tencent kline endpoint returned HTTP {resp.status_code} for {code}."
        )
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ChinaDataUnavailableError(
            f"Tencent kline response for {code} was not valid JSON."
        ) from exc
    if not isinstance(body, dict):
        raise ChinaDataUnavailableError(
            f"Tencent kline response for {code} was not a JSON object."
        )
    # `code: 0` is returned even for `msg: "param error"`, so the data shape --
    # not the status field -- is what distinguishes a real page.
    if not body.get("data"):
        raise ChinaDataUnavailableError(
            f"Tencent returned no kline data node for {code} "
            f"(msg={body.get('msg')!r})."
        )
    return body


def _node_rows(body: dict[str, Any], code: str, key: str) -> list[list[Any]]:
    """Extract the row list under ``data[code][key]``."""
    node = body["data"].get(code)
    if not isinstance(node, dict):
        return []
    rows = node.get(key)
    if not isinstance(rows, list):
        return []
    return rows


def _fetch_window(
    code: str,
    *,
    start_date: str,
    end_date: str,
    adjust: Literal["none", "qfq"],
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Walk backwards from ``end_date`` until the window start is covered.

    Tencent answers with the most recent ``count`` rows at or before ``end`` and
    carries no continuation marker, so the only way to prove the window is
    complete is to keep stepping the end date back until a segment comes back
    short (or the older edge is reached).
    """
    if period not in TENCENT_KLINE_PERIODS:
        raise ValueError(f"period must be one of {TENCENT_KLINE_PERIODS!r}")
    expected_key = f"qfq{period}" if adjust == "qfq" else period
    collected: dict[str, dict[str, Any]] = {}
    segments = 0
    segment_reports: list[dict[str, Any]] = []
    cursor = end_date
    truncated = False
    exhausted = True
    # "Did we prove the window starts at or before start_date?"  Only a segment
    # that reaches back to the start or comes back short can prove it.  A full
    # page leaves it unproven, which is exactly the probe's silent-640 defect.
    window_covered = False

    while segments < TENCENT_MAX_SEGMENTS:
        count = min(TENCENT_MAX_ROWS_PER_REQUEST, TENCENT_REQUEST_ROW_CAP)
        body = _request_page(
            code,
            start=start_date,
            end=cursor,
            count=count,
            adjust=adjust,
            period=period,
            session=session,
        )
        segments += 1
        raw_rows = _node_rows(body, code, expected_key)
        if adjust == "qfq" and not raw_rows:
            # A qfq request answered with the unadjusted period key (or nothing).
            # Serving those bars as "adjusted" is the exact masquerade design
            # §8.2 forbids, so this is an unavailable capability, not raw data.
            if _node_rows(body, code, period):
                raise ChinaDataUnavailableError(
                    f"Tencent answered the qfq request for {code} with unadjusted "
                    f"`{period}` bars and no `{expected_key}` key (HTTP 200, empty "
                    "msg). This symbol is not served on the forward-adjusted "
                    "series; treating raw bars as qfq is forbidden."
                )
            raise ChinaDataUnavailableError(
                f"Tencent returned no `{expected_key}` rows for {code} "
                f"(msg={body.get('msg')!r})."
            )
        parsed = [p for p in (_parse_kline_row(r) for r in raw_rows) if p]
        segment_reports.append(
            {
                "segment": segments,
                "requested_end": cursor,
                "rows": len(raw_rows),
            }
        )
        if not parsed:
            # An empty follow-up page means the provider stopped serving rows
            # while the requested window start is still unreached.  That is
            # provider-side truncation, not "the window had no events".
            if collected and min(collected) > start_date:
                raise TencentKlineTruncated(
                    f"Tencent kline for {code} returned no rows at or before "
                    f"{cursor} while the window still starts at {start_date} "
                    f"(oldest seen: {min(collected)}). Coverage is incomplete and "
                    f"must not be reported as complete."
                )
            window_covered = True
            break
        for row in parsed:
            collected.setdefault(row["Date"], row)
        oldest = min(row["Date"] for row in parsed)
        if oldest <= start_date:
            window_covered = True
            break
        if len(parsed) < count:
            # A short page means the provider has nothing older in this window.
            window_covered = True
            break
        # End at the previous calendar period, rather than subtracting a fixed
        # number of days from the last trading day. A holiday-shortened week or
        # a short month would otherwise skip an entire older bar.
        oldest_day = datetime.strptime(oldest, "%Y-%m-%d")
        if period == "week":
            previous_day = oldest_day - timedelta(days=oldest_day.weekday() + 1)
        elif period == "month":
            previous_day = oldest_day.replace(day=1) - timedelta(days=1)
        else:
            previous_day = oldest_day - timedelta(days=1)
        previous = previous_day.strftime("%Y-%m-%d")
        if previous >= cursor:
            # The cursor failed to advance, so another identical request would
            # repeat forever.  Coverage is unproven -- report it, do not guess.
            raise TencentKlineTruncated(
                f"Tencent kline for {code} could not advance past {cursor} "
                f"(oldest row {oldest} did not move the window). The returned "
                f"window cannot be proven complete."
            )
        cursor = previous
        truncated = True
    else:
        raise TencentKlineTruncated(
            f"Tencent kline for {code} did not reach {start_date} within "
            f"{TENCENT_MAX_SEGMENTS} segments (oldest seen: "
            f"{min(collected) if collected else 'none'}). The provider's 640-row "
            "cap makes older history unreachable within the segment budget; the "
            "window is incomplete and must not be reported as complete coverage."
        )

    if collected and not window_covered and min(collected) > start_date:
        exhausted = True
        raise TencentKlineTruncated(
            f"Tencent kline for {code} stopped at {min(collected)}, short of the "
            f"requested start {start_date}. The provider's per-request row cap "
            f"makes this window unreachable; coverage is incomplete."
        )
    exhausted = not window_covered

    if not collected:
        raise ChinaDataUnavailableError(
            f"Tencent returned no {expected_key} bars for {code} in "
            f"{start_date}..{end_date}."
        )

    frame = pd.DataFrame(sorted(collected.values(), key=lambda r: r["Date"]))
    frame = frame.reset_index(drop=True)
    return frame, {
        "segments": segments,
        "segment_reports": segment_reports,
        "truncated_by_provider": truncated,
        "segment_budget_exhausted": exhausted,
        "window_covered": window_covered,
    }


def _settled_through(
    end_date: str,
    *,
    period: KlinePeriod = "day",
    now: datetime | None = None,
) -> str:
    """Last session whose bar is complete at fetch time.

    ``day`` responses carry today's unfinished bar during trading hours while
    ``qfq`` responses do not; aligning both on the last settled session is what
    makes the two series comparable (probe §2.6).

    A ``week``/``month`` bar is unfinished for the whole of its own period, so
    the boundary is the last *closed* week or month rather than "yesterday":
    clamping a weekly request to yesterday would keep a partial current-week bar
    in a series the caller is told is settled.

    ``now`` is injectable so the boundary is testable without waiting for 15:00.
    """
    moment = now or datetime.now()
    today = moment.date()
    last_settled_day = (
        today - timedelta(days=1)
        if moment.hour < TENCENT_SETTLED_BAR_CUTOFF_HOUR
        else today
    )
    if period == "week":
        # The week ending on this Friday is settled only after Friday's close.
        days_since_friday = (last_settled_day.weekday() - 4) % 7
        boundary = last_settled_day - timedelta(days=days_since_friday)
    elif period == "month":
        # The current month is never settled; take the previous month's end.
        boundary = last_settled_day.replace(day=1) - timedelta(days=1)
    else:
        boundary = last_settled_day
    settled = boundary.isoformat()
    return end_date if end_date < settled else settled


def _tencent_kline_df(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    adjust: Literal["none", "qfq"],
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if period not in TENCENT_KLINE_PERIODS:
        raise ValueError(f"period must be one of {TENCENT_KLINE_PERIODS!r}")
    code = _tencent_code(ticker)
    effective_end = _settled_through(end_date, period=period, now=now)
    if effective_end < start_date:
        raise ChinaDataUnavailableError(
            f"Tencent kline window {start_date}..{end_date} contains no settled "
            f"{period} bar for the current time of day."
        )
    frame, walk = _fetch_window(
        code,
        start_date=start_date,
        end_date=effective_end,
        adjust=adjust,
        period=period,
        session=session,
    )
    frame = frame[
        (frame["Date"] >= start_date) & (frame["Date"] <= effective_end)
    ].reset_index(drop=True)
    if frame.empty:
        raise ChinaDataUnavailableError(
            f"Tencent returned no {period} bars for {code} inside "
            f"{start_date}..{effective_end}."
        )
    # Drop an in-progress trailing bar if one slipped through (suspended or
    # delayed sessions can leave today's bar present after 15:00 elsewhere).
    assert_ohlc_invariant(frame, context=f"{code} {adjust} {period}")
    provenance = {
        "provider": "tencent",
        "endpoint": "appstock/app/fqkline/get",
        "code": code,
        "period": period,
        "granularity": _PERIOD_GRANULARITY[period],
        "price_basis": "raw" if adjust == "none" else "qfq",
        "adjust_requested": adjust,
        "requested_start": start_date,
        "requested_end": end_date,
        "settled_through": effective_end,
        "column_order": "[date, OPEN, CLOSE, HIGH, LOW, VOLUME]",
        "volume_unit": "lots (100 shares)",
        **walk,
    }
    if adjust == "qfq":
        provenance["pit_status"] = "unverified"
        provenance["adjustment_note"] = _ADJUSTMENT_NOTE
    return frame, provenance


def get_a_share_kline_df(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Unadjusted Tencent bars (daily/weekly/monthly) plus provenance.

    Raw and adjusted are separate entry points on purpose: an adjusted
    capability must never be satisfied by raw bars, and a raw request must not
    silently pick up a different adjustment convention from a vendor switch.
    The same argument applies to ``period``, which is why each (period, adjust)
    pair is registered as its own capability rather than a flag on one method:
    answering a weekly request with daily bars is silently wrong.
    """
    return _tencent_kline_df(
        ticker, start_date, end_date, adjust="none", period=period, session=session, now=now
    )


def get_a_share_kline_qfq_df(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Forward-adjusted Tencent bars, or an error -- never raw bars.

    Raises :class:`ChinaDataUnavailableError` when the endpoint serves the
    unadjusted period key instead of ``qfq<period>``, which the live probe
    observed for ``688981.SH`` and for BSE codes with HTTP 200 and no warning.
    """
    return _tencent_kline_df(
        ticker, start_date, end_date, adjust="qfq", period=period, session=session, now=now
    )


def _render(frame: pd.DataFrame, provenance: dict[str, Any], *, title: str) -> str:
    basis = provenance["price_basis"]
    header = [
        f"# {title}",
        f"# Source: tencent ({provenance['endpoint']})",
        f"# Bar period: {provenance.get('period', 'day')}",
        f"# Price basis: {basis}",
        f"# Settled through: {provenance['settled_through']}",
        "# Volume unit: lots (100 shares).",
        f"# Provenance: {json.dumps(provenance, ensure_ascii=False, sort_keys=True)}",
    ]
    if basis == "qfq":
        header.append(f"# PIT status: {provenance['pit_status']}. {provenance['adjustment_note']}")
    else:
        header.append("# Unadjusted prices; cross-dividend dates carry raw price jumps.")
    return "\n".join(["\n".join(header), "", frame.to_csv(index=False)])


def _kline_report(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    adjust: Literal["none", "qfq"],
    period: KlinePeriod,
    session: requests.Session | None = None,
) -> str:
    """Shared renderer for the router-facing (period, adjust) entry points."""
    getter = get_a_share_kline_qfq_df if adjust == "qfq" else get_a_share_kline_df
    frame, provenance = getter(
        ticker, start_date, end_date, period=period, session=session
    )
    _capture_vendor_raw(frame, metadata=provenance)
    label = _PERIOD_LABEL[period]
    basis = "qfq" if adjust == "qfq" else "raw"
    return _render(
        frame,
        provenance,
        title=f"China A-share {label} bars ({basis}) for "
        f"{normalize_ticker_symbol(ticker)} from {start_date} to {end_date}",
    )


def get_a_share_kline(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
) -> str:
    """Router-facing raw Tencent bars for ``period`` (day/week/month)."""
    return _kline_report(
        ticker, start_date, end_date, adjust="none", period=period, session=session
    )


def get_a_share_kline_qfq(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    period: KlinePeriod = "day",
    session: requests.Session | None = None,
) -> str:
    """Router-facing forward-adjusted Tencent bars for ``period``."""
    return _kline_report(
        ticker, start_date, end_date, adjust="qfq", period=period, session=session
    )


# Each (period, adjust) pair is its own registered capability.  A router that
# could satisfy a weekly request from a daily vendor would silently change the
# bar width, so the period is part of the method identity, not an argument the
# fallback chain may drop.

def get_a_share_kline_weekly(ticker: str, start_date: str, end_date: str) -> str:
    """Router-facing raw Tencent weekly bars."""
    return get_a_share_kline(ticker, start_date, end_date, period="week")


def get_a_share_kline_weekly_qfq(ticker: str, start_date: str, end_date: str) -> str:
    """Router-facing forward-adjusted Tencent weekly bars."""
    return get_a_share_kline_qfq(ticker, start_date, end_date, period="week")


def get_a_share_kline_monthly(ticker: str, start_date: str, end_date: str) -> str:
    """Router-facing raw Tencent monthly bars."""
    return get_a_share_kline(ticker, start_date, end_date, period="month")


def get_a_share_kline_monthly_qfq(ticker: str, start_date: str, end_date: str) -> str:
    """Router-facing forward-adjusted Tencent monthly bars."""
    return get_a_share_kline_qfq(ticker, start_date, end_date, period="month")


def trading_day_count(start_date: str, end_date: str) -> int:
    """Upper bound on sessions in a window, used to detect short pages."""
    span = date.fromisoformat(end_date) - date.fromisoformat(start_date)
    return span.days + 1


def _capture_vendor_raw(data: Any, *, metadata: dict[str, Any]) -> None:
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(data, metadata=dict(metadata))
