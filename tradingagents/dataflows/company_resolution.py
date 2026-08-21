"""User-input resolution: company names and multi-format A-share codes.

Users should be able to type either a ticker in any common form or a company
name, and the pipeline must resolve both to the same canonical symbol::

    688825 / SH688825 / 688825.SH / sh688825  ->  688825.SS
    贵州茅台 / 茅台                           ->  600519.SS
    Apple / Apple Inc.                        ->  AAPL

Resolution order (cheap first, network only when needed):

1. **Local code form** (zero network): six-digit codes, ``SH/SZ/BJ`` prefixes,
   ``.SS/.SH/.SZ/.BJ`` suffixes, Yahoo-native symbols and the alias table in
   ``symbol_utils`` (``XAUUSD`` -> ``GC=F``, ``BTCUSD`` -> ``BTC-USD``, ...).
   Any input that *changed* under local normalization is a code and returned
   immediately.
2. **Company name** (network, cached):
   - CJK input (Chinese company names) resolves via the Sina suggest endpoint
     (zero key, stable for A-share short names): ``茅台`` -> ``600519``.
   - Non-CJK input (English company names) resolves via Yahoo Finance search:
     ``Apple`` -> ``AAPL``.
3. **Fallback**: if the name lookup fails and the input still looks like a
   plain ticker (ASCII, no spaces), the upper-cased input is returned so
   existing code paths keep their behaviour when the network is unavailable.

The resolver is best-effort and never raises; callers that need an A-share
ticker can keep validating with ``is_a_share_ticker``.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import requests

from .symbol_utils import normalize_symbol
from .ticker_utils import normalize_ticker_symbol

logger = logging.getLogger(__name__)

_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")
_PLAIN_TICKER = re.compile(r"^[A-Za-z0-9._\-^=]{1,32}$")
# A name-like ASCII input: starts with a letter, letters/spaces only, and is
# NOT all upper-case (so AAPL/TSLA are treated as codes while Apple/Microsoft
# are treated as company names).
_COMPANY_NAME_LIKE = re.compile(r"^[A-Za-z][A-Za-z ]{1,40}$")

_SINA_SUGGEST_URL = "https://suggest3.sinajs.cn/suggest/type=11,12&key="
# US exchanges preferred by Yahoo search results (equities listed in the US).
_YAHOO_US_EXCHANGES = frozenset(
    {"NMS", "NYQ", "NGM", "NAS", "ASE", "PCX", "BTS", "OQB", "OQX"}
)


@lru_cache(maxsize=256)
def _sina_suggest(query: str) -> tuple[tuple[str, str], ...]:
    """Query Sina suggest for A-share short names (zero key, GBK response).

    Returns tuples of ``(name, code)`` for A/B-share rows only.  The endpoint
    covers Chinese short names reliably (``茅台`` -> ``贵州茅台``); English
    names are routed to Yahoo instead.
    """
    try:
        resp = requests.get(
            _SINA_SUGGEST_URL + query,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn",
            },
            timeout=8,
        )
        text = resp.content.decode("gbk", errors="ignore")
    except Exception as exc:  # noqa: BLE001 - best-effort resolver
        logger.warning("Sina suggest failed for %r: %s", query, exc)
        return ()

    if 'suggestvalue="' not in text:
        return ()
    body = text.split('suggestvalue="', 1)[1].split('"', 1)[0]
    rows = []
    for record in body.split(";"):
        fields = record.split(",")
        if len(fields) < 4:
            continue
        name = fields[0].strip()
        market_type = fields[1].strip()
        code = fields[2].strip()
        # 11 = 沪深 A 股, 12 = 沪深 B 股; anything else (13 HK, 14 US, 15
        # futures) is not resolved through this endpoint.
        if market_type not in ("11", "12") or not name or not code:
            continue
        rows.append((name, code))
    return tuple(rows)


@lru_cache(maxsize=256)
def _yahoo_search(query: str) -> tuple[str, ...]:
    """Search Yahoo Finance for an English company name.

    Returns candidate symbols (US-listed equities first, then any equity).
    """
    try:
        resp = requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": 8, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        quotes = (resp.json() or {}).get("quotes", []) or []
    except Exception as exc:  # noqa: BLE001 - best-effort resolver
        logger.warning("Yahoo search failed for %r: %s", query, exc)
        return ()

    us_symbols = []
    other_symbols = []
    for quote in quotes or []:
        if not isinstance(quote, dict):
            continue
        if quote.get("quoteType") != "EQUITY":
            continue
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol or not re.fullmatch(r"[A-Z0-9.\-^=]{1,32}", symbol):
            continue
        if quote.get("exchange") in _YAHOO_US_EXCHANGES:
            us_symbols.append(symbol)
        else:
            other_symbols.append(symbol)
    return tuple(us_symbols + other_symbols)


def resolve_input_candidates(raw: str) -> tuple[tuple[str, str], ...]:
    """Return all unique ``(display_name, canonical_ticker)`` candidates."""
    if not isinstance(raw, str):
        return ()
    value = raw.strip()
    if not value:
        return ()
    local = normalize_symbol(normalize_ticker_symbol(value))
    if local != value.upper():
        return ((value, local),)
    if _HAS_CJK.search(value):
        candidates: list[tuple[str, str]] = []
        for name, code in _sina_suggest(value):
            if code and code.isdigit() and len(code) == 6:
                pair = (name, normalize_ticker_symbol(code))
                if pair not in candidates:
                    candidates.append(pair)
        return tuple(candidates)
    if value.isascii() and not value.isupper() and _COMPANY_NAME_LIKE.fullmatch(value):
        return tuple((value, symbol) for symbol in dict.fromkeys(_yahoo_search(value)))
    if _PLAIN_TICKER.fullmatch(value):
        return ((value, value.upper()),)
    return ()


def resolve_company_name(name: str) -> str | None:
    """Resolve a company name (Chinese or English) to a canonical symbol.

    CJK names use the Sina suggest endpoint (A-share short names); non-CJK
    names use Yahoo Finance search (US/global equities).  Returns None when
    nothing relevant is found.
    """
    query = name.strip()
    if not query:
        return None
    if _HAS_CJK.search(query):
        # A-share Chinese short name via Sina: 茅台 -> 贵州茅台 600519.
        for _row_name, code in _sina_suggest(query):
            if code and code.isdigit() and len(code) == 6:
                canonical = normalize_ticker_symbol(code)
                logger.info("Resolved Chinese company name %r to %s", query, canonical)
                return canonical
        return None
    # English company name via Yahoo: Apple -> AAPL.
    for symbol in _yahoo_search(query):
        logger.info("Resolved company name %r to %s", query, symbol)
        return symbol
    return None


def resolve_input_to_ticker(raw: str) -> str:
    """Resolve any user input to the first canonical candidate for compatibility."""
    candidates = resolve_input_candidates(raw)
    return candidates[0][1] if candidates else ""
