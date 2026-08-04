"""Per-run network reachability preflight for data sources that need a VPN.

A-share data uses domestic providers (mootdx/Tencent/EastMoney/Tushare) and
needs no proxy. US/HK/global tickers route through yfinance, which is
unreachable from a mainland network without a VPN. Starting a global run in
that state wastes a long analysis only to fail at the first data call. This
preflight does a short HTTPS probe before the run is created and raises a
typed error the web layer turns into a "enable your VPN" prompt.

It deliberately uses a real HTTPS request rather than ICMP ping: ICMP is
often blocked by networks/proxies, while an HTTPS round-trip is the exact
connectivity path yfinance uses.
"""

from __future__ import annotations

from typing import Any

import requests

from ..dataflows.symbol_utils import normalize_symbol
from ..dataflows.ticker_utils import is_a_share_ticker

# yfinance 1.5.x resolves quotes through query2.finance.yahoo.com. A 1-day
# chart is a minimal, stable JSON endpoint that proves real reachability.
_YAHOO_PROBE_HOST = "query2.finance.yahoo.com"
_YAHOO_PROBE_PATH = "/v8/finance/chart/{symbol}"
_PROBE_TIMEOUT = 5.0
_USER_AGENT = "Mozilla/5.0 (TradingAgents preflight)"


class YahooUnavailableError(RuntimeError):
    """Raised when a yfinance-dependent ticker cannot reach Yahoo Finance."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Yahoo Finance is unreachable: {detail}")


def requires_yfinance(ticker: str) -> bool:
    """Return True when the ticker resolves through the global (yfinance) path."""
    return not is_a_share_ticker(ticker)


def check_yfinance_reachable(
    ticker: str,
    *,
    timeout: float = _PROBE_TIMEOUT,
    session: Any | None = None,
) -> None:
    """Probe Yahoo Finance for a non-A-share ticker or return immediately.

    No-op for A-share tickers (they use domestic providers and never need a
    VPN). Raises :class:`YahooUnavailableError` when the probe fails for any
    reason (DNS, connection, timeout, non-2xx), so the caller can abort before
    creating a run. The HTTP layer maps this to a user-facing 503.
    """
    if not requires_yfinance(ticker):
        return

    canonical = normalize_symbol(ticker)
    http = session or requests
    url = f"https://{_YAHOO_PROBE_HOST}{_YAHOO_PROBE_PATH.format(symbol=canonical)}"
    try:
        response = http.get(
            url,
            params={"range": "1d", "interval": "1d"},
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )
    except requests.RequestException as exc:
        raise YahooUnavailableError(
            f"{type(exc).__name__}: cannot connect to {_YAHOO_PROBE_HOST}"
        ) from exc

    try:
        status = int(response.status_code)
    except (TypeError, ValueError):
        status = 0
    if not (200 <= status < 300):
        # A 4xx on a real symbol (e.g. 429) still proves the host is reachable;
        # treat 5xx and transport-level failures as unavailable.
        if status >= 500 or status == 0:
            raise YahooUnavailableError(
                f"{_YAHOO_PROBE_HOST} returned HTTP {status}"
            )
