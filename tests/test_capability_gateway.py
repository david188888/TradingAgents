"""Capability gateway: role scope, budgets, typed gaps and host-owned ticker."""

from datetime import date

from tests.test_search_budget import Journal
from tradingagents.agents.schemas._insight import CapabilityRequest
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.capability_gateway import execute_capability_requests


def run(requests, *, role="operating_quality", ticker="002130.SZ", journal=None, **kwargs):
    journal = journal or Journal()
    return execute_capability_requests(
        requests, role=role, ticker=ticker, cutoff=date(2026, 11, 5),
        ledger=journal.ledger, ensure_active=lambda: None, **kwargs), journal


def test_rejects_invisible_news_path_and_empty_disclosure_query():
    result, _ = run([
        {"capability_id": "news_search", "query": "客户", "gap_reason": "缺新闻"},
        {"capability_id": "disclosure_search", "query": "", "gap_reason": "缺公告"},
        {"capability_id": "longhubang", "query": "", "gap_reason": "未实现"},
        {"capability_id": "shareholder_count", "query": "", "gap_reason": " "},
    ], role="market_context")
    assert result.executed == ()
    assert "capability_use_search_path:news_search" in result.rejected
    assert "capability_query_required:disclosure_search" in result.rejected
    assert "capability_not_visible:longhubang" in result.rejected
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
