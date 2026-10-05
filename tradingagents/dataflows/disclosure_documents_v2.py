"""Bounded v5 official disclosure parser; legacy PDF parsing stays unchanged."""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from decimal import Decimal

from tradingagents.agents.schemas._evidence_checks import OfficialNumericRowV1
from tradingagents.dataflows.disclosure_documents import MAX_PDF_BYTES, MAX_PDF_PAGES, pdf_url
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable

PARSER_VERSION = "official-pdf-v2"
NUMERIC_SOURCE = "cninfo.numeric_row.v2"
NUMBER = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
SCALES = {"元": Decimal(1), "万元": Decimal(10000), "百万元": Decimal(1000000), "亿元": Decimal(100000000)}
BRIDGE_FIELDS = {
    "净利润": "net_income", "加：资产减值准备": "asset_impairment", "资产减值准备": "asset_impairment",
    "信用减值损失": "credit_impairment", "固定资产折旧": "depreciation",
    "使用权资产摊销": "right_of_use_amortization", "无形资产摊销": "intangible_amortization",
    "长期待摊费用摊销": "deferred_expense_amortization", "处置固定资产": "asset_disposal_loss",
    "固定资产报废损失": "asset_retirement_loss", "公允价值变动损失": "fair_value_loss",
    "财务费用": "finance_cost", "投资损失": "investment_loss",
    "递延所得税资产减少": "deferred_tax_asset", "递延所得税负债增加": "deferred_tax_liability",
    "存货的减少": "inventory", "经营性应收项目的减少": "operating_receivables",
    "经营性应付项目的增加": "operating_payables", "其他": "other",
    "经营活动产生的现金流量净额": "cfo",
}


def title_info(title):
    compact = re.sub(r"\s", "", title)
    if "修订" in compact or "更正" in compact:
        return None
    match = re.search(r"(20\d{2})年(半年度|年度)报告(摘要)?$", compact)
    if match:
        return {"period": match[1] + ("-06-30" if match[2] == "半年度" else "-12-31"),
                "kind": "summary" if match[3] else "report"}
    match = re.search(r"(20\d{2})年半年度主要(?:运营|经营)数据", compact)
    if match and "公告" in compact:
        return {"period": match[1] + "-06-30", "kind": "operating_notice"}
    return None


def select_documents(rows, cutoff):
    ordered = sorted((r for r in rows if isinstance(r.get("Published"), str) and r["Published"] <= cutoff),
        key=lambda r: (r["Published"], r["Announcement ID"]), reverse=True)
    reports = [(r, title_info(r.get("Title", ""))) for r in ordered]
    reports = [(r, info) for r, info in reports if info and info["kind"] == "report" and info["period"] <= cutoff]
    chosen = [max(reports, key=lambda pair: (pair[1]["period"], pair[0]["Published"]))[0]] if reports else []
    period = title_info(chosen[0]["Title"])["period"] if chosen else None
    for kind in ("summary", "operating_notice"):
        for row in ordered:
            info = title_info(row.get("Title", ""))
            if info and info["kind"] == kind and info["period"] == period:
                chosen.append(row)
                break
    for row in ordered:
        title = row.get("Title", "")
        if (row not in chosen and not title_info(title)
                and any(word in title for word in ("合同", "投资", "项目", "回购", "减持", "增持", "关联交易"))
                and not any(word in title for word in ("法律意见", "评估报告", "审核意见", "H股", "会议决议"))
                and (date.fromisoformat(cutoff)-date.fromisoformat(row["Published"])).days <= 90):
            chosen.append(row)
            break
    return chosen[:4]


def _row(kind, field, label, values, page, header_page, header, raw, period, unit, frequency=None):
    frequency = frequency or ("H1" if period.endswith("06-30") else "FY")
    prior = str(int(period[:4])-1) + period[4:]
    scale = SCALES[unit] if kind != "operating" else Decimal(1)
    raw_current, raw_previous = values
    def normalized(value):
        return str(Decimal(value.replace(",", ""))*scale) if value is not None else None
    return OfficialNumericRowV1(kind=kind, field=field, label=label[:180], period=period,
        prior_period=prior, frequency=frequency, unit="CNY" if kind != "operating" else unit,
        raw_unit=unit, raw_current=raw_current, raw_previous=raw_previous,
        current=normalized(raw_current), previous=normalized(raw_previous), page=page,
        header_page=header_page, raw_header=header[:600], raw_row=raw[:900]).model_dump(mode="json")


def _unit(line):
    match = re.search(r"单位\s*[:：]\s*(百万元|万元|亿元|元)(?:\s|$)", line)
    return match[1] if match and ("人民币" in line or "币种" not in line) else None


def financial_rows(pages, period):
    rows = []
    # Only explicit key-accounting sections or consolidated statements. Parent
    # statements and arbitrary occurrences of the same label are excluded.
    section = None
    unit = header = None
    header_page = 0
    for page in pages:
        for line in page["text"].splitlines():
            tight = re.sub(r"\s", "", line)
            if re.search(r"合并利润表$", tight):
                section, header, unit, header_page = "consolidated", None, None, page["page"]
            elif re.search(r"合并现金流量表$", tight):
                section, header, unit, header_page = "consolidated_cash", None, None, page["page"]
            elif re.search(r"(?:母公司利润表|母公司现金流量表|合并资产负债表|母公司资产负债表)$", tight):
                section, header, unit = None, None, None
            elif re.fullmatch(r"(?:[（(]一[）)]|\d+[.、])?(?:公司)?主要(?:会计|财务)数据", tight):
                section, header, unit, header_page = "key", None, None, page["page"]
            elif section == "key" and any(word in tight for word in ("主要财务指标", "非经常性损益", "主营业务分析")):
                section, header = None, None
            if section is None or page["page"]-header_page > 1:
                continue
            found_unit = _unit(line)
            if found_unit:
                unit = found_unit
            if section.startswith("consolidated") and str(int(period[:4])-1)+"年" in tight and period[:4]+"年" in tight:
                header, header_page = line, page["page"]
            if section == "key" and "本报告期" in tight and "上年同期" in tight:
                header, header_page = line, page["page"]
            if not header or not unit:
                continue
            split = re.split(r"\s{2,}", line.strip(), maxsplit=1)
            if len(split) != 2:
                continue
            label, cells = split
            compact = re.sub(r"\s", "", label)
            field = None
            if compact == "营业收入" or compact == "其中：营业收入":
                field = "revenue"
            elif compact.startswith("归属于上市公司股东的净利润") or compact.startswith("1.归属于母公司股东的净利润"):
                field = "parent_net_income"
            elif compact == "经营活动产生的现金流量净额":
                field = "cfo"
            elif section == "consolidated" and re.match(r"[一二三四五六七八九十]+、净利润[（(]", compact):
                field = "consolidated_net_income"
            if field is None:
                continue
            numbers = [m[0] for m in NUMBER.finditer(cells) if not m[0].endswith("%")]
            values = numbers[-2:] if section.startswith("consolidated") else numbers[:2]
            if len(values) != 2:
                continue
            rows.append(_row("financial", field, label, values, page["page"], header_page,
                             header, line, period, unit))
    return rows


def cash_bridge_rows(pages, period):
    rows, gaps = [], []
    active = False
    header = unit = None
    header_page = 0
    centers = None
    complete = False
    for page in pages:
        if active and page["page"]-header_page > 1:
            gaps.append("cash_bridge_nonadjacent_header")
            break
        for line in page["text"].splitlines():
            tight = re.sub(r"\s", "", line)
            if "现金流量表补充资料" in tight:
                header, unit = None, None
                header_page = page["page"]
            candidate_unit = _unit(line)
            if candidate_unit:
                unit = candidate_unit
            match = re.search(r"(本期金额|本期发生额)\s+(上期金额|上期发生额)", line)
            if match:
                header, header_page = line, page["page"]
                centers = tuple((match.start(i)+match.end(i))/2 for i in (1, 2))
            if "将净利润调节为经营活动现金流量" in tight:
                active = bool(header and unit and centers)
                if not active:
                    gaps.append("cash_bridge_explicit_header_missing")
                continue
            if not active:
                continue
            if re.match(r"2[．.]", tight):
                gaps.append("cash_bridge_end_missing")
                active = False
                break
            field = next((value for prefix, value in BRIDGE_FIELDS.items() if tight.startswith(prefix)), None)
            if field is None:
                if re.search(r"\s{2,}-?\d[\d,]*\s{2,}-?\d", line) and not re.fullmatch(r"\s*\d+/\d+\s*", line):
                    gaps.append("cash_bridge_component_unrecognized")
                continue
            numeric = list(NUMBER.finditer(line))
            # Ignore digits embedded in labels, retain explicitly blank cells.
            numeric = [m for m in numeric if (m.start()+m.end())/2 >= centers[0]-9 and not m[0].endswith("%")]
            split = sum(centers)/2
            columns = [[m[0] for m in numeric if ((m.start()+m.end())/2 < split) == (i == 0)] for i in range(2)]
            if any(len(c) > 1 for c in columns):
                gaps.append("cash_bridge_ambiguous_columns")
                continue
            values = [c[0] if c else None for c in columns]
            label = line[:numeric[0].start()].strip() if numeric else line.strip()
            rows.append(_row("cash_bridge", field, label, values, page["page"], header_page,
                             header, line, period, unit))
            if field == "cfo":
                complete, active = True, False
                break
        if complete:
            break
    if not complete or not rows or rows[0]["field"] != "net_income":
        return [], sorted({*gaps, "cash_bridge_complete_table_not_admitted"})
    if len({r["field"] for r in rows}) != len(rows):
        gaps.append("cash_bridge_duplicate_components")
    return (rows if not gaps else []), sorted(set(gaps))


def operating_notice_rows(pages, period):
    rows = []
    for page in pages:
        text = page["text"]
        compact = re.sub(r"\s", "", text)
        if not (period[:4]+"年" in compact and str(int(period[:4])-1)+"年" in compact
                and "第二季度" in compact and "1-6月累计" in compact and "计量单位" in compact):
            continue
        header = "\n".join(line for line in text.splitlines() if any(word in line for word in ("计量单位", "第二季度", "同比增减")))
        started = False
        last_rows = []
        for line in text.splitlines():
            if "计量单位" in line:
                started = True
                continue
            if not started:
                continue
            if "注：" in line or "风险提示" in line:
                break
            match = re.search(r"(百万立方米|万立方米|立方米|万吨|吨|万千瓦时|千瓦时)", line)
            if not match:
                tight = re.sub(r"\s", "", line)
                if re.fullmatch(r"[\u4e00-\u9fff：]{1,20}", tight) and not any(word in tight for word in ("董事", "运营数据", "产品")) and last_rows:
                    for row in last_rows:
                        row["label"] += tight
                        row["raw_row"] += "\n"+line
                continue
            values = [m[0] for m in NUMBER.finditer(line[match.end():])]
            if len(values) != 6 or any(v.endswith("%") for v in values[:4]) or not all(v.endswith("%") for v in values[4:]):
                continue
            label = re.sub(r"\s", "", line[:match.start()])
            if not label:
                continue
            last_rows = []
            for frequency, indices in (("Q2", (0, 2)), ("H1", (1, 3))):
                row = _row("operating", "operating_measure", label, [values[i] for i in indices],
                    page["page"], page["page"], header, line, period, match[1], frequency)
                rows.append(row)
                last_rows.append(row)
    return rows


def parse_pages(pages, row, *, ts_code, cutoff, issuer_name, pdf_sha256):
    header = re.sub(r"\s", "", "".join(p["text"] for p in pages[:10]))
    codes = re.findall(r"(?:证券代码|股票代码|公司代码)[:：]?(\d{6})", header)
    if not codes or set(codes) != {ts_code[:6]}:
        raise NativeSourceUnavailable("document_security_unqualified")
    if issuer_name and re.sub(r"\s", "", issuer_name) not in header:
        raise NativeSourceUnavailable("document_issuer_unqualified")
    info = title_info(row.get("Title", ""))
    period = info["period"] if info else None
    if period:
        marker = period[:4]+"年"+("半年度" if period.endswith("06-30") else "年度")
        if marker not in header or period > row["Published"] or period > cutoff:
            raise NativeSourceUnavailable("document_report_period_unqualified")
        if info["kind"] == "operating_notice" and not any(s in header for s in ("主要运营数据", "主要经营数据")):
            raise NativeSourceUnavailable("document_report_period_unqualified")
    if not any(len(p["text"].strip()) >= 40 for p in pages):
        raise NativeSourceUnavailable("document_text_unavailable")
    numeric, gaps = [], []
    if period:
        if info["kind"] == "operating_notice":
            numeric = operating_notice_rows(pages, period)
        else:
            numeric = financial_rows(pages, period)
            bridge, gaps = cash_bridge_rows(pages, period) if info["kind"] == "report" else ([], [])
            numeric.extend(bridge)
    # Relevant numeric pages have priority; excerpts are bounded separately
    # from the full (bounded) text scan. Never claim complete document coverage.
    numbers = {r["page"] for r in numeric} | {r["header_page"] for r in numeric}
    chosen = [p for p in pages if p["page"] in numbers]
    candidates = [p for p in pages if "目录" not in p["text"] and any(k in re.sub(r"\s", "", p["text"])
        for k in ("主要业务", "主要经营", "公司面临的风险", "主营业务", "现金流量表", "偿债"))]
    for p in (*candidates, *pages[:2]):
        if p not in chosen and len(chosen) < 12:
            chosen.append(p)
    excerpts = [{"page": p["page"], "text": p["text"][:4000], "truncated": len(p["text"]) > 4000}
                for p in sorted(chosen[:12], key=lambda p: p["page"]) if p["text"].strip()]
    if period and not numeric:
        gaps.append("official_numeric_layout_not_admitted")
    return {"document_id": row["Announcement ID"], "title": row["Title"], "published": row["Published"],
        "ts_code": ts_code, "url": pdf_url(row), "pdf_sha256": pdf_sha256, "page_count": len(pages),
        "parser_version": PARSER_VERSION, "report_period": period, "document_kind": info["kind"] if info else "event",
        "body_coverage": "partial", "excerpts": excerpts, "numeric_rows": numeric, "gaps": sorted(set(gaps))}


def parse_document(data, row, *, ts_code, cutoff, issuer_name=None, ensure_active=lambda: None):
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
        raise NativeSourceUnavailable("document_byte_limit_or_not_pdf")
    if not row.get("Published") or row["Published"] > cutoff:
        raise NativeSourceUnavailable("document_publication_unqualified")
    pdf_url(row)
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        raise NativeSourceUnavailable("document_parser_not_installed") from None
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise NativeSourceUnavailable("document_encrypted_or_page_limit")
        pages = []
        for index, page in enumerate(reader.pages):
            ensure_active()
            pages.append({"page": index+1, "text": page.extract_text(extraction_mode="layout") or ""})
    except (PyPdfError, ValueError, OSError, KeyError, TypeError) as exc:
        raise NativeSourceUnavailable("document_parse_failed") from exc
    return parse_pages(pages, row, ts_code=ts_code, cutoff=cutoff, issuer_name=issuer_name,
                       pdf_sha256=hashlib.sha256(data).hexdigest())
