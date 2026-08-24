"""A-stock V3.7.0 supplement adapters (a-stock-data v3.7.1 reference).

New capabilities added by simonlin1212/a-stock-data v3.7.0, adapted to this
project's degradable-adapter contract:

- §1.4  adjust factors qfq/hfq (Sina, zero-key)  -> ``get_a_share_adjust_factors``
- §6.5  valuation history (baostock)             -> ``get_a_share_valuation_history``
- §6.6  listing / delisting dates (baostock)     -> ``get_a_share_listing_history``
- §4.6  chip distribution CYQ (local derivation) -> ``get_a_share_chip_distribution``
- §6.7  SW industry history (swsresearch xls)    -> ``get_sw_industry_history``
- §11.1/11.2  macro layer (PBC / NBS direct)     -> ``get_china_social_financing``,
                                                    ``get_china_pmi``

Every adapter reports *source records*, never inferred meaning.  An empty
response, a changed schema, an unavailable optional dependency, or a provider
that rejects the instrument always raises a typed
``AshareCapabilityUnavailableError`` / ``ChinaDataUnavailableError`` so callers
degrade truthfully instead of reading an empty result as "no such thing".
"""

from __future__ import annotations

import io
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from .china_capabilities import AshareCapabilityUnavailableError
from .china_data import ChinaDataUnavailableError
from .ticker_utils import (
    infer_a_share_exchange,
    is_a_share_ticker,
    normalize_ticker_symbol,
    to_akshare_symbol,
)

_SINA_ADJUST_URL = "https://finance.sina.com.cn/realstock/company/{symbol}/{kind}.js"
_SINA_ADJUST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn/",
}
_SW_URL = "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls"
_SW_HEADERS = {"User-Agent": "Mozilla/5.0"}
_PBC_BASE = "https://www.pbc.gov.cn"
_PBC_INDEX = f"{_PBC_BASE}/diaochatongjisi/116219/116319/index.html"
_PBC_UA = {"User-Agent": "Mozilla/5.0"}
_NBS_PMI_URL = "https://data.stats.gov.cn/easyquery.htm"
_CN_TZ = timezone(timedelta(hours=8))


def _require_a_share_code(ticker: str, capability: str) -> str:
    """Return the bare six-digit A-share code or raise a typed degradation."""
    canonical = normalize_ticker_symbol(ticker)
    if not is_a_share_ticker(canonical):
        raise ChinaDataUnavailableError(f"{ticker} is not recognized as an A-share ticker.")
    return to_akshare_symbol(canonical)


def _exclude_bse(code: str, capability: str) -> None:
    """baostock rejects BSE segments server-side; fail before logging in."""
    if infer_a_share_exchange(code) == "BJ":
        raise AshareCapabilityUnavailableError(
            capability,
            "baostock",
            f"{code} 是北交所代码，baostock 服务端拒绝 4/8/92/920 号段；请改用腾讯当日快照/新浪等源",
        )


def _bs_code(code: str, capability: str) -> str:
    """Map a six-digit code to baostock's sh.xxxxxx / sz.xxxxxx convention."""
    _exclude_bse(code, capability)
    if code[:2] in ("60", "68", "90"):
        return f"sh.{code}"
    if code[:2] in ("00", "30", "20"):
        return f"sz.{code}"
    raise AshareCapabilityUnavailableError(
        capability, "baostock", f"unsupported baostock code prefix: {code[:2]}"
    )


@contextmanager
def _bs_session():
    """baostock login context manager; always logs out, even on error."""
    import baostock as bs  # lazy: optional dependency

    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        raise AshareCapabilityUnavailableError(
            "baostock", "baostock", f"login failed: {lg.error_code} {lg.error_msg}"
        )
    try:
        yield bs
    finally:
        bs.logout()


def _bs_to_df(rs: Any) -> pd.DataFrame:
    """baostock ResultData -> DataFrame; error code becomes a typed failure."""
    if getattr(rs, "error_code", "0") != "0":
        raise AshareCapabilityUnavailableError(
            "baostock", "baostock", f"query failed: {rs.error_code} {rs.error_msg}"
        )
    rows: list[list[str]] = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def _render(capability: str, ticker: str | None, provider: str, data: pd.DataFrame, note: str) -> str:
    """Render a source-labelled markdown report, empty rows degrade loudly."""
    if data.empty:
        raise AshareCapabilityUnavailableError(capability, provider, "no usable rows")
    target = ticker or "market-wide"
    return "\n".join(
        [
            f"# China A-share {capability.replace('_', ' ')} for {target}",
            f"# Source: {provider}",
            f"# Note: {note}",
            f"# Total records: {len(data)}",
            "",
            data.to_csv(index=False),
        ]
    )


def _capture_vendor_raw(data: Any, *, metadata: dict[str, Any]) -> None:
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(data, metadata=dict(metadata))


# ---------------------------------------------------------------------------
# §1.4 复权因子 qfq / hfq (Sina, zero-key)
# ---------------------------------------------------------------------------

def get_a_share_adjust_factors(ticker: str, kind: str = "qfq") -> str:
    """A-share adjusted-price factors (qfq/hfq) from Sina's realstock endpoint.

    Returns the factor series per trading day (newest first).  This is a
    *supplement* endpoint: it does not change the primary mootdx OHLCV chain,
    which intentionally stays unadjusted.  Apply the factors downstream when a
    cross-dividend comparison is needed.
    """
    if kind not in ("qfq", "hfq"):
        raise ValueError(f"kind 只能是 'qfq' 或 'hfq'，收到 {kind!r}")
    code = _require_a_share_code(ticker, "adjust_factors")
    raw = str(ticker).strip()
    m = re.match(r"^(sh|sz|bj)", raw, re.I) or re.search(r"\.(sh|sz|bj)$", raw, re.I)
    prefix = m.group(1).lower() if m else {
        "SH": "sh", "SZ": "sz", "BJ": "bj",
    }[infer_a_share_exchange(code) or "SZ"]
    symbol = f"{prefix}{code}"
    url = _SINA_ADJUST_URL.format(symbol=symbol, kind=kind)
    try:
        resp = requests.get(url, headers=_SINA_ADJUST_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ChinaDataUnavailableError(
            f"Sina adjust factor request failed for {ticker}: {type(exc).__name__}"
        ) from exc
    text = resp.text
    brace = text.find("{")
    if brace < 0:
        raise ChinaDataUnavailableError(f"Sina adjust factor returned no JSON for {symbol}/{kind}.")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[brace:])
    except json.JSONDecodeError as exc:
        raise ChinaDataUnavailableError(
            f"Sina adjust factor JSON parse failed for {symbol}/{kind}: {exc}"
        ) from exc
    rows = [{"date": it["d"], "factor": float(it["f"])} for it in data.get("data", [])]
    if not rows:
        raise ChinaDataUnavailableError(f"Sina returned no adjust-factor rows for {code} ({kind}).")
    df = pd.DataFrame(rows)
    _capture_vendor_raw(df, metadata={"provider": "sina", "dataset": "adjust_factors", "ticker": ticker, "kind": kind})
    note = (
        f"Sina realstock {kind} factor series; qfq 因子是除数（前复权价=不复权价÷因子），"
        "hfq 因子是乘数（后复权价=不复权价×因子）。跨除权日比价必须先套因子。"
    )
    return _render("adjust_factors", ticker, "sina", df, note)


# ---------------------------------------------------------------------------
# §6.5 估值历史 (baostock)
# ---------------------------------------------------------------------------

_VALUATION_HISTORY_FIELDS = (
    "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM,turn,tradestatus,isST"
)


def get_a_share_valuation_history(ticker: str, start_date: str | None = None, end_date: str | None = None) -> str:
    """A-share daily valuation history (PE/PB/PS/PCF + turnover + ST) via baostock.

    ``end_date`` defaults to today (Asia/Shanghai); ``start_date`` defaults to
    one year back.  baostock does not serve BSE segments -- those degrade with
    a typed error before any login is attempted.
    """
    code = _require_a_share_code(ticker, "valuation_history")
    end_date = end_date or datetime.now(_CN_TZ).strftime("%Y-%m-%d")
    start_date = start_date or (datetime.now(_CN_TZ) - timedelta(days=365)).strftime("%Y-%m-%d")
    bs_code = _bs_code(code, "valuation_history")
    with _bs_session() as bs:
        rs = bs.query_history_k_data_plus(
            bs_code,
            _VALUATION_HISTORY_FIELDS,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",  # 3 = unadjusted, consistent with the mootdx OHLCV chain
        )
        df = _bs_to_df(rs)
    if df.empty:
        raise AshareCapabilityUnavailableError("valuation_history", "baostock", "no rows in window")
    for col in ("close", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "turn"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    _capture_vendor_raw(df, metadata={"provider": "baostock", "dataset": "valuation_history", "ticker": ticker})
    note = (
        "baostock daily valuation history; unadjusted (adjustflag=3). peTTM/pbMRQ/psTTM/pcfNcfTTM "
        "are point-in-time snapshots; tradestatus=='0' is a suspension day; isST==1 marks an ST ticker. "
        "BSE segments are not served by baostock."
    )
    return _render("valuation_history", ticker, "baostock", df, note)


# ---------------------------------------------------------------------------
# §6.6 上市 / 退市日 (baostock)
# ---------------------------------------------------------------------------

def get_a_share_listing_history(ticker: str) -> str:
    """A-share basic record: ipoDate / outDate / status via baostock.

    ``outDate`` is empty while the instrument is still listed -- the only
    zero-auth source of delisting dates, useful for screening out zombie codes.
    """
    code = _require_a_share_code(ticker, "listing_history")
    bs_code = _bs_code(code, "listing_history")
    with _bs_session() as bs:
        df = _bs_to_df(bs.query_stock_basic(code=bs_code))
    if df.empty:
        raise AshareCapabilityUnavailableError("listing_history", "baostock", "no basic record")
    _capture_vendor_raw(df, metadata={"provider": "baostock", "dataset": "listing_history", "ticker": ticker})
    note = (
        "baostock stock_basic: ipoDate=上市日, outDate=退市日（在市为空）, status=1 上市 / 0 退市. "
        "BSE segments are not served by baostock."
    )
    return _render("listing_history", ticker, "baostock", df, note)


# ---------------------------------------------------------------------------
# §4.6 筹码分布 CYQ（本地推演，输入需含 date/high/low/close/turn）
# ---------------------------------------------------------------------------

def _triangular_weights(grid: Any, low: float, high: float, avg: float) -> Any:
    """Daily chips over the price grid with a triangular profile peaking at avg."""
    import numpy as np

    w = np.zeros_like(grid)
    if not np.isfinite([low, high, avg]).all() or high < low:
        return w
    if high - low < 1e-9:
        w[np.argmin(np.abs(grid - low))] = 1.0
        return w
    avg = min(max(avg, low), high)
    left = (grid >= low) & (grid <= avg)
    right = (grid > avg) & (grid <= high)
    if avg - low > 1e-9:
        w[left] = (grid[left] - low) / (avg - low)
    else:
        w[left] = 1.0
    if high - avg > 1e-9:
        w[right] = (high - grid[right]) / (high - avg)
    else:
        w[right] = 1.0
    total = w.sum()
    if total > 0:
        return w / total
    w[np.argmin(np.abs(grid - avg))] = 1.0
    return w


def chip_distribution(df: pd.DataFrame, grid_size: int = 300, decay: float = 1.0) -> dict[str, Any]:
    """Local chip-distribution (CYQ) derivation from OHLC + turnover rows.

    ``df`` must contain ``date/high/low/close/turn`` (turn in percent, e.g. 0.31
    means 0.31%).  Rows are force-sorted by date ascending because turnover
    decay is a directional time recursion.  Returns profit_ratio / avg_cost /
    cost_90 / cost_70 / concentration / peak_price / histogram.
    """
    import numpy as np

    need = {"date", "high", "low", "close", "turn"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"chip_distribution 缺少列: {sorted(missing)}（date 用于强制时间升序）")
    d = df.dropna(subset=["high", "low", "close", "turn"]).copy()
    d = d[d["high"] > 0]
    if d.empty:
        raise ValueError("chip_distribution: 有效行数为 0（检查是否全是停牌日，或字段类型不对）")
    d = d.sort_values("date").reset_index(drop=True)

    lo, hi = float(d["low"].min()), float(d["high"].max())
    pad = (hi - lo) * 0.02 or max(lo * 0.02, 0.01)
    grid = np.linspace(lo - pad, hi + pad, grid_size)

    chips = None
    for row in d.itertuples(index=False):
        t = float(row.turn) / 100.0 * decay
        t = min(max(t, 0.0), 1.0)
        avg = (float(row.high) + float(row.low) + float(row.close)) / 3.0
        w = _triangular_weights(grid, float(row.low), float(row.high), avg)
        if w.sum() <= 0:
            continue
        if chips is None:
            chips = w.copy()
            continue
        chips = chips * (1.0 - t) + w * t
    if chips is None:
        raise RuntimeError("chip_distribution: 所有交易日的价格区间都无效，无法构建分布")

    total = chips.sum()
    if total <= 0:
        raise RuntimeError("chip_distribution: 筹码总量为 0，无法计算指标")
    chips = chips / total

    price = float(d["close"].iloc[-1])
    cum = np.cumsum(chips)

    def price_at(q: float) -> float:
        return float(np.interp(q, cum, grid))

    p05, p15, p85, p95 = (price_at(q) for q in (0.05, 0.15, 0.85, 0.95))
    peak_i = int(np.argmax(chips))
    return {
        "price": price,
        "profit_ratio": float(chips[grid <= price].sum()),
        "avg_cost": float((grid * chips).sum()),
        "cost_90": (p05, p95),
        "cost_70": (p15, p85),
        "concentration_90": float((p95 - p05) / (p95 + p05)) if p95 + p05 else None,
        "concentration_70": float((p85 - p15) / (p85 + p15)) if p85 + p15 else None,
        "peak_price": float(grid[peak_i]),
        "histogram": [
            (float(pp), float(cc)) for pp, cc in zip(grid, chips, strict=False) if cc > 1e-6
        ],
    }


def get_a_share_chip_distribution(ticker: str, start_date: str | None = None, end_date: str | None = None) -> str:
    """A-share chip distribution (CYQ) derived locally from baostock OHLC+turnover.

    This is a *derived* supplement: it combines baostock daily bars (qfq
    adjusted) with a local triangular-weights recursion.  Cost numbers are
    advisory heuristics, not an exchange-reported fact.
    """
    code = _require_a_share_code(ticker, "chip_distribution")
    end_date = end_date or datetime.now(_CN_TZ).strftime("%Y-%m-%d")
    start_date = start_date or (datetime.now(_CN_TZ) - timedelta(days=365)).strftime("%Y-%m-%d")
    bs_code = _bs_code(code, "chip_distribution")
    with _bs_session() as bs:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,turn,tradestatus",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",  # 2 = qfq: chip cost must use adjusted prices
        )
        k = _bs_to_df(rs)
    if k.empty:
        raise AshareCapabilityUnavailableError("chip_distribution", "baostock", "no rows in window")
    for col in ("open", "high", "low", "close", "turn"):
        k[col] = pd.to_numeric(k[col], errors="coerce")
    k = k[k["tradestatus"] == "1"]  # suspended days do not participate in turnover decay
    try:
        result = chip_distribution(k)
    except (ValueError, RuntimeError) as exc:
        raise AshareCapabilityUnavailableError("chip_distribution", "baostock", str(exc)) from exc
    summary = pd.DataFrame(
        [
            {
                "Price": round(result["price"], 2),
                "Profit Ratio": round(result["profit_ratio"], 4),
                "Avg Cost": round(result["avg_cost"], 2),
                "Cost 90 Low": round(result["cost_90"][0], 2),
                "Cost 90 High": round(result["cost_90"][1], 2),
                "Cost 70 Low": round(result["cost_70"][0], 2),
                "Cost 70 High": round(result["cost_70"][1], 2),
                "Concentration 90": round(result["concentration_90"], 4) if result["concentration_90"] else None,
                "Concentration 70": round(result["concentration_70"], 4) if result["concentration_70"] else None,
                "Peak Price": round(result["peak_price"], 2),
            }
        ]
    )
    _capture_vendor_raw(summary, metadata={"provider": "baostock", "dataset": "chip_distribution", "ticker": ticker})
    note = (
        "Local chip-distribution (CYQ) derivation from baostock qfq-adjusted OHLC + turnover; "
        "advisory heuristic, not an exchange-reported fact. profit_ratio in [0,1]; cost_90 contains cost_70."
    )
    return _render("chip_distribution", ticker, "baostock", summary, note)


# ---------------------------------------------------------------------------
# §6.7 申万行业变迁史 (swsresearch xls)
# ---------------------------------------------------------------------------

def get_sw_industry_history() -> str:
    """SW industry membership history (every industry change per stock, one row each).

    Uses the official SW Class 2021 table.  SW publishes *codes* only (no
    Chinese names); EastMoney/TDX industry names cannot be joined onto these.
    """
    try:
        r = requests.get(_SW_URL, headers=_SW_HEADERS, timeout=60)
        r.raise_for_status()
    except requests.exceptions.SSLError as exc:
        raise AshareCapabilityUnavailableError(
            "sw_industry_history",
            "swsresearch",
            "申万站点 SSL 握手失败；先试 `pip install -U certifi` 或检查本机 CA。原始错误: " + str(exc),
        ) from exc
    except requests.RequestException as exc:
        raise AshareCapabilityUnavailableError(
            "sw_industry_history", "swsresearch", type(exc).__name__
        ) from exc
    try:
        df = pd.read_excel(io.BytesIO(r.content))
    except Exception as exc:  # noqa: BLE001 - xls parse failure is a typed degradation
        raise AshareCapabilityUnavailableError("sw_industry_history", "swsresearch", f"xls parse failed: {type(exc).__name__}") from exc
    df = df.rename(columns={"股票代码": "code", "计入日期": "start_date", "行业代码": "industry_code", "更新日期": "update_date"})
    missing = {"code", "start_date", "industry_code"} - set(df.columns)
    if missing:
        raise AshareCapabilityUnavailableError(
            "sw_industry_history", "swsresearch", f"SW table schema changed, missing {sorted(missing)}"
        )
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["industry_code"] = df["industry_code"].astype(str).str.zfill(6)
    df["l1_code"] = df["industry_code"].str[:2] + "0000"
    df["l2_code"] = df["industry_code"].str[:4] + "00"
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df = df.sort_values(["code", "start_date"]).reset_index(drop=True)
    _capture_vendor_raw(df, metadata={"provider": "swsresearch", "dataset": "sw_industry_history"})
    note = (
        "Official SW Class 2021 industry membership history; codes only (no Chinese names). "
        "Use this instead of today's industry to avoid look-ahead bias in historical comparisons."
    )
    return _render("sw_industry_history", None, "swsresearch", df, note)


def _sw_industry_as_of(df: pd.DataFrame, code: str, as_of: str) -> dict[str, Any] | None:
    """Industry membership for ``code`` as of ``as_of`` (last change not after)."""
    code = str(code).zfill(6)
    sub = df[(df["code"] == code) & (df["start_date"] <= pd.to_datetime(as_of, errors="coerce"))]
    if sub.empty:
        return None
    return sub.sort_values("start_date").iloc[-1].to_dict()


# ---------------------------------------------------------------------------
# §11.1 / §11.2 宏观层（人民银行社融 / 统计局 PMI，零鉴权直连）
# ---------------------------------------------------------------------------

def _macro_get(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=_PBC_UA, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def get_china_social_financing(year: int | None = None) -> str:
    """PBOC social-financing incremental table (monthly, 亿元), latest year by default.

    This is a *direct* zero-auth complement to the existing AKShare china_macro
    chain: it does not depend on the optional akshare package and covers the
    12-column official 社融增量表.
    """
    try:
        idx = _macro_get(_PBC_INDEX)
    except requests.RequestException as exc:
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", type(exc).__name__) from exc
    years = re.findall(r"""href=["']([^"']+)["'][^>]*>\s*(\d{4})年统计数据\s*</a>""", idx)
    if not years:
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", "index page structure changed (no year links)")
    table = {int(y): href for href, y in years}
    target = max(table) if year is None else year
    if target not in table:
        raise AshareCapabilityUnavailableError(
            "china_social_financing", "pbc", f"no {target} data; available years: {sorted(table, reverse=True)[:8]}"
        )
    try:
        ypage = _macro_get(table[target] if table[target].startswith("http") else _PBC_BASE + table[target])
    except requests.RequestException as exc:
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", type(exc).__name__) from exc
    topics = re.findall(r"""href=["']([^"']+)["'][^>]*>\s*(社会融资规模)\s*</a>""", ypage)
    if not topics:
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", "year page has no 社会融资规模 topic link")
    topic_href = topics[0][0]
    try:
        tpage = _macro_get(topic_href if topic_href.startswith("http") else _PBC_BASE + topic_href)
    except requests.RequestException as exc:
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", type(exc).__name__) from exc
    xls_hrefs = re.findall(r"""href=["']([^"']+\.(?:xls|xlsx))["']""", tpage, re.I)
    if not xls_hrefs:
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", "topic page has no xls attachment")
    xls_url = xls_hrefs[-1] if xls_hrefs[-1].startswith("http") else _PBC_BASE + xls_hrefs[-1]
    try:
        r = requests.get(xls_url, headers=_PBC_UA, timeout=60)
        r.raise_for_status()
        df = pd.read_excel(io.BytesIO(r.content))
    except Exception as exc:  # noqa: BLE001 - degrade on any download/parse failure
        raise AshareCapabilityUnavailableError("china_social_financing", "pbc", f"download/parse failed: {type(exc).__name__}") from exc
    _capture_vendor_raw(df, metadata={"provider": "pbc", "dataset": "social_financing", "year": target})
    note = (
        "PBOC 社会融资规模增量统计表（官方口径，月度 亿元）。直接零鉴权抓取；"
        "如页面结构变化会 fail-fast 抛出类型化不可用，不静默返回空表。"
    )
    return _render("china_social_financing", None, "pbc", df, note)


def get_china_pmi() -> str:
    """NBS manufacturing / non-manufacturing / composite PMI (monthly).

    Direct zero-auth complement to the AKShare china_macro chain.  Uses the
    NBS easyquery endpoint; a changed API contract degrades to a typed error.
    """
    params = {
        "m": "QueryData",
        "dbcode": "hgyd",
        "rowcode": "zb",
        "colcode": "sj",
        "wds": "[]",
        "dfwds": '[{"wdcode":"zb","valuecode":"A090201,A090202,A090203"}]',
        "k1": str(int(datetime.now().timestamp() * 1000)),
    }
    try:
        r = requests.get(_NBS_PMI_URL, params=params, headers=_PBC_UA, timeout=30)
        r.raise_for_status()
        payload = r.json()
    except Exception as exc:  # noqa: BLE001
        raise AshareCapabilityUnavailableError("china_pmi", "nbs", f"request/parse failed: {type(exc).__name__}") from exc
    rows: list[dict[str, Any]] = []
    for node in payload.get("returndata", {}).get("datanodes", []):
        wds = {w["wdcode"]: w["valuecode"] for w in node.get("wds", [])}
        period = wds.get("sj", "")
        zb = wds.get("zb", "")
        value = (node.get("data", {}) or {}).get("data")
        rows.append({"period": period, "indicator": zb, "value": value})
    if not rows:
        raise AshareCapabilityUnavailableError("china_pmi", "nbs", "no data nodes returned")
    df = pd.DataFrame(rows)
    _capture_vendor_raw(df, metadata={"provider": "nbs", "dataset": "china_pmi"})
    note = "NBS PMI (manufacturing A090201 / non-manufacturing A090202 / composite A090203), monthly; official zero-auth."
    return _render("china_pmi", None, "nbs", df, note)
