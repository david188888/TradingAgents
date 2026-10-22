"""Actual offline HTTP publication and saved numeric/Reader boundaries."""

from fastapi.testclient import TestClient

from tests.test_native_record import fixture as source_fixture
from tests.test_structured_financial_checks import payload
from tests.web import test_native_production_wiring as wiring
from tests.web.test_native_production_wiring import runtime as runtime
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.native_runner import validate_native_resume
from tradingagents.research.native_versions import STRUCTURED_FINANCIAL_POLICY
from tradingagents.research.numeric_integration import validate_record_numeric
from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
from tradingagents.web.api import create_app


def test_v3_financial_checks_survive_publication_numeric_proof_reader_agent_and_markdown(runtime, monkeypatch):
    manager, caller = runtime
    def repeating_comparison(*, extra=()):
        fields = payload()
        fields["cashflow"][0]["n_cashflow_act"] = "31"
        return source_fixture(financial_payload=fields, extra=extra)

    monkeypatch.setattr(wiring, "fixture", repeating_comparison)
    original = caller._proposal

    def proposal(stage, context):
        result = original(stage, context)
        if stage == "challenge":
            result["challenges"][0]["check_id"] = "cashflow_comparison"
        return result

    monkeypatch.setattr(caller, "_proposal", proposal)
    with TestClient(create_app(manager=manager, recover_startup=False,
        environment={"OPENAI_API_KEY": "offline-placeholder"}, connectivity_check=lambda _: None)) as client:
        response = client.post("/api/runs", json={**wiring.BODY, "ticker": "600519", "analysis_date": "2026-09-30", "mode": "company_research"})
        assert response.status_code == 201, response.text
        run_id = response.json()["run_id"]
        snapshot = manager.wait(run_id, 60)
        assert snapshot.status == "completed", snapshot.error_message
        cp = load_checkpoint(manager.store, run_id)
        assert cp["identity"]["structured_financial_policy"] == STRUCTURED_FINANCIAL_POLICY
        saved = client.get(f"/api/runs/{run_id}/reader/record").json()
        assert saved["state"] == "ready", saved
        record = ResearchRecordV1.model_validate(saved["record"])
        checks = {c.check_id: c for c in record.evidence_checks.checks}
        assert checks["cashflow_comparison"].status == checks["financial_baseline"].status == "passed"
        assert checks["cash_conversion"].status == "unavailable"
        outcome = record.assessment.challenge_assessments[0]
        assert outcome.outcome == "evidence_sufficient" and outcome.economic_outcome == "unresolved"
        assert outcome.question_scope == "cashflow_comparison.same_period_endpoints"
        validate_record_numeric(record, cp["identity"])
        validate_native_resume(manager.store, run_id, manager._requests[run_id])
        from tradingagents.web.reader_process_projection import project_reader_agent
        assert project_reader_agent(manager.store, run_id, "synthesis")["availability"] == "available"
        from tradingagents.runtime.reports import build_markdown_from_native_record
        text = build_markdown_from_native_record(record, workflow_version=cp["identity"]["workflow_version"])
        assert "利润与现金流同期比较" in text and "现金流桥核对" in text
        assert "不代表完整现金流调节桥" in text
        assert "n_cashflow_act_current" not in text  # human-facing labels only
