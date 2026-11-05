"""Capability gateway: role scope, budgets, typed gaps and host-owned ticker."""

from datetime import date

from tests.test_search_budget import Journal
from tradingagents.agents.schemas._insight import CapabilityRequest
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.capability_gateway import execute_capability_requests


def run(requests, *, role="operating_quality", ticker="002130.SZ", journal=None, cutoff=None, **kwargs):
    journal = journal or Journal()
    return execute_capability_requests(
        requests, role=role, ticker=ticker, cutoff=cutoff or date(2026, 11, 5),
        ledger=journal.ledger, ensure_active=lambda: None, **kwargs), journal


def test_rejects_invisible_news_path_and_empty_disclosure_query():
    result, _ = run([
        {"capability_id": "news_search", "query": "客户", "gap_reason": "缺新闻"},
        {"capability_id": "disclosure_search", "query": "", "gap_reason": "缺公告"},
        {"capability_id": "valuation_history", "query": "", "gap_reason": "未实现"},
        {"capability_id": "shareholder_count", "query": "", "gap_reason": " "},
    ], role="market_context")
    assert result.executed == ()
    assert "capability_use_search_path:news_search" in result.rejected
    assert "capability_query_required:disclosure_search" in result.rejected
    assert "capability_not_visible:valuation_history" in result.rejected
    assert "capability_request_invalid" in result.rejected


def test_shareholder_fetch_is_admitted_and_budgeted(monkeypatch):
    report = "\n".join([
        "# China A-share shareholder counts for 002130.SZ",
        "# Source: eastmoney",
        "",
        "Date,Holder Num,Change Num,Change %,Avg Hold Num",
        "2026-09-30,12000,-500,-4.0,8000",
        "2025-12-31,12500,100,0.8,7800",
    ])
    monkeypatch.setattr(
        "tradingagents.dataflows.china_specialty_em.get_a_share_shareholder_counts_em",
        lambda ticker: report)
    result, journal = run([CapabilityRequest(
        capability_id="shareholder_count", query="", gap_reason="缺股东户数变化")])
    assert result.executed == ("shareholder_count",)
    assert len(result.admitted.observations) == 2
    assert all(item.role == "operating_quality" for item in result.admitted.observations)
    assert "native_dimension:operating_quality" in result.admitted.observations[0].fact.limitations
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == 1
    again, _ = run([{"capability_id": "shareholder_count", "query": "", "gap_reason": "缺股东户数变化"}],
                   journal=journal)
    assert again.admitted == result.admitted
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == 1


def test_disclosure_filters_by_query_and_cutoff(monkeypatch):
    records = [
        {"Published": "2026-10-01", "Title": "限售股解禁提示性公告", "Type": "提示",
         "Announcement ID": "1", "Detail URL": "https://www.cninfo.com.cn/a"},
        {"Published": "2026-10-02", "Title": "日常经营公告", "Type": "其他",
         "Announcement ID": "2", "Detail URL": "https://www.cninfo.com.cn/b"},
        {"Published": "2026-12-01", "Title": "限售股解禁未来公告", "Type": "提示",
         "Announcement ID": "3", "Detail URL": "https://www.cninfo.com.cn/c"},
    ]

    def fake(ticker, start, end, page_size=30, max_pages=10, session=None, records_sink=None):
        assert ticker == "600418.SS"
        if records_sink is not None:
            records_sink(records)
        return "ok"

    monkeypatch.setattr(
        "tradingagents.dataflows.china_specialty.get_a_share_cninfo_announcements", fake)
    result, _ = run([{"capability_id": "disclosure_search", "query": "解禁",
                      "gap_reason": "需核实解禁公告"}], ticker="600418.SS", role="market_context")
    assert result.executed == ("disclosure_search",)
    assert len(result.admitted.observations) == 1
    assert "限售股解禁提示性公告" in result.admitted.observations[0].source.content.text


def test_card_limit_counts_durable_attempts_not_one_call(monkeypatch):
    report = "\n".join(["# China A-share shareholder counts for 002130.SZ", "# Source: eastmoney", "",
                        "Date,Holder Num,Change Num,Change %,Avg Hold Num", "2026-09-30,12000,-500,-4.0,8000"])
    monkeypatch.setattr("tradingagents.dataflows.china_specialty_em.get_a_share_shareholder_counts_em",
                        lambda ticker: report)
    first, journal = run([{"capability_id": "shareholder_count", "query": "", "gap_reason": "缺户数"}])
    assert first.executed == ("shareholder_count",)
    again, _ = run([{"capability_id": "shareholder_count", "query": "", "gap_reason": "仍缺户数变化"}],
                   journal=journal)
    assert again.executed == ()
    assert "capability_card_limit:shareholder_count" in again.rejected
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == 1


def test_budget_exhaustion_stops_further_cards(monkeypatch):
    journal = Journal()
    for i in range(journal.ledger.limit(BudgetBucket.SUPPLEMENT_CAPABILITIES)):
        token = journal.ledger.reserve(BudgetBucket.SUPPLEMENT_CAPABILITIES,
                                       stage="capability.operating_quality", logical_call_id=f"fill.{i}")
        journal.ledger.mark_dispatched(token)
        journal.ledger.settle(token, ok=True, usage_available=False)
    monkeypatch.setattr(
        "tradingagents.dataflows.china_specialty_em.get_a_share_shareholder_counts_em",
        lambda ticker: (_ for _ in ()).throw(AssertionError("should not fetch")))
    result, _ = run([{"capability_id": "shareholder_count", "query": "", "gap_reason": "缺户数"}],
                    journal=journal)
    assert result.executed == ()
    assert "capability_budget_exhausted" in result.gaps


def test_consensus_eps_snapshot_is_admitted_only_for_a_live_cutoff(monkeypatch):
    text = "\n".join([
        "# China A-share consensus EPS forecast for 002130.SZ", "# Source: ths", "",
        "年度,预测机构数,最小值,均值,最大值,行业平均数",
        "2026,2,0.88,1.02,1.16,2.69",
        "2027,2,1.19,1.37,1.54,4.14",
    ])
    monkeypatch.setattr("tradingagents.dataflows.china_specialty_em.get_a_share_eps_forecast",
                        lambda ticker, as_of=None: text)
    result, journal = run([{"capability_id": "consensus_eps", "query": "", "gap_reason": "缺机构预期"}],
                          cutoff=date.today())
    assert result.executed == ("consensus_eps",)
    assert len(result.admitted.observations) == 2
    first = result.admitted.observations[0]
    assert "2026年" in first.source.content.text and "1.02" in first.source.content.text
    assert first.source.source_name == "ths.eps_forecast"
    assert "forecast_snapshot_not_reported_eps" in first.source.limitations
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == 1
    stale, _ = run([{"capability_id": "consensus_eps", "query": "", "gap_reason": "补历史"}],
                   cutoff=date(2026, 1, 1))
    assert stale.executed == ()
    assert "capability_unavailable:consensus_eps:capability_not_point_in_time" in stale.gaps


def test_dragon_tiger_admits_appearances_and_keeps_empty_typed(monkeypatch):
    text = "\n".join([
        "# China A-share dragon-tiger records for 002131.SZ", "# Source: eastmoney", "",
        "Date,Reason,Net Buy (wan),Turnover %",
        "2026-11-05,日涨幅偏离值达到7%的前5只证券,32994.8,8.48",
        "", "", "## TOP5 buy/sell seats on 2026-11-05", "",
        "Side,Seat,Buy (wan),Sell (wan),Net (wan)",
        "buy,深股通专用,11138.9,5905.0,5233.9",
    ])
    monkeypatch.setattr("tradingagents.dataflows.china_specialty_em.get_a_share_dragon_tiger_em",
                        lambda ticker, trade_date: text)
    result, _ = run([{"capability_id": "longhubang", "query": "", "gap_reason": "需核实上榜"}],
                    role="market_context")
    assert result.executed == ("longhubang",)
    assert len(result.admitted.observations) == 1
    observed = result.admitted.observations[0].source.content.text
    assert "净买入=32994.8万元" in observed and "深股通专用" not in observed
    assert "market_record_not_motive" in result.admitted.observations[0].source.limitations

    empty = "\n".join(["# China A-share dragon-tiger records for 300308.SZ", "# Source: eastmoney", "",
                       "# Total records: 0", "# Coverage: complete (0 matching records)", "", ""])
    monkeypatch.setattr("tradingagents.dataflows.china_specialty_em.get_a_share_dragon_tiger_em",
                        lambda ticker, trade_date: empty)
    again, _ = run([{"capability_id": "longhubang", "query": "", "gap_reason": "另一个缺口"}],
                   role="market_context")
    assert again.executed == ("longhubang",)
    assert again.admitted.observations == ()
    assert "capability_empty:longhubang" in again.gaps


def test_holder_change_admits_disclosures_and_empty_window_is_not_a_failure(monkeypatch):
    text = "\n".join([
        "# China A-share insider trades for 002130.SZ", "# Source: eastmoney", "",
        "CHANGE_NUM,NOTICE_DATE,HOLDER_NAME,DIRECTION,AFTER_CHANGE_RATE,CHANGE_NUM_SYMBOL,END_DATE,TRADE_AVERAGE_PRICE",
        "20.0,2026-06-12 00:00:00,某私募基金,增持,0.0142,20.0,2026-06-10 00:00:00,19.35",
        "20.0,2026-06-12 00:00:00,某私募基金,减持,0.0142,-20.0,2026-06-10 00:00:00,19.35",
    ])
    monkeypatch.setattr("tradingagents.dataflows.china_capital_flow.get_a_share_insider_trades",
                        lambda ticker, start_date=None, end_date=None: text)
    result, _ = run([{"capability_id": "holder_change", "query": "", "gap_reason": "需核实增减持"}],
                    role="event_context")
    assert result.executed == ("holder_change",)
    assert len(result.admitted.observations) == 2
    assert "disclosure_record_not_motive" in result.admitted.observations[0].source.limitations

    from tradingagents.dataflows.china_capabilities import AshareCapabilityUnavailableError

    def no_rows(ticker, start_date=None, end_date=None):
        raise AshareCapabilityUnavailableError("date_window", "eastmoney", "no rows in requested date window")

    monkeypatch.setattr("tradingagents.dataflows.china_capital_flow.get_a_share_insider_trades", no_rows)
    empty, _ = run([{"capability_id": "holder_change", "query": "", "gap_reason": "不同缺口"}],
                   role="event_context")
    assert empty.executed == ("holder_change",)
    assert empty.admitted.observations == ()
    assert "capability_empty:holder_change" in empty.gaps
