"""Admission, independent fallback, mode consumers and topology recovery."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
from tradingagents.dataflows.native_qualification import (
    NativeSourceUnavailable,
    prepare_public_prices,
    sina_factors,
    sina_identity,
    sina_statement,
    szse_month,
)
from tradingagents.dataflows.native_sources import NativeSources, source_chains
from tradingagents.execution.budget import BudgetBucket, BudgetLedger
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
from tradingagents.research.native_policy import dimension_policy, fact_views
from tradingagents.research.native_record import build_native_record
from tradingagents.research.verification_tools import _financial_operand
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict

PROFILE = '<title>沃尔核材(002130)公司资料_新浪财经_新浪网</title><table id="comInfo1"><tr><td>上市市场：</td><td>深圳证券交易所</td><td>上市日期：</td><td><a>2007-04-20</a></td></tr></table>'
FIELDS = {"income": ("BIZINCO", "NETPROFIT"), "balancesheet": ("TOTASSET", "TOTLIAB"), "cashflow": ("MANANETR",)}


def statement(table):
    return {"result": {"status": {"code": 0}, "data": {"report_list": {
        "20260630": {"rType": "合并期末", "rCurrency": "CNY", "publish_date": "20260825",
            "data": [{"item_field": field, "item_value": "4653091807.210000"} for field in FIELDS[table]]}}}}}


def collector(monkeypatch):
    request = SimpleNamespace(ticker="002130.SZ", analysis_date="2026-10-03",
        catalyst_policy=catalyst_evidence_policy_v1(), effective_config={
            "evidence_source_vendors": {"identity": ["sina"], "events": [], "calendar": [], "price": []}})
    calls = []
    def fetch(key, operation):
        calls.append(key)
        return operation()
    sources = NativeSources(request, "multisource-run", None, fetch)
    def get(url, **kwargs):
        if "CorpInfo" in url:
            return PROFILE
        table = {"lrb": "income", "fzb": "balancesheet", "llb": "cashflow"}[kwargs["params"]["source"]]
        return statement(table)
    monkeypatch.setattr(sources, "_get", get)
    return sources, calls


def test_native_defaults_and_explicit_overrides_are_independent_of_classic():
    chains = source_chains({"data_vendors": {"fundamental_data": "tushare"}})
    assert chains["financial"] == ("sina", "tushare")
    assert source_chains({"evidence_source_vendors": {"financial": ["tushare"]}})["financial"] == ("tushare",)
    assert source_chains({"evidence_source_exclusions": ["tushare"]})["financial"] == ("sina",)
    assert source_chains({"evidence_source_vendors": {"identity": []}})["identity"] == ()


@pytest.mark.parametrize("config", [{"evidence_source_vendors": {"typo": []}},
    {"evidence_source_vendors": {"price": ["sina"]}}, {"evidence_source_exclusions": ["unknown"]},
    {"evidence_source_vendors": {"identity": ["sina", "sina"]}}])
def test_unknown_configuration_does_not_silently_enable_an_unselected_provider(config):
    with pytest.raises(ValueError, match="configuration"):
        source_chains(config)


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_sina_sources_feed_all_mode_facts_c1_and_reports_without_tushare(monkeypatch, mode):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_API_KEY", raising=False)
    sources, calls = collector(monkeypatch)
    monkeypatch.setattr(sources, "tushare", lambda *a, **k: pytest.fail("primary should not call Tushare"))
    record = build_native_record(*sources.collect(), mode=mode)
    assert "security_identity_unqualified" not in record.limitations
    source = next(s for s in record.evidence if s.source_name == "sina.financial_statements")
    value, _ = _financial_operand(record, FinancialOperandV1(evidence_id=source.evidence_id,
        table="income", field="revenue", report_period="2026-06-30"))
    assert str(value) == "4653091807.210000"
    assert fact_views(record)["operating_quality"]
    assert dimension_policy(record)["operating_quality"][0] == "conditional"
    assert "4653091807.210000" in record.model_dump_json()
    assert not any("tushare" in c for c in calls)


def test_financial_fallback_keeps_partial_primary_and_separate_backup_family(monkeypatch):
    sources, calls = collector(monkeypatch)
    original_get = sources._get
    def get(url, **kwargs):
        if kwargs.get("params", {}).get("source") == "llb":
            raise NativeSourceUnavailable("sina_statement_scope_or_unit_unqualified")
        return original_get(url, **kwargs)
    monkeypatch.setattr(sources, "_get", get)
    monkeypatch.setattr(sources, "tushare", lambda api, *a, **k: [{"ts_code": "002130.SZ", "report_type": "1",
        "end_date": "20260630", "ann_date": "20260825", "n_cashflow_act": "472115060.72"}])
    draft, context = sources.collect()
    record = build_native_record(draft, context, mode="company_research")
    financial = [s for s in record.evidence if s.source_name.endswith("financial_statements")]
    assert {s.source_name for s in financial} == {"sina.financial_statements", "tushare.financial_statements"}
    assert len({s.source_family_id for s in financial}) == 2
    assert sum("cashflow" in c for c in calls) == 2
    assert any("472115060.72" in fact.statement for fact in record.claims)
    cap = next(c for c in draft.capabilities if c.capability == "fundamentals")
    assert cap.detail["selected_tables"]["income"] == "sina"
    assert cap.detail["selected_tables"]["cashflow"] == "tushare"


def test_rate_limit_stops_same_run_tushare_but_preserves_public_results(monkeypatch):
    sources, _ = collector(monkeypatch)
    original_get = sources._get
    def get(url, **kwargs):
        if "CorpInfo" not in url:
            raise NativeSourceUnavailable("sina_no_qualified_statement_rows")
        return original_get(url, **kwargs)
    monkeypatch.setattr(sources, "_get", get)
    called = []
    def tushare(*args, **kwargs):
        called.append(args)
        raise NativeSourceUnavailable("tushare_rate_limited")
    monkeypatch.setattr(sources, "tushare", tushare)
    draft, _ = sources.collect()
    assert len(called) == 1
    assert sources.tushare_limited
    assert any(a["code"] == "tushare_run_cooldown" for a in sources.attempts["fundamentals"] if a["status"] == "unavailable")
    assert draft.capability("security_identity").status.value == "qualified"


@pytest.mark.parametrize("error", [AnalysisCancelled("cancelled"), TimeoutError("deadline"),
    CatalystCheckpointConflict("disk conflict")])
def test_control_flow_errors_are_not_provider_fallback(monkeypatch, error):
    sources, _ = collector(monkeypatch)
    def fetch(*args):
        raise error
    sources.fetch = fetch
    with pytest.raises(type(error)):
        sources.collect()


def test_exhausted_capability_budget_stops_fallback(monkeypatch):
    from tradingagents.execution.budget import BudgetExhausted
    sources, _ = collector(monkeypatch)
    ledger = BudgetLedger("limited", limits={BudgetBucket.DATA_CAPABILITY_CALLS: 0})
    def fetch(key, operation):
        ledger.reserve_or_raise(BudgetBucket.DATA_CAPABILITY_CALLS, stage="native.evidence", logical_call_id=key)
        pytest.fail("zero budget dispatched an operation")
    sources.fetch = fetch
    with pytest.raises(BudgetExhausted):
        sources.collect()


@pytest.mark.parametrize("field,value", [("publish_date", None), ("publish_date", "20260601"),
    ("rCurrency", "USD"), ("rType", "母公司"), ("unit", "亿元")])
def test_financial_dates_scope_and_units_cannot_be_invented(field, value):
    payload = statement("income")
    payload["result"]["data"]["report_list"]["20260630"][field] = value
    with pytest.raises(NativeSourceUnavailable):
        sina_statement(payload, table="income", ts_code="002130.SZ", cutoff="2026-10-03")


def test_future_financial_disclosure_and_wrong_profile_are_rejected():
    payload = statement("income")
    payload["result"]["data"]["report_list"]["20260630"]["publish_date"] = "20261004"
    with pytest.raises(NativeSourceUnavailable, match="no_qualified"):
        sina_statement(payload, table="income", ts_code="002130.SZ", cutoff="2026-10-03")
    with pytest.raises(NativeSourceUnavailable, match="code_mismatch"):
        sina_identity(PROFILE.replace("002130", "002131"), ts_code="002130.SZ", cutoff="2026-10-03")


def test_financial_metadata_is_retained_and_later_update_is_excluded():
    payload = statement("income")
    report = payload["result"]["data"]["report_list"]["20260630"]
    rows = sina_statement(payload, table="income", ts_code="002130.SZ", cutoff="2026-10-03")
    assert rows[0]["provider_metadata"]["rCurrency"] == "CNY"
    assert rows[0]["provider_metadata"]["publish_date"] == "20260825"
    report["update_time"] = int(datetime(2026,10,4,tzinfo=timezone.utc).timestamp())
    with pytest.raises(NativeSourceUnavailable, match="no_qualified"):
        sina_statement(payload, table="income", ts_code="002130.SZ", cutoff="2026-10-03")


def test_official_calendar_requires_whole_natural_month():
    payload = {"data": [{"jyrq": f"2026-09-{day:02d}", "jybz": "0"} for day in range(1,31)]}
    assert len(szse_month(payload, 2026, 9)) == 30
    payload["data"].pop()
    with pytest.raises(NativeSourceUnavailable, match="window_not_complete"):
        szse_month(payload, 2026, 9)


def price_fixture():
    raw = {"provenance": {"code": "sz002130"}, "bars": [{"Date": f"2026-09-{day:02d}",
        "Open": 10, "High": 12, "Low": 9, "Close": 11} for day in range(28,31)]}
    factors = [{"d": "2026-01-01", "f": "2"}, {"d": "2026-09-29", "f": "1"}]
    calendar = [{"cal_date": f"202609{day}", "is_open": "1"} for day in range(28,31)]
    return raw, factors, calendar


def test_dated_sina_divisor_scales_all_ohlc_and_current_cutoff_is_qualified():
    raw, factors, calendar = price_fixture()
    result = prepare_public_prices(raw, factors, calendar, ts_code="002130.SZ", start="2026-09-28",
        cutoff="2026-09-30", captured_at=datetime(2026,9,30,9,tzinfo=timezone.utc))
    assert result["bars"][0]["Close"] == 5.5 and result["bars"][-1]["Close"] == 11
    assert result["bars"][0]["High"] == 6
    assert result["provenance"]["pit_status"] == "verified"
    old = prepare_public_prices(raw, factors, calendar, ts_code="002130.SZ", start="2026-09-28",
        cutoff="2026-09-30", captured_at=datetime(2026,10,1,9,tzinfo=timezone.utc))
    assert old["provenance"]["pit_status"] == "unverified"


@pytest.mark.parametrize("mutation", ["wrong_code", "session_gap", "factor_gap", "future_factor", "ohlc"])
def test_price_qualification_rejects_each_independent_failure(mutation):
    raw, factors, calendar = price_fixture()
    if mutation == "wrong_code":
        raw["provenance"]["code"] = "sz002131"
    if mutation == "session_gap":
        raw["bars"].pop()
    if mutation == "factor_gap":
        factors.pop(0)
    if mutation == "future_factor":
        factors.append({"d": "2026-10-01", "f": "1"})
    if mutation == "ohlc":
        raw["bars"][0]["Low"] = 20
    with pytest.raises(ValueError):
        prepare_public_prices(raw, factors, calendar, ts_code="002130.SZ", start="2026-09-28",
            cutoff="2026-09-30", captured_at=datetime(2026,9,30,9,tzinfo=timezone.utc))


def test_factor_assignment_binds_security_and_total():
    rows = [{"d": "2026-01-01", "f": "1"}]
    import json
    text = 'var sz002130qfq='+json.dumps({"total": 1, "data": rows})+';/* vendor footer */'
    assert sina_factors(text, symbol="sz002130") == rows
    with pytest.raises(NativeSourceUnavailable, match="identity"):
        sina_factors(text, symbol="sz002131")
