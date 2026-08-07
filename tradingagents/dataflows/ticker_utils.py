"""Ticker normalization helpers for market-specific data providers."""

from __future__ import annotations

import re

_A_SHARE_EXCHANGE_BY_PREFIX = {
    "0": "SZ",
    "2": "SZ",
    "3": "SZ",
    "4": "BJ",
    "6": "SH",
    "8": "BJ",
    "9": "SH",
}

# Shanghai-listed index codes (000xxx segment) that must route to the SH
# exchange, not the SZ fallback a bare prefix would infer.  Verified against
# a-stock-data's ``SH_INDEX`` whitelist; ``000001`` stays SZ (Ping An Bank)
# unless the caller passes an explicit ``sh`` prefix / ``.SS`` suffix.
_SH_INDEX_CODES = frozenset({"000300", "000905", "000016", "000688", "000852", "000010"})

# Beijing Stock Exchange new-segment prefix: since 2024-04 new listings use the
# 920xxx segment and since 2025-10 the old 43/83/87 codes are fully retired
# (renumbered to 920xxx).  ``92`` must be matched before the generic ``9`` -> SH
# rule so a BSE code is never routed to Shanghai.
_BJ_NEW_SEGMENT_PREFIX = "92"


def infer_a_share_exchange(code: str) -> str | None:
    """Infer exchange from a six-digit A-share code.

    Checks the Shanghai index whitelist first, then the Beijing 920xxx segment,
    then the legacy prefix map.
    """
    if not re.fullmatch(r"\d{6}", str(code or "")):
        return None
    if code in _SH_INDEX_CODES:
        return "SH"
    if code.startswith(_BJ_NEW_SEGMENT_PREFIX):
        return "BJ"
    return _A_SHARE_EXCHANGE_BY_PREFIX.get(code[0])


def normalize_ticker_symbol(ticker: str) -> str:
    """Normalize user ticker input while preserving exchange suffixes.

    A-share bare six-digit codes are converted to Yahoo-style suffixes because
    the rest of the app already treats suffix-qualified tickers as canonical.
    """
    value = str(ticker or "").strip().upper()
    if not value:
        return value

    value = value.replace("_", ".")
    compact = re.sub(r"[^A-Z0-9]", "", value)

    if re.fullmatch(r"\d{6}", compact):
        exchange = infer_a_share_exchange(compact)
        return _format_canonical_a_share(compact, exchange) if exchange else compact

    prefix_match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", compact)
    if prefix_match:
        exchange, code = prefix_match.groups()
        return _format_canonical_a_share(code, exchange)

    suffix_match = re.fullmatch(r"(\d{6})(SH|SS|SZ|BJ)", compact)
    if suffix_match:
        code, exchange = suffix_match.groups()
        return _format_canonical_a_share(code, exchange)

    return value


def is_a_share_ticker(ticker: str) -> bool:
    """Return True when the ticker looks like a Shanghai/Shenzhen/Beijing A-share."""
    canonical = normalize_ticker_symbol(ticker)
    return bool(re.fullmatch(r"\d{6}\.(SS|SH|SZ|BJ)", canonical))


def to_yfinance_symbol(ticker: str) -> str:
    """Convert a ticker to the suffix convention expected by Yahoo Finance."""
    canonical = normalize_ticker_symbol(ticker)
    if canonical.endswith(".SH"):
        return canonical[:-3] + ".SS"
    return canonical


def to_tushare_symbol(ticker: str) -> str:
    """Convert a ticker to the ts_code convention expected by Tushare."""
    canonical = normalize_ticker_symbol(ticker)
    if canonical.endswith(".SS"):
        return canonical[:-3] + ".SH"
    return canonical


def to_akshare_symbol(ticker: str) -> str:
    """Convert a ticker to the bare six-digit symbol used by common AKShare APIs."""
    canonical = normalize_ticker_symbol(ticker)
    if is_a_share_ticker(canonical):
        return canonical.split(".", 1)[0]
    return canonical


def to_akshare_prefixed_symbol(ticker: str) -> str:
    """Convert to AKShare's occasional exchange-prefixed convention, e.g. SZ000001."""
    tushare_symbol = to_tushare_symbol(ticker)
    if "." not in tushare_symbol:
        return tushare_symbol
    code, exchange = tushare_symbol.split(".", 1)
    return f"{exchange}{code}"


def _format_canonical_a_share(code: str, exchange: str) -> str:
    if exchange == "SH":
        return f"{code}.SS"
    return f"{code}.{exchange}"
