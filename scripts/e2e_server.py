"""Real V9 HTTP/SSE lifecycle with explicitly synthetic offline evidence."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.agents.schemas._evidence import RecordClaimV1, SourceContentV1, SourceEvidenceV1
from tradingagents.agents.schemas._evidence_record import EvidenceRecord, make_evidence_snapshot
from tradingagents.execution.native_runner import NativeRunner
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.broker import EventBroker
from tradingagents.web.manager import SingleRunManager


class InsightFixtureSources:
    def __init__(self, request, run_id, session, fetch, coordinator):
        self.request, self.run_id = request, run_id

    def collect(self):
        text = "合成测试资料：公司客户结构与未来订单仍需进一步核查。"
        source = SourceEvidenceV1(evidence_id="fixture.source", source_name="web.fixture",
            source_kind="derived", availability="available", usable_as_of=datetime.fromisoformat(
                self.request.analysis_date + "T00:00:00+08:00"), captured_at=datetime.now(timezone.utc),
            content=SourceContentV1(kind="excerpt", text=text, locator_label="离线浏览器测试合成片段",
                content_sha256=hashlib.sha256(text.encode()).hexdigest()), limitations=("synthetic_fixture",))
        fact = RecordClaimV1(claim_id="fixture.fact", kind="fact", statement=text,
            evidence_ids=(source.evidence_id,), limitations=("native_dimension:operating_quality", "synthetic_fixture"))
        return EvidenceRecord(run_id=self.run_id, ticker=self.request.ticker,
            analysis_date=self.request.analysis_date, evidence=(source,), claims=(fact,),
            snapshots=(make_evidence_snapshot((source,)),), limitations=("synthetic_fixture",)), {}


class InsightFixtureCaller:
    def __init__(self, *, fail_synthesis=False, **kwargs):
        self.fail_synthesis = fail_synthesis

    def __call__(self, stage, context, *, phase="main"):
        time.sleep(0.03)
        if stage == "challenge":
            return {"reviews": [{"target": i["ref"], "concern": None,
                "reasoning": "已审阅合成测试资料，未发现额外反证。", "evidence_refs": []} for i in context["insights"]]}
        if stage == "synthesis":
            return {"judgement": "合成测试：现有研究仅提供有限支持。", "stance": "neutral",
                "insight_refs": ["I999"] if self.fail_synthesis else [context["insights"][0]["ref"]],
                "reasoning": "结论来自已保存的专项观点。", "limitations": "全部内容仅用于离线界面测试。",
                "next_check": "另行验证真实模型和来源。"}
        return {"insights": [{"claim": "合成测试：客户结构需要持续核查。" if stage != "focus_response" else "合成测试：回应用户关注问题。",
            "evidence_refs": [context["evidence"][0]["ref"]], "reasoning": "保存片段支持有边界的研究解释。",
            "limitations": "无法从本测试判断未来业绩。"}], "search_requests": []}

    def call_jev_verification(self, insight_id, insight_state, questions):
        return ({name: 0.02 if name.startswith("conflict_") else 0.92 for name in questions},
            {"id": "fixture-jev", "model": "typesafe/jev-1.14", "provider": "TypeSafe", "usage": {"input_tokens": 10}})


def build_app():
    from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuth
    root = os.environ.get("TRADINGAGENTS_E2E_RUN_ROOT") or tempfile.mkdtemp(prefix="insight-e2e-")
    store = RunStore(root)
    broker = EventBroker(store)

    def factory(request, observer):
        return NativeRunner(observer, sources_factory=InsightFixtureSources,
            caller_factory=lambda **kwargs: InsightFixtureCaller(
                fail_synthesis=request.ticker.startswith("600418"), **kwargs))

    manager = SingleRunManager(store, broker, runner_factory=factory)

    def explain_fixture(prompt):
        targets, _ = json.JSONDecoder().raw_decode(prompt.split("\nDATA:\n", 1)[1])
        return SimpleNamespace(content=json.dumps({"entries": [{"target": t["target"],
            "explanation": "这是保存分析的通俗说明，判断仍需结合对应证据和限定条件理解。",
            "uncertainty": "现有资料不能保证未来结果。", "references": t["references"][:1]} for t in targets]}, ensure_ascii=False))

    manager.explanations.client_factory = lambda **kwargs: SimpleNamespace(
        get_llm=lambda: SimpleNamespace(invoke=explain_fixture))
    os.environ["TRADINGAGENTS_EVIDENCE_ENABLED"] = "true"
    return create_app(manager=manager, chatgpt_auth=ChatGPTAuth(Path(root) / "fixture-chatgpt-auth"),
        environment={"DEEPSEEK_API_KEY": "synthetic-fixture-key", "BAILIAN_API_KEY": "synthetic-bailian-key"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=int(os.environ.get("TRADINGAGENTS_E2E_PORT", "4173")))
