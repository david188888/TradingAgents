"""Native V0 facts preserve source identity, PIT dates and epistemic limits."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
from tradingagents.research.evidence_freeze import (
    CAP_EVENT_COVERAGE,
    CAP_FUNDAMENTALS,
    CAP_IDENTITY,
    CAP_PRICE,
    CapabilityStatus,
    FrozenCapability,
    FrozenEvidenceDraft,
)
from tradingagents.research.native_record import build_native_record
from tradingagents.research.verification_tools import _financial_operand


def source(capability, name, payload, *, published=None, **changes):
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result = {
        "evidence_id": f"e.{capability}.d{digest[:16]}", "run_id": "native-run",
        "ticker": "600519", "capability": capability,
        "source_tier": "official" if name == "cninfo" else "vendor",
        "source_name": name, "source_family_id": f"{name}:{digest}",
        "captured_at": "2026-09-30T08:00:00Z", "observed_at": "2026-09-30T08:00:00Z",
        "usable_as_of": "2026-09-30T08:00:00Z", "time_basis": "qualified cutoff",
        "value_basis": "source values in CNY", "published_at": published,
    }
    return {**result, **changes}


def financials(periods=2):
    periods_all = ["20260630", "20260331", "20251231", "20250930",
        "20250630", "20250331", "20241231", "20240930"]
    values = {"income": {"revenue": "120.125", "n_income": "20"},
        "balancesheet": {"total_assets": "300", "total_liab": "100"},
        "cashflow": {"n_cashflow_act": "30"}}
    return {table: [{"ts_code": "600519.SH", "report_type": "1", "end_date": period,
        "ann_date": (datetime.strptime(period, "%Y%m%d") + timedelta(days=45)).strftime("%Y%m%d"),
        **fields, "private_note": "must-never-be-published"} for period in periods_all[:periods]]
        for table, fields in values.items()}


def fixture(*, financial_payload=None, statuses=None, extra=()):
    payloads = [
        (CAP_IDENTITY, "tushare.stock_basic", {"ts_code": "600519.SH", "list_date": "20010827"}, None),
        (CAP_FUNDAMENTALS, "tushare.financial_statements", financial_payload or financials(), None),
        (CAP_EVENT_COVERAGE, "cninfo", {"Title": "签订重大合同的公告", "Published": "2026-09-29",
            "Announcement ID": "1", "private_note": "never-copy"}, "2026-09-29T00:00:00+08:00"),
        *extra,
    ]
    evidence = tuple(source(cap, name, payload, published=published) for cap, name, payload, published in payloads)
    context = {item["evidence_id"]: payload[2] for item, payload in zip(evidence, payloads, strict=True)}
    statuses = statuses or {}
    capabilities = tuple(FrozenCapability(capability=cap,
        status=statuses.get(cap, CapabilityStatus.QUALIFIED), reason="fixture qualification",
        degradations=("fixture_partial",) if statuses.get(cap) == CapabilityStatus.PARTIAL else (),
        detail={"fixture": True}) for cap in (CAP_IDENTITY, CAP_FUNDAMENTALS, CAP_EVENT_COVERAGE, CAP_PRICE))
    draft = FrozenEvidenceDraft(run_id="native-run", ticker="600519", cutoff="2026-09-30",
        policy_version="catalyst-evidence-policy-v1", draft_id="native-fixture",
        frozen_at=datetime(2026, 9, 30, 8, tzinfo=timezone.utc), evidence=evidence,
        capabilities=capabilities)
    return draft, context


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_three_modes_start_from_same_code_owned_facts_without_model_judgement(mode):
    record = build_native_record(*fixture(), mode=mode)
    assert record.mode == mode and record.construction == "native"
    assert record.assessment is None
    assert record.hypotheses == record.challenges == record.verifications == ()
    assert len(record.snapshots) == 1 and record.snapshots[0].version == 0
    assert all(item.kind == "fact" for item in record.claims)
    assert len(record.claims) == 11
    assert "must-never" not in record.model_dump_json()
    assert "never-copy" not in record.model_dump_json()
    assert build_native_record(*fixture(), mode=mode) == record


def test_all_eight_periods_are_saved_exactly_without_changing_c1_numeric_parser():
    record = build_native_record(*fixture(financial_payload=financials(8)), mode="company_research")
    source_record = next(item for item in record.evidence if item.source_name == "tushare.financial_statements")
    saved = json.loads(source_record.content.text)
    assert len(saved["income"]) == len(saved["balancesheet"]) == len(saved["cashflow"]) == 8
    assert len(source_record.content.text) <= 4000 and not source_record.content.truncated
    value, lineage = _financial_operand(record, FinancialOperandV1(evidence_id=source_record.evidence_id,
        table="income", field="revenue", report_period="2025-06-30"))
    assert str(value) == "120.125"
    assert lineage["source_content_sha256"] == source_record.content.content_sha256
    assert any("income[end_date=2025-06-30].revenue" in item.limitations[-2] for item in record.claims)


def test_partial_financial_and_event_coverage_retains_returned_fields_not_absence_proof():
    record = build_native_record(*fixture(statuses={CAP_FUNDAMENTALS: CapabilityStatus.PARTIAL,
        CAP_EVENT_COVERAGE: CapabilityStatus.PARTIAL}), mode="company_research")
    assert len(record.claims) == 11
    assert all("partial_source_coverage" in item.limitations for item in record.claims)
    assert all("no announcement" not in item.statement for item in record.claims)


@pytest.mark.parametrize("status", [CapabilityStatus.UNAVAILABLE, CapabilityStatus.COVERAGE_UNKNOWN,
    CapabilityStatus.PARTIAL, CapabilityStatus.COVERED_NO_MATCH])
def test_unqualified_security_identity_prevents_every_fact_and_metric(status):
    record = build_native_record(*fixture(statuses={CAP_IDENTITY: status}), mode="company_research")
    assert record.claims == record.metrics == ()
    assert "security_identity_unqualified" in record.limitations


@pytest.mark.parametrize("change", [{"ticker": "000001"}, {"run_id": "different-run"}])
def test_cross_security_or_run_source_cannot_enter_native_snapshot(change):
    draft, context = fixture()
    draft = draft.model_copy(update={"evidence": ({**draft.evidence[0], **change}, *draft.evidence[1:])})
    with pytest.raises(ValueError, match="identity"):
        build_native_record(draft, context, mode="company_research")


def test_same_source_metadata_cannot_mask_mutated_context():
    draft, context = fixture()
    context[draft.evidence[1]["evidence_id"]]["income"][0]["revenue"] = 999
    with pytest.raises(ValueError, match="digest"):
        build_native_record(draft, context, mode="company_research")


def test_missing_source_payload_is_a_gap_without_empty_or_estimated_facts():
    draft, context = fixture()
    context.pop(draft.evidence[1]["evidence_id"])
    record = build_native_record(draft, context, mode="company_research")
    assert len(record.claims) == 1
    financial_source = record.evidence[1]
    assert financial_source.availability == "unavailable" and financial_source.content is None


@pytest.mark.parametrize("status", [CapabilityStatus.COVERED_NO_MATCH, CapabilityStatus.NOT_APPLICABLE])
def test_nonmatching_or_inapplicable_financial_capability_cannot_admit_positive_facts(status):
    record = build_native_record(*fixture(statuses={CAP_FUNDAMENTALS: status}), mode="company_research")
    assert len(record.claims) == 1
    assert record.evidence[1].availability == "unavailable"


@pytest.mark.parametrize("defect", ["future_disclosure", "missing_disclosure", "duplicate_period", "nonfinite",
    "bool", "wrong_security", "unconsolidated", "bad_date", "future_period"])
def test_invalid_financial_rows_do_not_become_facts(defect):
    payload = financials(1)
    row = payload["income"][0]
    if defect == "future_disclosure":
        row["f_ann_date"] = "20261001"
    elif defect == "missing_disclosure":
        row.pop("ann_date")
    elif defect == "duplicate_period":
        payload["income"].append(dict(row))
    elif defect == "nonfinite":
        row["revenue"] = "NaN"
    elif defect == "bool":
        row["revenue"] = True
    elif defect == "wrong_security":
        row["ts_code"] = "000001.SZ"
    elif defect == "unconsolidated":
        row["report_type"] = "2"
    elif defect == "bad_date":
        row["f_ann_date"] = "private-note"
    else:
        row["end_date"] = "20261231"
    record = build_native_record(*fixture(financial_payload=payload), mode="company_research")
    assert not any("income.revenue" in item.statement for item in record.claims)
    assert "private-note" not in record.model_dump_json()


@pytest.mark.parametrize("change", [{"usable_as_of": "2026-10-01T00:00:00+08:00"},
    {"usable_as_of": None}, {"published_at": "2026-10-01T00:00:00+08:00"}])
def test_source_point_in_time_failures_keep_gap_without_claims(change):
    draft, context = fixture()
    draft = draft.model_copy(update={"evidence": (draft.evidence[0], {**draft.evidence[1], **change}, draft.evidence[2])})
    record = build_native_record(draft, context, mode="company_research")
    assert len(record.claims) == 1
    assert record.evidence[1].availability == "unavailable"


def test_announcement_title_is_locatable_and_does_not_prove_implementation():
    record = build_native_record(*fixture(), mode="catalyst_research")
    claim = next(item for item in record.claims if "event_context" in item.limitations[-1])
    assert "签订重大合同的公告" in claim.statement
    assert "尚未核对正文或实施情况" in claim.statement
    source_record = next(item for item in record.evidence if item.evidence_id == claim.evidence_ids[0])
    assert source_record.source_name == "cninfo.announcements"
    assert source_record.source_family_id.startswith("cninfo:")
    assert "Title;Published" in claim.limitations[-2]


def test_user_original_thesis_is_a_saved_declaration_not_an_economic_fact():
    record = build_native_record(*fixture(), mode="holding_review", original_thesis="现金流改善可以延续",
        holding_facts_as_of="2026-09-01")
    user_source = next(item for item in record.evidence if item.source_name == "user.original_thesis")
    assert user_source.content.text == "现金流改善可以延续"
    claim = next(item for item in record.claims if item.evidence_ids == (user_source.evidence_id,))
    assert "不证明该论点为真" in claim.statement
    assert "user_declaration_not_independently_verified" in claim.limitations


def test_missing_original_thesis_does_not_remove_company_operating_facts():
    record = build_native_record(*fixture(), mode="holding_review")
    assert len(record.claims) == 11
    assert not any(item.source_name == "user.original_thesis" for item in record.evidence)


@pytest.mark.parametrize("mode,date", [("company_research", "2026-09-01"), ("holding_review", None),
    ("holding_review", "2026-10-01")])
def test_original_thesis_cannot_be_silently_assigned_an_invented_or_future_date(mode, date):
    with pytest.raises(ValueError):
        build_native_record(*fixture(), mode=mode, original_thesis="original", holding_facts_as_of=date)


@pytest.mark.parametrize("qualified", [True, False])
def test_price_statistics_only_enter_when_pit_qualified_and_never_become_valuation(qualified):
    from tests.test_price_statistics_context import context as price_context
    from tradingagents.research.price_statistics import build_price_statistics
    bars, provenance = price_context(30)
    provenance["input_sha256"] = "a" * 64
    provenance["pit_status"] = "verified" if qualified else "unverified"
    payload = {"bars": bars, "provenance": provenance,
        "computed_statistics": build_price_statistics(bars, provenance)}
    record = build_native_record(*fixture(extra=((CAP_PRICE, "tushare.adjusted_daily", payload, None),)),
        mode="company_research")
    assert len(record.metrics) == (6 if qualified else 0)
    price_claims = [item for item in record.claims if "native_dimension:market_context" in item.limitations]
    assert len(price_claims) == (6 if qualified else 0)
    assert all("不是价值区间" in item.statement for item in price_claims)
    assert not any("native_dimension:valuation" in item.limitations for item in record.claims)


@pytest.mark.parametrize("field,value", [("ts_code", "000001.SZ"), ("list_date", "20261001")])
def test_identity_payload_must_match_security_and_listing_at_cutoff(field, value):
    draft, context = fixture()
    payload = {**context[draft.evidence[0]["evidence_id"]], field: value}
    identity = source(CAP_IDENTITY, "tushare.stock_basic", payload)
    draft = draft.model_copy(update={"evidence": (identity, *draft.evidence[1:])})
    context[identity["evidence_id"]] = payload
    assert build_native_record(draft, context, mode="company_research").claims == ()


def test_tencent_qualified_close_is_a_fact_even_without_computed_statistics():
    payload = {"bars": [{"Date": "2026-09-30", "Close": "123.45"}],
        "provenance": {"pit_status": "verified", "window_covered": True,
            "price_unit": "CNY/share", "adjustment_anchor": "2026-09-30"}}
    record = build_native_record(*fixture(extra=((CAP_PRICE, "tencent.qfq", payload, None),)), mode="company_research")
    assert record.metrics == ()
    price_claims = [item for item in record.claims if "native_dimension:market_context" in item.limitations]
    assert len(price_claims) == 1 and "123.45" in price_claims[0].statement


@pytest.mark.parametrize("defect", ["future_bar", "future_anchor", "wrong_unit"])
def test_price_history_qualifier_cannot_admit_future_or_wrong_unit_close(defect):
    payload = {"bars": [{"Date": "2026-09-30", "Close": "123.45"}],
        "provenance": {"pit_status": "verified", "window_covered": True,
            "price_unit": "CNY/share", "adjustment_anchor": "2026-09-30"}}
    if defect == "future_bar":
        payload["bars"][0]["Date"] = "2026-10-01"
    elif defect == "future_anchor":
        payload["provenance"]["adjustment_anchor"] = "2026-10-01"
    else:
        payload["provenance"]["price_unit"] = "USD/share"
    record = build_native_record(*fixture(extra=((CAP_PRICE, "tencent.qfq", payload, None),)), mode="company_research")
    assert not any("native_dimension:market_context" in item.limitations for item in record.claims)
    assert record.evidence[-1].availability == "unavailable"


def test_financial_public_size_limit_is_explicit_and_never_slices_invalid_json():
    payload = financials(8)
    for rows in payload.values():
        for row in rows:
            for key in ("revenue", "n_income", "total_assets", "total_liab", "n_cashflow_act"):
                if key in row:
                    row[key] = "1." + "2" * 60
    record = build_native_record(*fixture(financial_payload=payload), mode="company_research")
    financial_source = record.evidence[1]
    assert financial_source.content is None and financial_source.availability == "unavailable"
    assert "source_fields_missing_invalid_or_exceed_public_limit" in financial_source.limitations
