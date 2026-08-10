from datetime import datetime
from io import StringIO

import pandas as pd

from .alpha_vantage_common import _filter_csv_by_date_range, _make_api_request
from .coverage import CoveredText, PriceSeriesCoverageV1


def get_stock(
    symbol: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Returns raw daily OHLCV values, adjusted close values, and historical split/dividend events
    filtered to the specified date range.

    Args:
        symbol: The name of the equity. For example: symbol=IBM
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing the daily adjusted time series data filtered to the date range.
    """
    # Parse dates to determine the range
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.now()

    # Choose outputsize based on whether the requested range is within the latest 100 days
    # Compact returns latest 100 data points, so check if start_date is recent enough
    days_from_today_to_start = (today - start_dt).days
    outputsize = "compact" if days_from_today_to_start < 100 else "full"

    params = {
        "symbol": symbol,
        "outputsize": outputsize,
        "datatype": "csv",
    }

    response = _make_api_request("TIME_SERIES_DAILY_ADJUSTED", params)

    return _filter_csv_by_date_range(response, start_date, end_date)


def get_adjusted_stock(
    symbol: str,
    start_date: str,
    end_date: str,
) -> CoveredText:
    """Return fully adjusted OHLC, not raw OHLC beside adjusted close."""
    raw = get_stock(symbol, start_date, end_date)
    frame = pd.read_csv(StringIO(raw))
    required = {"timestamp", "open", "high", "low", "close", "adjusted_close"}
    if frame.empty or not required <= set(frame.columns):
        raise ValueError("Alpha Vantage adjusted daily response lacks required OHLC fields")
    numeric = frame[["open", "high", "low", "close", "adjusted_close"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    valid = numeric["close"].notna() & numeric["adjusted_close"].notna()
    valid &= numeric["close"] != 0
    frame = frame.loc[valid].copy()
    numeric = numeric.loc[valid]
    if frame.empty:
        raise ValueError("Alpha Vantage adjusted daily response has no usable rows")
    factor = numeric["adjusted_close"] / numeric["close"]
    for column in ("open", "high", "low", "close"):
        frame[column] = (numeric[column] * factor).round(6)
    frame["close"] = numeric["adjusted_close"].round(6)
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    frame = frame[
        (frame["timestamp"] >= start_date) & (frame["timestamp"] <= end_date)
    ]
    if frame.empty:
        raise ValueError("Alpha Vantage adjusted response has no rows in requested window")
    actual_start = str(frame["timestamp"].iloc[0])
    actual_end = str(frame["timestamp"].iloc[-1])
    exact_boundaries = actual_start == start_date and actual_end == end_date
    coverage = PriceSeriesCoverageV1(
        capability="adjusted_price_history",
        source_id="alpha_vantage.TIME_SERIES_DAILY_ADJUSTED",
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        item_count=len(frame),
        completeness="complete" if exact_boundaries else "unknown",
        sources=("alpha_vantage.TIME_SERIES_DAILY_ADJUSTED",),
        degradations=(
            () if exact_boundaries else ("trading_calendar_boundaries_not_proven",)
        ),
        as_of=end_date,
        price_basis="split_dividend_adjusted",
        adjustment_source="alpha_vantage.adjusted_close_ratio",
        adjustment_verified=True,
        granularity="daily",
    )
    rendered = "\n".join(
        [
            f"# Adjusted stock data for {symbol} from {start_date} to {end_date}",
            "# Source: alpha_vantage.TIME_SERIES_DAILY_ADJUSTED",
            "# Price basis: split_dividend_adjusted",
            "# Adjustment source: adjusted_close / close ratio applied to OHLC",
            "",
            frame.to_csv(index=False),
        ]
    )
    return CoveredText(rendered, coverage)
