"""financial-detail-fields-v1: baseline records stay frozen, one detail record per table."""

import json
from types import SimpleNamespace

import pytest

from tradingagents.agents.schemas._verification_plan import (
    DETAIL_FIELDS,
    DETAIL_LABELS,
    FINANCIAL_FIELDS,
    SINA_FIELDS,
    VERIFIABLE_FIELDS,
    FinancialConditionV1,
    FinancialOperandV1,
)
from tradingagents.dataflows.native_qualification import sina_statement
from tradingagents.dataflows.native_sources import NativeSources
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity
from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
from tradingagents.research.native_record import _financial_detail_content, build_native_record
from tradingagents.research.native_versions import FINANCIAL_DETAIL_POLICY
from tradingagents.research.verification_tools import _financial_operand

PROFILE = '<title>沃尔核材(002130)公司资料_新浪财经_新浪网</title><table id="comInfo1"><tr><td>上市市场：</td><td>深圳证券交易所</td><td>上市日期：</td><td><a>2007-04-20</a></td></tr></table>'
CODES = {
    "income": ("BIZINCO", "NETPROFIT", "PARENETP", "BIZCOST", "SALESEXPE", "MANAEXPE", "DEVEEXPE", "FINEXPE"),
    "balancesheet": ("TOTASSET", "TOTLIAB", "ACCORECE", "NOTESACCORECE", "INVE", "ACCOPAYA", "NOTESACCOPAYA"),
    "cashflow": ("MANANETR", "ACQUASSETCASH"),
}


def payload(table, periods=2):
    reports = {}
    for offset in range(periods):
        period = f"{2026 - offset}0630"
        reports[period] = {"rType": "合并期末", "rCurrency": "CNY", "publish_date": f"{2026 - offset}0825",
            "data": [{"item_field": code, "item_value": f"{1000000000 + i}.5"} for i, code in enumerate(CODES[table])]}
    return {"result": {"status": {"code": 0}, "data": {"report_list": reports}}}


def collector(monkeypatch, *, detail):
    request = SimpleNamespace(ticker="002130.SZ", analysis_date="2026-10-03",
        catalyst_policy=catalyst_evidence_policy_v1(), effective_config={
            "evidence_source_vendors": {"identity": ["sina"], "events": [], "calendar": [], "price": []}})
    if detail:
        request.financial_detail_policy = FINANCIAL_DETAIL_POLICY
    calls = []
    sources = NativeSources(request, "detail-run", None, lambda key, operation: (calls.append(key), operation())[1])

    def get(url, **kwargs):
        if "CorpInfo" in url:
            return PROFILE
        table = {"lrb": "income", "fzb": "balancesheet", "llb": "cashflow"}[kwargs["params"]["source"]]
        return payload(table)

    monkeypatch.setattr(sources, "_get", get)
    return sources, calls


def test_baseline_fields_are_unchanged_and_detail_is_a_separate_registry():
    assert {"income": frozenset({"revenue", "n_income", "n_income_attr_p"}),
        "balancesheet": frozenset({"total_assets", "total_liab"}), "cashflow": frozenset({"n_cashflow_act"})} == FINANCIAL_FIELDS
    assert len(DETAIL_FIELDS["income"] | DETAIL_FIELDS["balancesheet"] | DETAIL_FIELDS["cashflow"]) == 11
    assert not set(DETAIL_LABELS) & {f for fields in FINANCIAL_FIELDS.values() for f in fields}
    for table in FINANCIAL_FIELDS:
        assert VERIFIABLE_FIELDS[table] == FINANCIAL_FIELDS[table] | DETAIL_FIELDS[table]
        assert set(SINA_FIELDS[table].values()) >= VERIFIABLE_FIELDS[table]


def test_sina_qualification_reads_detail_codes_without_dropping_baseline_fields():
    rows = sina_statement(payload("income"), table="income", ts_code="002130.SZ", cutoff="2026-10-03")
    assert rows
    assert {"revenue", "n_income", "n_income_attr_p", "oper_cost", "sell_exp", "admin_exp", "rd_exp", "fin_exp"} <= set(rows[0])


def test_detail_record_keeps_the_baseline_evidence_identical(monkeypatch):
    base, _ = collector(monkeypatch, detail=False)
    detailed, _ = collector(monkeypatch, detail=True)
    plain = build_native_record(*base.collect(), mode="company_research")
    rich = build_native_record(*detailed.collect(), mode="company_research")
    baseline_plain = next(s for s in plain.evidence if s.source_name == "sina.financial_statements")
    baseline_rich = next(s for s in rich.evidence if s.source_name == "sina.financial_statements")
    assert baseline_plain.content == baseline_rich.content
    assert not any(s.source_name == "sina.financial_detail" for s in plain.evidence)
    details = [s for s in rich.evidence if s.source_name == "sina.financial_detail"]
    assert len(details) == 3
    # Each detail record holds exactly one statement table.
    for source in details:
        assert len(json.loads(source.content.text)) == 1


def test_detail_fields_are_verifiable_and_visible_as_facts(monkeypatch):
    sources, _ = collector(monkeypatch, detail=True)
    record = build_native_record(*sources.collect(), mode="company_research")
    detail = next(s for s in record.evidence if s.source_name == "sina.financial_detail"
                  and "income" in s.content.text)
    value, _ = _financial_operand(record, FinancialOperandV1(evidence_id=detail.evidence_id,
        table="income", field="sell_exp", report_period="2026-06-30"))
    assert value > 0
    assert any("销售费用" in fact.statement for fact in record.claims)


def test_detail_content_stays_under_the_source_text_limit():
    rows = []
    for offset in range(8):
        rows.append({"ts_code": "002130.SZ", "report_type": "1", "end_date": f"{2026 - offset}1231",
            "ann_date": f"{2026 - offset}0501", "f_ann_date": f"{2026 - offset}0501",
            **{field: str(-98765432101.23) for field in DETAIL_FIELDS["balancesheet"]}})
    content = _financial_detail_content({"balancesheet": rows}, "002130.SZ")
    assert content is not None and content.truncated is False
    assert len(content.text) < 4000


def test_condition_schema_accepts_detail_fields_and_rejects_unknown_ones():
    condition = FinancialConditionV1.model_validate({"kind": "financial", "operation": "value",
        "current": {"evidence_id": "e.x", "table": "income", "field": "sell_exp", "report_period": "2026-06-30"},
        "predicate": {"operator": "gt", "threshold": "0", "unit": "CNY"}})
    assert condition.current.field == "sell_exp"
    with pytest.raises(ValueError):
        FinancialConditionV1.model_validate({"kind": "financial", "operation": "value",
            "current": {"evidence_id": "e.x", "table": "income", "field": "unknown", "report_period": "2026-06-30"},
            "predicate": {"operator": "gt", "threshold": "0", "unit": "CNY"}})


def test_identity_records_the_detail_policy_only_for_the_unified_workflow():
    request = AnalysisRequest(ticker="600418.SS", analysis_date="2026-10-19", effective_config={},
        research_profile="evidence_v1")
    assert native_identity(request).get("financial_detail_policy") == FINANCIAL_DETAIL_POLICY
    assert "financial_detail_policy" not in native_identity(request, financial_detail_policy=False)
