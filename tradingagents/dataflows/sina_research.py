"""Sina research-report list adapter — the independent second research source.

EastMoney's report API (``china_specialty_em.get_a_share_research_reports``) is
the primary research-report source and carries ratings and target prices.  This
module adds the Sina list, which is independent of EastMoney and therefore
useful when the EastMoney IP is throttled — at the cost of *not* carrying
ratings or target prices, which the rendered report states explicitly.

Sina serves a bogus ``没有找到相关内容`` page (HTTP 200, indistinguishable from a
genuine empty result) on rapid consecutive requests, so the adapter enforces a
minimum interval between requests and retries an empty page once.  A page whose
numbered table rows do not all parse, or whose research-table markers are
missing, raises ``ChinaDataUnavailableError`` instead of reporting "no reports".
"""

from __future__ import annotations

import html as _html
import re
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .ticker_utils import infer_a_share_exchange, strict_ticker_code

SINA_REPORT_URL = "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/{kind}/index.phtml"
SINA_REPORT_REFERER = "https://finance.sina.com.cn/"
# Observed 2026-09-20: two per-stock report searches 1s apart returned the fake
# empty page from the second request on; >=5s was healthy.  A minimum interval
# plus one retry keeps batch paging honest at the cost of being slow.
SINA_REPORT_MIN_INTERVAL = 6.0
_sina_report_last = [0.0]
_SINA_EMPTY_NOTE = "没有找到相关内容"
_SINA_REPORT_ROW = re.compile(
    r"<tr>\s*<td>\d+</td>\s*<td class=\"tal f14\">\s*<a[^>]*?title=\"([^\"]*)\"[^>]*?"
    r"href=\"([^\"]*?/rptid/(\d+)/[^\"]*)\"[^>]*>.*?</a>\s*</td>\s*"
    r"<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
    re.S,
)
_SINA_NUMBERED_ROW = re.compile(r"<tr>\s*<td>\d+</td>")
_SINA_COLUMNS = ["date", "title", "type", "org", "author", "report_id", "url"]

_HTTP_TIMEOUT = (10, 20)
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def get_sina_research_reports(ticker: str | None = None, page: int = 1) -> str:
    """Sina research-report list: title/type/date/org/analyst plus a detail URL.

    ``ticker=None`` returns the market-wide latest page (``kind="lastest"``);
    a code switches to the per-stock search (``kind="search"``).  Each page
    holds roughly 40 rows and ``page`` starts at 1.  This source carries **no
    ratings and no target prices** — the report header says so; use the
    EastMoney adapter when those fields are required.
    """
    try:
        page_no = int(page)
    except (TypeError, ValueError) as exc:
        raise ValueError("page 必须为整数") from exc
    if page_no < 1:
        raise ValueError("page 从 1 开始")
    if ticker is None:
        url = SINA_REPORT_URL.format(kind="lastest")
        params: dict[str, Any] = {"p": page_no}
        title = f"China A-share research reports for the whole market (Sina, page {page_no})"
    else:
        url = SINA_REPORT_URL.format(kind="search")
        symbol = strict_ticker_code(ticker, stock_only=True)
        # Beijing codes need the bj prefix: with a bare six-digit code Sina
        # returns a fake 没有找到相关内容 page (observed 2026-09-20, 920982).
        if infer_a_share_exchange(symbol) == "BJ":
            symbol = "bj" + symbol
        params = {"symbol": symbol, "t1": "all", "p": page_no}
        title = f"China A-share research reports for {symbol} (Sina, page {page_no})"
    response, text = _sina_report_page(url, params)
    if "tb_01" not in text or "研究员" not in text:
        raise ChinaDataUnavailableError("新浪研报页面结构改变（找不到研报表格）")
    rows: list[dict[str, Any]] = []
    for reported_title, href, report_id, kind, day, org, author in _SINA_REPORT_ROW.findall(text):
        rows.append(
            {
                "date": _source_date(day.strip()),
                "title": _html.unescape(reported_title).strip(),
                "type": kind.strip(),
                "org": _sina_text(org),
                "author": _sina_text(author),
                "report_id": report_id,
                "url": ("https:" + href) if href.startswith("//") else href,
            }
        )
    # Every page numbers its rows from 1 (observed on pages 2 and 3 too), so the
    # numbered rows must all parse.  Zero rows is only a real "no reports" when
    # the page says 没有找到相关内容 (past the last page / no research at all).
    numbered = len(_SINA_NUMBERED_ROW.findall(text))
    if len(rows) != numbered or (not rows and _SINA_EMPTY_NOTE not in text):
        raise ChinaDataUnavailableError(
            f"新浪研报表格有 {numbered} 行带序号、解析出 {len(rows)} 条，行结构可能已变"
        )
    _capture_vendor_raw(
        text,
        metadata={
            "provider": "sina",
            "dataset": "research_reports",
            "ticker": ticker or "",
            "page": str(page_no),
        },
    )
    frame = _frame(rows, columns=_SINA_COLUMNS, source="sina", url=url)
    return _format_report(
        frame,
        title=title,
        caveat=(
            "新浪研报列表只提供标题/类型/日期/机构/研究员与详情页链接，"
            "不含评级与目标价（需要评级或目标价请用东财研报）；"
            "连续请求会被新浪用假的空页限流，本函数已内置最小请求间隔与一次重试。"
        ),
        source="sina",
        source_url=url,
        empty_note=(
            "页面明确写着「没有找到相关内容」（翻过末页或该股确实没有研报），"
            "因此 0 条是来源事实而不是解析失败。"
            if not rows
            else None
        ),
    )


def _sina_report_page(
    url: str, params: Mapping[str, Any]
) -> tuple[requests.Response, str]:
    """Fetch one page, enforcing the minimum interval and retrying a fake empty page.

    The timestamp is refreshed even when the request raises, so a failed call
    still counts against the throttle window.
    """
    response: requests.Response | None = None
    text = ""
    for _ in range(2):
        wait = SINA_REPORT_MIN_INTERVAL - (time.time() - _sina_report_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            response = _request("GET", url, params=params)
        finally:
            _sina_report_last[0] = time.time()
        text = response.content.decode("gbk", "replace")
        if _SINA_EMPTY_NOTE not in text:
            return response, text
    assert response is not None  # the loop always runs at least once
    return response, text


def _request(method: str, url: str, *, params: Mapping[str, Any] | None = None) -> requests.Response:
    """One explicit-timeout Sina request; every transport fault is typed."""
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": _BROWSER_UA, "Referer": SINA_REPORT_REFERER},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ChinaDataUnavailableError(f"请求 {url} 失败: {type(exc).__name__}: {exc}") from exc
    if not 200 <= int(response.status_code) < 300:
        raise ChinaDataUnavailableError(f"{url} 返回 HTTP {response.status_code}")
    return response


def _source_date(value: object) -> str:
    """A date returned by the source; unparseable means the source format changed."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    fmt = "%Y%m%d" if re.fullmatch(r"[0-9]{8}", text) else "%Y-%m-%d"
    try:
        return datetime.strptime(text, fmt).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ChinaDataUnavailableError(f"来源返回了无法识别的日期 {value!r}") from exc


def _sina_text(fragment: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _frame(
    rows: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str],
    source: str,
    url: str,
) -> pd.DataFrame:
    """Attach source provenance; an empty frame keeps its declared columns."""
    frame = pd.DataFrame(list(rows), columns=columns)
    frame["source"] = source
    frame["source_url"] = url
    frame["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return frame


def _format_report(
    data: pd.DataFrame,
    *,
    title: str,
    caveat: str,
    source: str,
    source_url: str | None = None,
    empty_note: str | None = None,
) -> str:
    """Source-labelled report; an empty table is only allowed with an explicit note."""
    if data.empty and empty_note is None:
        raise ChinaDataUnavailableError(f"{source} returned no rows for {title}.")
    note = f"{caveat} {empty_note}" if empty_note else caveat
    lines = [f"# {title}", f"# Source: {source}"]
    if source_url:
        lines.append(f"# Source URL: {source_url}")
    lines += [
        f"# Note: {note}",
        f"# Total records: {len(data)}",
        f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        data.to_csv(index=False),
    ]
    return "\n".join(lines)


def _capture_vendor_raw(payload: Any, *, metadata: Mapping[str, str]) -> None:
    """Load cross-cutting observability after a successful data call only."""
    from tradingagents.observability.provenance import capture_vendor_raw

    capture_vendor_raw(payload, metadata=dict(metadata))
