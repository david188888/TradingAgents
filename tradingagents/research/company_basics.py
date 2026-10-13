"""Select report foundation facts; missing detail never removes saved basics."""

import json
import re
from decimal import Decimal

from tradingagents.agents.schemas._company_basics import CompanyBasicFieldV1, CompanyBasicsV1

PROFILE_LABELS = {"introduction": "公司简介", "main_business": "主营业务",
                  "business_scope": "经营范围", "industry": "所属行业"}
FINANCIAL_LABELS = {"revenue": "营业收入", "n_income": "净利润",
                    "n_income_attr_p": "归母净利润", "total_assets": "总资产",
                    "total_liab": "总负债", "n_cashflow_act": "经营现金流净额"}


def basic_claim_text(statement):
    match = re.fullmatch(r"合并财务字段：报告期 (\d{4}-\d{2}-\d{2})，(?:income|balancesheet|cashflow)\.(\w+) = (-?\d+(?:\.\d+)?) CNY。", statement)
    if match and match[2] in FINANCIAL_LABELS:
        value = Decimal(match[3]) / Decimal("100000000")
        return f"{match[1]} 报告期 · {FINANCIAL_LABELS[match[2]]} {value:.2f} 亿元（合并口径）"
    return statement.replace("PE-TTM None 倍", "PE-TTM 未取得").replace("PB None 倍", "PB 未取得")


def disclosed_profile_fields(text):
    """Recognize explicit saved business headings and an industry statement."""
    fields = {}
    direct = re.search(r"(?m)^\s*(?:主营业务|公司主要业务|公司从事的主要业务)[：:]\s*([^\n]{20,700})$", text)
    if direct:
        fields["main_business"] = direct[1].strip()
    else:
        lines = text.splitlines()
        for index, line in enumerate(lines):
            heading = re.sub(r"\s", "", line)
            if not re.fullmatch(r"(?:[（(][一二三四五六七八九十]+[）)])?公司主营业务情况", heading):
                continue
            paragraph = []
            for following in lines[index + 1:index + 12]:
                value = following.strip()
                if not value and paragraph or value.startswith(("报告期内", "二、", "三、", "（三）")):
                    break
                if value:
                    paragraph.append(value)
            excerpt = "\n".join(paragraph)
            if 20 <= len(excerpt) <= 700:
                fields["main_business"] = excerpt
            break
    industry = re.search(r"本公司属([^。\n]{2,40}行业)[。]", text)
    if industry:
        fields["industry"] = industry[1]
    return fields


def assemble_company_basics(record, *, company_name=None):
    intro, quantitative, financial = [], [], {}
    sources = {source.evidence_id: source for source in record.evidence}
    for claim in record.claims:
        if claim.kind != "fact":
            continue
        locators = [item.removeprefix("source_field:") for item in claim.limitations if item.startswith("source_field:")]
        for locator in locators:
            if locator.startswith("profile.") and locator[8:] in PROFILE_LABELS:
                intro.append(CompanyBasicFieldV1(label=PROFILE_LABELS[locator[8:]], claim_id=claim.claim_id))
            elif match := re.fullmatch(r"(?:income|balancesheet|cashflow)\[end_date=(\d{4}-\d{2}-\d{2})\]\.(\w+)", locator):
                period, field = match.groups()
                if field in FINANCIAL_LABELS and (field not in financial or period > financial[field].report_period.isoformat()):
                    financial[field] = CompanyBasicFieldV1(label=FINANCIAL_LABELS[field], claim_id=claim.claim_id, report_period=period)
            elif locator == "snapshot" or locator.startswith(("computed_statistics:", "bars[")):
                quantitative.append(CompanyBasicFieldV1(label="行情与估值快照" if locator == "snapshot" else "价格与历史风险统计", claim_id=claim.claim_id))
            elif locator.startswith("official.financial."):
                field = {"revenue": "revenue", "parent_net_income": "n_income_attr_p",
                         "consolidated_net_income": "n_income", "cfo": "n_cashflow_act"}.get(locator.split(".")[2])
                source = sources[claim.evidence_ids[0]]
                row = json.loads(source.content.text)["row"]
                period = row["period"]
                if (field and row.get("current") is not None and row["frequency"] != "Q2"
                        and (field not in financial or period > financial[field].report_period.isoformat())):
                    financial[field] = CompanyBasicFieldV1(label=FINANCIAL_LABELS[field], claim_id=claim.claim_id, report_period=period)
    gaps = []
    labels = {field.label for field in intro}
    for label in ("主营业务", "所属行业"):
        if label not in labels:
            gaps.append(label + "的明确公开字段未取得；该缺口不影响已保存财务与行情。")
    if not labels & {"公司简介", "主营业务"}:
        gaps.insert(0, "公司公开介绍的明确字段未取得；该缺口不影响已保存财务与行情。")
    for field, label in FINANCIAL_LABELS.items():
        if field not in financial:
            gaps.append(label + "的合格字段未取得。")
    if not quantitative:
        gaps.append("合格行情或历史统计未取得。")
    intro.sort(key=lambda item: tuple(PROFILE_LABELS.values()).index(item.label))
    return CompanyBasicsV1(company_name=company_name, introduction=tuple(intro[:4]),
        fundamentals=tuple(financial.values()), quantitative=tuple(quantitative[:12]), gaps=tuple(gaps))


def foundation_context(record):
    if record.company_basics is None:
        return None
    fields = (*record.company_basics.introduction, *record.company_basics.fundamentals, *record.company_basics.quantitative)
    ids = {field.claim_id for field in fields}
    facts = [claim.model_dump(mode="json") for claim in record.claims if claim.claim_id in ids]
    evidence_ids = {eid for fact in facts for eid in fact["evidence_ids"]}
    return {"basics": record.company_basics.model_dump(mode="json"), "facts": facts,
            "sources": [source.model_dump(mode="json") for source in record.evidence if source.evidence_id in evidence_ids],
            "instruction": "公共基础资料只用于理解公司与全局覆盖；专项引用仍只能使用本专项facts。公开介绍不是业绩兑现证明，不得将局部缺口写成全局无数据。"}
