"""Official document qualification and operating-table failure boundaries."""

import copy
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.test_native_multisource import PROFILE, statement
from tradingagents.dataflows.disclosure_documents import (
    BODY_SOURCE,
    MAX_PDF_BYTES,
    OPERATING_SOURCE,
    operating_rows,
    parse_document,
    pdf_url,
    report_period,
    select_documents,
)
from tradingagents.dataflows.native_disclosures import DisclosureSources
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.research.evidence_freeze import CAP_FUNDAMENTALS, CapabilityStatus
from tradingagents.research.native_policy import fact_views, global_coverage
from tradingagents.research.native_record import build_native_record

ROW = {
    "Title": "2026年半年度报告",
    "Published": "2026-08-25",
    "Announcement ID": "123",
    "PDF URL": "finalpage/2026-08-25/123.PDF",
}
PAGES = [
    {
        "page": 2,
        "text": "营业收入构成\n单位：元\n本报告期 上年同期 同比增减\n营业收入合计 100.00 100% 80.00 100% 25.00%\n分产品\n通信线缆 60.00 60% 40.00 50% 50.00%\n电子材料 40.00 40% 40.00 50% 0.00%\n占公司营业收入或营业利润10%以上的行业、产品或地区情况\n单位：元\n营业收入 营业成本 毛利率 营业收入比上年同期增减 营业成本比上年同期增减 毛利率比上年同期增减\n分产品",
    },
    {
        "page": 3,
        "text": "通信线缆 60.00 45.00 25.00% 50.00% 50.00% 0.00%\n新能源汽车 40.00 20.00 50.00% 0.00% 0.00% 0.00%\n产品\n公司主营业务数据统计口径\n四、非主营业务分析",
    },
]


def document(row=ROW):
    return {
        "document_id": row["Announcement ID"],
        "title": row["Title"],
        "published": row["Published"],
        "ts_code": "002130.SZ",
        "url": pdf_url(row),
        "pdf_sha256": "a" * 64,
        "page_count": 3,
        "parser_version": "official-pdf-v1",
        "report_period": "2026-06-30",
        "excerpts": [
            {"page": 2, "text": "公司披露通信线缆业务增长；此处为已保存原文。", "truncated": False}
        ],
        "operating_rows": operating_rows(PAGES, "2026-06-30")[0],
        "gaps": [],
        "body_coverage": "selected_excerpts_only",
    }


def test_cross_page_table_preserves_units_period_names_and_original_rows():
    rows, gaps = operating_rows(PAGES, "2026-06-30")
    assert len(rows) == 4 and not gaps
    assert rows[-1]["name"] == "新能源汽车产品"
    assert rows[-1]["page"] == 3 and rows[-1]["unit"] == "CNY"
    assert rows[0]["prior_revenue"] == "40.00"
    assert rows[-1]["gross_margin_percent"] == "50.00"
    assert "40.00" in rows[-1]["raw_row"]


@pytest.mark.parametrize(
    "replacement",
    [
        "通信线缆 60.00 44.00 25.00% 50.00% 50.00% 0.00%",
        "通信线缆 60.00 45.00 25.00% 50.00% 50.00%",
    ],
)
def test_bad_margin_or_column_count_keeps_other_table(replacement):
    pages = copy.deepcopy(PAGES)
    pages[1]["text"] = pages[1]["text"].replace(
        "通信线缆 60.00 45.00 25.00% 50.00% 50.00% 0.00%", replacement
    )
    rows, gaps = operating_rows(pages, "2026-06-30")
    assert len(rows) == 2 and all(row["table"] == "composition" for row in rows)
    assert "operating_table_unqualified:profitability" in gaps


@pytest.mark.parametrize("unit", ["美元", "亿元", ""])
def test_missing_or_unadmitted_unit_does_not_produce_numbers(unit):
    pages = [{**p, "text": p["text"].replace("单位：元", "单位：" + unit)} for p in PAGES]
    rows, gaps = operating_rows(pages, "2026-06-30")
    assert not rows and gaps


def test_incomplete_classification_does_not_invent_residual():
    pages = copy.deepcopy(PAGES)
    pages[0]["text"] = pages[0]["text"].replace("电子材料 40.00 40% 40.00 50% 0.00%\n", "")
    rows, gaps = operating_rows(pages, "2026-06-30")
    assert "operating_classification_total_not_covered:product" in gaps
    assert not any(row["name"] == "其他" for row in rows)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/finalpage/2026-08-25/123.PDF",
        "https://static.cninfo.com.cn@localhost/finalpage/2026-08-25/123.PDF",
        "finalpage/2026-08-25/124.PDF",
        "finalpage/2026-08-25/123.PDF?token=x",
        "finalpage/2026-08-25/../123.PDF",
    ],
)
def test_attachment_allowlist_and_identifier(url):
    with pytest.raises(NativeSourceUnavailable):
        pdf_url({**ROW, "PDF URL": url})


def test_selection_is_bounded_stable_and_excludes_summary_and_revisions():
    rows = [
        ROW,
        {**ROW, "Title": "2026年半年度报告摘要", "Announcement ID": "124"},
        *[
            {
                **ROW,
                "Title": "关于投资项目的公告",
                "Announcement ID": str(i),
                "Published": "2026-09-18",
            }
            for i in range(10)
        ],
    ]
    selected = select_documents(rows, "2026-10-03")
    assert selected[0] == ROW and len(selected) == 4
    assert select_documents(list(reversed(rows)), "2026-10-03") == selected
    assert report_period("2026年半年度报告（修订版）") is None


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_documents_feed_all_modes_without_becoming_c1_statement_family(monkeypatch, mode):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    calls = []
    request = SimpleNamespace(
        ticker="002130.SZ",
        analysis_date=today,
        catalyst_policy=__import__(
            "tradingagents.research.catalyst_evidence_policy",
            fromlist=["catalyst_evidence_policy_v1"],
        ).catalyst_evidence_policy_v1(),
        effective_config={
            "evidence_source_vendors": {
                "identity": ["sina"],
                "financial": ["sina"],
                "calendar": [],
                "price": [],
            }
        },
    )
    sources = DisclosureSources(
        request,
        "docs-run",
        SimpleNamespace(ensure_active=lambda: None),
        lambda key, op: (calls.append(key), op())[1],
    )
    monkeypatch.setattr(
        sources,
        "_get",
        lambda url, **kwargs: (
            PROFILE
            if "CorpInfo" in url
            else statement(
                {"lrb": "income", "fzb": "balancesheet", "llb": "cashflow"}[
                    kwargs["params"]["source"]
                ]
            )
        ),
    )

    def events(inputs):
        sources.evidence(inputs, "event_coverage", "cninfo", ROW, published=ROW["Published"])
        sources._cap(inputs, "event_coverage", ("cninfo.announcements",))

    monkeypatch.setattr(sources, "_events", events)
    monkeypatch.setattr(sources, "_document_get", lambda *args: document())
    draft, context = sources.collect()
    record = build_native_record(draft, context, mode=mode, include_coverage=True)
    names = {e.source_name for e in record.evidence if e.availability == "available"}
    assert {BODY_SOURCE, OPERATING_SOURCE, "sina.financial_statements"} <= names
    views = fact_views(record)
    assert any("通信线缆" in f.statement for f in views["operating_quality"])
    assert all("公司经营披露" not in f.statement for f in views["event_context"])
    assert (
        global_coverage(record)["fundamentals"]["status"] == "partial"
    )  # fixture has one of eight periods
    assert global_coverage(record)["announcement_bodies"]["status"] == "partial"
    assert all(
        e.content and len(e.content.text) <= 4000
        for e in record.evidence
        if e.source_name in {BODY_SOURCE, OPERATING_SOURCE}
    )
    from tradingagents.agents.schemas._verification_plan import FinancialOperandV1
    from tradingagents.research.verification_tools import _financial_operand, _Unavailable

    op = next(e for e in record.evidence if e.source_name == OPERATING_SOURCE)
    with pytest.raises(_Unavailable):
        _financial_operand(
            record,
            FinancialOperandV1(
                evidence_id=op.evidence_id,
                table="income",
                field="revenue",
                report_period="2026-06-30",
            ),
        )
    assert len([call for call in calls if ".document." in call]) == 1


def fake_pdf(monkeypatch, texts, *, encrypted=False):
    import pypdf

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self, **kwargs):
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *a, **k: SimpleNamespace(is_encrypted=encrypted, pages=[Page(t) for t in texts]),
    )


def test_wrong_security_future_period_and_blank_pdf(monkeypatch):
    fake_pdf(monkeypatch, ["证券代码：000001\n2026年半年度报告\n" + "原文" * 30])
    with pytest.raises(NativeSourceUnavailable, match="security"):
        parse_document(b"%PDF-abc", ROW, ts_code="002130.SZ", cutoff="2026-10-03")
    fake_pdf(monkeypatch, ["证券代码：002130\n2026年半年度报告\n" + "原文" * 30])
    with pytest.raises(NativeSourceUnavailable, match="publication"):
        parse_document(b"%PDF-abc", ROW, ts_code="002130.SZ", cutoff="2026-07-01")
    fake_pdf(monkeypatch, [""])
    with pytest.raises(NativeSourceUnavailable):
        parse_document(b"%PDF-abc", ROW, ts_code="002130.SZ", cutoff="2026-10-03")


def test_document_limits_encryption_invalid_pdf_and_cancel_propagate(monkeypatch):
    with pytest.raises(NativeSourceUnavailable, match="byte_limit"):
        parse_document(b"x" * (MAX_PDF_BYTES + 1), ROW, ts_code="002130.SZ", cutoff="2026-10-03")
    with pytest.raises(NativeSourceUnavailable, match="not_pdf"):
        parse_document(b"<html>", ROW, ts_code="002130.SZ", cutoff="2026-10-03")
    fake_pdf(monkeypatch, ["x"], encrypted=True)
    with pytest.raises(NativeSourceUnavailable, match="encrypted"):
        parse_document(b"%PDF-x", ROW, ts_code="002130.SZ", cutoff="2026-10-03")
    fake_pdf(monkeypatch, ["x"] * 501)
    with pytest.raises(NativeSourceUnavailable, match="page_limit"):
        parse_document(b"%PDF-x", ROW, ts_code="002130.SZ", cutoff="2026-10-03")
    fake_pdf(monkeypatch, ["x"])
    for error in (TimeoutError("deadline"), AnalysisCancelled("cancelled")):

        def cancel(error=error):
            raise error

        with pytest.raises(type(error)):
            parse_document(
                b"%PDF-x", ROW, ts_code="002130.SZ", cutoff="2026-10-03", ensure_active=cancel
            )


def test_supplement_budget_stop_keeps_prior_financial_evidence(monkeypatch):
    from tradingagents.execution.budget import BudgetBucket, BudgetLedger
    from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
    from tradingagents.research.evidence_freeze import FreezeInputs

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    request = SimpleNamespace(ticker="002130.SZ", analysis_date=today, effective_config={})
    ledger = BudgetLedger("stop", limits={BudgetBucket.DATA_CAPABILITY_CALLS: 0})

    def fetch(key, op):
        ledger.reserve_or_raise(
            BudgetBucket.DATA_CAPABILITY_CALLS, stage="docs", logical_call_id=key
        )
        pytest.fail("zero budget dispatched")

    sources = DisclosureSources(request, "stop", None, fetch)
    sources.context["catalogue"] = ROW
    inputs = FreezeInputs("stop", "002130.SZ", today, catalyst_evidence_policy_v1())
    sources.evidence(inputs, CAP_FUNDAMENTALS, "sina.financial_statements", {"kept": True})
    before = copy.deepcopy(inputs.evidence)
    sources._documents(inputs, "002130.SZ", {"ts_code": "002130.SZ"})
    assert inputs.evidence == before
    assert all("document_budget_exhausted" in cap.degradations for cap in inputs.capabilities)


def test_malformed_missing_cell_does_not_silently_qualify_remaining_rows():
    pages = copy.deepcopy(PAGES)
    pages[1]["text"] = pages[1]["text"].replace("60.00 45.00 25.00%", "60.00 — 25.00%")
    rows, gaps = operating_rows(pages, "2026-06-30")
    assert all(row["table"] == "composition" for row in rows)
    assert "operating_table_unqualified:profitability" in gaps


def test_legacy_unknown_labels_and_global_scope_are_explicit():
    from tradingagents.research.coverage_labels import limitation_label

    assert "旧记录未保存专项范围" in limitation_label("specialist_unknown:缺少行情")
    assert "事件专项待核查" in limitation_label("specialist_unknown:event_context:本视图未见财务")
    assert (
        limitation_label("global_coverage:fundamentals:qualified")
        == "全局覆盖 · 财务三表：合格资料可用"
    )


def test_saved_pages_of_one_document_share_one_public_family(monkeypatch):
    from tests.test_native_record import fixture, source

    draft, context = fixture()
    from tradingagents.research.evidence_freeze import FrozenCapability

    payload = document()
    base = {
        k: payload[k]
        for k in (
            "document_id",
            "title",
            "published",
            "ts_code",
            "url",
            "pdf_sha256",
            "page_count",
            "parser_version",
            "report_period",
            "body_coverage",
        )
    }
    items = []
    for index in (1, 2):
        body = {
            **base,
            "ts_code": "600519.SH",
            "page": index,
            "text": "公司保存原文",
            "truncated": False,
        }
        item = source(
            "announcement_bodies", BODY_SOURCE, body, published="2026-08-25T00:00:00+08:00"
        )
        items.append(item)
        context[item["evidence_id"]] = body
    draft = draft.model_copy(
        update={
            "evidence": (*draft.evidence, *items),
            "capabilities": (
                *draft.capabilities,
                FrozenCapability(
                    capability="announcement_bodies",
                    status=CapabilityStatus.PARTIAL,
                    reason="selected excerpts",
                    degradations=("document_selected_excerpts_only",),
                ),
            ),
        }
    )
    record = build_native_record(draft, context, mode="company_research")
    bodies = [e for e in record.evidence if e.source_name == BODY_SOURCE]
    assert len(bodies) == 2 and all(e.availability == "available" for e in bodies)
    assert len({e.source_family_id for e in bodies}) == 1


def test_stream_limit_closes_response_and_does_not_dispatch_parser(monkeypatch):
    class Response:
        status_code = 200
        closed = False

        def iter_content(self, size):
            yield b"x" * (MAX_PDF_BYTES + 1)

        def close(self):
            self.closed = True

    response = Response()
    session = SimpleNamespace(get=lambda *a, **k: response, ensure_active=lambda: None)
    sources = DisclosureSources(
        SimpleNamespace(effective_config={}), "stream-run", session, lambda *a: None
    )
    with pytest.raises(NativeSourceUnavailable, match="byte_limit"):
        sources._document_get(ROW, "002130.SZ", "2026-10-03", "沃尔核材")
    assert response.closed


def test_corrupt_pdf_has_safe_typed_code():
    with pytest.raises(NativeSourceUnavailable, match="parse_failed"):
        parse_document(b"%PDF-broken", ROW, ts_code="002130.SZ", cutoff="2026-10-03")


def test_event_body_failure_does_not_degrade_available_operating_table(monkeypatch):
    from tradingagents.research.catalyst_evidence_policy import catalyst_evidence_policy_v1
    from tradingagents.research.evidence_freeze import FreezeInputs

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    req = SimpleNamespace(ticker="002130.SZ", analysis_date=today, effective_config={})
    sources = DisclosureSources(req, "isolation", None, lambda key, op: op())
    event = {
        **ROW,
        "Title": "关于投资项目的公告",
        "Published": today,
        "Announcement ID": "456",
        "PDF URL": f"finalpage/{today}/456.PDF",
    }
    sources.context = {"report": ROW, "event": event}

    def retrieve(row, *args):
        if row["Announcement ID"] == "456":
            raise NativeSourceUnavailable("document_http_unavailable")
        return document()

    monkeypatch.setattr(sources, "_document_get", retrieve)
    inputs = FreezeInputs("isolation", "002130.SZ", today, catalyst_evidence_policy_v1())
    sources._documents(inputs, "002130.SZ", {"name": "沃尔核材"})
    operating = next(cap for cap in inputs.capabilities if cap.capability == "operating_detail")
    assert operating.status is CapabilityStatus.QUALIFIED
    assert "document_selected_unavailable" not in operating.degradations
    bodies = next(cap for cap in inputs.capabilities if cap.capability == "announcement_bodies")
    assert "document_selected_unavailable" in bodies.degradations
    assert bodies.detail["selected_unavailable_ids"] == ["456"]
    assert not bodies.detail["unselected_ids"]
