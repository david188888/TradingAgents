"""Real SDK adapter → kernel → publication → Reader, with mocked transport."""

import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_native_pipeline import PipelineCaller
from tests.web.test_native_production_wiring import Sources, request
from tradingagents.execution.native_runner import NativeRunner
from tradingagents.runtime.catalyst_checkpoint import load_checkpoint
from tradingagents.runtime.store import RunStore
from tradingagents.web.manager import SingleRunManager
from tradingagents.web.reader_process_projection import project_reader_agent, project_reader_process
from tradingagents.web.research_record_projection import project_research_record


@pytest.mark.parametrize("all_invalid", [False, True])
def test_bad_reference_is_isolated_in_actual_adapter_and_published_reader(tmp_path, monkeypatch, all_invalid):
    delegate = PipelineCaller()
    calls = []
    def invoke(prompt):
        schema, _ = json.JSONDecoder().raw_decode(prompt.split("Schema:\n", 1)[1])
        context, _ = json.JSONDecoder().raw_decode(prompt.split("Saved research context:\n", 1)[1])
        title = schema.get("properties", {}).get("proposal", schema)["title"]
        if title == "SpecialistProposalV1":
            stage = context["view_scope"]["role"]
        elif title == "ResponsesProposalV1":
            stage = "response_" + context["role"]
        else:
            stage = "challenge" if title.startswith("Challenges") else "synthesis"
        calls.append(stage)
        if stage == "challenge" and all_invalid:
            value = {"proposal": {"challenges": []}, "plans": [], "structured_bindings": []}
        else:
            value = delegate(stage, context)
        if stage == "operating_quality":
            proposal = value["proposal"]
            bad = deepcopy(proposal["hypotheses"][0])
            bad["supporting_fact_ids"] = ["f.fabricated"]
            # Isolate the original reference gate. An unbound numeric operand
            # is now rejected earlier by the separate numeric scope gate.
            bad["conditions"] = [{"condition_role": "invalidation", "text": "后续经营恶化", "check": None}]
            proposal["hypotheses"] = [bad] if all_invalid else [bad, *proposal["hypotheses"]]
            for key in ("plans", "structured_bindings"):
                value[key] = [] if all_invalid else [
                    {**item, "field_path": item["field_path"].replace("hypotheses.0.", "hypotheses.1.")}
                    for item in value[key]]
        return SimpleNamespace(content=json.dumps(value, ensure_ascii=False),
            usage_metadata={"input_tokens": 10, "output_tokens": 20})
    def forbidden(*args, **kwargs):
        pytest.fail("publication test must not contact a provider")
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    monkeypatch.setattr("tradingagents.execution.native_model.create_llm_client", lambda **kwargs:
        SimpleNamespace(get_llm=lambda: SimpleNamespace(invoke=invoke)))
    monkeypatch.setattr("tradingagents.execution.native_runner.NativeRunner", lambda observer:
        NativeRunner(observer, sources_factory=Sources))
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_ENABLED", "true")
    manager = SingleRunManager(RunStore(tmp_path))
    run_id = manager.start(replace(request(), research_question=None)).run_id
    snapshot = manager.wait(run_id, 10)
    assert snapshot.status == "completed", snapshot.error_message
    published = project_research_record(manager.store, run_id)
    assert published["state"] == "ready"
    record = published["record"]
    assert record["assessment"]["completeness"] == "partial"
    assert record["assessment"]["quality"] == "LOW_CONFIDENCE"
    assert "fabricated" not in json.dumps(record)
    rejection = "native_hypothesis_rejected:operating_quality:specialist_fact_reference:0"
    assert rejection in record["limitations"]
    cp = load_checkpoint(manager.store, run_id)
    accepted = cp["results"]["native.specialist_accepted.operating_quality"]
    assert accepted["indices"] == ([] if all_invalid else [1])
    assert calls.count("operating_quality") == 2
    before = (list(calls), snapshot.latest_sequence)
    process = project_reader_process(manager.store, run_id)
    assert process["availability"] == ("partial" if all_invalid else "ready")
    agent = project_reader_agent(manager.store, run_id, "operating_quality")
    assert agent["availability"] == ("unavailable" if all_invalid else "available")
    if not all_invalid:
        assert len(agent["proposal"]["hypotheses"]) == len(agent["claim_ids"]) == 1
        claim = next(c for c in record["claims"] if c["claim_id"] == agent["claim_ids"][0])
        assert claim["statement"] == agent["proposal"]["hypotheses"][0]["statement"]
    else:
        assert "native_stage_unavailable:operating_quality" in record["limitations"]
    assert (calls, manager.store.read_snapshot(run_id).latest_sequence) == before
