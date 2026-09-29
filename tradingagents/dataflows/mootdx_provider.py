"""mootdx (通达信 TCP 7709) A-share OHLCV provider -- no IP ban, zero key.

The TDX binary protocol over TCP 7709 is not rate-limited and never IP-bans,
unlike the EastMoney HTTP endpoints behind tushare/akshare, so it stays
registered for A-share quotes, finance snapshots, and F10.

**It is no longer the rank-1 daily-bar source.**  The 2026-09-29 live probe
(docs/superpowers/operations/capability-probe-2026-09-29.md §4) recorded 13/13
failures: 3 of 8 servers complete the TCP handshake and ``Quotes.factory()``
returns a real ``StdQuotes``, but every data call returns an empty DataFrame
with no columns.  The old code therefore burned 25-28s probing servers on every
single A-share request before falling back to tushare.  Two mitigations:

* the in-process circuit breaker in :func:`tdx_client` (see
  :data:`_TDX_BREAKER_COOLDOWN_SECONDS`), and
* mootdx sitting *after* tushare in ``registry.VENDOR_METHODS['get_stock_data']``.

tushare/akshare remain as fallbacks for when every TDX server is unreachable.

The mootdx 0.11.x library carries a BESTIP bug where a fresh install leaves
``BESTIP.HQ`` misconfigured and ``Quotes.factory`` cannot unpack it.
``tdx_client()`` below probes a server list with a *real one-bar fetch*
(not just a TCP handshake, which is a false positive -- broken servers
handshake then return an empty body) and reuses the first server that
actually returns data.  See a-stock-data SKILL.md §1.1 + V3.7.1.
"""

from __future__ import annotations

import logging
import socket
import time
from datetime import datetime
from typing import Any

import pandas as pd

from .china_data import ChinaDataUnavailableError
from .ticker_utils import is_a_share_ticker, normalize_ticker_symbol, to_akshare_symbol

logger = logging.getLogger(__name__)

# TDX quote servers (host, port).  Order matters: the first server that
# returns real bar data wins.  Not every TCP-reachable server actually serves
# bars -- some accept the connection then send an empty body -- so
# tdx_client() validates each candidate with a real one-bar fetch.
_TDX_SERVERS: list[tuple[str, int]] = [
    ("218.75.126.9", 7709),    # config BESTIP, verified 2026-07
    ("110.41.147.114", 7709),  # 深圳双线主站1
    ("8.129.13.54", 7709),     # 深圳双线主站2
    ("47.100.236.28", 7709),   # 上海双线主站2
    ("121.36.54.217", 7709),   # 北京双线主站1
    ("124.71.85.110", 7709),   # 广州双线主站1
    ("119.97.185.59", 7709),   # 武汉电信主站1
    ("124.70.176.52", 7709),   # 上海双线主站1
]

# mootdx bars() caps offset at 800 per call; daily bars need pagination to
# cover the 5-year window the OHLCV cache expects.
_BAR_PAGE_SIZE = 800
_BAR_MAX_PAGES = 4  # 4 * 800 = 3200 daily bars ≈ 12.8 years

# Module-level cache: reusing a validated client avoids re-probing on every call.
_tdx_client_cache: Any = None

# --- T-D1 fast circuit breaker -------------------------------------------------
#
# Live probe (2026-09-29, capability-probe-2026-09-29.md §4) found the TDX
# binary protocol *silently* dead on this network: 3 of 8 servers complete the
# TCP handshake and `Quotes.factory()` returns a real `StdQuotes`, but every
# data call yields an empty DataFrame with no columns.  Because
# ``_validate_bar_fetch`` rejects those servers one by one, a single request
# paid 25-28s before the router ever reached tushare -- and it paid it again
# on the *next* request, because nothing remembered the outcome.
#
# The breaker below records "no server served bars" and refuses to re-probe
# until the cooldown expires, turning a ~26s per-request tax into ~0s.  It is
# deliberately local to this module: the shared VendorHealthRegistry keys on
# (vendor, market, capability), and mootdx's finance/F10 capabilities go
# through the same `tdx_client()`.  Suppressing only the daily-bar probe keeps
# those capabilities independently re-probeable if the server list recovers.
_TDX_BREAKER_COOLDOWN_SECONDS = 300.0
_tdx_probe_failure_until: float = 0.0
_tdx_probe_failure_count: int = 0


def _validate_bar_fetch(client: Any, symbol: str = "000001") -> bool:
    """Return True only if the client actually returns bar rows.

    A TCP handshake alone is a false positive: some servers accept the
    connection then return an empty body.  We require one real daily bar.
    """
    try:
        klines = client.bars(symbol=symbol, frequency=9, offset=1)
        return klines is not None and not klines.empty
    except Exception:
        return False


def tdx_client(market: str = "std") -> Any:
    """Create a validated mootdx client, bypassing the 0.11.x BESTIP bug.

    Probes each candidate server with a real one-bar fetch; the first that
    returns data wins and is cached for reuse.  Raises
    :class:`ChinaDataUnavailableError` when no server serves bars (common
    overseas -- TCP 7709 is typically blocked), so the router falls back to
    tushare/akshare.

    When every candidate has failed, an in-process circuit breaker short-circuits
    subsequent calls for :data:`_TDX_BREAKER_COOLDOWN_SECONDS` instead of paying
    the full server sweep again.  Without it a dead TDX network costs ~26s on
    *every* A-share request, not just the first one.
    """
    global _tdx_client_cache
    if _tdx_client_cache is not None:
        return _tdx_client_cache

    if _tdx_breaker_open():
        raise ChinaDataUnavailableError(
            f"mootdx/TDX server probe failed {_tdx_probe_failure_count} time(s); "
            f"circuit breaker open for another "
            f"{_tdx_breaker_remaining():.0f}s. tushare/akshare fallback applies."
        )

    from mootdx.quotes import Quotes  # optional dependency, lazy import

    for ip, port in _TDX_SERVERS:
        try:
            with socket.create_connection((ip, port), timeout=3):
                pass
        except OSError:
            continue
        try:
            client = Quotes.factory(market=market, server=(ip, port))
        except Exception as exc:
            logger.debug("mootdx factory failed for %s: %s", ip, exc)
            continue
        if _validate_bar_fetch(client):
            _tdx_client_cache = client
            _close_tdx_breaker()
            logger.debug("mootdx validated server: %s:%s", ip, port)
            return client
    _open_tdx_breaker()
    raise ChinaDataUnavailableError(
        "No mootdx/TDX server returned bar data. The TCP 7709 protocol may be "
        "unreachable from this network (common overseas); tushare/akshare fallback applies."
    )


def _tdx_breaker_open() -> bool:
    """True while a prior full-server sweep failed and its cooldown is live."""
    return time.monotonic() < _tdx_probe_failure_until


def _tdx_breaker_remaining() -> float:
    return max(0.0, _tdx_probe_failure_until - time.monotonic())


def _open_tdx_breaker() -> None:
    global _tdx_probe_failure_until, _tdx_probe_failure_count
    _tdx_probe_failure_count += 1
    _tdx_probe_failure_until = time.monotonic() + _TDX_BREAKER_COOLDOWN_SECONDS
    logger.warning(
        "mootdx/TDX: no server returned bar data (attempt %d); circuit breaker "
        "open for %.0fs so later requests skip the ~26s server sweep.",
        _tdx_probe_failure_count,
        _TDX_BREAKER_COOLDOWN_SECONDS,
    )


def _close_tdx_breaker() -> None:
    global _tdx_probe_failure_until, _tdx_probe_failure_count
    _tdx_probe_failure_until = 0.0
    _tdx_probe_failure_count = 0


def _reset_tdx_client_cache() -> None:
    """Clear the cached client (test hook for swapping servers between cases)."""
    global _tdx_client_cache
    _tdx_client_cache = None
    _close_tdx_breaker()


def _a_share_code(ticker: str) -> str:
    canonical = normalize_ticker_symbol(ticker)
    if not is_a_share_ticker(canonical):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return to_akshare_symbol(canonical)


def get_fundamentals_mootdx(ticker: str, curr_date: str | None = None) -> str:
    """Return mootdx's 37-field quarterly A-share financial snapshot."""
    code = _a_share_code(ticker)
    client = tdx_client()
    try:
        raw = client.finance(symbol=code)
    except Exception as exc:
        raise ChinaDataUnavailableError(f"mootdx finance failed for {code}: {type(exc).__name__}") from exc
    if raw is None or (hasattr(raw, "empty") and raw.empty):
        raise ChinaDataUnavailableError(f"mootdx returned no finance snapshot for {code}.")
    from tradingagents.observability.provenance import capture_vendor_raw

    payload = raw.to_dict(orient="records") if isinstance(raw, pd.DataFrame) else raw
    capture_vendor_raw(payload, metadata={"provider": "mootdx", "dataset": "finance_snapshot", "ticker": ticker, "as_of": curr_date})
    frame = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame([raw] if isinstance(raw, dict) else raw)
    return "\n".join([
        f"# China A-share mootdx finance snapshot for {normalize_ticker_symbol(ticker)}",
        "# Source: mootdx",
        "# Data type: quarterly snapshot; not real-time fundamentals",
        f"# Analysis cutoff: {curr_date or 'not supplied'}",
        "# Raw monetary units and field meanings must be read from the source schema.",
        "",
        frame.to_csv(index=False),
    ])


def get_a_share_f10(ticker: str, category: str = "最新提示") -> str:
    """Return a bounded mootdx F10 company-information section."""
    allowed = {"最新提示", "公司概况", "财务分析", "股东研究", "股本结构", "资本运作", "业内点评", "行业分析", "公司大事"}
    if category not in allowed:
        raise ValueError(f"unsupported F10 category: {category}")
    code = _a_share_code(ticker)
    client = tdx_client()
    try:
        text = str(client.F10(symbol=code, name=category) or "").strip()
    except Exception as exc:
        raise ChinaDataUnavailableError(f"mootdx F10 failed for {code}: {type(exc).__name__}") from exc
    if not text:
        raise ChinaDataUnavailableError(f"mootdx returned no F10 text for {code}/{category}.")
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw({"category": category, "text": text}, metadata={"provider": "mootdx", "dataset": "f10", "ticker": ticker})
    # F10股东研究可能包含上万字历史表格；保留最新上下文的有界前缀。
    return "\n".join([
        f"# China A-share F10 for {normalize_ticker_symbol(ticker)}",
        "# Source: mootdx",
        f"# Category: {category}",
        "# Text is source material, not an interpreted company fact.",
        "",
        text[:12000],
    ])
def _format_mootdx_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Rename mootdx columns to the local OHLCV schema.

    mootdx returns both ``vol`` and ``volume``; ``vol`` is in lots (consistent
    with tushare/akshare), so it is preferred.  ``datetime`` is
    'YYYY-MM-DD HH:MM' (daily bars carry 15:00) and is truncated to the date.
    Only the target OHLCV columns are retained so the unrelated ``volume``
    column does not leak through alongside the renamed ``vol``.
    """
    vol_col = "vol" if "vol" in df.columns else ("volume" if "volume" in df.columns else None)
    renamed = df.rename(
        columns={
            "datetime": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "amount": "Amount",
            **({vol_col: "Volume"} if vol_col else {}),
        }
    )
    target = ["Date", "Open", "High", "Low", "Close", "Volume", "Amount"]
    renamed = renamed[[c for c in target if c in renamed.columns]].copy()
    if "Date" in renamed.columns:
        renamed["Date"] = pd.to_datetime(renamed["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        renamed = renamed.sort_values("Date").drop_duplicates(subset=["Date"]).reset_index(drop=True)
    return renamed


def _fetch_all_bars(client: Any, code: str) -> pd.DataFrame:
    """Fetch daily bars via pagination (mootdx caps offset at 800 per call)."""
    frames: list[pd.DataFrame] = []
    for page in range(_BAR_MAX_PAGES):
        start = page * _BAR_PAGE_SIZE
        klines = client.bars(symbol=code, frequency=9, start=start, offset=_BAR_PAGE_SIZE)
        if klines is None or klines.empty:
            break
        frames.append(klines)
        if len(klines) < _BAR_PAGE_SIZE:
            break
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def get_stock_mootdx_df(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """A-share daily OHLCV as a DataFrame from mootdx (primary A-share vendor).

    mootdx ``bars`` returns the most recent ``offset`` bars (not a date range),
    so we paginate and then filter to ``[start_date, end_date]``.  Prices are
    **unadjusted** -- mootdx has no adjust parameter; cross-ex-dividend dates
    carry raw price jumps.  tushare/akshare defaults are likewise unadjusted,
    so the vendor switch does not silently change the adjustment convention.
    """
    code = _a_share_code(symbol)
    client = tdx_client()
    raw = _fetch_all_bars(client, code)
    if raw.empty:
        raise ChinaDataUnavailableError(f"mootdx returned no daily bars for {code}.")
    formatted = _format_mootdx_daily(raw)
    if "Date" not in formatted.columns:
        raise ChinaDataUnavailableError(f"mootdx bars for {code} have no datetime column.")
    selected = formatted[(formatted["Date"] >= start_date) & (formatted["Date"] <= end_date)]
    if selected.empty:
        raise ChinaDataUnavailableError(
            f"mootdx returned no rows for {code} in {start_date}..{end_date}."
        )
    _capture_vendor_raw(formatted, metadata={"provider": "mootdx", "dataset": "daily_bars", "ticker": symbol})
    return selected.reset_index(drop=True)


def get_stock_mootdx(symbol: str, start_date: str, end_date: str) -> str:
    """A-share daily OHLCV markdown report from mootdx (router-facing)."""
    df = get_stock_mootdx_df(symbol, start_date, end_date)
    return "\n".join(
        [
            f"# China A-share stock data for {normalize_ticker_symbol(symbol)} from {start_date} to {end_date}",
            "# Source: mootdx",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# Note: mootdx returns unadjusted prices (no adjust parameter).",
            f"# Total records: {len(df)}",
            "",
            df.to_csv(index=False),
        ]
    )


def _capture_vendor_raw(data: Any, *, metadata: dict[str, Any]) -> None:
    """Capture provenance only after a provider call succeeds (lazy import)."""
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(data, metadata=dict(metadata))
