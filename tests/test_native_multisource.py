"""Admission, independent fallback, mode consumers and topology recovery."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
from tradingagents.dataflows.native_qualification import (
    CALENDAR_INDEX_SYMBOL,
    NativeSourceUnavailable,
    calendar_disputes,
    calendar_gaps,
    index_session_dates,
    prepare_public_prices,
    qualify_session_calendar,
    settle_calendar_disputes,
    sina_factors,
    sina_identity,
    sina_statement,
    szse_month,
)
from tradingagents.dataflows.native_sources import NativeSources, source_chains
from tradingagents.dataflows.tushare_price_history import settled_sessions
from tradingagents.execution.budget import BudgetBucket, BudgetLedger
from tradingagents.execution.config_identity import SemanticConfigError
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
    # The official SZSE calendar serves every A-share exchange; the quota-free
    # index walk is its witness and fallback; capped tushare is the last resort.
    assert chains["calendar"] == ("szse", "tencent", "tushare")
    assert source_chains({"evidence_source_vendors": {"financial": ["tushare"]}})["financial"] == ("tushare",)
    assert source_chains({"evidence_source_exclusions": ["tushare"]})["financial"] == ("sina",)
    assert source_chains({"evidence_source_exclusions": ["tushare"]})["calendar"] == ("szse", "tencent")
    assert source_chains({"evidence_source_vendors": {"identity": []}})["identity"] == ()


@pytest.mark.parametrize("config", [{"evidence_source_vendors": {"typo": []}},
    {"evidence_source_vendors": {"price": ["sina"]}}, {"evidence_source_exclusions": ["unknown"]},
    {"evidence_source_vendors": {"identity": ["sina", "sina"]}}])
def test_unknown_configuration_does_not_silently_enable_an_unselected_provider(config):
    with pytest.raises(SemanticConfigError, match="configuration"):
        source_chains(config)


@pytest.mark.parametrize("config", [
    {"evidence_source_vendors": []},
    {"evidence_source_vendors": {"valuation": ["unknown"]}},
])
@pytest.mark.parametrize("version", ["valuation", "minimum"])
def test_extended_source_configuration_is_typed_before_collection(config, version):
    from tradingagents.dataflows.minimum_sources import MinimumEvidenceSources
    from tradingagents.dataflows.native_valuation import ValuationSources

    factory = ValuationSources if version == "valuation" else MinimumEvidenceSources
    request = SimpleNamespace(effective_config=config)
    with pytest.raises(SemanticConfigError, match="configuration"):
        factory(request, "configuration-check", None, None)


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


CST = timezone(timedelta(hours=8))


def index_calendar(bars):
    return {"data": {CALENDAR_INDEX_SYMBOL: {"day": [[day] for day in bars]}}}


def at(day, hour, minute=0):
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=CST)


def test_index_session_dates_reads_bar_dates_only():
    assert index_session_dates(index_calendar(["2026-10-09", "2026-10-08"]),
        index_symbol=CALENDAR_INDEX_SYMBOL) == ["2026-10-08", "2026-10-09"]


@pytest.mark.parametrize("payload,code", [
    ({}, "invalid_shape"), ({"data": []}, "invalid_shape"),
    ({"data": {CALENDAR_INDEX_SYMBOL: {}}}, "invalid_shape"),
    (index_calendar(["not-a-date"]), "invalid_row"), (index_calendar(["2026-02-30"]), "invalid_row"),
    (index_calendar(["2026-10-08", "2026-10-08"]), "duplicate_row"),
    # 2026-10-10 is a Saturday: A shares never trade at weekends.
    (index_calendar(["2026-10-09", "2026-10-10"]), "invalid_row"),
])
def test_index_session_dates_rejects_unqualified_series(payload, code):
    with pytest.raises(NativeSourceUnavailable, match=code):
        index_session_dates(payload, index_symbol=CALENDAR_INDEX_SYMBOL)


def test_weekend_cutoff_with_settled_weekday_bars_is_admitted():
    """Review probe 1: a natural-day tail is not a missing session."""
    captured = at("2026-10-18", 12)
    rows = qualify_session_calendar(["2026-10-15", "2026-10-16"], [], start="2026-10-15",
        cutoff="2026-10-18", captured_at=captured)
    assert [r["is_open"] for r in rows] == ["1", "1", "0", "0"]
    assert settled_sessions(rows, start="2026-10-15", cutoff="2026-10-18",
        captured_at=captured) == ("2026-10-15", "2026-10-16")


def test_capture_day_before_settlement_is_unconfirmed_not_required():
    """Review probe 2: no complete bar can exist before the session opens."""
    captured = at("2026-10-19", 0, 8)
    assert calendar_gaps(["2026-10-15", "2026-10-16"], start="2026-10-15",
        cutoff="2026-10-19", captured_at=captured) == []
    rows = qualify_session_calendar(["2026-10-15", "2026-10-16"], [], start="2026-10-15",
        cutoff="2026-10-19", captured_at=captured)
    assert rows[-1] == {"cal_date": "20261019", "is_open": "0"}
    assert settled_sessions(rows, start="2026-10-15", cutoff="2026-10-19",
        captured_at=captured)[-1] == "2026-10-16"


def test_internal_weekday_without_bar_is_not_presumed_closed():
    """Review probe 3: a missing weekday needs an independent closure witness."""
    captured = at("2026-10-19", 17)
    sessions = ["2026-10-15", "2026-10-19"]
    assert calendar_gaps(sessions, start="2026-10-15", cutoff="2026-10-19",
        captured_at=captured) == ["2026-10-16"]
    with pytest.raises(NativeSourceUnavailable, match="calendar_gap_unwitnessed"):
        qualify_session_calendar(sessions, [], start="2026-10-15", cutoff="2026-10-19", captured_at=captured)


def test_long_holiday_is_closed_only_with_witnessed_closures():
    captured = at("2026-10-12", 17)
    sessions = ["2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12"]
    holiday = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
    assert calendar_gaps(sessions, start="2026-09-30", cutoff="2026-10-12", captured_at=captured) == holiday
    rows = qualify_session_calendar(sessions, holiday, start="2026-09-30", cutoff="2026-10-12", captured_at=captured)
    assert settled_sessions(rows, start="2026-09-30", cutoff="2026-10-12", captured_at=captured) == tuple(sessions)


def test_truncated_index_series_cannot_witness_the_window():
    with pytest.raises(NativeSourceUnavailable, match="window_not_complete"):
        calendar_gaps(["2026-10-09", "2026-10-12"], start="2026-10-01", cutoff="2026-10-12",
            captured_at=at("2026-10-12", 17))


def szse_rows(start, cutoff, closed_weekdays=()):
    begin, end = date.fromisoformat(start), date.fromisoformat(cutoff)
    days = [begin + timedelta(days=i) for i in range((end - begin).days + 1)]
    return [{"cal_date": d.strftime("%Y%m%d"),
             "is_open": "0" if d.weekday() >= 5 or d.isoformat() in closed_weekdays else "1"} for d in days]


def test_calendar_disputes_compare_only_settled_days():
    rows = szse_rows("2026-10-12", "2026-10-19")
    sessions = ["2026-10-12", "2026-10-13", "2026-10-15", "2026-10-16"]
    # 10-14 is missing from the index; 10-19 is unsettled at 10:00 and not compared.
    assert calendar_disputes(rows, sessions, start="2026-10-12", cutoff="2026-10-19",
        captured_at=at("2026-10-19", 10)) == ["2026-10-14"]


def test_dispute_witness_upholds_unresolves_or_rejects_the_official_calendar():
    rows = szse_rows("2026-10-12", "2026-10-16")
    assert settle_calendar_disputes(rows, ["2026-10-14"], {"2026-10-14": True}) == []
    assert settle_calendar_disputes(rows, ["2026-10-14"], {"2026-10-14": None}) == ["2026-10-14"]
    with pytest.raises(NativeSourceUnavailable, match="calendar_sources_conflict"):
        settle_calendar_disputes(rows, ["2026-10-14"], {"2026-10-14": False})


class CalendarHarness:
    """Routes the calendar chain over scripted SZSE, Tencent, TDX and tushare."""

    def __init__(self, monkeypatch, *, ticker="600418.SH", szse=None, index=None, tdx=None,
                 config=None):
        self.calls = []
        self.tdx = tdx or {}
        request = SimpleNamespace(ticker=ticker, analysis_date="2026-10-16",
            catalyst_policy=catalyst_evidence_policy_v1(), effective_config=config or {})
        session = SimpleNamespace(head=self.head)
        self.sources = NativeSources(request, "calendar-run", session, self.fetch)
        def get(url, **kwargs):
            if "szse" in url:
                self.calls.append("szse")
                if isinstance(szse, Exception):
                    raise szse
                year, month = (int(v) for v in kwargs["params"]["month"].split("-"))
                first = date(year, month, 1)
                last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                return {"data": [{"jyrq": api(r["cal_date"]), "jybz": r["is_open"]}
                                 for r in szse_rows(first.isoformat(), last.isoformat(), HOLIDAY)]}
            self.calls.append("tencent")
            if isinstance(index, Exception):
                raise index
            return index_calendar(index)
        monkeypatch.setattr(self.sources, "_get", get)
        monkeypatch.setattr(self.sources, "tushare", self.tushare)

    def fetch(self, key, operation):
        return operation()

    def head(self, url, **kwargs):
        day = url.rsplit("/", 1)[1][:8]
        self.calls.append("tdx:"+day)
        status = self.tdx.get(day, 200)
        if isinstance(status, Exception):
            raise status
        return SimpleNamespace(status_code=status)

    def tushare(self, *args, **kwargs):
        self.calls.append("tushare")
        raise NativeSourceUnavailable("tushare_rate_limited")

    def calendar(self, start="2026-09-28", cutoff="2026-10-16"):
        rows = self.sources._calendar(SimpleNamespace(cutoff=cutoff), self.sources.request.ticker, start)
        return rows, self.sources.calendar_gaps, self.sources.attempts["price_history"]


HOLIDAY = ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07")
INDEX = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09",
         "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]


def api(value):
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def opened(rows):
    return [api(r["cal_date"]) for r in rows if r["is_open"] == "1"]


def test_official_calendar_serves_shanghai_tickers_with_quota_free_witness(monkeypatch):
    harness = CalendarHarness(monkeypatch, index=INDEX)
    rows, gaps, attempts = harness.calendar()
    assert opened(rows) == INDEX
    assert gaps == []
    assert [a["vendor"] for a in attempts] == ["szse", "tencent"]
    assert "tushare" not in harness.calls and not any(c.startswith("tdx") for c in harness.calls)


def test_unavailable_witness_accepts_official_calendar_with_degradation(monkeypatch):
    harness = CalendarHarness(monkeypatch, index=requests.ConnectionError("down"))
    rows, gaps, _ = harness.calendar()
    assert opened(rows) == INDEX
    assert gaps == ["calendar_cross_check_unavailable"]
    assert "tushare" not in harness.calls


def test_excluded_witness_is_not_called_or_reported(monkeypatch):
    harness = CalendarHarness(monkeypatch, index=INDEX, config={"evidence_source_exclusions": ["tencent"]})
    rows, gaps, _ = harness.calendar()
    assert opened(rows) == INDEX and gaps == [] and "tencent" not in harness.calls


def test_index_omission_is_settled_by_tdx_without_tushare(monkeypatch):
    index = [d for d in INDEX if d != "2026-10-14"]
    harness = CalendarHarness(monkeypatch, index=index, tdx={"20261014": 200})
    rows, gaps, _ = harness.calendar()
    assert opened(rows) == INDEX and gaps == []
    assert harness.sources.calendar_detail == {"calendar_disputes": ["2026-10-14"],
                                               "calendar_disputes_unresolved": []}
    # The positive control is the latest session both sources agree on.
    assert harness.calls[-2:] == ["tdx:20261013", "tdx:20261014"]
    assert "tushare" not in harness.calls


@pytest.mark.parametrize("tdx", [{"20261014": requests.Timeout("slow")}, {"20261013": 404}])
def test_unwitnessed_dispute_keeps_official_calendar_with_degradation(monkeypatch, tdx):
    index = [d for d in INDEX if d != "2026-10-14"]
    harness = CalendarHarness(monkeypatch, index=index, tdx=tdx)
    rows, gaps, _ = harness.calendar()
    assert opened(rows) == INDEX
    assert gaps == ["calendar_cross_check_unresolved"]
    assert "tushare" not in harness.calls


def test_two_vendors_contradicting_the_official_calendar_reject_it(monkeypatch):
    index = [d for d in INDEX if d != "2026-10-14"]
    harness = CalendarHarness(monkeypatch, index=index, tdx={"20261014": 404})
    rows, _, attempts = harness.calendar()
    assert rows is None
    assert attempts[-1]["code"] == "calendar_sources_conflict"
    assert "tushare" not in harness.calls


def test_unreachable_official_calendar_falls_back_to_witnessed_index_walk(monkeypatch):
    harness = CalendarHarness(monkeypatch, szse=requests.ConnectionError("down"), index=INDEX,
        tdx={f"2026{d[5:7]}{d[8:]}": 404 for d in HOLIDAY})
    rows, gaps, attempts = harness.calendar()
    assert opened(rows) == INDEX and gaps == []
    assert [a["vendor"] for a in attempts] == ["szse", "tencent"]
    assert "tdx:20260930" in harness.calls and "tushare" not in harness.calls


def test_price_capability_stays_qualified_and_reports_calendar_degradation(monkeypatch):
    harness = CalendarHarness(monkeypatch, index=requests.ConnectionError("down"))
    sources = harness.sources
    original = sources._attempt
    def attempt(capability, vendor, key, operation):
        if key.startswith("price."):
            return {"bars": [{"Date": "2026-10-16", "Close": 10.0}], "provenance": {"window_covered": True}}
        return original(capability, vendor, key, operation)
    monkeypatch.setattr(sources, "_attempt", attempt)
    monkeypatch.setattr(sources, "evidence", lambda *args, **kwargs: None)
    inputs = SimpleNamespace(cutoff="2026-10-16", prices=[], capabilities=[])
    sources._prices(inputs, "600418.SH", {"list_date": "20010824"})
    cap = inputs.capabilities[-1]
    assert cap.status.value == "qualified"
    assert cap.degradations == ("calendar_cross_check_unavailable",)


@pytest.mark.parametrize("tdx,code", [
    ({"20261002": 200}, "calendar_index_session_missing"),
    ({"20260930": 404}, "calendar_gap_unwitnessed"),
])
def test_index_walk_rejects_omitted_or_unwitnessed_weekdays(monkeypatch, tdx, code):
    statuses = {f"2026{d[5:7]}{d[8:]}": 404 for d in HOLIDAY} | tdx
    harness = CalendarHarness(monkeypatch, szse=requests.ConnectionError("down"), index=INDEX, tdx=statuses)
    rows, _, attempts = harness.calendar()
    assert rows is None
    assert next(a for a in attempts if a["vendor"] == "tencent")["code"] == code
    assert attempts[-1]["code"] == "tushare_rate_limited"


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
