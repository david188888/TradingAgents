"""Offline real contracts, durable kernel, mocked SDK and report publication."""

import json
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tests.test_native_record import fixture
from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.dataflows.company_profile import (
    PROFILE_CAPABILITY,
    PROFILE_SOURCE,
    qualify_company_profile,
)
from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
from tradingagents.execution.models import AnalysisCancelled
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.research.evidence_freeze import CapabilityStatus, FrozenCapability
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_versions import REPORT_DELIVERY_POLICY, UNIFIED_WORKFLOW_VERSION
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.reports import build_markdown_from_native_record


def profile_html(code="600519", exchange="上海证券交易所", description="白酒生产和销售"):
    return (f'<title>贵州茅台({code})公司资料_新浪财经_新浪网</title><table id="comInfo1">'
            f'<tr><td>上市市场：</td><td>{exchange}</td></tr><tr><td>上市日期：</td><td>2001-08-27</td></tr>'
            f'<tr><td>主营业务：</td><td>{description}</td></tr><tr><td>经营范围：</td><td>依法核准业务</td></tr></table>')


def test_explicit_profile_fields_do_not_infer_business_from_scope():
    value = qualify_company_profile(profile_html(), ts_code="600519.SH", cutoff="2026-09-30")
    assert value["fields"] == {"main_business": "白酒生产和销售", "business_scope": "依法核准业务"}
    assert "introduction" not in value["fields"] and "industry" not in value["fields"]
    for html in (profile_html(code="600418"), profile_html(exchange="深圳证券交易所")):
        with pytest.raises(NativeSourceUnavailable, match="identity"):
            qualify_company_profile(html, ts_code="600519.SH", cutoff="2026-09-30")


def test_disclosure_profile_extracts_only_explicit_company_description():
    from tradingagents.research.company_basics import disclosed_profile_fields
    text = "（二）公司主营业务情况\n公司是一家从事整车研发、制造和销售的综合型汽车集团，覆盖乘用车和商用车。\n报告期内销量增长。\n本公司属汽车整车制造行业。"
    fields = disclosed_profile_fields(text)
    assert fields["main_business"] == text.splitlines()[1]
    assert fields["industry"] == "汽车整车制造行业"
    assert disclosed_profile_fields("行业内主营业务多为汽车制造；\n主营业务分析\n行业销量增长。") == {}


def test_basic_pack_keeps_latest_financials_without_pdf_or_profile():
    record = build_native_record(*fixture(), mode="company_research", include_basics=True)
    assert record.company_basics.introduction == ()
    assert len(record.company_basics.fundamentals) == 5
    assert {field.report_period.isoformat() for field in record.company_basics.fundamentals} == {"2026-06-30"}
    assert record.hypotheses == () and record.assessment is None
    assert any("主营业务" in gap for gap in record.company_basics.gaps)
    assert all(record.claims[next(i for i,c in enumerate(record.claims) if c.claim_id == field.claim_id)].kind == "fact"
               for field in record.company_basics.fundamentals)


def test_qualified_public_intro_has_real_source_binding_and_is_read_only():
    payload = qualify_company_profile(profile_html(), ts_code="600519.SH", cutoff="2026-09-30")
    draft, context = fixture(extra=((PROFILE_CAPABILITY, PROFILE_SOURCE, payload, None),))
    draft = draft.model_copy(update={"capabilities": (*draft.capabilities, FrozenCapability(
        capability=PROFILE_CAPABILITY, required=False, status=CapabilityStatus.QUALIFIED, reason="offline labelled fields"))})
    record = build_native_record(draft, context, mode="company_research", include_basics=True)
    field = record.company_basics.introduction[0]
    fact = next(c for c in record.claims if c.claim_id == field.claim_id)
    source = next(e for e in record.evidence if e.evidence_id in fact.evidence_ids)
    assert "白酒生产和销售" in fact.statement and source.source_name == PROFILE_SOURCE
    assert source.content.content_sha256 and source.usable_as_of
    from tradingagents.research.company_basics import foundation_context
    from tradingagents.research.native_policy import fact_views
    assert all(fact not in facts for facts in fact_views(record).values())
    assert fact.model_dump(mode="json") in foundation_context(record)["facts"]


class FailedSynthesis(UnifiedCaller):
    def __call__(self, stage, context):
        if stage == "synthesis":
            self.calls.append((stage, context))
            raise ValueError("offline deliberately unusable synthesis")
        return super().__call__(stage, context)


@pytest.mark.parametrize("disposition", ["maintained", "revised", "withdrawn"])
def test_failed_synthesis_delivers_basics_and_effective_findings_without_rating(tmp_path, disposition):
    journal, seed = setup(tmp_path, delivery=True)
    result = run(journal, seed, FailedSynthesis(disposition=disposition))
    assert result.assessment.investment_stance is None
    assert result.assessment.report_status == "specialist_summary"
    assert result.company_basics.fundamentals
    assert result.assessment.dimensions[0].claim_ids
    assert "综合阶段未完成" in result.assessment.judgement
    if disposition != "maintained":
        assert result.hypotheses[0].claim_id not in result.assessment.key_claim_ids
        assert all(result.hypotheses[0].claim_id not in d.claim_ids for d in result.assessment.dimensions)
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert run(restored, seed, lambda *_: pytest.fail("replay must not call models")) == result
    publish_native_record(journal.observer, record=result, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    from tradingagents.web.reader_process_projection import (
        project_reader_agent,
        project_reader_process,
    )
    from tradingagents.web.research_record_projection import project_research_record
    assert project_research_record(journal.observer.store, seed.run_id)["state"] == "ready"
    process = project_reader_process(journal.observer.store, seed.run_id)
    assert process["availability"] == "ready", process
    assert process["primary_selection"] == "code"
    assert all({"claim_id":field.claim_id,"role_key":"evidence"} in process["claim_origins"] for field in result.company_basics.fundamentals)
    assert project_reader_agent(journal.observer.store, seed.run_id, "synthesis")["availability"] == "not_recorded"
    markdown = build_markdown_from_native_record(result, workflow_version=UNIFIED_WORKFLOW_VERSION)
    assert "公司基础资料" in markdown and "综合阶段未完成" in markdown
    assert "## 投资吸引力判断\n\n证据不足" not in markdown and "综合裁决：" not in markdown
    assert "代码保留的回应状态：" in markdown


def test_missing_range_or_operating_dimension_does_not_force_blanket_verdict(tmp_path):
    journal, seed = setup(tmp_path, delivery=True)
    seed = ResearchRecordV1.model_validate({**seed.model_dump(mode="json"), "valuation": None})
    result = run(journal, seed, UnifiedCaller(challenge=False))
    assert result.assessment.investment_stance == "unfavorable"
    assert result.assessment.report_status == "synthesized"
    payload = result.model_dump(mode="json")
    payload["assessment"]["dimensions"][0].update(status="unresolved", claim_ids=[], limitations=["specific_detail_missing"])
    assert ResearchRecordV1.model_validate(payload).assessment.investment_stance == "unfavorable"
    payload["assessment"]["investment_stance"] = "favorable"
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


def test_copied_synthesis_bindings_are_host_owned_but_fake_facts_reject(tmp_path, monkeypatch):
    from tests.test_native_model import main
    from tradingagents.execution import native_model as adapter
    journal, seed = setup(tmp_path / "context", delivery=True)
    proposals = UnifiedCaller(disposition="revised")
    run(journal, seed, proposals)
    context = next(c for stage, c in proposals.calls if stage == "synthesis")
    candidate = proposals("synthesis", context)
    hypothesis = context["record"]["hypotheses"][0]
    candidate["change_conditions"] = [{"hypothesis_id": hypothesis["hypothesis_id"], "invalidation_index": 0, "text": "paraphrased"}]
    candidate["adjudications"][0].update(response_id="wrong.reply", disposition="maintained")
    journal, _ = setup(tmp_path / "sdk", delivery=True)
    main(journal, "synthesis")
    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: pytest.fail("offline parser must not create SDK"))
    model = adapter.NativeModelCaller(effective_config={"llm_provider":"chatgpt","quick_think_llm":"gpt-6-luna","deep_think_llm":"gpt-6-luna"},
        run_id=journal.ledger.run_id, ledger=journal.ledger, cancelled=lambda:False, deadline=lambda:time.monotonic()+30)
    result = model._parse("synthesis", SimpleNamespace(content=json.dumps(candidate)), context)
    assert result["change_conditions"][0]["text"] == hypothesis["invalidation_conditions"][0]
    assert result["adjudications"][0]["disposition"] == "revised"
    assert result["adjudications"][0]["response_id"] == context["record"]["dialogue"]["responses"][0]["response_id"]
    candidate["opposing_arguments"][0]["claim_ids"] = ["fabricated.fact"]
    with pytest.raises(adapter.NativeModelUnavailable):
        model._parse("synthesis", SimpleNamespace(content=json.dumps(candidate)), context, phase="repair")


def test_legacy_hash_and_null_rating_boundary(tmp_path):
    journal, seed = setup(tmp_path)
    result = run(journal, seed, UnifiedCaller())
    raw = result.model_dump_json()
    assert "report_status" not in raw and "company_basics" not in raw
    assert ResearchRecordV1.model_validate_json(raw).model_dump_json() == raw
    payload = result.model_dump(mode="json")
    payload["assessment"]["investment_stance"] = None
    with pytest.raises(ValidationError, match="legacy"):
        ResearchRecordV1.model_validate(payload)


def test_cancellation_cannot_be_delivered_as_summary(tmp_path):
    journal, seed = setup(tmp_path, delivery=True)
    from tradingagents.graph.native_research import run_native_research
    with pytest.raises(AnalysisCancelled):
        run_native_research(seed, caller=lambda *_:pytest.fail("cancelled"), ledger=journal.ledger,
            minimum=True, valuation=True, scoped=True, independent=True, unified=True, cancelled=lambda:True)


def test_no_usable_specialist_still_delivers_only_basics(tmp_path):
    journal, seed = setup(tmp_path, delivery=True)
    result = run(journal, seed, lambda *_:None)
    assert result.assessment.report_status == "basic_report"
    assert result.assessment.investment_stance is None
    assert result.company_basics.fundamentals and result.assessment.dimensions[0].claim_ids


def test_profile_failure_stays_local_to_optional_capability(monkeypatch):
    from tradingagents.dataflows.minimum_sources import MinimumEvidenceSources
    from tradingagents.dataflows.native_sources import NativeSources
    collector = object.__new__(MinimumEvidenceSources)
    collector.request = SimpleNamespace(report_delivery_policy=REPORT_DELIVERY_POLICY, effective_config={})
    collector.attempts = {}
    monkeypatch.setattr(NativeSources, "_identity", lambda *_:{"ts_code":"600418.SH","name":"江淮汽车"})
    collector._attempt = lambda *_:None
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    inputs = SimpleNamespace(ticker="600418", cutoff=today, capabilities=[])
    identity = collector._identity(inputs, "600418.SH")
    assert identity["name"] == "江淮汽车"
    assert inputs.capabilities[-1].required is False
    assert inputs.capabilities[-1].status == CapabilityStatus.UNAVAILABLE
