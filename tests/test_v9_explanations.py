"""V9 saved reports support both current explanation delivery policies offline."""

import json
import time
from types import SimpleNamespace

import pytest

from scripts.e2e_server import InsightFixtureCaller
from tests.web.test_v9_api import BODY, workbench
from tradingagents.execution.report_explanation import ExplanationService
from tradingagents.runtime.report_explanation import read_explanation_job
from tradingagents.web.report_explanation import load_explanation_record, project_report_explanation


@pytest.mark.parametrize("batched", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_v9_explanations_preserve_rating_state_and_saved_focus(tmp_path, batched, partial):
    with workbench(tmp_path, caller=InsightFixtureCaller(fail_synthesis=partial)) as (client, manager, store, _calls):
        run_id = client.post("/api/runs", json={**BODY, "research_question": "核查客户风险"}).json()["run_id"]
        assert manager.wait(run_id, timeout=5).status == "completed"
        if batched:
            snapshot = store.read_snapshot(run_id)
            store.write_snapshot_atomic(snapshot.evolve(metadata={**snapshot.metadata, "research_delivery_policy": "evidence-packets-v1"}))
        before = client.get(f"/api/runs/{run_id}/reader/record").json()["record"]
        prompts = []

        def explain(prompt):
            prompts.append(prompt)
            targets, _ = json.JSONDecoder().raw_decode(prompt.split("\nDATA:\n", 1)[1])
            return json.dumps({"entries": [{"target": target["target"],
                "explanation": "这是已保存观点的通俗解释。", "uncertainty": "相关判断仍有局限。",
                "references": target["references"]} for target in targets]}, ensure_ascii=False)

        service = ExplanationService(store, lambda run: load_explanation_record(store, run),
            client_factory=lambda **kwargs: SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=explain)))
        try:
            service.start(run_id)
            deadline = time.monotonic() + 5
            while service.active(run_id, read_explanation_job(store, run_id).job_id) and time.monotonic() < deadline:
                time.sleep(0.01)
            view = project_report_explanation(store, run_id, service=service)
            assert view["state"] == "available", view
            expected = {"insight:" + item["insight_id"] for item in (*before["insights"], *before["focus_insights"])}
            assert set(view["entries"]) == expected
            assert len(prompts) == 1
            status = json.JSONDecoder().raw_decode(prompts[0].split("Research status: ", 1)[1])[0]
            assert status["report_status"] == ("partial" if partial else "available")
            assert status["investment_stance"] == (None if partial else "neutral")
            assert client.get(f"/api/runs/{run_id}/reader/record").json()["record"] == before
        finally:
            service.close()
