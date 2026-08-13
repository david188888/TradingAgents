"""Ticker normalization helpers for market-specific data providers."""

from __future__ import annotations

import re

_A_SHARE_EXCHANGE_BY_PREFIX = {
    "0": "SZ",
    "1": "SZ",  # Shenzhen ETFs/LOFs (159xxx/16xxx segments)
    "2": "SZ",
    "3": "SZ",
    "4": "BJ",
    "5": "SH",  # Shanghai ETFs/LOFs (510xxx/512xxx/518xxx/588xxx segments)
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

# Strict ticker forms accepted by research/EPS-style endpoints that only
# understand a bare six-digit code.  A market identifier may appear either as
# a prefix (SH600519) or a suffix (600519.SH), never both.  Anchored so a
# 7-digit or mixed string is rejected instead of silently truncated.
_STRICT_TICKER_RE = re.compile(
    r"^(?:(SH|SZ|BJ)(\d{6})|(\d{6})(?:\.(SH|SZ|BJ))?)$",
    re.IGNORECASE,
)


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


def _natural_market(digits: str) -> str:
    """The market a six-digit A-share code naturally belongs to.

    Used only to validate an explicit market identifier; never to guess.
    ``000xxx`` is intentionally ambiguous (SH index / SZ stock) and is handled
    by the caller, mirroring a-stock-data's ``norm_ticker``.
    """
    if digits.startswith("92") or digits[:2] in ("43", "83", "87"):
        return "BJ"
    if digits[0] in ("5", "6", "9"):
        return "SH"
    return "SZ"


def strict_ticker_code(code: str, *, stock_only: bool = False) -> str:
    """Parse a supported ticker form into a bare six-digit A-share code.

    Accepts ``600519`` / ``SH600519`` / ``600519.SH`` / ``BJ920982``.  Raises
    ``ValueError`` on malformed or ambiguous input instead of guessing a code:
    silently picking the wrong instrument (for example ``SH000001`` as Ping An
    Bank, or truncating ``6005190`` to ``600519``) is worse than failing
    loudly.  ``stock_only`` rejects explicit Shanghai index codes (``000xxx``)
    for stock-only endpoints such as research reports and consensus forecasts.
    """
    raw = str(code or "").strip()
    match = _STRICT_TICKER_RE.match(raw)
    if not match:
        raise ValueError(
            f"无法把 {code!r} 解析为 6 位股票代码；支持格式：600519 / "
            "SH600519 / 600519.SH（前缀与后缀二选一，不能同时写）"
        )
    digits = match.group(2) or match.group(3)
    market = (match.group(1) or match.group(4) or "").lower()
    if market:
        if digits.startswith("000"):
            # 000xxx is shared between Shanghai indices and Shenzhen stocks.
            # An explicit identifier here is disambiguation, not contradiction.
            if market == "bj":
                raise ValueError(f"{code!r} 市场标识与号段矛盾：000xxx 不属北交所。")
            if stock_only and market == "sh":
                raise ValueError(
                    f"{code!r} 指向沪市指数而非个股（沪市无 000xxx 个股），本接口只服务个股。"
                    f"要查同号段的深市个股请显式传 sz{digits}。"
                )
        else:
            natural = _natural_market(digits)
            if market != natural.lower():
                raise ValueError(
                    f"{code!r} 的市场标识与号段矛盾：{digits} 属 {natural} 市，而不是 {market.upper()} 市。"
                )
    return digits


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
        strict_ticker_code(f"{exchange}{code}")
        return _format_canonical_a_share(code, exchange)

    suffix_match = re.fullmatch(r"(\d{6})(SH|SS|SZ|BJ)", compact)
    if suffix_match:
        code, exchange = suffix_match.groups()
        strict_ticker_code(f"{code}.{'SH' if exchange == 'SS' else exchange}")
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
