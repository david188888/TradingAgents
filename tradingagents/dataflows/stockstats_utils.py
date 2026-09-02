import logging
import os
import time
from pathlib import Path
from typing import Annotated

import pandas as pd
import yfinance as yf
from stockstats import wrap
from yfinance.exceptions import YFRateLimitError

try:
    # curl_cffi is a yfinance dependency; guard the import so a broken or
    # optional environment never breaks this module's import itself.
    from curl_cffi.requests.exceptions import (
        CertificateVerifyError as _CurlCertificateVerifyError,
        ConnectionError as _CurlConnectionError,
        Timeout as _CurlTimeout,
    )

    _CURL_TRANSIENT_ERRORS = (_CurlConnectionError, _CurlTimeout)
    _CURL_NON_TRANSIENT_ERRORS = (_CurlCertificateVerifyError,)

    def _is_curl_transient(exc: BaseException) -> bool:
        """True for curl transport failures that heal on their own.

        Covers connection refused/dropped (curl 7/52/56), TLS connect races
        such as right after a VPN link comes up (curl 35 -> SSLError, which is
        a ConnectionError subclass), and timeouts (curl 28). Certificate
        verification failures (curl 60) are excluded: a bad cert will not heal.
        """
        return isinstance(exc, _CURL_TRANSIENT_ERRORS) and not isinstance(
            exc, _CURL_NON_TRANSIENT_ERRORS
        )

except Exception:  # pragma: no cover - curl_cffi is a yfinance dependency
    def _is_curl_transient(exc: BaseException) -> bool:
        return False


from .config import get_config
from .symbol_utils import NoMarketDataError, normalize_symbol
from .ticker_utils import is_a_share_ticker
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# A vendor's latest OHLCV row this many calendar days before the requested date
# is treated as stale. Generous enough to span long holiday weekends, tight
# enough to catch the year-old frames yfinance occasionally returns (#1021).
MAX_OHLCV_STALE_DAYS = 10

# How long a same-day cache that does not yet reach the requested day may be
# reused before it is refetched (#1150). Short enough that an intraday run picks
# up today's close soon after it publishes, long enough that a day with no bar
# at all (weekend, holiday) cannot trigger a download on every call.
OHLCV_CACHE_TTL_SECONDS = 900


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on transient failures.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not retry
    them internally. This wrapper adds retry logic for rate limits and for
    transient curl transport failures -- connection refused/dropped, TLS
    connect races (e.g. right after a VPN link comes up), and timeouts --
    which also heal on their own. Certificate verification errors and all
    other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Yahoo Finance rate limited, retrying in %.0fs (attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                time.sleep(delay)
            else:
                raise
        except Exception as exc:
            if _is_curl_transient(exc) and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Yahoo Finance transient transport error %s, retrying in %.0fs (attempt %d/%d)",
                    type(exc).__name__, delay, attempt + 1, max_retries,
                )
                time.sleep(delay)
            else:
                raise


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize the date column to ``Date``.

    Some yfinance builds leave the index unnamed (so ``reset_index()`` yields
    ``index``) or use ``Datetime`` for intraday data. Rename the first
    date-like column so indicators don't silently drop when it isn't ``Date``.
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _local_midnight(value) -> pd.Timestamp:
    """A single timestamp as its naive, midnight-normalized local date (or NaT)."""
    if pd.isna(value):
        return pd.NaT
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return pd.NaT
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)  # drop tz, keep the local wall-clock date
    return ts.normalize()


def _normalize_dates(dates) -> pd.Series:
    """Parse to naive, midnight-normalized dates so tz-aware or intraday
    timestamps compare correctly against the naive ``curr_date`` cutoff
    (upstream #1201).

    Normalized per element: 5 years of yfinance bars span daylight-saving
    changes (and cache CSVs round-trip the offsets as strings), so the series
    can carry mixed UTC offsets that ``pd.to_datetime`` cannot unify without
    ``utc=True`` — which would shift non-US (positive-offset) markets to the
    previous day. Keeping each bar's own local date avoids both.
    """
    return pd.to_datetime(pd.Series(dates).map(_local_midnight))


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Parse and normalize an OHLCV frame without inventing values.

    Dates are parsed per element (DST- and non-US-market safe) and prices are
    coerced to numeric. Dropping incomplete rows is left to
    ``_drop_incomplete_rows`` so the caller can first inspect the latest
    in-range bar (upstream #1201).
    """
    data = _ensure_date_column(data)
    data["Date"] = _normalize_dates(data["Date"])
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    return data


def _fill_price_gaps(data: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with no close and forward/back-fill remaining price gaps so
    indicators compute on a continuous series."""
    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    # copy() so a filtered (sliced) input is written to safely, not via a view.
    data = data.dropna(subset=["Close"]).copy()
    data[price_cols] = data[price_cols].ffill().bfill()
    return data


def _drop_incomplete_rows(data: pd.DataFrame) -> pd.DataFrame:
    """Drop rows missing any OHLC price without inventing historical values.

    Missing OHLC rows are unusable for price analysis and are dropped. Volume
    may remain unknown; it is never forward- or backward-filled because either
    operation would manufacture trading activity.
    """
    required_price_cols = [
        column for column in ("Open", "High", "Low", "Close") if column in data
    ]
    return data.dropna(subset=required_price_cols)


def _coerce_ohlcv_dates(data: pd.DataFrame) -> pd.Series:
    """Return parsed dates from an OHLCV frame, whether Date is a column or the index.

    Uses the same per-element normalization as ``_clean_dataframe`` so raw
    vendor frames with mixed UTC offsets (e.g. cache CSVs spanning DST) parse
    instead of failing or shifting dates (upstream #1201).
    """
    if "Date" in data.columns:
        return _normalize_dates(data["Date"]).dropna()
    # yfinance keeps the dates in the index (a DatetimeIndex, sometimes unnamed).
    if isinstance(data.index, pd.DatetimeIndex):
        return _normalize_dates(pd.Series(list(data.index))).dropna()
    # Fallback: expose the index and look for any date-like column.
    df = data.reset_index()
    for col in ("Date", "Datetime", "date", "index"):
        if col in df.columns:
            parsed = _normalize_dates(df[col]).dropna()
            if not parsed.empty:
                return parsed
    return pd.Series(dtype="datetime64[ns]")


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """Reject OHLCV whose latest row is far older than curr_date.

    Raises NoMarketDataError (with a stale-specific detail) so the router treats
    it like any other "no usable data from this vendor" — try the next vendor,
    then emit one clear unavailable signal. Empty frames are left to the
    caller's existing no-data handling; this guards only the dangerous case of
    present-but-stale rows (a vendor returning a year-old frame that would
    otherwise feed wrong prices to the agent, #1021).
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = _coerce_ohlcv_dates(data)
    if dates.empty:
        return
    latest = dates.max().normalize()
    stale_days = (requested - latest).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )


def _needs_same_day_refresh(data_file, curr_date_dt, today_date) -> bool:
    """Whether a cached frame must be refetched to reflect the requested day.

    The cache file is keyed per day, so without this a run started before the
    day's bar was final keeps serving that snapshot to every later run (#1150).
    Two distinct staleness cases exist for a current-day request: the bar may be
    missing entirely, or present but still in progress — Yahoo publishes a
    partial daily candle during market hours, whose ``Close`` is not the closing
    price. Row inspection cannot tell a partial bar from a final one, so the TTL
    governs every current-day cache. Historical requests always reuse the cache,
    since those rows are immutable.
    """
    if curr_date_dt.date() < today_date.date():
        return False
    return time.time() - os.path.getmtime(data_file) > OHLCV_CACHE_TTL_SECONDS


def load_ohlcv(symbol: str, curr_date: str, via_vendor: bool = False) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.

    When ``via_vendor=True`` and ``symbol`` is an A-share ticker, route through
    tushare/akshare (see ``_load_ohlcv_a_share``) instead of yfinance, because
    yfinance's .SZ/.SS OHLCV coverage is unreliable for A-shares. The yfinance
    vendor itself calls this without ``via_vendor`` and must stay on yfinance.
    """
    if via_vendor and is_a_share_ticker(symbol):
        return _load_ohlcv_a_share(symbol, curr_date)
    # Resolve broker/forex symbols (XAUUSD+ -> GC=F) to Yahoo's convention,
    # then reject values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date).normalize()

    # Cache uses a fixed window (5y to today) so one file per symbol.
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    # yfinance ``end`` is EXCLUSIVE; request tomorrow so today's row is included
    # when curr_date is the current day (#986). Look-ahead is still prevented by
    # the curr_date filter below.
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    # A cached file may be empty if a prior fetch failed (unknown symbol,
    # transient rate limit). Treat an empty/columnless cache as a miss and
    # re-fetch rather than serving the poisoned file forever.
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        # Serve the cache only when it is usable and not a stale snapshot of the
        # day being requested (#1150); otherwise fall through and refetch.
        if (
            not cached.empty
            and "Close" in cached.columns
            and not _needs_same_day_refresh(data_file, curr_date_dt, today_date)
        ):
            data = cached

    if data is None:
        downloaded = yf_retry(lambda: yf.download(
            canonical,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        downloaded = _ensure_date_column(downloaded.reset_index())
        # Only cache real data — never persist an empty frame.
        if downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(
                symbol, canonical, "Yahoo Finance returned no rows"
            )
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)
    data.attrs["source_id"] = "yfinance.ohlcv"

    # Filter to curr_date to prevent look-ahead bias in backtesting.
    data = data[data["Date"] <= curr_date_dt]

    # Guard the latest in-range bar before dropping incomplete rows: a newest bar
    # with no close is "not settled yet", not "does not exist". Silently dropping
    if not data.empty and pd.isna(data["Close"].iloc[-1]):
        raise NoMarketDataError(
            symbol, canonical, "latest in-range OHLCV bar has no closing price"
        )
    data = _drop_incomplete_rows(data)

    # Reject a stale frame (latest row far older than curr_date) rather than
    # feeding year-old prices into indicators (#1021).
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)

    return data


def _load_ohlcv_a_share(symbol: str, curr_date: str) -> pd.DataFrame:
    """A-share OHLCV via mootdx/tushare/akshare, with caching + look-ahead + stale guard.

    Mirrors ``load_ohlcv``'s contract (5y window, per-symbol CSV cache,
    curr_date filter, stale rejection) but pulls from mootdx (TCP 7709, no IP
    ban) with tushare/akshare fallback, so the verified-snapshot and indicator
    tools get real A-share rows instead of yfinance's unreliable .SZ/.SS
    coverage.
    """
    from .china_data import (
        _require_a_share_tushare_symbol,
        get_stock_akshare_df,
        get_stock_tushare_df,
    )
    from .mootdx_provider import get_stock_mootdx_df

    canonical = _require_a_share_tushare_symbol(symbol)  # 300750 -> 300750.SZ
    safe_symbol = safe_ticker_component(canonical)
    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date).normalize()

    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-Tushare-data-{start_str}-{end_str}.csv",
    )

    data = None
    source_id: str | None = None
    source_file = f"{data_file}.source"
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if (
            not cached.empty
            and "Close" in cached.columns
            and not _needs_same_day_refresh(data_file, curr_date_dt, today_date)
        ):
            data = cached
            try:
                source_id = Path(source_file).read_text(encoding="utf-8").strip() or None
            except OSError:
                source_id = None

    if data is None:
        errors: list[str] = []
        for fetch, name, candidate_source_id in (
            (get_stock_mootdx_df, "mootdx", "mootdx.daily_bars"),
            (get_stock_tushare_df, "tushare", "tushare.tushare_get_stock"),
            (get_stock_akshare_df, "akshare", "akshare.daily_bars"),
        ):
            try:
                fetched = fetch(symbol, start_str, end_str)
                if fetched is not None and not fetched.empty and "Close" in fetched.columns:
                    data = fetched
                    source_id = candidate_source_id
                    break
                errors.append(f"{name}: empty result")
            except Exception as exc:  # noqa: BLE001 - try next vendor
                errors.append(f"{name}: {exc}")
        if data is None:
            raise NoMarketDataError(
                symbol,
                canonical,
                "A-share vendors (mootdx/tushare/akshare) returned no rows ("
                + "; ".join(errors)
                + ")",
            )
        data.to_csv(data_file, index=False, encoding="utf-8")
        if source_id is not None:
            Path(source_file).write_text(source_id, encoding="utf-8")

    data = _clean_dataframe(data)
    if source_id is not None:
        data.attrs["source_id"] = source_id
    data = data[data["Date"] <= curr_date_dt]

    # Guard the latest in-range bar before dropping incomplete rows (upstream
    # #1201): a newest bar with no close is "not settled yet", not "does not
    # exist".
    if not data.empty and pd.isna(data["Close"].iloc[-1]):
        raise NoMarketDataError(
            symbol, canonical, "latest in-range OHLCV bar has no closing price"
        )
    data = _drop_incomplete_rows(data)
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)
    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date, via_vendor=True)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
