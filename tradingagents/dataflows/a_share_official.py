"""Official-exchange A-share adapters: trading calendar, margin trading, 上证e互动.

These adapters read the exchanges themselves rather than a commercial
aggregator, because each dataset has exactly one authoritative record:

* the Shenzhen exchange publishes the whole-month trading calendar
  (``monthList``); it is the only source that can tell a closed weekend from an
  unpublished month, so an incomplete month must fail rather than schedule
  around the hole;
* margin-trading (融资融券) balances come from the Shanghai and Shenzhen
  official files, one exchange per call, because the two exchanges publish
  different schemas and the Beijing exchange is covered by neither;
* ``上证e互动`` is the Shanghai exchange's investor-relations platform and is
  the only public record of Shanghai-listed Q&A (CNINFO's 互动易 returns
  nothing for Shanghai codes).

Every adapter either returns a source-labelled report or raises a typed
``ChinaDataUnavailableError``.  A partial page, a changed schema, or an
unpublished month is never rendered as "there is no such data"; only an
explicit platform marker (暂无 / 暂时没有 / 没有找到相关内容) may produce a
zero-row report.
"""

from __future__ import annotations

import calendar
import html as _html
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any

import pandas as pd
import requests

from .china_data import ChinaDataUnavailableError
from .ticker_utils import infer_a_share_exchange, strict_ticker_code

SZSE_CALENDAR_URL = "https://www.szse.cn/api/report/exchange/onepersistenthour/monthList"
SSE_MARGIN_URL = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
SZSE_MARGIN_URL = "https://www.szse.cn/api/report/ShowReport"
SSE_E_BASE = "https://sns.sseinfo.com"

# Explicit request budget: a connect timeout plus a hard 20s read timeout, so a
# hung exchange endpoint can never block an analysis run unbounded.
_HTTP_TIMEOUT = (10, 20)
_OFFICIAL_UA = "Mozilla/5.0"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 上证e互动 feed type codes (a-stock-data v3.10.0 §10.2): 11 = answered Q&A,
# 10 = questions, including the ones without a reply yet.
_SSE_KIND = {"answered": 11, "questions": 10}
# "No Q&A" marker: a company page says 近1个月暂无回复 / 暂无提问 and the
# market-wide list says 暂时没有问答内容 past its last page (observed 2026-09-20).
_SSE_EMPTY_NOTE = re.compile(r'class="m_feed_note"[^>]*>[^<]*(暂无|暂时没有)[^<]*<')
_SSE_COMPANY_END = "没有任何上市公司的信息"
_SSE_COLUMNS = [
    "id",
    "code",
    "name",
    "asker",
    "question",
    "question_time",
    "answer",
    "answer_time",
]
# Module-level uid cache: resolving a company costs ~10-13 company-list
# requests (doubling + binary search), so it is paid once per process.
_SSE_UID_CACHE: dict[str, str] = {}
_SSE_COMPANY_PAGES: dict[int, list[tuple[str, str]]] = {}

_SH_MARGIN_FIELDS = {
    "rzye": "margin_balance",
    "rzmre": "margin_buy",
    "rqylje": "short_balance",
    "rqyl": "short_volume",
    "rqmcl": "short_sell_volume",
}
_SZ_MARGIN_FIELDS = {
    "融资余额(元)": "margin_balance",
    "融资买入额(元)": "margin_buy",
    "融券余额(元)": "short_balance",
    "融券余量(股/份)": "short_volume",
    "融券卖出量(股/份)": "short_sell_volume",
}


def get_a_share_trading_calendar(year: int, month: int) -> str:
    """Shenzhen exchange whole-month trading calendar.

    Returns one row per *natural* day of the requested month with ``is_open``
    taken from the exchange's ``jybz`` flag (1 = session, 0 = closed), so
    weekends and 调休 are visible rather than inferred.  The returned dates must
    equal the complete set of calendar days of that month: an unpublished,
    mis-aligned, or short month raises instead of silently scheduling around
    the hole.
    """
    if type(year) is not int or type(month) is not int or not 1 <= month <= 12:
        raise ValueError("year/month 必须为整数，month 在 1–12 之间")
    last_day = calendar.monthrange(year, month)[1]
    expected = {date(year, month, day).isoformat() for day in range(1, last_day + 1)}
    response = _official_get(SZSE_CALENDAR_URL, {"month": f"{year}-{month}"})
    payload = _json_object(response, "深交所日历")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ChinaDataUnavailableError("深交所尚未返回该月日历；不能推断全月休市")
    rows: list[dict[str, Any]] = []
    for record in data:
        if not isinstance(record, Mapping):
            raise ChinaDataUnavailableError("深交所日历条目不是对象，页面结构可能已变")
        if str(record.get("jybz")) not in ("0", "1") or not record.get("jyrq"):
            raise ChinaDataUnavailableError("深交所日历字段异常")
        rows.append({"date": _source_date(record["jyrq"]), "is_open": str(record["jybz"]) == "1"})
    frame = _official_frame(rows, ["date"], "szse", SZSE_CALENDAR_URL)
    if set(frame["date"]) != expected:
        raise ChinaDataUnavailableError("日历月份错位或日期不完整，不能继续调度")
    _capture_vendor_raw(
        payload,
        metadata={
            "provider": "szse",
            "dataset": "trading_calendar",
            "year": str(year),
            "month": str(month),
        },
    )
    return _format_report(
        frame,
        title=f"China A-share trading calendar for {year}-{month:02d}",
        caveat=(
            "深交所官方整月日历；行覆盖该自然月全部自然日，is_open=1 表示交易日"
            "（周末与调休不作交易日）；缺一天即报错，不会静默顺延。"
        ),
        source="szse",
        source_url=SZSE_CALENDAR_URL,
    )


def get_a_share_margin_trading_backup(
    trade_date: str,
    exchange: str,
    ticker: str | None = None,
) -> str:
    """Exchange-official margin-trading (融资融券) snapshot for one exchange.

    One call covers exactly one exchange; ``exchange`` must be ``SH`` or ``SZ``
    because the Beijing exchange publishes neither file.  The Shanghai endpoint
    is paged by ``pageHelp.total`` and the Shenzhen endpoint is a single xlsx,
    so the whole snapshot is validated before any ``ticker`` filter is applied:
    a filter is never allowed to hide an incomplete read.
    """
    try:
        day = _official_date(trade_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("trade_date 必须是 YYYYMMDD 或 YYYY-MM-DD") from exc
    exchange = str(exchange).upper()
    if exchange not in ("SH", "SZ"):
        raise ValueError("exchange 必须为 SH 或 SZ；本函数不覆盖北交所两融")
    code = None
    if ticker is not None:
        code = _official_margin_code(strict_ticker_code(ticker, stock_only=True), exchange)
    frame = (
        _sh_margin_frame(day, exchange)
        if exchange == "SH"
        else _sz_margin_frame(day, exchange)
    )
    if code is not None:
        frame = frame.loc[frame["code"] == code].reset_index(drop=True)
        if frame.empty:
            # The snapshot is complete, so this is a fact about the security,
            # not an unexplained empty result -- say so explicitly.
            raise ChinaDataUnavailableError(
                f"{code} 不在 {day} {exchange} 官方两融完整名单中"
                "（快照已核对完整，该证券当日没有两融记录）"
            )
    caveat = (
        f"交易所官方两融完整快照，一次只覆盖 {exchange}（北交所不在本函数范围内）；"
        "上交所按 pageHelp.total 核对分页、深交所按官方 xlsx 核对行结构，"
        "缺页或行列变化一律报错。"
    )
    if code is not None:
        caveat += f" 已从完整快照中按 {code} 过滤。"
    return _format_report(
        frame,
        title=f"China A-share margin trading for {day} ({exchange})",
        caveat=caveat,
        source="sse" if exchange == "SH" else "szse",
        source_url=SSE_MARGIN_URL if exchange == "SH" else SZSE_MARGIN_URL,
    )


def get_a_share_sse_e_interaction(
    ticker: str | None = None,
    kind: str = "answered",
    page: int = 1,
    page_size: int = 10,
) -> str:
    """上证e互动 — investor questions and Shanghai-listed company replies.

    ``ticker=None`` reads the market-wide feed; a Shanghai code (60/68/900)
    reads one company, whose platform ``uid`` is resolved from the company list
    and cached module-level.  ``kind='answered'`` returns answered Q&A while
    ``kind='questions'`` also includes questions with ``answer=None``.

    The platform only exposes recent Q&A (company view: roughly the last
    month).  A parsed zero-row page is only believed when the page carries an
    explicit 暂无/暂时没有 marker; rows for a different company mean the uid
    mapping drifted and raise.
    """
    if kind not in _SSE_KIND:
        raise ValueError("kind 只能是 'answered' 或 'questions'")
    try:
        page_no = int(page)
        size = int(page_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("page 与 page_size 必须为整数") from exc
    if page_no < 1 or not 1 <= size <= 50:
        raise ValueError("page 从 1 开始，page_size 范围 1–50")
    digits: str | None = None
    if ticker is None:
        response = _http_request(
            "GET",
            SSE_E_BASE + "/ajax/feeds.do",
            params={
                "type": _SSE_KIND[kind],
                "pageSize": size,
                "lastid": -1,
                "show": 1,
                "page": page_no,
            },
            referer=SSE_E_BASE + "/",
        )
    else:
        digits = strict_ticker_code(ticker, stock_only=True)
        if infer_a_share_exchange(digits) != "SH":
            raise ValueError(
                f"{ticker} 不是沪市证券：上证e互动只覆盖沪市 60/68/900 代码；"
                "深市/北交所互动问答请走巨潮互动易 cninfo_irm 路径"
            )
        response = _http_request(
            "POST",
            SSE_E_BASE + "/ajax/userfeeds.do",
            data={
                "typeCode": "company",
                "type": _SSE_KIND[kind],
                "pageSize": size,
                "uid": _sse_company_uid(digits),
                "page": page_no,
            },
            referer=SSE_E_BASE + "/",
        )
    text = response.content.decode("utf-8", "replace")
    rows = _sse_parse_feed(text)
    # Only an explicit 暂无 / 暂时没有 note makes a parsed zero-row page mean
    # "genuinely no Q&A"; anything else is a changed page structure.
    if not rows and not _SSE_EMPTY_NOTE.search(text):
        raise ChinaDataUnavailableError("上证e互动返回的页面既没有问答也没有「暂无」提示，结构可能已变")
    if digits is not None and any(row["code"] != digits for row in rows):
        raise ChinaDataUnavailableError("上证e互动返回了其他公司的问答，uid 映射可能已变")
    _capture_vendor_raw(
        text,
        metadata={
            "provider": "sse_e",
            "dataset": "investor_interaction",
            "ticker": digits or "",
        },
    )
    frame = _frame(rows, columns=_SSE_COLUMNS, source="sse_e", url=SSE_E_BASE + "/")
    scope = digits or "全市场"
    return _format_report(
        frame,
        title=f"China A-share 上证e互动 {kind} for {scope} (page {page_no})",
        caveat=(
            "上交所官方互动平台；平台只开放近期问答（公司维度约近 1 个月），"
            "更早的翻页为空；页面没有明确的暂无/暂时没有提示时不会把 0 条当成没有数据。"
        ),
        source="sse_e",
        source_url=SSE_E_BASE + "/",
        empty_note=(
            "平台页面明确标注「暂无 / 暂时没有」问答，本页确认没有数据（不是解析失败）。"
            if not rows
            else None
        ),
    )


# --------------------------------------------------------------------------- #
# Official HTTP + parsing helpers
# --------------------------------------------------------------------------- #
def _http_request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    referer: str | None = None,
    user_agent: str | None = None,
) -> requests.Response:
    """One explicit-timeout exchange request; every transport fault is typed."""
    headers = {"User-Agent": user_agent or _BROWSER_UA, "Referer": referer or url}
    send = requests.get if method == "GET" else requests.post
    extra = {"params": params} if method == "GET" else {"data": data}
    try:
        response = send(url, headers=headers, timeout=_HTTP_TIMEOUT, **extra)
    except requests.RequestException as exc:
        raise ChinaDataUnavailableError(f"请求 {url} 失败: {type(exc).__name__}: {exc}") from exc
    if not 200 <= int(response.status_code) < 300:
        raise ChinaDataUnavailableError(f"{url} 返回 HTTP {response.status_code}")
    return response


def _official_get(
    url: str,
    params: Mapping[str, Any] | None = None,
    referer: str | None = None,
) -> requests.Response:
    """Official exchange GET with the upstream referer/UA pairing."""
    return _http_request("GET", url, params=params, referer=referer, user_agent=_OFFICIAL_UA)


def _json_object(response: requests.Response, what: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ChinaDataUnavailableError(f"{what} 返回的不是 JSON，可能是错误页") from exc
    if not isinstance(payload, Mapping):
        raise ChinaDataUnavailableError(f"{what} 返回的 JSON 根不是对象")
    return payload


def _official_code(value: object) -> str:
    """Caller-supplied security code; a malformed argument is a ``ValueError``."""
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{6}", text):
        raise ValueError("代码必须是 6 位纯数字；指数 provider 与证券交易所不是同一概念")
    return text


def _official_margin_code(value: object, exchange: str) -> str:
    """Caller-supplied margin code; a segment/exchange mismatch is a ``ValueError``."""
    code = _official_code(value)
    prefixes = ("5", "6", "900") if exchange == "SH" else ("0", "1", "2", "3")
    if not code.startswith(prefixes):
        raise ValueError("两融证券代码与请求的交易所不符")
    return code


def _source_margin_code(value: object, exchange: str) -> str:
    """A vendor row whose code contradicts the requested exchange is a source defect."""
    try:
        return _official_margin_code(value, exchange)
    except ValueError as exc:
        raise ChinaDataUnavailableError(
            f"官方两融数据中出现了与 {exchange} 不符的证券代码 {value!r}"
        ) from exc


def _official_date(value: object) -> str:
    """``20260918`` / ``2026-09-18`` / ``date`` -> ``YYYY-MM-DD``; else ``ValueError``."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    fmt = "%Y%m%d" if re.fullmatch(r"[0-9]{8}", text) else "%Y-%m-%d"
    return datetime.strptime(text, fmt).date().isoformat()


def _source_date(value: object) -> str:
    """A date returned by a source: unparseable means the source format changed."""
    try:
        return _official_date(value)
    except (TypeError, ValueError) as exc:
        raise ChinaDataUnavailableError(f"来源返回了无法识别的日期 {value!r}") from exc


def _official_number(value: object, required: bool = False) -> float | None:
    """Official numeric cell; empty-style placeholders are ``None`` unless required."""
    if pd.isna(value) or str(value).strip() in ("", "-", "--"):
        if required:
            raise ChinaDataUnavailableError("官方源缺少必需数值")
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ChinaDataUnavailableError(f"官方源返回了无法识别的数值 {value!r}") from exc
    if not math.isfinite(number):
        raise ChinaDataUnavailableError("官方源返回非有限数值")
    return number


def _official_total(value: object) -> int:
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise ChinaDataUnavailableError("官方分页总数必须为非负整数")
    return int(str(value))


def _official_columns(frame: pd.DataFrame, names: Sequence[str]) -> None:
    missing = set(names) - set(frame.columns)
    if missing:
        raise ChinaDataUnavailableError("官方数据列缺失: " + ", ".join(sorted(missing)))


def _official_excel(response: requests.Response) -> pd.DataFrame:
    try:
        frame = pd.read_excel(BytesIO(response.content), dtype=str)
    except Exception as exc:  # noqa: BLE001 - any xls parse failure is a typed degradation
        raise ChinaDataUnavailableError(
            "官方源未返回可解析的 Excel；可能未发布或响应结构改变"
        ) from exc
    # Header whitespace differs slightly between official files, so match on
    # the de-whitespaced column names.
    frame.columns = [re.sub(r"\s+", "", str(column)) for column in frame.columns]
    return frame


def _frame(
    rows: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str] | None = None,
    source: str,
    url: str,
) -> pd.DataFrame:
    """Attach source provenance; an empty frame keeps its declared columns."""
    frame = pd.DataFrame(list(rows), columns=columns)
    frame["source"] = source
    frame["source_url"] = url
    frame["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return frame


def _official_frame(
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    source: str,
    url: str,
) -> pd.DataFrame:
    """A complete official snapshot: empty or duplicate-keyed data is not a snapshot."""
    frame = pd.DataFrame(list(rows))
    if frame.empty or frame.duplicated(list(keys)).any():
        raise ChinaDataUnavailableError("官方数据为空或主键重复，不能当成完整快照")
    return _frame(rows, source=source, url=url).sort_values(list(keys)).reset_index(drop=True)


def _sh_margin_frame(day: str, exchange: str) -> pd.DataFrame:
    response = _official_get(
        SSE_MARGIN_URL,
        {
            "isPagination": "true",
            "tabType": "mxtype",
            "detailsDate": day.replace("-", ""),
            "pageHelp.pageSize": 5000,
            "pageHelp.pageNo": 1,
            "pageHelp.beginPage": 1,
            "pageHelp.cacheSize": 1,
            "pageHelp.endPage": 1,
        },
        "https://www.sse.com.cn/",
    )
    payload = _json_object(response, "上交所两融")
    page = payload.get("pageHelp")
    page = page if isinstance(page, Mapping) else {}
    data = page.get("data")
    if not isinstance(data, list) or not data or len(data) != _official_total(page.get("total")):
        raise ChinaDataUnavailableError("上交所该日数据未发布或分页不完整")
    required = {"stockCode", *_SH_MARGIN_FIELDS}
    rows: list[dict[str, Any]] = []
    for record in data:
        if not isinstance(record, Mapping):
            raise ChinaDataUnavailableError("上交所两融条目不是对象，响应结构可能已变")
        if _source_date(record.get("opDate")) != day:
            raise ChinaDataUnavailableError("上交所两融数据日期不符")
        if not required.issubset(record):
            raise ChinaDataUnavailableError("上交所两融字段发生变化")
        rows.append(
            {
                "date": day,
                "code": _source_margin_code(record["stockCode"], exchange),
                "name": record.get("securityAbbr"),
                "exchange": exchange,
                **{
                    dest: _official_number(record[src], required=(src != "rqylje"))
                    for src, dest in _SH_MARGIN_FIELDS.items()
                },
            }
        )
    _capture_vendor_raw(
        payload,
        metadata={"provider": "sse", "dataset": "margin_trading", "trade_date": day},
    )
    return _official_frame(rows, ["date", "code"], "sse", SSE_MARGIN_URL)


def _sz_margin_frame(day: str, exchange: str) -> pd.DataFrame:
    response = _official_get(
        SZSE_MARGIN_URL,
        {
            "SHOWTYPE": "xlsx",
            "CATALOGID": "1837_xxpl",
            "TABKEY": "tab2",
            "txtDate": day,
        },
        "https://www.szse.cn/",
    )
    data = _official_excel(response)
    _official_columns(data, ["证券代码", "证券简称", *_SZ_MARGIN_FIELDS])
    rows = [
        {
            "date": day,
            "code": _source_margin_code(str(record["证券代码"]).zfill(6), exchange),
            "name": record["证券简称"],
            "exchange": exchange,
            **{
                dest: _official_number(record[src], required=True)
                for src, dest in _SZ_MARGIN_FIELDS.items()
            },
        }
        for record in data.to_dict("records")
    ]
    _capture_vendor_raw(
        data.to_dict("records"),
        metadata={"provider": "szse", "dataset": "margin_trading", "trade_date": day},
    )
    return _official_frame(rows, ["date", "code"], "szse", SZSE_MARGIN_URL)


# --------------------------------------------------------------------------- #
# 上证e互动 company-list resolution and feed parsing
# --------------------------------------------------------------------------- #
def _sse_company_page(page: int) -> list[tuple[str, str]]:
    """One page of the platform's company list as ``[(code, uid), ...]``."""
    if page not in _SSE_COMPANY_PAGES:
        response = _http_request(
            "POST",
            SSE_E_BASE + "/allcompany.do",
            data={"code": "0", "order": "2", "areaId": "0", "page": page},
            referer=SSE_E_BASE + "/",
        )
        payload = _json_object(response, f"上证e互动公司列表第 {page} 页")
        content = payload.get("content")
        if not isinstance(content, str):
            raise ChinaDataUnavailableError(
                f"上证e互动公司列表第 {page} 页的返回结构变了（没有 content 字符串）"
            )
        pairs = [
            (code, uid)
            for uid, code in re.findall(
                r"uid=['\"]?(\d+)['\"]?[^>]*>\s*<img[^>]*company/(\d{6})\.png", content
            )
        ]
        # Past the last page the endpoint returns 没有任何上市公司的信息 (observed
        # at page 74 on 2026-09-20).  Page 1 empty, or any other page that has
        # no companies and no end marker, means the page format changed.
        if not pairs and (page == 1 or _SSE_COMPANY_END not in content):
            raise ChinaDataUnavailableError(
                f"上证e互动公司列表第 {page} 页解析出 0 家公司，页面格式可能已变"
            )
        _SSE_COMPANY_PAGES[page] = pairs
        for code, uid in pairs:
            _SSE_UID_CACHE[code] = uid
    return _SSE_COMPANY_PAGES[page]


def _sse_company_uid(code: str) -> str:
    """Locate a company uid in the code-ascending list (32 companies/page).

    Upstream doubles the page number to bracket the code, then binary-searches
    the range; the resolved uid and every visited page are cached module-level.
    """
    if code in _SSE_UID_CACHE:
        return _SSE_UID_CACHE[code]
    low, high = 1, 1
    while _sse_company_page(high):  # double until the page past the code's range
        if _sse_company_page(high)[-1][0] >= code:
            break
        low, high = high, high * 2
    while low <= high:
        mid = (low + high) // 2
        pairs = _sse_company_page(mid)
        if not pairs or code < pairs[0][0]:
            high = mid - 1
        elif code > pairs[-1][0]:
            low = mid + 1
        else:
            break
    if code not in _SSE_UID_CACHE:
        raise ChinaDataUnavailableError(
            f"上证e互动没有 {code}（公司不在上交所，或已退市）"
        )
    return _SSE_UID_CACHE[code]


def _sse_parse_feed(text: str) -> list[dict[str, Any]]:
    """Split the feed on the reply block marker ``class="m_feed_detail m_qa"``.

    The "latest replies" and "latest questions" lists use different markup
    (whether the question box carries an id), so Q&A are separated positionally
    rather than by id.  The market-wide list uses
    ``class="m_feed_detail m_qa_detail"``, hence the full-class split.
    """
    rows: list[dict[str, Any]] = []
    for chunk in re.split(r'<div class="m_feed_item[^"]*" id="item-', text)[1:]:
        numbered = re.match(r"(\d+)", chunk)
        if not numbered:
            raise ChinaDataUnavailableError(
                f"上证e互动条目 id 不是数字，页面结构可能已变: {chunk[:60]}"
            )
        item_id = numbered.group(1)
        ask_part, _, answer_part = chunk.partition('class="m_feed_detail m_qa"')
        question = re.search(
            r'<div class="m_feed_txt"[^>]*>\s*<a[^>]*>:(.*?)\((\d{6})\)</a>(.*?)</div>',
            ask_part,
            re.S,
        )
        asker = re.search(r'rel="face"[^>]*?title="([^"]*)"', ask_part, re.S)
        ask_time = re.search(r'<div class="m_feed_from"[^>]*>\s*<span>([^<]+)</span>', ask_part)
        if not question or not ask_time:
            raise ChinaDataUnavailableError(
                f"上证e互动第 {item_id} 条结构改变，无法解析问题或时间"
            )
        answer = answer_time = None
        if answer_part:
            body = re.search(r'<div class="m_feed_txt"[^>]*>(.*?)</div>', answer_part, re.S)
            when = re.search(r'<div class="m_feed_from"[^>]*>\s*<span>([^<]+)</span>', answer_part)
            if not body or not when:
                raise ChinaDataUnavailableError(
                    f"上证e互动第 {item_id} 条有回复块但解析不出回复内容或回复时间"
                )
            answer, answer_time = _sse_text(body.group(1)), _sse_time(when.group(1))
            if answer_time is None:  # 500 observed Q&A (250 replies) had no missing time
                raise ChinaDataUnavailableError(
                    f"上证e互动第 {item_id} 条的回复时间认不出: {when.group(1)!r}"
                )
        rows.append(
            {
                "id": item_id,
                "code": question.group(2),
                "name": _sse_text(question.group(1)),
                "asker": asker.group(1) if asker else None,
                "question": _sse_text(question.group(3)),
                "question_time": _sse_required_time(item_id, ask_time.group(1)),
                "answer": answer,
                "answer_time": answer_time,
            }
        )
    return rows


def _sse_time(text: str) -> str | None:
    match = re.search(r"(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}:\d{2})", text)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}"


def _sse_required_time(item_id: str, text: str) -> str:
    """A question time that cannot be parsed means the time format changed."""
    when = _sse_time(text)
    if when is None:
        raise ChinaDataUnavailableError(f"上证e互动第 {item_id} 条的提问时间认不出: {text!r}")
    return when


def _sse_text(fragment: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


# --------------------------------------------------------------------------- #
# Report rendering + provenance
# --------------------------------------------------------------------------- #
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
