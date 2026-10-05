"""Valuation is code-calculated from admitted, dated 600803 source evidence."""
import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.dataflows.native_valuation import qualify_history, qualify_snapshot
from tradingagents.research.evidence_freeze import (
    CapabilityStatus,
    FrozenCapability,
    FrozenEvidenceDraft,
)
from tradingagents.research.native_policy import dimension_policy, fact_views
from tradingagents.research.native_record import build_native_record


def valuation_fixture(*, annual=True, history=True, cutoff="2026-09-30"):
    payloads = [("security_identity", "tushare.stock_basic", {"ts_code": "600803.SH", "list_date": "19940103"}),
        ("valuation", "tencent.valuation_snapshot", {"ts_code": "600803.SH", "name": "新奥股份", "as_of": "2026-09-30",
            "quote_timestamp": "2026-09-30T16:14:55+08:00", "price": 20., "pe_ttm": 12., "pb": 2., "total_market_cap_yi": 100., "currency": "CNY"})]
    if history:
        days = [date(2026, 4, 1)+timedelta(days=i) for i in range(183)]
        rows = [{"date": day.isoformat(), "pe_ttm": 10.+i%5, "pb": 1.+i%5/10} for i, day in enumerate(days) if day.weekday()<5]
        payloads.append(("valuation", "tushare.valuation_history", {"ts_code": "600803.SH", "as_of": "2026-09-30", "currency": "CNY",
            "capture_scope": "current_cutoff_retrospective_history", "rows": rows}))
    if annual:
        row = {"ts_code": "600803.SH", "report_type": "1", "end_date": "20251231", "ann_date": "20260331", "n_income_attr_p": "800000000"}
        payloads.append(("fundamentals", "tushare.financial_statements", {"income": [row], "balancesheet": [], "cashflow": []}))
    evidence, context = [], {}
    for cap, name, payload in payloads:
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        key = "e.d"+digest[:16]
        evidence.append({"evidence_id": key, "run_id": "valuation-600803", "ticker": "600803", "capability": cap,
            "source_tier": "vendor", "source_name": name, "source_family_id": name+":"+digest,
            "captured_at": "2026-09-30T08:30:00Z", "observed_at": "2026-09-30T08:30:00Z", "usable_as_of": "2026-09-30T08:30:00Z",
            "time_basis": "current snapshot", "value_basis": "CNY and yi"})
        context[key] = payload
    caps = tuple(FrozenCapability(capability=cap, status=CapabilityStatus.QUALIFIED, reason="offline qualification")
        for cap in {x[0] for x in payloads})
    return FrozenEvidenceDraft(run_id="valuation-600803", ticker="600803", cutoff=cutoff, policy_version="catalyst-evidence-policy-v1",
        draft_id="valuation-fixture", frozen_at=datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc), evidence=tuple(evidence), capabilities=caps), context


def test_native_valuation_binds_dates_sources_hash_and_deterministic_math():
    record = build_native_record(*valuation_fixture(), mode="company_research", include_valuation=True)
    value = record.valuation
    assert value is not None
    assert value.inputs.net_income_annual.value_yi == 8
    anchor = next(a for a in value.assessment.anchor_outputs if a.per_share_low is not None)
    assert anchor.per_share_low == pytest.approx(anchor.multiple_low*8/5, abs=.01)
    assert anchor.per_share_high == pytest.approx(anchor.multiple_high*8/5, abs=.01)
    assert len(value.input_evidence_ids) == 3
    assert dimension_policy(record, scoped=True, valuation=True)["valuation"][0] == "conditional"
    assert any("valuation" in c.claim_id or "回溯" in c.statement for c in fact_views(record, valuation=True)["operating_quality"])
    assert "valuation" not in build_native_record(*valuation_fixture(), mode="company_research").model_dump()
    mutated = record.model_dump(mode="json")
    mutated["valuation"]["inputs"]["snapshot"]["price"] = 40
    with pytest.raises(ValidationError, match="hash mismatch"):
        ResearchRecordV1.model_validate(mutated)
    mutated = record.model_dump(mode="json")
    mutated["valuation"]["assessment"]["current_price"] = 99
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(mutated)


@pytest.mark.parametrize("annual,history", [(False, True), (True, False), (False, False)])
def test_missing_inputs_never_invent_reference_interval(annual, history):
    record = build_native_record(*valuation_fixture(annual=annual, history=history), mode="holding_review", include_valuation=True)
    assert record.valuation is not None
    assert all(anchor.per_share_low is None for anchor in record.valuation.assessment.anchor_outputs)
    assert record.valuation.assessment.synthesis.status == "unavailable"


@pytest.mark.parametrize("field,value", [("price", 0), ("price", float("nan")), ("total_market_cap_yi", -1), ("pe_ttm", True), ("pb", float("inf")), ("ts_code", "600519.SH")])
def test_invalid_snapshot_cannot_support_native_valuation(field, value):
    draft, context = valuation_fixture()
    key = draft.evidence[1]["evidence_id"]
    context = copy.deepcopy(context)
    context[key][field] = value
    # A mutated provider payload cannot pass the frozen source-family digest.
    with pytest.raises(ValueError):
        build_native_record(draft, context, mode="company_research", include_valuation=True)
    from tradingagents.research.native_valuation import valuation_content
    with pytest.raises(ValueError):
        valuation_content(context[key], "tencent.valuation_snapshot", "600803.SH", date(2026, 9, 30))


def test_capture_after_historical_cutoff_does_not_become_pit_evidence():
    record = build_native_record(*valuation_fixture(cutoff="2026-09-29"), mode="company_research", include_valuation=True)
    assert record.valuation is None


def test_quote_requires_exact_security_and_last_settled_trading_day():
    fields = [""]*53
    for index, value in {1:"新奥股份",2:"600803",3:"19.20",30:"20260930161455",37:"20",39:"13.63",45:"594.28",46:"2.53"}.items():
        fields[index] = value
    raw = 'v_sh600803="'+"~".join(fields)+'";'
    qualified = qualify_snapshot(raw, ts_code="600803.SH", last_session="2026-09-30")
    assert qualified["total_market_cap_yi"] == 594.28
    with pytest.raises(NativeSourceUnavailable):
        qualify_snapshot(raw, ts_code="600803.SH", last_session="2026-09-29")
    with pytest.raises(NativeSourceUnavailable):
        qualify_snapshot(raw.replace("sh600803", "sh600519"), ts_code="600803.SH", last_session="2026-09-30")


def test_multiple_history_rejects_duplicate_cross_security_and_missing_latest():
    row = {"ts_code":"600803.SH", "trade_date":"20260930", "pe_ttm":13.63, "pb":2.53}
    assert qualify_history([row], ts_code="600803.SH", start="2026-09-01", end="2026-09-30")[0]["pe_ttm"] == 13.63
    for rows in ([row,row], [{**row,"ts_code":"600519.SH"}], [{**row,"trade_date":"20260929"}]):
        with pytest.raises(NativeSourceUnavailable):
            qualify_history(rows, ts_code="600803.SH", start="2026-09-01", end="2026-09-30")


def test_optional_history_budget_exhaustion_retains_qualified_snapshot():
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from tradingagents.dataflows.native_valuation import SNAPSHOT_SOURCE, ValuationSources
    from tradingagents.execution.budget import BudgetBucket, BudgetExhausted, BudgetLimitHit

    collector = object.__new__(ValuationSources)
    collector.valuation_vendors = ["tencent", "tushare"]
    collector.last_session = "2026-09-30"
    collector.attempts = {}
    snapshot = {"ts_code": "600803.SH", "as_of": "2026-09-30", "price": 19.2, "currency": "CNY"}
    saved = []
    def attempt(capability, vendor, logical_id, query):
        if vendor == "tencent":
            return snapshot
        raise BudgetExhausted(BudgetLimitHit(BudgetBucket.DATA_HTTP_ATTEMPTS, logical_id, 64, 64, "exhausted"))
    collector._attempt = attempt
    collector.evidence = lambda inputs, capability, source, payload, **kwargs: saved.append((source, payload))
    inputs = SimpleNamespace(cutoff=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), capabilities=[])
    collector._valuation(inputs, "600803.SH", {"ts_code": "600803.SH"})
    capability = inputs.capabilities[0]
    assert saved == [(SNAPSHOT_SOURCE, snapshot)]
    assert capability.status == CapabilityStatus.PARTIAL and capability.sources == (SNAPSHOT_SOURCE,)
    assert "valuation_budget_exhausted" in capability.degradations
    assert "valuation_history_unavailable" in capability.degradations
