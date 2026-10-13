"""Explicit Sina profile fields; no business interpretation or live I/O."""

from tradingagents.dataflows.native_qualification import (
    NativeSourceUnavailable,
    _ProfileParser,
    sina_identity,
)

PROFILE_SOURCE = "sina.company_overview"
PROFILE_CAPABILITY = "company_profile"
PROFILE_FIELDS = {"公司简介": "introduction", "主营业务": "main_business",
                  "经营范围": "business_scope", "所属行业": "industry"}


def qualify_company_profile(text, *, ts_code, cutoff):
    identity = sina_identity(text, ts_code=ts_code, cutoff=cutoff)
    parser = _ProfileParser()
    parser.feed(text)
    fields = {}
    for index, label in enumerate(parser.cells[:-1]):
        key = PROFILE_FIELDS.get(label.rstrip("：:").strip())
        if key is None:
            continue
        value = " ".join(parser.cells[index + 1].split())
        if value and value not in {"--", "-", "暂无", "暂无数据"}:
            if key in fields and fields[key] != value:
                raise NativeSourceUnavailable("profile_duplicate_field")
            fields[key] = value[:700]
    if not fields:
        raise NativeSourceUnavailable("profile_description_unavailable")
    return {**identity, "fields": fields, "capture_scope": "current_public_profile"}
