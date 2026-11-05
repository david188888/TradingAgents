"""Capability supplements: qualification, role isolation and durable replay."""

from datetime import date

from tests.test_insight_protocol import catalog
from tests.test_search_budget import Journal
from tradingagents.agents.schemas._evidence import RecordClaimV1
from tradingagents.agents.schemas._evidence_record import EvidenceRecord, make_evidence_snapshot
from tradingagents.execution.insight_capability import collect_capability_supplement
from tradingagents.research.native_policy import fact_views

SHAREHOLDER_REPORT = "\n".join([
    "# China A-share shareholder counts for 002130.SZ", "# Source: eastmoney", "",
    "Date,Holder Num,Change Num,Change %,Avg Hold Num", "2026-09-30,12000,-500,-4.0,8000",
])


def base_record():
    journal = Journal()
    source = catalog().sources[0]
    record = EvidenceRecord(run_id=journal.ledger.run_id, ticker="002130.SZ", analysis_date=date(2026, 11, 5),
        evidence=(source,), snapshots=(make_evidence_snapshot((source,)),),
        claims=(RecordClaimV1(claim_id="fact-1", kind="fact", statement="已保存原始资料。",
            evidence_ids=(source.evidence_id,)),))
    return journal, record


def capability_fact(record):
    return next(claim for claim in record.claims if claim.evidence_ids[0].startswith("capability."))


def test_shareholder_supplement_is_admitted_for_the_requesting_role_only(monkeypatch):
    monkeypatch.setattr("tradingagents.dataflows.china_specialty_em.get_a_share_shareholder_counts_em",
                        lambda ticker: SHAREHOLDER_REPORT)
    journal, before = base_record()
    updated, result = collect_capability_supplement(before, {"operating_quality": (
        {"capability_id": "shareholder_count", "query": "", "gap_reason": "缺近一年股东户数"},)},
        ledger=journal.ledger, ensure_active=lambda: None, round_id=1)
    fact = capability_fact(updated)
    assert fact.limitations[:2] == ("capability_supplement", "native_dimension:operating_quality")
    assert updated.evidence[-1].source_family_id == "capability:shareholder_count"
    assert result["affected_roles"] == ["operating_quality"]
    views = fact_views(updated)
    assert fact in views["operating_quality"]
    assert fact not in views["event_context"] and fact not in views["market_context"]
    other_roles = {entry.fact_id for role in ("event_context", "market_context")
                   for entry in result["catalogs"][role].evidence}
    assert fact.claim_id not in other_roles


def test_market_role_disclosure_supplement_stays_in_its_own_view(monkeypatch):
    records = [{"Published": "2026-10-01", "Title": "限售股解禁提示性公告", "Type": "提示",
                "Announcement ID": "1", "Detail URL": "https://www.cninfo.com.cn/a"}]

    def fake(ticker, start, end, page_size=30, max_pages=2, *, searchkey="", session=None, records_sink=None):
        records_sink(records)
        return "ok"

    monkeypatch.setattr("tradingagents.dataflows.china_specialty.get_a_share_cninfo_announcements", fake)
    journal, before = base_record()
    updated, result = collect_capability_supplement(before, {"market_context": (
        {"capability_id": "disclosure_search", "query": "解禁", "gap_reason": "需核实解禁公告"},)},
        ledger=journal.ledger, ensure_active=lambda: None, round_id=1)
    fact = capability_fact(updated)
    assert result["affected_roles"] == ["market_context"]
    views = fact_views(updated)
    assert fact in views["market_context"]
    assert fact not in views["operating_quality"] and fact not in views["event_context"]


def test_round_replay_returns_the_saved_increment_without_refetching(monkeypatch):
    fetched = []

    def fake(ticker):
        fetched.append(ticker)
        return SHAREHOLDER_REPORT

    monkeypatch.setattr("tradingagents.dataflows.china_specialty_em.get_a_share_shareholder_counts_em", fake)
    journal, before = base_record()
    requests = {"operating_quality": (
        {"capability_id": "shareholder_count", "query": "", "gap_reason": "缺股东户数"},)}
    first = collect_capability_supplement(before, requests, ledger=journal.ledger,
        ensure_active=lambda: None, round_id=1)
    second = collect_capability_supplement(before, requests, ledger=journal.ledger,
        ensure_active=lambda: None, round_id=1)
    assert second == first
    assert len(fetched) == 1
