"""V5 public Web lifecycle uses fixtures; never spends an SDK request."""

import copy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_minimum_evidence import fixture
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import NativeRunner
from tradingagents.graph.native_research import run_native_research
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal, load_checkpoint
from tradingagents.runtime.reports import build_markdown_from_native_record
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.manager import SingleRunManager
from tradingagents.web.research_record_projection import project_research_record


class MinimumCaller:
    """Fixed proposals exercise bindings and publication, not research quality."""

    def __init__(self):
        self.calls = []

    def __call__(self, stage, context):
        self.calls.append((stage, copy.deepcopy(context)))
        if stage in {"operating_quality", "event_context", "market_context"}:
            return {"hypotheses": [{"statement": "已有披露可用于核查，经营持续性仍待观察。",
                "supporting_fact_ids": [context["facts"][0]["claim_id"]],
                "conditions": [{"condition_role": "invalidation", "text": "后续经营证据与当前解释矛盾。"}],
                "alternative_explanation": "时点因素和会计调整可能解释部分变化。"}]}
        if stage == "challenge":
            hypothesis = context["record"]["hypotheses"][0]["hypothesis_id"]
            return {"challenges": [{"hypothesis_id": hypothesis, "statement": label,
                "severity": "critical", "risk_type": "operations", "proposed_test": "核对保存证据并观察后续变化。",
                "check_id": check, **extra} for check, label, extra in (
                    ("operating_disclosures", "经营披露是否足以回答基础资料问题？", {}),
                    ("cash_conversion", "经营现金流下降是否存在？", {"observed_risk": "cash_conversion.cfo_yoy_decline"}),
                    ("valuation_context", "估值补充资料是否已取得？", {}))]}
        record = context["record"]
        dimensions = []
        for name, (ceiling, reason) in context["dimension_policy"].items():
            allowed = context["dimension_claim_ids"].get(name, [])
            dimensions.append({"dimension": name, "status": ceiling, "judgement": "依据限于保存资料，仍需后续核查。",
                "claim_ids": allowed[:1] if ceiling != "unresolved" else [],
                "limitations": [reason] if ceiling == "unresolved" else []})
        return {"judgement": "三项基础证据问题已有核查结果；经济原因、持续性及合理价值仍待判断。",
            "next_check": "核对下一期现金流及营运资金变化。", "dimensions": dimensions,
            "key_claim_ids": [h["claim_id"] for h in record["hypotheses"]],
            "primary_challenge_id": record["challenges"][1]["challenge_id"],
            "challenge_assessments": [{"challenge_id": c["challenge_id"], "rationale": "模型文字不会替代代码裁定。"}
                                      for c in record["challenges"]]}


class MinimumFixtureSources:
    def __init__(self, request, run_id, session, fetch):
        self.request, self.run_id = request, run_id

    def collect(self):
        draft, context = fixture()
        return draft.model_copy(update={"run_id": self.run_id,
            "evidence": tuple({**e, "run_id": self.run_id} for e in draft.evidence)}), context


def start_fixture(root, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("fixture acceptance must not call network or SDK")
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    monkeypatch.setattr("tradingagents.execution.native_model.create_llm_client", forbidden)
    caller = MinimumCaller()
    monkeypatch.setattr("tradingagents.execution.native_runner.NativeRunner",
        lambda observer: NativeRunner(observer, sources_factory=MinimumFixtureSources, caller_factory=lambda **_: caller))
    manager = SingleRunManager(RunStore(root))
    request = AnalysisRequest("600803", "2026-10-05", mode="company_research", research_profile="evidence_v1",
        effective_config={"llm_provider": "openai", "quick_think_llm": "fixture", "deep_think_llm": "fixture"})
    started = manager.start(request)
    done = manager.wait(started.run_id, 10)
    assert done.status == "completed", done.error_message
    return manager, caller, done


def test_v5_publication_reader_report_and_replay_use_one_validated_artifact(tmp_path, monkeypatch):
    manager, caller, done = start_fixture(tmp_path, monkeypatch)
    checkpoint = load_checkpoint(manager.store, done.run_id)
    assert checkpoint["identity"]["workflow_version"] == "evidence-production-v5"
    response = project_research_record(manager.store, done.run_id)
    assert response["state"] == "ready"
    record = ResearchRecordV1.model_validate(response["record"])
    assert record.assessment.schema_version == "research-assessment-v2"
    assert [c.outcome for c in record.assessment.challenge_assessments] == [
        "evidence_sufficient", "risk_supported", "evidence_sufficient"]
    assert all(c.economic_outcome == "unresolved" for c in record.assessment.challenge_assessments)
    assert record.assessment.quality == "LOW_CONFIDENCE"
    markdown = build_markdown_from_native_record(record)
    assert "-10.9542 亿元" in markdown and "经济判断仍待核查" in markdown
    assert "证据子问题已回答" in markdown and "数据支持所列风险" in markdown
    assert "已执行上述本地证据核查" in markdown
    assert [stage for stage, _ in caller.calls] == ["operating_quality", "challenge", "synthesis"]
    before = manager.store.read_events(done.run_id)
    with TestClient(create_app(manager=manager)) as client:
        assert client.get(f"/api/runs/{done.run_id}/reader/record").json() == response
    assert manager.store.read_events(done.run_id) == before
    observer = DurableRunObserver(manager.store, done.run_id, development_assertions=False)
    journal = CatalystJournal(observer, checkpoint["identity"], require_existing=True)
    seed = ResearchRecordV1.model_validate(checkpoint["native_seed"])
    restored = run_native_research(seed, caller=lambda *_: pytest.fail("replay dispatched a model"),
        ledger=journal.ledger, scoped=True, valuation=True, minimum=True)
    assert restored == record and build_markdown_from_native_record(restored) == markdown


@pytest.mark.parametrize("field,value", [("outcome", "unresolved"), ("economic_outcome", "resolved"),
    ("answered_question", "所有经济风险已关闭"), ("rationale", "模型替代本地裁定")])
def test_saved_v2_cannot_relabel_the_code_owned_answer(tmp_path, monkeypatch, field, value):
    manager, _, done = start_fixture(tmp_path, monkeypatch)
    payload = project_research_record(manager.store, done.run_id)["record"]
    payload["assessment"]["challenge_assessments"][0][field] = value
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


def test_cfo_risk_cannot_be_bound_to_a_different_question():
    from tradingagents.agents.schemas._evidence_checks import ChallengeCheckBindingV1
    with pytest.raises(ValidationError, match="another check"):
        ChallengeCheckBindingV1(challenge_id="c", check_id="valuation_context", observed_risk="cash_conversion.cfo_yoy_decline")
