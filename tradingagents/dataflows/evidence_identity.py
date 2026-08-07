"""A-share company profile resolution and canonical identity lookup."""

from __future__ import annotations

import contextlib
import io
import os
import re
from functools import lru_cache
from typing import Any

import pandas as pd
import requests

from .ticker_utils import (
    is_a_share_ticker,
    normalize_ticker_symbol,
    to_tushare_symbol,
    to_yfinance_symbol,
)


@lru_cache(maxsize=256)
def resolve_canonical_company_profile(ticker: str) -> dict[str, Any]:
    """Resolve a stable profile for the instrument, best-effort for prompts."""
    from tradingagents.dataflows import evidence as _evidence
    normalized = normalize_ticker_symbol(ticker)
    profile = {
        "ticker": normalized,
        "symbol": normalized.split(".", 1)[0],
        "ts_code": to_tushare_symbol(normalized) if is_a_share_ticker(normalized) else normalized,
        "name": "",
        "full_name": "",
        "industry": "",
        "exchange": _exchange_name(normalized),
    }
    if not is_a_share_ticker(normalized):
        return profile

    try:
        from .china_data import _get_tushare_pro

        pro = _get_tushare_pro()
        ts_code = profile["ts_code"]
        try:
            df = pro.stock_basic(
                ts_code=ts_code,
                fields="ts_code,symbol,name,fullname,area,industry,market,list_date,act_name,act_ent_type",
            )
        except TypeError:
            df = pro.stock_basic(ts_code=ts_code)
        if isinstance(df, pd.DataFrame) and not df.empty:
            row = df.iloc[0].to_dict()
            profile.update(
                {
                    "ticker": normalize_ticker_symbol(str(row.get("ts_code") or normalized)),
                    "symbol": str(row.get("symbol") or profile["symbol"]),
                    "ts_code": str(row.get("ts_code") or profile["ts_code"]),
                    "name": str(row.get("name") or ""),
                    "full_name": str(
                        row.get("fullname") or row.get("full_name") or row.get("name") or ""
                    ),
                    "industry": str(row.get("industry") or ""),
                    "market": str(row.get("market") or ""),
                    "area": str(row.get("area") or ""),
                    "act_name": str(row.get("act_name") or ""),
                    "act_ent_type": str(row.get("act_ent_type") or ""),
                    "exchange": _exchange_name(str(row.get("ts_code") or normalized)),
                }
            )
    except Exception as exc:
        profile["resolution_error"] = str(exc)
    # EastMoney push2 direct (zero key) fills identity without the akshare SDK;
    # it sits between the tushare primary and the akshare/yfinance fallbacks.
    if not profile.get("name"):
        _evidence._apply_eastmoney_profile(profile)
    if not profile.get("name"):
        _evidence._apply_akshare_profile(profile)
    if not profile.get("name"):
        _evidence._apply_yfinance_profile(profile)
    return profile


_A_SHARE_CODE_NAME_CACHE: dict[str, str] | None = None


def _apply_eastmoney_profile(profile: dict[str, Any]) -> None:
    """Fill profile identity from EastMoney push2 (zero key, direct HTTP).

    Aligned with a-stock-data SKILL.md §6.3 ``eastmoney_stock_info`` and
    replaces the akshare ``stock_individual_info_em`` wrapper (which calls the
    same push2 source) with a direct request, so identity resolution no longer
    depends on the akshare SDK. Best-effort: failures are recorded on the
    profile and the resolution chain falls through to akshare/yfinance.
    """
    try:
        symbol = str(profile.get("symbol") or "")
        if not re.fullmatch(r"\d{6}", symbol):
            return
        # push2 secid market: 1 for Shanghai, 0 for Shenzhen/Beijing.  920xxx BSE
        # new-segment codes are served under market 0.
        market_code = 1 if symbol.startswith(("5", "6", "9")) else 0
        if symbol.startswith("92"):
            market_code = 0
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
            "secid": f"{market_code}.{symbol}",
        }
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        data = (resp.json() or {}).get("data") or {}
        if not data:
            profile["eastmoney_resolution_error"] = "push2 returned empty data"
            return
        name = str(data.get("f58") or "").strip()
        if name:
            profile["name"] = name
            if not profile.get("full_name"):
                profile["full_name"] = name
        if data.get("f127"):
            profile["industry"] = str(data["f127"])
        if data.get("f84") is not None:
            profile["total_shares"] = data.get("f84")
        if data.get("f85") is not None:
            profile["float_shares"] = data.get("f85")
        if data.get("f116") is not None:
            profile["market_cap"] = data.get("f116")
        if data.get("f117") is not None:
            profile["float_market_cap"] = data.get("f117")
        if data.get("f189"):
            profile["list_date"] = str(data["f189"])
        profile["profile_source"] = "eastmoney_push2"
    except Exception as exc:  # noqa: BLE001 - best-effort supplement
        profile["eastmoney_resolution_error"] = str(exc)


def _apply_akshare_profile(profile: dict[str, Any]) -> None:
    try:
        from .china_data import _import_optional

        ak = _import_optional("akshare", "pip install akshare")
        symbol = str(profile.get("symbol") or "")
        if not symbol:
            return

        # Primary: East Wealth stock_individual_info_em (rich - name + industry).
        # This endpoint is rate-limited / frequently drops connections, so a
        # failure here must not abort the akshare tier - fall through to the
        # Sina-backed code/name list below.
        try:
            df = ak.stock_individual_info_em(symbol=symbol)
        except Exception:
            df = None

        if isinstance(df, pd.DataFrame) and not df.empty:
            rows = {
                str(row.get("item") or "").strip(): str(row.get("value") or "").strip()
                for row in df.to_dict("records")
            }
            if rows.get("股票简称"):
                profile["name"] = rows["股票简称"]
            if rows.get("行业"):
                profile["industry"] = rows["行业"]
            if rows.get("股票代码"):
                profile["symbol"] = rows["股票代码"].zfill(6)
                suffix = str(profile.get("ticker", "")).split(".")[-1]
                profile["ticker"] = normalize_ticker_symbol(f"{profile['symbol']}.{suffix}")
                profile["ts_code"] = to_tushare_symbol(str(profile["ticker"]))
                profile["exchange"] = _exchange_name(str(profile["ticker"]))
            profile["profile_source"] = "akshare"

        # Fallback: Sina stock_info_a_code_name (name only, reliable when East
        # Wealth is unreachable). Cached module-level because the list is large
        # (~5500 rows) and changes rarely. Without this fallback the akshare
        # tier silently returns an empty name whenever East Wealth drops the
        # connection, leaving canonical_company_profile without a name and
        # tripping the Evidence Steward A-share gate.
        if not profile.get("name"):
            name = _lookup_a_share_name_from_code_list(ak, symbol)
            if name:
                profile["name"] = name
                if not profile.get("full_name"):
                    profile["full_name"] = name
                profile["profile_source"] = "akshare_code_name"
    except Exception as exc:
        profile["akshare_resolution_error"] = str(exc)


def _lookup_a_share_name_from_code_list(ak: Any, symbol: str) -> str:
    """Look up company name from the full A-share code/name list (Sina source).

    Cached module-level: the list covers both SSE and SZSE, is large, and
    changes rarely. Suppresses stderr while paginating because akshare emits
    a tqdm progress bar for the multi-page fetch.
    """
    global _A_SHARE_CODE_NAME_CACHE
    try:
        if _A_SHARE_CODE_NAME_CACHE is None:
            saved = os.environ.get("TQDM_DISABLE")
            os.environ["TQDM_DISABLE"] = "1"
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    df = ak.stock_info_a_code_name()
            finally:
                if saved is None:
                    os.environ.pop("TQDM_DISABLE", None)
                else:
                    os.environ["TQDM_DISABLE"] = saved
            _A_SHARE_CODE_NAME_CACHE = {
                str(row.get("code") or "").zfill(6): str(row.get("name") or "").strip()
                for row in df.to_dict("records")
            }
        return _A_SHARE_CODE_NAME_CACHE.get(str(symbol).zfill(6), "")
    except Exception:
        return ""


def _apply_yfinance_profile(profile: dict[str, Any]) -> None:
    try:
        yf = __import__("yfinance")
        ticker = to_yfinance_symbol(str(profile.get("ticker") or profile.get("ts_code") or ""))
        if not ticker:
            return
        yf_ticker = yf.Ticker(ticker)
        get_info = getattr(yf_ticker, "get_info", None)
        info = get_info() if callable(get_info) else getattr(yf_ticker, "info", {})
        if not isinstance(info, dict) or not info:
            return
        info_symbol = str(info.get("symbol") or "").upper()
        if info_symbol and info_symbol != ticker.upper():
            profile["yfinance_resolution_error"] = (
                f"YFinance symbol mismatch: requested {ticker}, got {info_symbol}"
            )
            return

        short_name = _first_nonempty(
            info.get("shortName"),
            info.get("displayName"),
            info.get("longName"),
        )
        long_name = _first_nonempty(info.get("longName"), short_name)
        industry = _first_nonempty(info.get("industry"), info.get("sector"))
        if short_name:
            profile["name"] = short_name
        if long_name:
            profile["full_name"] = long_name
        if industry:
            profile["industry"] = industry
        if info.get("exchange"):
            profile["yfinance_exchange"] = str(info["exchange"])
        if info.get("fullExchangeName"):
            profile["yfinance_full_exchange_name"] = str(info["fullExchangeName"])
        profile["profile_source"] = "yfinance"
    except Exception as exc:
        profile["yfinance_resolution_error"] = str(exc)


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return ""


def _complete_profile(profile: Any, ticker: str) -> dict[str, Any]:
    if isinstance(profile, dict) and profile.get("name"):
        completed = dict(profile)
        completed.setdefault("ticker", normalize_ticker_symbol(ticker))
        completed.setdefault("symbol", str(completed["ticker"]).split(".", 1)[0])
        completed.setdefault("ts_code", to_tushare_symbol(str(completed["ticker"])))
        completed.setdefault("exchange", _exchange_name(str(completed["ticker"])))
        return completed
    return resolve_canonical_company_profile(ticker)


def _exchange_name(ticker: str) -> str:
    value = to_tushare_symbol(str(ticker or ""))
    if value.endswith(".SZ"):
        return "深圳证券交易所"
    if value.endswith(".SH") or value.endswith(".SS"):
        return "上海证券交易所"
    if value.endswith(".BJ"):
        return "北京证券交易所"
    return ""

