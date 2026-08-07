"""Degradable China capital-flow, northbound, and insider source adapters.

These data sets are *research supplements*.  They deliberately live outside
the OHLCV route: a changing public endpoint must never turn a usable price
request into an unavailable one.  Every adapter returns source-labelled rows
or raises a typed vendor error; it never derives a trading conclusion from a
missing field.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import requests

from .china_capabilities import AshareCapabilityUnavailableError, CapabilityReport
from .ticker_utils import is_a_share_ticker, normalize_ticker_symbol, to_akshare_symbol

# Bounded timeout for every direct HTTP call here. The previous AKShare
# adapters could hang for minutes (full-market pagination behind EastMoney
# anti-crawler), which stalled the whole sentiment prefetch; a failed optional
# supplement must fail fast and degrade, not block the run.
_HTTP_TIMEOUT = 10.0

_HEXIN_URL = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
_HEXIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
    "Referer": "https://data.hexin.cn/",
}
_EASTMONEY_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
# RPT_SHARE_HOLDER_INCREASE is EastMoney's manager/shareholder change dataset.
# AKShare's stock_ggcg_em pulls it WITHOUT a per-ticker filter and paginates the
# entire market (500 rows/page, tqdm) — that is what hung for 120s+. We request
# one page for one ticker instead.
_INSIDER_REPORT = "RPT_SHARE_HOLDER_INCREASE"


class ChinaCapitalFlowProvider:
    """Direct HTTP adapters for northbound flow and insider trades.

    Replaces the earlier AKShare-backed implementation: the AKShare endpoints
    for northbound holdings/insider trades paginated the whole market and hung
    behind EastMoney anti-crawler. These adapters issue single bounded requests
    (THS for aggregate northbound flow, EastMoney datacenter for per-ticker
    insider changes) and raise a typed error on any failure so the router can
    degrade without stalling. See a-stock-data SKILL.md §3.2/§4.
    """

    name = "eastmoney"

    def __init__(self, session: Any | None = None) -> None:
        self._session = session

    def _http(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def northbound_flow(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CapabilityReport:
        """Return aggregate SH/SZ northbound net-buy minute series via THS.

        This is market-wide flow (沪股通/深股通 hgt/sgt, in 亿元), not a
        per-ticker attribution. Since 2024-08 EastMoney's per-stock northbound
        net-buy fields return NaN/0 (industry-wide upstream gap); THS still
        serves the aggregate intraday series, which is the usable signal here.
        """
        try:
            response = self._http().get(
                _HEXIN_URL, headers=_HEXIN_HEADERS, timeout=_HTTP_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AshareCapabilityUnavailableError(
                "northbound_flow", "ths", f"{type(exc).__name__}: {exc}"
            ) from exc

        times = payload.get("time") or []
        hgt = payload.get("hgt") or []
        sgt = payload.get("sgt") or []
        if not times:
            raise AshareCapabilityUnavailableError(
                "northbound_flow", "ths", "empty dayChart series"
            )
        n = len(times)
        data = pd.DataFrame(
            {
                "time": times,
                "hgt_net_buy_yi": list(hgt[:n]) + [None] * (n - len(hgt)),
                "sgt_net_buy_yi": list(sgt[:n]) + [None] * (n - len(sgt)),
            }
        )
        return _market_report(
            data,
            capability="northbound_flow",
            provider="ths",
            note=(
                "Aggregate Shanghai/Shenzhen northbound net-buy (亿元) from THS "
                "intraday series; SH connect is reliable, SZ connect disclosure "
                "has tightened upstream and is indicative only. Not a per-ticker attribution."
            ),
        )

    def northbound_holdings(
        self,
        ticker: str,
        indicator: str = "今日排行",
    ) -> CapabilityReport:
        """Per-ticker northbound holding/ranking record.

        EastMoney's RPT_MUTUAL_STOCK_NORTHSTA no longer returns usable per-stock
        holding rows after the 2024-08 northbound disclosure cutoff, and AKShare
        only reached it by scraping the whole-market ranking. Instead of hanging
        on a known-depleted source, fail fast with a typed degradation.
        """
        # Validate the ticker is A-share so the failure is correctly attributed.
        _require_a_share_code(ticker, "northbound_holdings")
        raise AshareCapabilityUnavailableError(
            "northbound_holdings",
            self.name,
            "per-stock northbound holdings upstream data is unavailable after the 2024-08 disclosure cutoff",
        )

    def insider_trades(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CapabilityReport:
        """Return disclosed manager/shareholder change rows for one A-share."""
        code = _require_a_share_code(ticker, "insider_trades")
        params = {
            "reportName": _INSIDER_REPORT,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{code}")',
            "pageNumber": "1",
            "pageSize": "50",
            "sortColumns": "END_DATE,SECURITY_CODE,EITIME",
            "sortTypes": "-1,-1,-1",
            "source": "WEB",
            "client": "WEB",
        }
        try:
            response = self._http().get(
                _EASTMONEY_DATACENTER,
                params=params,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=_HTTP_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AshareCapabilityUnavailableError(
                "insider_trades", self.name, f"{type(exc).__name__}: {exc}"
            ) from exc

        rows = ((payload.get("result") or {}).get("data")) or []
        if not rows:
            raise AshareCapabilityUnavailableError(
                "insider_trades", self.name, f"no insider rows for security code {code}"
            )
        data = pd.DataFrame(rows)
        selected = _filter_date_window(data, start_date, end_date)
        return _ticker_report(
            selected,
            capability="insider_trades",
            ticker=ticker,
            provider=self.name,
            note=(
                "Public disclosed manager/shareholder share-change records from "
                "EastMoney datacenter. Identity, relation, and disclosure timing "
                "must be verified against the source filing."
            ),
        )


def get_a_share_northbound_flow(
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Render aggregate northbound-flow history as an optional research input."""
    return ChinaCapitalFlowProvider().northbound_flow(start_date, end_date).render()


def get_a_share_northbound_holdings(ticker: str, indicator: str = "今日排行") -> str:
    """Render one ticker's provider-reported northbound holding/ranking row(s)."""
    return ChinaCapitalFlowProvider().northbound_holdings(ticker, indicator).render()


def get_a_share_insider_trades(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Render disclosed manager/shareholder share-change rows for one A-share."""
    return ChinaCapitalFlowProvider().insider_trades(ticker, start_date, end_date).render()


def _require_a_share_code(ticker: str, capability: str) -> str:
    canonical = normalize_ticker_symbol(ticker)
    if not is_a_share_ticker(canonical):
        raise AshareCapabilityUnavailableError(capability, "eastmoney", f"{ticker} is not an A-share ticker")
    return to_akshare_symbol(canonical)


def _filter_date_window(
    data: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    if not start_date and not end_date:
        return data.copy()
    start = _parse_iso_date(start_date) if start_date else None
    end = _parse_iso_date(end_date) if end_date else None
    for column in ("日期", "交易日期", "变动截止日", "END_DATE", "变动日期", "公告日", "NOTICE_DATE", "TRADE_DATE", "REPORT_DATE"):
        if column not in data.columns:
            continue
        dates = pd.to_datetime(data[column], errors="coerce").dt.date
        selected = data.copy()
        if start:
            selected = selected.loc[dates >= start]
            dates = dates.loc[selected.index]
        if end:
            selected = selected.loc[dates <= end]
        if selected.empty:
            raise AshareCapabilityUnavailableError("date_window", "eastmoney", "no rows in requested date window")
        return selected
    # The provider gave rows, but no stable date field.  Preserve the rows and
    # say so in the report note instead of fabricating a time filter.
    return data.copy()


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (AttributeError, ValueError) as exc:
        raise AshareCapabilityUnavailableError("date_window", "eastmoney", f"invalid ISO date: {value!r}") from exc


def _ticker_report(
    data: pd.DataFrame,
    *,
    capability: str,
    ticker: str,
    provider: str,
    note: str,
) -> CapabilityReport:
    _capture_vendor_raw(data, provider=provider, capability=capability, ticker=ticker)
    return CapabilityReport(capability, normalize_ticker_symbol(ticker), provider, data, note)


def _market_report(
    data: pd.DataFrame,
    *,
    capability: str,
    provider: str,
    note: str,
) -> CapabilityReport:
    _capture_vendor_raw(data, provider=provider, capability=capability, ticker=None)
    return CapabilityReport(capability, None, provider, data, note)


def _capture_vendor_raw(
    data: pd.DataFrame,
    *,
    provider: str,
    capability: str,
    ticker: str | None,
) -> None:
    """Capture only usable source rows when a provenance scope is active."""
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(
        data,
        metadata={"provider": provider, "dataset": capability, "ticker": ticker or "market-wide"},
    )
