"""Deterministic admission of official PDF excerpts and operating tables.

No I/O, OCR or model extraction. Unsupported layouts retain readable excerpts,
but cannot produce guessed numeric rows.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from tradingagents.dataflows.native_qualification import NativeSourceUnavailable

PARSER_VERSION = "official-pdf-v1"
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 500
BODY_SOURCE = "cninfo.document_excerpt"
OPERATING_SOURCE = "cninfo.operating_detail"
NUMBER = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?"
ROW = re.compile(rf"^(.*?)\s+({NUMBER}(?:\s+{NUMBER}){{4,5}})\s*$")
GROUPS = {"分行业": "industry", "分产品": "product", "分地区": "region", "分部": "segment"}


def pdf_url(row):
    path = row.get("PDF URL", "")
    if not isinstance(path, str):
        raise NativeSourceUnavailable("document_url_invalid")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.netloc != "static.cninfo.com.cn":
            raise NativeSourceUnavailable("document_url_invalid")
        path = parsed.path.lstrip("/")
    if parsed.query or parsed.fragment or not re.fullmatch(r"finalpage/\d{4}-\d{2}-\d{2}/\d+\.pdf", path, re.I):
        raise NativeSourceUnavailable("document_url_invalid")
    if path.rsplit("/", 1)[-1].split(".")[0] != row.get("Announcement ID"):
        raise NativeSourceUnavailable("document_attachment_identity_mismatch")
    return "https://static.cninfo.com.cn/" + path


def report_period(title):
    match = re.fullmatch(r"(20\d{2})年(?:半年度|年度)报告(?:[（(]修订版[）)])?", re.sub(r"\s", "", title))
    if not match:
        return None
    # Revisions have separate identifiers; without original/revision lineage
    # their applicability is deliberately not inferred.
    if "修订" in title:
        return None
    return match[1] + ("-06-30" if "半年度" in title else "-12-31")


def select_documents(rows, cutoff):
    ordered = sorted((row for row in rows if row.get("Published", "") <= cutoff),
                     key=lambda row: (row["Published"], row["Announcement ID"]), reverse=True)
    reports = [row for row in ordered if report_period(row.get("Title", ""))]
    selected = reports[:1]
    for row in ordered:
        title = row.get("Title", "")
        if (row not in selected and any(word in title for word in ("合同", "投资", "项目", "回购", "减持", "增持", "上市", "关联交易"))
                and not any(word in title for word in ("法律意见", "评估报告", "审核意见", "H股", "会议决议"))
                and (date.fromisoformat(cutoff) - date.fromisoformat(row["Published"])).days <= 90):
            selected.append(row)
            if len(selected) >= (4 if reports else 3):
                break
    return selected


def _decimal(value):
    try:
        result = Decimal(value.replace(",", "").rstrip("%"))
    except InvalidOperation:
        raise NativeSourceUnavailable("operating_table_invalid_number") from None
    if not result.is_finite():
        raise NativeSourceUnavailable("operating_table_invalid_number")
    return result


def operating_rows(pages, period):
    """Recognize two explicit statutory-report table headers, never all digits.

    Layout extraction preserves column positions. A row with a different column
    count invalidates that table; narrative numbers are never used as cells.
    """
    rows, composition, gaps = [], [], []
    kind = group = unit = None
    unit_label, header_text = None, ""
    pending_name = ""
    totals = {}
    invalid = set()
    for page in pages:
        text = page["text"]
        compact = re.sub(r"\s", "", text)
        if "营业收入构成" in compact:
            kind, group, unit = "composition", None, None
            header_text, unit_label = "", None
        if "占公司营业收入或营业利润10%以上" in compact or "主营业务分行业" in compact:
            # A page can contain both tables. Switch below at the actual header.
            pass
        for raw in text.splitlines():
            line = raw.strip()
            tight = re.sub(r"\s", "", line)
            if tight.startswith("四、") or tight.startswith("公司主营业务数据统计口径"):
                kind = group = None
            if tight.startswith("单位：") or tight.startswith("单位:"):
                label = tight.split("：")[-1].split(":")[-1]
                unit = {"元": Decimal(1), "万元": Decimal(10000)}.get(label)
                unit_label = label
            if kind == "composition" and not group and any(key in tight for key in ("本报告期", "上年同期", "占营业收入比重")):
                header_text = (header_text+"\n"+line).strip()[:500]
            if "营业成本" in tight and "毛利率" in tight and "营业收入" in tight:
                kind, group = "profitability", None
                header_text = line
                pending_name = ""
            if tight in GROUPS:
                group, pending_name = GROUPS[tight], ""
                continue
            if not kind:
                continue
            match = ROW.fullmatch(line)
            if not match:
                if group and unit is not None and len(re.findall(r"\d[\d,]*\.\d+", line)) >= 2:
                    invalid.add(kind)
                    continue
                # Some line-wrapped labels end after the numeric line.
                if rows and tight == "产品" and rows[-1]["name"].endswith("汽车"):
                    rows[-1]["name"] += "产品"
                elif (group and re.fullmatch(r"[\u4e00-\u9fffA-Za-z（）()、\-]{1,30}", tight)
                      and not any(word in tight for word in ("营业", "毛利", "同期", "单位", "增减", "深圳市", "年度报告"))):
                    pending_name = tight
                continue
            name, values_text = match.groups()
            name = re.sub(r"\s", "", name) or pending_name
            pending_name = ""
            values = values_text.split()
            if unit is None or len(values) != (5 if kind == "composition" else 6):
                invalid.add(kind)
                continue
            if kind == "composition" and name == "营业收入合计":
                totals["current"] = _decimal(values[0]) * unit
                totals["previous"] = _decimal(values[2]) * unit
                continue
            if not group or not name:
                continue
            if kind == "composition":
                if not all(values[i].endswith("%") for i in (1, 3, 4)):
                    invalid.add(kind)
                    continue
                if any(values[i].endswith("%") for i in (0, 2)):
                    invalid.add(kind)
                    continue
                composition.append({"classification": group, "name": name,
                    "revenue": str(_decimal(values[0])*unit),
                    "prior_revenue": str(_decimal(values[2])*unit),
                    "revenue_share_percent": str(_decimal(values[1])),
                    "prior_share_percent": str(_decimal(values[3])),
                    "revenue_change_percent": str(_decimal(values[4])),
                    "report_period": period, "unit": "CNY", "page": page["page"],
                    "raw_unit": unit_label, "raw_header": header_text,
                    "raw_row": line, "table": kind})
            else:
                if any(v.endswith("%") for v in values[:2]) or not all(v.endswith("%") for v in values[2:]):
                    invalid.add(kind)
                    continue
                revenue, cost, margin = map(_decimal, values[:3])
                precision = len(values[2].rstrip("%").partition(".")[2])
                tolerance = Decimal(5).scaleb(-precision-1) + Decimal("0.000001")
                if revenue <= 0 or cost < 0 or abs((revenue-cost)/revenue*100-margin) > tolerance:
                    invalid.add(kind)
                    continue
                rows.append({"classification": group, "name": name,
                    "revenue": str(revenue*unit), "cost": str(cost*unit),
                    "gross_margin_percent": str(margin),
                    "revenue_change_percent": str(_decimal(values[3])),
                    "cost_change_percent": str(_decimal(values[4])),
                    # Preserve the reported glyph; do not reinterpret % as pp.
                    "margin_change_reported": values[5],
                    "report_period": period, "unit": "CNY", "page": page["page"],
                    "raw_unit": unit_label, "raw_header": header_text,
                    "raw_row": line, "table": kind})
    for category in {row["classification"] for row in composition}:
        group_rows = [row for row in composition if row["classification"] == category]
        if len({row["name"] for row in group_rows}) != len(group_rows):
            invalid.add("composition")
        for field, total in (("revenue", totals.get("current")), ("prior_revenue", totals.get("previous"))):
            if total is not None and abs(sum((_decimal(row[field]) for row in group_rows), Decimal(0))-total) > Decimal("0.02"):
                # The table may intentionally omit minor segments. No guessed
                # residual row or claim of complete classification coverage.
                gaps.append("operating_classification_total_not_covered:"+category)
    for table in invalid:
        gaps.append("operating_table_unqualified:"+table)
    output = [row for row in (*composition, *rows) if row["table"] not in invalid]
    if not output:
        gaps.append("operating_table_layout_not_admitted")
    return output, sorted(set(gaps))


def parse_document(data, row, *, ts_code, cutoff, issuer_name=None, ensure_active=lambda: None):
    if len(data) > MAX_PDF_BYTES:
        raise NativeSourceUnavailable("document_byte_limit")
    if not data.startswith(b"%PDF-"):
        raise NativeSourceUnavailable("document_not_pdf")
    if not row.get("Published") or row["Published"] > cutoff:
        raise NativeSourceUnavailable("document_publication_unqualified")
    url = pdf_url(row)
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        raise NativeSourceUnavailable("document_parser_not_installed") from None
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise NativeSourceUnavailable("document_encrypted")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise NativeSourceUnavailable("document_page_limit")
        pages = []
        for index, page in enumerate(reader.pages):
            ensure_active()
            pages.append({"page": index+1, "text": page.extract_text(extraction_mode="layout") or ""})
    except NativeSourceUnavailable:
        raise
    except TimeoutError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError, TypeError) as exc:
        raise NativeSourceUnavailable("document_parse_failed") from exc
    header = re.sub(r"\s", "", "".join(p["text"] for p in pages[:10]))
    codes = re.findall(r"(?:证券代码|股票代码)[:：]?(\d{6})", header)
    if not codes or set(codes) != {ts_code[:6]}:
        raise NativeSourceUnavailable("document_security_unqualified")
    if issuer_name and re.sub(r"\s", "", issuer_name) not in header:
        raise NativeSourceUnavailable("document_issuer_unqualified")
    if not any(len(p["text"].strip()) >= 40 for p in pages):
        raise NativeSourceUnavailable("document_text_unavailable")
    period = report_period(row.get("Title", ""))
    if period and (period > row["Published"] or period > cutoff or
                   re.sub(r"\s", "", row["Title"]) not in header):
        raise NativeSourceUnavailable("document_report_period_unqualified")
    digest = hashlib.sha256(data).hexdigest()
    selected = pages[:2]
    if period:
        tables = [p for p in pages if "营业收入构成" in re.sub(r"\s", "", p["text"])
            or re.search(r"(?m)^\s*分(?:行业|产品|地区)\s*$", p["text"])]
        business = [p for p in pages if any(key in re.sub(r"\s", "", p["text"])
            for key in ("主要业务", "主要产品", "业务实现营业收入")) and p not in tables]
        business.sort(key=lambda p: ("业务实现营业收入" not in re.sub(r"\s", "", p["text"]), p["page"]))
        risk = [p for p in pages if "公司面临的风险和应对措施" in re.sub(r"\s", "", p["text"]) and "目录" not in p["text"]]
        selected = sorted({p["page"]: p for p in (*tables[:3], *business[:2], *risk[:1])}.values(), key=lambda p: p["page"])
    if not period:
        for p in pages[2:]:
            if "风险" in p["text"] and len(selected) < 4:
                selected.append(p)
    excerpts = [{"page": p["page"], "text": p["text"][:4000],
                 "truncated": len(p["text"]) > 4000} for p in selected if p["text"].strip()]
    rows, gaps = operating_rows(pages, period) if period else ([], [])
    return {"document_id": row["Announcement ID"], "title": row["Title"],
        "published": row["Published"], "ts_code": ts_code, "url": url,
        "pdf_sha256": digest, "page_count": len(pages), "parser_version": PARSER_VERSION,
        "report_period": period, "excerpts": excerpts, "operating_rows": rows,
        "gaps": gaps, "body_coverage": "selected_excerpts_only"}
