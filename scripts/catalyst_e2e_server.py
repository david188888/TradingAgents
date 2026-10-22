"""Isolated real HTTP/SSE server with explicit synthetic catalyst evidence.

This fixture exercises production persistence and lifecycle wiring. It never
calls a model or data provider and does not represent research-quality evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.agents.schemas import CatalystEvidence
from tradingagents.execution.catalyst_runner import CatalystRunner
from tradingagents.research.evidence_freeze import (
    REQUIRED_CAPABILITIES,
    CapabilityStatus,
    EvidenceFreezer,
    FreezeInputs,
    FrozenCapability,
    PriceObservation,
)
from tradingagents.web.api import create_app
from tradingagents.web.broker import EventBroker
from tradingagents.web.manager import SingleRunManager
from tradingagents.web.store import RunStore


class FixtureSources:
    def __init__(self, request, run_id, session, fetch):
        self.request, self.run_id = request, run_id

    def collect(self):
        inputs = FreezeInputs(self.run_id, self.request.ticker, self.request.analysis_date, self.request.catalyst_policy)
        context = {}
        for capability in REQUIRED_CAPABILITIES:
            evidence = CatalystEvidence(
                evidence_id=f"fixture.{capability}", run_id=self.run_id, ticker=self.request.ticker,
                capability=capability, source_tier="derived", source_name="Synthetic browser fixture",
                source_family_id=f"fixture:{capability}", captured_at=datetime.now(timezone.utc),
                time_basis="synthetic fixture; not a live research observation",
                value_basis="synthetic test data only",
            )
            inputs.evidence.append(evidence.model_dump(mode="json"))
            context[evidence.evidence_id] = {"fixture": True}
            inputs.capabilities.append(FrozenCapability(capability=capability, status=CapabilityStatus.QUALIFIED,
                required=True, reason="synthetic fixture qualification only"))
        inputs.prices.append(PriceObservation(observed_on=self.request.analysis_date, close=10, adjustment="qfq", source="fixture"))
        return EvidenceFreezer(inputs).close(), context


class FixtureCaller:
    def __init__(self, request, draft, context, journal, ensure_active, remaining):
        self.active = ensure_active
        self.draft = draft

    def __call__(self, *, role, prompt):
        # A short active window makes cancellation/stream progress reviewable.
        for _ in range(5):
            time.sleep(0.05)
            self.active()
        if role == "independent_refutation":
            return {"challenges": []}
        if role == "synthesis":
            return {"judgement": "固定测试证据用于验证页面与发布接线。", "priority": "keep_watching",
                "key_evidence_finding_ids": ["f.catalyst_events.i0"], "key_question": "真实来源尚未经过此 fixture 验证。",
                "next_check": "单独进行真实来源验证。", "critical_limitations": ["本页全部研究内容为 synthetic fixture，不是实时研究结论。"],
                "dispositions": []}
        from tradingagents.research.evidence_freeze import build_specialist_view
        eid = build_specialist_view(self.draft, role).citable_evidence_ids[0]
        return {"findings": [{"kind": "fact", "text": "固定浏览器证据示例（fixture）。", "confidence": 0.5, "evidence_ids": [eid]}]}


class NativeFixtureSources:
    def __init__(self, request, run_id, session, fetch):
        self.request, self.run_id = request, run_id

    def collect(self):
        from tests.test_native_valuation import valuation_fixture
        draft, context = valuation_fixture()
        if self.request.ticker.startswith("600519"):
            from tests.test_native_record import fixture as structured_fixture
            from tests.test_structured_financial_checks import payload as structured_payload
            draft, context = structured_fixture(financial_payload=structured_payload())
        if self.request.ticker.startswith("600418"):
            from tradingagents.dataflows.company_profile import PROFILE_CAPABILITY, PROFILE_SOURCE
            from tradingagents.research.evidence_freeze import CapabilityStatus, FrozenCapability
            payloads = [(e, json.loads(json.dumps(context[e["evidence_id"]], ensure_ascii=False)
                        .replace("600803.SH", "600418.SH").replace("新奥股份", "江淮汽车（合成测试）"))) for e in draft.evidence]
            payloads.append(({"capability": PROFILE_CAPABILITY, "source_name": PROFILE_SOURCE,
                "source_tier": "vendor", "captured_at": "2026-09-30T08:30:00Z", "observed_at": "2026-09-30T08:30:00Z",
                "usable_as_of": "2026-09-30T08:30:00Z", "time_basis": "synthetic fixture", "value_basis": "synthetic fixture"},
                {"ts_code": "600418.SH", "name": "江淮汽车（合成测试）", "capture_scope": "current_public_profile",
                 "fields": {"main_business": "汽车业务介绍（仅为离线浏览器测试合成字段）"}}))
            evidence, context = [], {}
            for item, payload in payloads:
                digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                key = "e.d" + digest[:16]
                evidence.append({**item, "evidence_id":key, "source_family_id":item["source_name"]+":"+digest,
                    "run_id":self.run_id,"ticker":self.request.ticker})
                context[key] = payload
            draft = draft.model_copy(update={"evidence":tuple(evidence), "capabilities":(*draft.capabilities,
                FrozenCapability(capability=PROFILE_CAPABILITY, status=CapabilityStatus.QUALIFIED, required=False, reason="synthetic fixture"))})
        return draft.model_copy(update={"run_id": self.run_id, "ticker": self.request.ticker,
            "cutoff": self.request.analysis_date,
            "evidence": tuple({**e, "run_id":self.run_id, "ticker":self.request.ticker} for e in draft.evidence)}), context


class NativeFixtureCaller:
    def __init__(self, *, fail_synthesis=False, **kwargs):
        self.fail_synthesis = fail_synthesis

    def __call__(self, stage, context):
        proposal = self._proposal(stage, context)
        if context.get("numeric_narrative_policy") is not None:
            value = {"proposal": proposal, "plans": [], "structured_bindings": []}
            if stage == "challenge" and proposal["challenges"]:
                anchors = {a["anchor_id"]: a for a in context["numeric_catalog"]["anchors"]}
                for index, item in enumerate(proposal["challenges"]):
                    root = f"challenges.{index}"
                    if item.get("check"):
                        check = item["check"]
                        operand = check["current"]
                        alias = next(key for key, aid in context["numeric_aliases"].items()
                            if operand["evidence_id"] in anchors[aid]["input_evidence_ids"]
                            and all(anchors[aid]["lineage"].get("source_selector", {}).get(k) == operand[k]
                                    for k in ("table", "field", "report_period")))
                        item["supporting_fact_ids"] = anchors[context["numeric_aliases"][alias]]["required_fact_ids"]
                        item["proposed_test"] = "合成核查命题：{{plan:p_threshold}}"
                        value["plans"].append({"alias": "p_threshold", "kind": "quantity",
                            "field_path": root + ".proposed_test", **check["predicate"]})
                        value["structured_bindings"].extend([
                            {"field_path": root + ".check.current", "kind": "num", "alias": alias},
                            {"field_path": root + ".check.predicate", "kind": "plan", "alias": "p_threshold"}])
                    if item.get("observation_date"):
                        value["plans"].append({"alias": "p_future", "kind": "date",
                            "field_path": root + ".observation_date", "date": item["observation_date"]})
                        value["structured_bindings"].append({"field_path": root + ".observation_date",
                            "kind": "plan", "alias": "p_future"})
            if context.get("factual_premise_policy"):
                from tests.factual_premise_fixtures import bind
                value = bind(stage, value, context)
            return value
        return proposal

    def _proposal(self, stage, context):
        time.sleep(.25)
        if stage == "challenge" and context.get("challenge_check_policy") and context["record"]["ticker"].startswith("600519"):
            record = context["record"]
            fact = next(f for f in record["claims"] if f["kind"] == "fact" and "income.revenue" in f["statement"])
            base = {"hypothesis_id": record["hypotheses"][0]["hypothesis_id"], "severity": "material", "risk_type": "operations"}
            return {"challenges": [
                {**base, "statement": "合成测试：当前收入字段需要核查。", "proposed_test": "当前收入是否为正",
                 "verifiability": "computable_now", "supporting_fact_ids": [fact["claim_id"]],
                 "check": {"kind": "financial", "operation": "value", "current": {"evidence_id": fact["evidence_ids"][0],
                    "table": "income", "field": "revenue", "report_period": "2026-06-30"},
                    "predicate": {"operator": "gt", "threshold": "0", "unit": "CNY"}}},
                {**base, "statement": "合成测试：费用变动原因需要补充说明。", "proposed_test": "补充管理层费用原因说明",
                 "verifiability": "needs_source", "required_inputs": [{"kind": "source", "description": "管理层费用变动原因说明"}]},
                {**base, "statement": "合成测试：经营持续性需要后续观察。", "proposed_test": "后续经营披露再核对",
                 "verifiability": "future_observation", "observation_date": "2027-01-01"}]}
        if stage.startswith("response_"):
            return {"responses": [{"challenge_id": cid, "hypothesis_id": hid, "disposition": "unanswerable",
                "rationale": "合成测试：承认经济解释仍未确定。"} for cid, hid in context["assigned"].items()]}
        if stage == "focus_response":
            return {"answer": "固定测试补充回应：已有经营数据不能证明 AI 业务关系。",
                    "answerability": "partial", "claim_ids": [context["record"]["claims"][0]["claim_id"]],
                    "limitations": ["固定测试未提供细分业务披露。"]}
        if stage == "operating_quality":
            # One admitted, bound hypothesis makes Agent-to-fact navigation testable.
            # Other specialists retain legal zero proposals; no real model is invoked.
            return {"hypotheses": [{
                "statement": "固定测试假设：经营改善仍需验证。",
                "supporting_fact_ids": [context["facts"][0]["claim_id"]],
                "conditions": [
                    {"condition_role": "necessary", "text": "需要同口径的持续经营数据。"},
                    {"condition_role": "invalidation", "text": "后续同口径数据不能支持改善。"},
                ],
                "alternative_explanation": "测试替代解释：期间差异。",
            }]}
        if stage == "synthesis":
            if self.fail_synthesis:
                raise ValueError("synthetic unusable synthesis")
            dimensions = []
            for dimension, (ceiling, reason) in context["dimension_policy"].items():
                refs = context["dimension_claim_ids"].get(dimension, [])[:1]
                dimensions.append({"dimension": dimension, "status": ceiling if refs else "unresolved",
                    "judgement": "固定测试输入，非真实研究结论。", "claim_ids": refs,
                    "limitations": [] if refs else [reason]})
            result = {"investment_stance": "neutral",
                "supporting_arguments": [{"rationale": "固定测试：经营字段提供有限依据。", "claim_ids": context["dimension_claim_ids"]["operating_quality"][:1]}],
                "judgement": "固定测试证据用于验证网页、引用和确定性估值接线。", "dimensions":dimensions,
                "key_claim_ids": context["dimension_claim_ids"]["operating_quality"][:1],
                "next_check": "本页全部为 synthetic fixture；需独立验证真实来源。"}
            if context["record"].get("challenge_check_policy"):
                record = context["record"]
                result["primary_challenge_id"] = record["challenges"][0]["challenge_id"] if record["challenges"] else None
                result["adjudications"] = [{"challenge_id": r["challenge_id"], "response_id": r["response_id"],
                    "disposition": r["disposition"], "rationale": "合成测试：命题结果不确定经济成因。"}
                    for r in record["dialogue"]["responses"]]
                result["challenge_assessments"] = [{"challenge_id": c["challenge_id"], "rationale": "合成测试：风险仍待评估。"}
                    for c in record["challenges"]]
            return result
        return {"challenges":[]} if stage == "challenge" else {"hypotheses":[]}


def build_app():
    from scripts.e2e_server import _fake_runner_factory, _stub_summary_llm
    root = os.environ.get("TRADINGAGENTS_E2E_RUN_ROOT") or tempfile.mkdtemp(prefix="catalyst-e2e-")
    store = RunStore(root)
    broker = EventBroker(store)
    def factory(request, observer):
        if request.research_profile == "evidence_v1":
            from tradingagents.execution.native_runner import NativeRunner
            return NativeRunner(observer, sources_factory=NativeFixtureSources,
                caller_factory=lambda **kwargs: NativeFixtureCaller(fail_synthesis=request.ticker.startswith("600418"), **kwargs))
        if request.research_profile == "catalyst_v1":
            return CatalystRunner(observer, sources_factory=FixtureSources, caller_factory=FixtureCaller)
        return _fake_runner_factory(request, observer)
    manager = SingleRunManager(store, broker, runner_factory=factory)
    # Exercise the real supplement lifecycle without an external model request.
    from types import SimpleNamespace

    def explain_fixture(prompt):
        targets = json.loads(prompt.split("\nDATA:\n")[1].split("\nRepair:")[0])
        return SimpleNamespace(content=json.dumps({"entries": [{"target": t["target"],
            "explanation": "这是保存分析的通俗说明，判断仍需结合对应证据和限定条件理解。",
            "uncertainty": "现有资料不能保证未来结果。", "references": t["references"][:1]} for t in targets]}, ensure_ascii=False))

    manager.explanations.client_factory = lambda **kwargs: SimpleNamespace(
        get_llm=lambda: SimpleNamespace(invoke=explain_fixture))
    os.environ["TRADINGAGENTS_CATALYST_PROFILE_ENABLED"] = "1"
    os.environ["TRADINGAGENTS_EVIDENCE_ENABLED"] = "true"
    _stub_summary_llm()
    from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuth

    return create_app(manager=manager, checkpoint_available=False,
        chatgpt_auth=ChatGPTAuth(Path(root) / "fixture-chatgpt-auth"),
        environment={"DEEPSEEK_API_KEY": "synthetic-fixture-key"}, connectivity_check=lambda _ticker: None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=int(os.environ.get("TRADINGAGENTS_E2E_PORT", "4173")))
