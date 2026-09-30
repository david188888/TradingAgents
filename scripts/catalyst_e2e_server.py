"""Isolated real HTTP/SSE server with explicit synthetic catalyst evidence.

This fixture exercises production persistence and lifecycle wiring. It never
calls a model or data provider and does not represent research-quality evidence.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timezone

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


def build_app():
    from scripts.e2e_server import _fake_runner_factory, _stub_summary_llm
    root = os.environ.get("TRADINGAGENTS_E2E_RUN_ROOT") or tempfile.mkdtemp(prefix="catalyst-e2e-")
    store = RunStore(root)
    broker = EventBroker(store)
    def factory(request, observer):
        if request.research_profile == "catalyst_v1":
            return CatalystRunner(observer, sources_factory=FixtureSources, caller_factory=FixtureCaller)
        return _fake_runner_factory(request, observer)
    manager = SingleRunManager(store, broker, runner_factory=factory)
    os.environ["TRADINGAGENTS_CATALYST_PROFILE_ENABLED"] = "1"
    _stub_summary_llm()
    return create_app(manager=manager, checkpoint_available=False,
        environment={"DEEPSEEK_API_KEY": "synthetic-fixture-key"}, connectivity_check=lambda _ticker: None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=int(os.environ.get("TRADINGAGENTS_E2E_PORT", "4173")))
