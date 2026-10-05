"""600803 fixtures verify bounded questions, not live model research accuracy."""

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas._evidence_checks import OfficialNumericRowV1
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.dataflows.disclosure_documents_v2 import (
    NUMERIC_SOURCE,
    cash_bridge_rows,
    parse_pages,
    select_documents,
    title_info,
)
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.supplemental_valuation import (
    deduplicate_forecasts,
    eastmoney_forecasts,
    peer_candidates,
    ths_forecasts,
)
from tradingagents.research.evidence_freeze import (
    CapabilityStatus,
    FrozenCapability,
    FrozenEvidenceDraft,
)
from tradingagents.research.minimum_evidence import (
    cfo_decline,
    challenge_assessments,
    compute_checks,
)
from tradingagents.research.native_record import build_native_record

EXCERPTS = Path(__file__).parent / "fixtures/600803-official-table-excerpts-v2.json"


def documents():
    fixtures = json.loads(EXCERPTS.read_text())["documents"]
    result = []
    for fixture in fixtures:
        # Blank padding preserves the real page locators. These are selected
        # table fixtures, not a reproduced or authenticated full PDF.
        saved = {p["page"]: p for p in fixture["pages"]}
        pages = [saved.get(i, {"page": i, "text": ""}) for i in range(1, fixture["page_count"]+1)]
        row = {"Title": fixture["title"], "Published": fixture["published"], "Announcement ID": fixture["document_id"],
               "PDF URL": f"finalpage/{fixture['published']}/{fixture['document_id']}.PDF"}
        result.append(parse_pages(pages, row, ts_code="600803.SH", cutoff="2026-10-05", issuer_name="新奥股份", pdf_sha256="a"*64))
    return result


def forecast(institution="甲证券", year=2026, published="2026-09-04", eps="1.78"):
    return {"ts_code": "600803.SH", "institution": institution, "analyst": "研究员", "report_id": institution+published,
            "published": published, "forecast_year": year, "eps": eps, "unit": "CNY/share", "year_basis": "explicit_header"}


def fixture(*, forecasts=True, peers=True, numeric_mutator=None):
    payloads = [("security_identity", "tushare.stock_basic", {"ts_code": "600803.SH", "list_date": "19940103"}, None, None),
        ("valuation", "tencent.valuation_snapshot", {"ts_code": "600803.SH", "name": "新奥股份", "as_of": "2026-09-30",
            "quote_timestamp": "2026-09-30T16:14:55+08:00", "price": 19.2, "pe_ttm": 13.63, "pb": 2.53,
            "total_market_cap_yi": 594.28, "currency": "CNY"}, "2026-09-30", None)]
    docs = documents()
    if numeric_mutator:
        numeric_mutator(docs)
    for doc in docs:
        metadata = {k: v for k, v in doc.items() if k not in {"numeric_rows", "excerpts", "gaps"}}
        for row in doc["numeric_rows"]:
            payloads.append(("operating_detail", NUMERIC_SOURCE, {**metadata, "row": row}, doc["published"], doc["url"]))
    if forecasts:
        for institution in ("甲证券", "乙证券", "丙证券"):
            payloads.append(("dated_forecasts", "ths.dated_forecast", forecast(institution), "2026-09-04", None))
    if peers:
        candidates = [{"ts_code": code, "name": name, "financial_period": "2025-12-31"}
                      for code, name in (("601139.SH", "深圳燃气"), ("605090.SH", "九丰能源"), ("002911.SZ", "佛燃能源"))]
        payloads.append(("peer_context", "eastmoney.peer_candidates", {"target_ts_code": "600803.SH", "candidates": candidates,
            "reported_population": 31, "selection_method": "eastmoney_industry_candidates"}, "2026-10-05", None))
        for index, candidate in enumerate(candidates):
            payloads.append(("peer_context", "tencent.peer_valuation", {"target_ts_code": "600803.SH", "ts_code": candidate["ts_code"],
                "name": candidate["name"], "as_of": "2026-09-30", "quote_timestamp": "2026-09-30T16:14:55+08:00",
                "price": 10., "total_market_cap_yi": 100., "currency": "CNY", "pe_ttm": 12.+index, "pb": 1.+index}, "2026-09-30", None))
    evidence, context = [], {}
    for cap, name, payload, published, url in payloads:
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        key = "e.d"+digest[:24]
        evidence.append({"evidence_id": key, "run_id": "minimum-600803", "ticker": "600803", "capability": cap,
            "source_name": name, "source_tier": "vendor", "source_family_id": name+":"+digest,
            "captured_at": "2026-10-05T08:00:00Z", "observed_at": "2026-10-05T08:00:00Z", "usable_as_of": "2026-10-05T08:00:00Z",
            "published_at": published+"T00:00:00+08:00" if published else None, "public_url": url,
            "time_basis": "offline fixture", "value_basis": "explicit units"})
        context[key] = payload
    caps = tuple(FrozenCapability(capability=cap, status=CapabilityStatus.QUALIFIED, reason="offline fixture") for cap in sorted({p[0] for p in payloads}))
    draft = FrozenEvidenceDraft(run_id="minimum-600803", ticker="600803", cutoff="2026-10-05", policy_version="catalyst-evidence-policy-v1",
        draft_id="minimum-fixture", frozen_at=datetime(2026, 10, 5, 8, tzinfo=timezone.utc), evidence=tuple(evidence), capabilities=caps)
    return draft, context


def record(**kwargs):
    return build_native_record(*fixture(**kwargs), mode="company_research", include_valuation=True, include_minimum=True)


def test_real_prefixed_report_summary_and_operating_notice_selection():
    rows = [{"Title": f["title"], "Published": f["published"], "Announcement ID": f["document_id"]}
            for f in json.loads(EXCERPTS.read_text())["documents"]]
    assert [r["Announcement ID"] for r in select_documents(rows, "2026-10-05")] == ["1225526373", "1225526315", "1225525549"]
    assert title_info("新奥股份2026年半年度报告") == {"period": "2026-06-30", "kind": "report"}
    assert title_info("新奥股份2026年半年度报告（修订版）") is None
    assert title_info("2026年半年度报告摘要")["kind"] == "summary"


def test_company_code_header_and_bounded_excerpts_are_admitted():
    full, summary, notice = documents()
    assert summary["report_period"] == "2026-06-30"
    assert len(full["excerpts"]) <= 12 and all(len(p["text"]) <= 4000 for p in full["excerpts"])
    assert full["body_coverage"] == summary["body_coverage"] == notice["body_coverage"] == "partial"
    assert next(r for r in full["numeric_rows"] if r["field"] == "consolidated_net_income")["current"] == "4606810000"


def test_physical_operating_units_quarter_and_half_year_are_not_mixed():
    rows = documents()[2]["numeric_rows"]
    total = [r for r in rows if r["label"] == "天然气总销售气量"]
    assert [(r["frequency"], r["current"], r["previous"], r["unit"]) for r in total] == [
        ("Q2", "9523", "9785", "百万立方米"), ("H1", "20467", "20329", "百万立方米")]
    assert {r["label"] for r in rows} == {"天然气总销售气量", "其中：平台交易气销售量", "天然气零售气销售量", "接收站接卸量"}
    assert len(rows) == 8


def test_cash_bridge_exact_sum_and_working_capital_contribution():
    result = record()
    checks = {c.check_id: c for c in result.evidence_checks.checks}
    assert all(c.status == "passed" for c in checks.values())
    cash = checks["cash_conversion"]
    values = {o.key: Decimal(o.value) for o in cash.observations}
    assert values["bridge_residual_current"] == values["bridge_residual_previous"] == 0
    assert values["cfo_change"] == -1095420000
    assert values["working_capital_change"] == -283460000
    assert values["investment_loss_change"] == -988010000
    assert values["fair_value_loss_change"] == 572430000
    assert compute_checks(result) == result.evidence_checks
    assert cfo_decline(result) and Decimal(cfo_decline(result).value) < 0
    assert "single_disclosure_family_no_supplier_crosscheck" in checks["operating_disclosures"].limitations
    assert len({s.source_family_id for s in result.evidence if s.source_name == NUMERIC_SOURCE}) == 1


@pytest.mark.parametrize("forecasts,peers,expected", [(False, True, "passed"), (True, False, "passed"), (False, False, "unavailable")])
def test_optional_branch_failure_preserves_passed_local_questions(forecasts, peers, expected):
    checks = {c.check_id: c for c in record(forecasts=forecasts, peers=peers).evidence_checks.checks}
    assert checks["valuation_context"].status == expected
    assert checks["operating_disclosures"].status == checks["cash_conversion"].status == "passed"


def test_cash_bridge_blank_required_cell_duplicate_or_changed_sum_cannot_pass():
    def missing(docs):
        row = next(r for r in docs[0]["numeric_rows"] if r["kind"] == "cash_bridge" and r["field"] == "inventory")
        row["raw_current"] = row["current"] = None
    def duplicate(docs):
        docs[0]["numeric_rows"].append(copy.deepcopy(next(r for r in docs[0]["numeric_rows"] if r["kind"] == "cash_bridge" and r["field"] == "inventory")))
        docs[0]["numeric_rows"][-1]["raw_row"] += " duplicated"
    def changed(docs):
        row = next(r for r in docs[0]["numeric_rows"] if r["kind"] == "cash_bridge" and r["field"] == "inventory")
        row["raw_current"], row["current"] = "197,807", "1978070000"
    for mutate in (missing, duplicate, changed):
        check = record(numeric_mutator=mutate).evidence_checks.checks[1]
        assert check.status in {"unavailable", "conflict"}


def test_complete_bridge_without_independent_statement_endpoints_is_unavailable():
    def remove(docs):
        for doc in docs:
            doc["numeric_rows"] = [r for r in doc["numeric_rows"] if r["kind"] != "financial" or r["field"] != "consolidated_net_income"]
    assert record(numeric_mutator=remove).evidence_checks.checks[1].status == "unavailable"


def test_numeric_unit_blank_period_and_header_tampering_are_rejected():
    row = next(r for r in documents()[0]["numeric_rows"] if r["kind"] == "cash_bridge")
    for changes in ({"current": "1"}, {"raw_current": None}, {"unit": "USD"}, {"prior_period": "2025-03-31"}, {"header_page": 177}, {"raw_current": "1e1000000"}):
        with pytest.raises(ValidationError):
            OfficialNumericRowV1.model_validate({**row, **changes})


def test_cash_bridge_requires_explicit_adjacent_header_and_complete_end():
    pages = [p for p in json.loads(EXCERPTS.read_text())["documents"][0]["pages"] if p["page"] in {179, 180}]
    assert len(cash_bridge_rows(pages, "2026-06-30")[0]) > 10
    wrong = copy.deepcopy(pages)
    wrong[1]["page"] = 181
    assert cash_bridge_rows(wrong, "2026-06-30")[0] == []
    wrong = copy.deepcopy(pages)
    wrong[0]["text"] = wrong[0]["text"].replace("本期金额", "未知列")
    assert cash_bridge_rows(wrong, "2026-06-30")[0] == []


def test_saved_record_recomputes_input_binding_requirements_and_arithmetic():
    original = record()
    for change in ("hash", "status", "scope", "number", "requirements"):
        value = original.model_dump(mode="json")
        if change == "hash":
            value["evidence_checks"]["input_sha256"] = "b"*64
        elif change == "status":
            value["evidence_checks"]["checks"][0]["status"] = "unavailable"
        elif change == "scope":
            value["evidence_checks"]["checks"][0]["question_scope"] = "cash_conversion.reported_bridge"
        elif change == "number":
            value["evidence_checks"]["checks"][1]["observations"][0]["value"] = "123"
        else:
            value["evidence_checks"]["checks"][0]["satisfied"] = []
        with pytest.raises(ValidationError, match="checks"):
            ResearchRecordV1.model_validate(value)


def test_forecast_window_years_positive_numbers_and_institution_dedup():
    rows = [forecast(), forecast(published="2026-09-01", eps="1.1"), forecast("乙证券"), forecast("丙证券"),
        forecast("未来", published="2026-10-06"), forecast("过期", published="2025-01-01"), forecast("零", eps="0"),
        forecast("非数", eps="NaN"), forecast("猜年", year=2025), forecast("指数", eps="1e1000000")]
    selected = deduplicate_forecasts(rows, ts_code="600803.SH", cutoff="2026-10-05")
    assert len(selected) == 3
    assert next(r for r in selected if r["institution"] == "甲证券")["eps"] == "1.78"
    assert deduplicate_forecasts([forecast(institution=str(i)) for i in range(12)], ts_code="600803.SH", cutoff="2026-10-05") and len(deduplicate_forecasts([forecast(institution=str(i)) for i in range(12)], ts_code="600803.SH", cutoff="2026-10-05")) == 8


def test_eastmoney_uses_explicit_response_year_not_publication_year():
    item = {"stockCode": "600803", "orgSName": "甲证券", "infoCode": "AP1", "publishDate": "2026-09-04", "predictThisYearEps": "1.78"}
    assert eastmoney_forecasts({"currentYear": 2026, "data": [item]}, ts_code="600803.SH", cutoff="2026-10-05")[0]["forecast_year"] == 2026
    assert eastmoney_forecasts({"data": [item]}, ts_code="600803.SH", cutoff="2026-10-05") == []


def test_ths_aggregate_is_not_a_dated_forecast():
    html = '<title>新奥股份(600803) 盈利预测</title><table><tr><th>年度</th><th>均值</th></tr><tr><td>2026</td><td>1.78</td></tr></table>'
    assert ths_forecasts(html, ts_code="600803.SH", cutoff="2026-10-05") == []
    with pytest.raises(NativeSourceUnavailable):
        ths_forecasts(html, ts_code="600519.SH", cutoff="2026-10-05")


def test_peer_candidates_exclude_aggregates_target_and_duplicate_wrappers():
    rows = [{"SECUCODE": "600803.SH", "CORRE_SECUCODE": c, "CORRE_SECURITY_CODE": c[:6], "CORRE_SECURITY_NAME": n, "TOTAL_COUNT": 31}
            for c, n in (("行业平均", "行业平均"), ("600803.SH", "新奥股份"), ("601139.SH", "深圳燃气"), ("601139.SH", "深圳燃气"))]
    result = peer_candidates({"success": True, "result": {"data": rows}}, ts_code="600803.SH")
    assert [r["ts_code"] for r in result["candidates"]] == ["601139.SH"]
    assert result["reported_population"] == 31
    rows[-1]["SECUCODE"] = "600519.SH"
    with pytest.raises(NativeSourceUnavailable):
        peer_candidates({"success": True, "result": {"data": rows}}, ts_code="600803.SH")


def test_old_record_has_no_new_fields_and_no_checks_by_default():
    old = build_native_record(*fixture(), mode="company_research", include_valuation=True)
    assert "evidence_checks" not in old.model_dump() and "challenge_bindings" not in old.model_dump()
    assert ResearchRecordV1.model_validate_json(old.model_dump_json()).model_dump_json() == old.model_dump_json()


def bound_record(binding):
    original = record()
    fact = next(c for c in original.claims if c.kind == "fact")
    value = {**original.model_dump(mode="json"), "challenges": [{"challenge_id": "challenge.fixture", "target_claim_ids": [fact.claim_id],
        "statement": "现金流原因与持续性仍不确定。", "severity": "critical", "risk_type": "operations", "proposed_test": "核对本期并保留后续观察。"}],
        "challenge_bindings": [{"challenge_id": "challenge.fixture", **binding}]}
    return ResearchRecordV1.model_validate(value)


@pytest.mark.parametrize("binding,outcome", [({"check_id": "cash_conversion"}, "evidence_sufficient"),
    ({"check_id": "cash_conversion", "observed_risk": "cash_conversion.cfo_yoy_decline"}, "risk_supported"),
    ({"check_id": "cash_conversion", "observation_date": "2027-03-31"}, "future_observation"), ({}, "unresolved")])
def test_local_resolution_never_resolves_economic_parent(binding, outcome):
    result = challenge_assessments(bound_record(binding))[0]
    assert result.outcome == outcome and result.economic_outcome == "unresolved"
    assert result.answered_question is None or result.answered_question == "当前及上年同期间的净利润到经营现金流桥是否完整、可核对？"


def test_nonpositive_base_cannot_manufacture_decline_risk():
    def mutate(docs):
        for doc in docs:
            for row in doc["numeric_rows"]:
                if row["kind"] == "financial" and row["field"] == "cfo":
                    row["previous"] = row["raw_previous"] = "0"
    assert cfo_decline(record(numeric_mutator=mutate)) is None


def test_official_rows_do_not_bypass_missing_qualified_security_identity():
    draft, context = fixture()
    draft = draft.model_copy(update={"capabilities": tuple(cap.model_copy(update={"status": CapabilityStatus.UNAVAILABLE})
        if cap.capability == "security_identity" else cap for cap in draft.capabilities)})
    result = build_native_record(draft, context, mode="company_research", include_minimum=True, include_valuation=True)
    assert not result.claims
    assert all(c.status == "unavailable" for c in result.evidence_checks.checks)
    assert cfo_decline(result) is None
