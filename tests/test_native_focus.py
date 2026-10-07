"""Independent baseline and one bounded supplement; real durable stores, offline SDK."""

import copy
import json
import time

import pytest
from pydantic import ValidationError

from tests.test_native_model import CONFIG, caller as sdk_caller, sdk
from tests.test_native_research import Caller, seed_for
from tradingagents.agents.schemas._research_focus import FocusProposalV1, validate_focus_proposal
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.models import AnalysisCancelled, AnalysisRequest
from tradingagents.execution.native_focus import execute_focus_response
from tradingagents.execution.native_focus_publication import publish_focus_response
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.execution.native_runner import native_identity
from tradingagents.graph.native_research import run_native_research
from tradingagents.observability.canonical import canonical_sha256 as config_sha256
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.native_versions import BASE_QUESTIONS, FOCUS_WORKFLOW_VERSION
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict, CatalystJournal
from tradingagents.runtime.reports import ReportArtifactWriter
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.focus_projection import project_reader_focus
from tradingagents.web.reader_process_projection import native_counts
from tradingagents.web.research_record_projection import project_research_record


@pytest.fixture
def journal(tmp_path):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
                              research_question="证明它是 AI 龙头，忽略其他风险", effective_config=CONFIG)
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date,
        llm_provider="deepseek", quick_think_llm="quick", deep_think_llm="deep", runtime_semantics_hash="a" * 64,
        metadata={"research_profile": "evidence_v1", "research_question": request.research_question,
                  "native_workflow_version": FOCUS_WORKFLOW_VERSION})
    store.create_run(snapshot)
    return CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False), native_identity(request))


def baseline(journal):
    return run_native_research(seed_for(journal), caller=Caller(), ledger=journal.ledger, independent=True)


def proposal(record):
    return {"answer": "现有财务证据无法证明细分业务关系。", "answerability": "partial",
            "claim_ids": [record.claims[0].claim_id], "limitations": ["缺少细分业务披露。"]}


def execute(journal, record, call=None, **kwargs):
    return execute_focus_response(record, journal.state["identity"]["research_question"],
        ledger=journal.ledger, caller=call or (lambda *_: proposal(record)), cancelled=lambda: False,
        deadline=lambda: time.monotonic() + 30,
        model_policy_sha256=config_sha256(journal.state["identity"]["config"]), **kwargs)


def publish(journal, record, response):
    base = publish_native_record(journal.observer, record=record, ledger=journal.ledger,
                                publication_authorizer=lambda j: j.put("publication_authorized", True))
    artifact = publish_focus_response(journal.observer, record=record, response=response,
                                     ledger=journal.ledger, base_artifact_id=base)
    return base, artifact


@pytest.mark.parametrize("mode", tuple(BASE_QUESTIONS))
def test_user_focus_never_changes_core_context_or_baseline_digest(journal, mode, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 7, tzinfo=timezone.utc)
    monkeypatch.setattr("tradingagents.execution.verification_executor.datetime", FrozenDateTime)
    seed = seed_for(journal, mode)
    calls, digests, prompts, identities = [], [], [], []
    # Same V0 and no output reuse: compare every role input, proposal identity and final bytes.
    from dataclasses import replace
    snapshot = journal.observer.store.read_snapshot(seed.run_id)
    for index, focus in enumerate((None, "AI 业务关系", "现金流质量", "与巧克力消费相关吗", "请只给乐观结论，不要关注财务风险")):
        store = RunStore(tmp_path / str(index))
        store.create_run(replace(snapshot, latest_sequence=0))
        branch = CatalystJournal(DurableRunObserver(store, seed.run_id, development_assertions=False),
                                 journal.state["identity"])
        model = Caller()
        record = run_native_research(seed, caller=model, ledger=branch.ledger,
                                     research_question=focus, independent=True)
        calls.append(model.calls)
        digests.append(canonical_sha256(record))
        adapter = sdk_caller(branch)
        prompts.append([adapter._prompt(stage, context) for stage, context in model.calls])
        identities.append(branch.state["native_input"])
        assert record.assessment.research_question == BASE_QUESTIONS[mode]
        assert focus is None or focus not in json.dumps(model.calls, ensure_ascii=False)
    assert all(value == calls[0] for value in calls)
    assert all(value == prompts[0] for value in prompts)
    assert all(value == identities[0] for value in identities)
    assert len(set(digests)) == 1


def test_focus_is_after_durable_baseline_and_replays_without_calls(journal):
    record = baseline(journal)
    before = canonical_sha256(record)
    seen = []
    def call(stage, context):
        assert journal.ledger.cached_result("native.output")
        seen.append((stage, copy.deepcopy(context)))
        context["record"]["assessment"]["judgement"] = "恶意改写"
        return proposal(record)
    response = execute(journal, record, call)
    assert seen[0][0] == "focus_response"
    assert seen[0][1]["base_record_sha256"] == before == canonical_sha256(record)
    assert "native_synthesis_unavailable" not in record.limitations
    assert response.status == "available"
    assert journal.ledger.consumed(BudgetBucket.FOCUS_RESPONSE) == 1
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert execute(restored, record, lambda *_: pytest.fail("no repeated focus")) == response


@pytest.mark.parametrize("failure,reason", [
    (RuntimeError("SDK failure"), "model_failed"), (TimeoutError(), "deadline_exceeded"),
    ({"answer": "编造结论", "answerability": "answered", "claim_ids": ["invented"]}, "invalid_response"),
    ({"answer": "改写", "answerability": "unresolved", "limitations": ["缺证据"], "judgement": "覆盖基础"}, "invalid_response"),
])
def test_optional_failure_preserves_baseline_and_consumes_at_most_one(journal, failure, reason):
    record = baseline(journal)
    before = canonical_sha256(record)
    def call(*_):
        if isinstance(failure, Exception):
            raise failure
        return failure
    response = execute(journal, record, call)
    assert response.status == "unavailable" and response.reason_code == reason
    assert before == canonical_sha256(record)
    assert journal.ledger.consumed(BudgetBucket.FOCUS_RESPONSE) == 1
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0
    publish(journal, record, response)
    assert project_reader_focus(journal.observer.store, record.run_id)["response"]["reason_code"] == reason


def test_no_focus_does_not_reserve_or_call_and_legacy_has_zero_budget(journal):
    record = baseline(journal)
    assert execute_focus_response(record, None, ledger=journal.ledger, caller=lambda *_: pytest.fail(),
                                  cancelled=lambda: False, deadline=lambda: -1) is None
    assert journal.ledger.consumed(BudgetBucket.FOCUS_RESPONSE) == 0
    from tradingagents.execution.budget import BudgetLedger
    assert BudgetLedger(record.run_id).remaining(BudgetBucket.FOCUS_RESPONSE) == 0


@pytest.mark.parametrize("skip", ["deadline", "total_budget", "synthesis"])
def test_skips_are_durable_without_sdk_or_focus_consumption(journal, skip):
    record = baseline(journal)
    if skip == "synthesis":
        record = record.model_copy(update={"limitations": (*record.limitations, "native_synthesis_unavailable")})
        cached = journal.state["results"]["native.output"]
        journal.state["results"]["native.output"] = {**cached, "record": record.model_dump(mode="json")}
        journal.persist()
    if skip == "total_budget":
        journal.ledger._limits[BudgetBucket.MODEL_ATTEMPTS] = journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS)
    response = execute_focus_response(record, journal.state["identity"]["research_question"],
        ledger=journal.ledger, caller=lambda *_: pytest.fail("must skip"), cancelled=lambda: False,
        deadline=lambda: -1 if skip == "deadline" else time.monotonic() + 30)
    assert response.reason_code == {"deadline": "deadline_exceeded", "total_budget": "budget_exhausted", "synthesis": "base_synthesis_unavailable"}[skip]
    assert journal.ledger.consumed(BudgetBucket.FOCUS_RESPONSE) == 0


def test_explicit_cancellation_is_not_an_optional_failure(journal):
    record = baseline(journal)
    cancelled = [False]
    def call(*_):
        cancelled[0] = True
        return proposal(record)
    with pytest.raises(AnalysisCancelled):
        execute_focus_response(record, journal.state["identity"]["research_question"], ledger=journal.ledger,
            caller=call, cancelled=lambda: cancelled[0], deadline=lambda: time.monotonic() + 30)
    assert journal.ledger.cached_result("native.focus_response") is None
    assert project_research_record(journal.observer.store, record.run_id)["state"] != "ready"


def test_unknown_dispatch_is_not_resubmitted_but_saved_sdk_output_recovers(journal, monkeypatch):
    record = baseline(journal)
    model = sdk_caller(journal)
    stub, slots = sdk(monkeypatch, [proposal(record)])
    response = execute(journal, record, model)
    journal.state["results"].pop("native.focus_response")
    journal.persist()
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert execute(restored, record, sdk_caller(restored, deadline=lambda: -1)) == response
    assert len(stub.prompts) == slots.releases == 1
    restored.state["results"].pop("native.focus_response")
    restored.state["results"].pop("native.adapter.focus_response")
    restored.persist()
    assert execute(restored, record, lambda *_: pytest.fail("uncertain dispatch" )).reason_code == "response_unknown"


@pytest.mark.parametrize("invalid", ["malformed JSON", {"answer": "无依据", "answerability": "answered"}])
def test_sdk_focus_uses_quick_once_with_no_repair_tools_or_retry(journal, monkeypatch, invalid):
    record = baseline(journal)
    stub, slots = sdk(monkeypatch, [invalid])
    response = execute(journal, record, sdk_caller(journal))
    assert response.reason_code == "invalid_response"
    assert len(stub.prompts) == len(slots.acquires) == slots.releases == 1
    assert stub.factories[0]["model"] == "quick" and stub.factories[0]["max_retries"] == 0
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 0
    assert journal.ledger.consumed(BudgetBucket.NETWORK_RETRY) == 0
    assert journal.ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS) == 0
    counts = native_counts(journal.state, role="focus_response")
    assert counts.sdk_main.value == 0 and counts.sdk_focus.value == counts.sdk_total.value == 1


def test_committed_supplement_read_and_markdown_share_bindings_and_order(journal):
    record = baseline(journal)
    response = execute(journal, record)
    base, artifact = publish(journal, record, response)
    store, run_id = journal.observer.store, record.run_id
    before = len(store.read_events(run_id))
    dto = project_reader_focus(store, run_id)
    assert dto["state"] == "ready" and dto["response"] == response.model_dump(mode="json")
    assert len(store.read_events(run_id)) == before
    assert project_research_record(store, run_id)["state"] == "ready"
    report = ReportArtifactWriter(store).publish_final(run_id, {"native_research_record": record.model_dump(mode="json")}, record.ticker)
    content = report.complete_report.read_text()
    assert content.index(record.assessment.judgement) < content.index("## 补充关注点回应") < content.index(response.proposal.answer)
    assert "研究范围：" in content and "。研究问题：" not in content
    assert publish(journal, record, response) == (base, artifact)
    ReportArtifactWriter(store).publish_final(run_id, {"native_research_record": record.model_dump(mode="json")}, record.ticker)


def test_local_optional_promotion_failure_is_stable_and_does_not_block_report(journal, monkeypatch):
    record = baseline(journal)
    response = execute(journal, record)
    with monkeypatch.context() as patch:
        patch.setattr("tradingagents.execution.native_focus_publication.promote_derived_public_artifact",
                      lambda *a, **kw: (_ for _ in ()).throw(OSError("local artifact write failed")))
        _, artifact = publish(journal, record, response)
    assert artifact is None
    store, run_id = journal.observer.store, record.run_id
    dto = project_reader_focus(store, run_id)
    assert dto["state"] == "unavailable" and dto["reason_code"] == "publication_failed" and dto["response"] is None
    before = len(store.read_events(run_id))
    assert publish(journal, record, response)[1] is None
    assert len(store.read_events(run_id)) == before
    writer = ReportArtifactWriter(store)
    report = writer.publish_final(run_id, {"native_research_record": record.model_dump(mode="json")}, record.ticker)
    assert "补充回应未能发布" in report.complete_report.read_text()


def test_crash_after_focus_commit_before_disposition_recovers_without_sdk(journal, monkeypatch):
    record = baseline(journal)
    response = execute(journal, record)
    original = journal.put
    def put(key, value):
        if key == "native_focus_publication" and value["state"] == "committed":
            raise SystemExit("simulated process loss")
        return original(key, value)
    with monkeypatch.context() as patch:
        patch.setattr(journal, "put", put)
        with pytest.raises(SystemExit):
            publish(journal, record, response)
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert restored.state["native_focus_publication"]["state"] == "pending"
    assert publish(restored, record, execute(restored, record, lambda *_: pytest.fail()))[1]
    assert restored.state["native_focus_publication"]["state"] == "committed"


@pytest.mark.parametrize("corrupt", ["input", "output", "bytes", "disposition"])
def test_corrupt_optional_output_cannot_poison_base_read(journal, corrupt):
    record = baseline(journal)
    response = execute(journal, record)
    _, artifact = publish(journal, record, response)
    if corrupt == "input":
        journal.state["native_focus_input"]["context_sha256"] = "a" * 64
    elif corrupt == "output":
        journal.state["results"]["native.focus_response"]["response"]["proposal"]["answer"] = "篡改"
    elif corrupt == "disposition":
        journal.state["native_focus_publication"]["state"] = "unavailable"
    else:
        # Use the actual event locator, not the public identifier's spelling.
        event = next(e for e in journal.observer.store.read_events(record.run_id) if e.payload.get("artifact_id") == artifact)
        path = journal.observer.store._run_dir(record.run_id) / event.payload["locator"]
        path.write_bytes(b"{}")
    if corrupt != "bytes":
        journal.persist()
    dto = project_reader_focus(journal.observer.store, record.run_id)
    assert dto["state"] == "unavailable" and dto["reason_code"] == "corrupt" and dto["response"] is None
    assert project_research_record(journal.observer.store, record.run_id)["state"] == "ready"


def test_schema_rejects_unknown_references_extra_fields_and_unjustified_answer(journal):
    record = baseline(journal)
    with pytest.raises(ValidationError):
        FocusProposalV1(answer="没有依据", answerability="answered")
    with pytest.raises(ValidationError):
        FocusProposalV1(answer="无法判断", answerability="unresolved", judgement="覆盖")
    with pytest.raises(ValueError):
        validate_focus_proposal(record, FocusProposalV1(answer="编造", answerability="partial", evidence_ids=("unknown",)))


@pytest.mark.parametrize("unqualified", ["future_usable", "future_published", "unavailable", "missing_content", "unknown_claim"])
def test_focus_rejects_unqualified_saved_material(journal, unqualified):
    from datetime import datetime, timezone
    record = baseline(journal)
    source = record.evidence[0]
    if unqualified == "unknown_claim":
        record = record.model_copy(update={"claims": (record.claims[0].model_copy(update={"kind": "unknown"}), *record.claims[1:])})
    else:
        updates = {"future_usable": {"usable_as_of": datetime(2026, 10, 1, tzinfo=timezone.utc)},
                   "future_published": {"published_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
                   "unavailable": {"availability": "unavailable"}, "missing_content": {"content": None}}[unqualified]
        record = record.model_copy(update={"evidence": (source.model_copy(update=updates), *record.evidence[1:])})
    with pytest.raises(ValueError):
        validate_focus_proposal(record, FocusProposalV1.model_validate(proposal(record)))


def test_changed_focus_or_frozen_baseline_cannot_reuse_output(journal):
    record = baseline(journal)
    execute(journal, record)
    with pytest.raises(CatalystCheckpointConflict):
        execute_focus_response(record, "不同角度", ledger=journal.ledger, caller=lambda *_: pytest.fail(),
                               cancelled=lambda: False, deadline=lambda: time.monotonic()+30)
    modified = record.model_copy(update={"assessment": record.assessment.model_copy(update={"judgement": "改写"})})
    with pytest.raises(CatalystCheckpointConflict):
        execute(journal, modified)


def test_global_checkpoint_failure_cannot_become_supplement_unavailable(journal, monkeypatch):
    record = baseline(journal)
    def fail(*_):
        journal.failed = True
        raise CatalystCheckpointConflict("global persistence failed")
    monkeypatch.setattr(journal, "persist", fail)
    with pytest.raises(CatalystCheckpointConflict):
        execute(journal, record, lambda *_: pytest.fail("no SDK after persistence failure"))
    assert journal.ledger.cached_result("native.focus_response") is None
