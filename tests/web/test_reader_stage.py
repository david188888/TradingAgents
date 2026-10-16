"""Saved stage bodies qualify before final publication, without executing work."""

import copy
import json

import pytest

from tests.test_numeric_pipeline import NumericCaller, numeric_setup
from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.web.reader_process_projection import (
    _context,
    _process,
    project_reader_agent,
)

pytestmark = pytest.mark.unit


def first_saved(store, run_id, key):
    for event in store.read_events(run_id):
        if event.type == "artifact.written" and event.payload.get("kind") == "catalyst-checkpoint":
            cp = json.loads(store.read_artifact(run_id, event.payload["artifact_id"]))
            if key in cp or key in cp["results"]:
                return event.sequence
    raise AssertionError(key)


@pytest.mark.parametrize("numeric", [False, True])
def test_all_v7_stages_are_readable_at_their_own_saved_boundary(tmp_path, monkeypatch, numeric):
    journal, seed = numeric_setup(tmp_path, full=True) if numeric else setup(tmp_path, full=True)
    run(journal, seed, NumericCaller() if numeric else UnifiedCaller())
    store, run_id = journal.observer.store, seed.run_id
    events = store.read_events(run_id)
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("read must not persist"))
    monkeypatch.setattr("tradingagents.research.verification_tools.evaluate_condition", lambda *a: pytest.fail("read must not execute checks"))
    monkeypatch.setattr("tradingagents.graph.native_research.run_native_research", lambda *a, **k: pytest.fail("read must not run research"))
    stages = {"evidence": "native_seed", "operating_quality": "native.operating_quality",
        "event_context": "native.event_context", "market_context": "native.market_context",
        "challenge": "native.challenge", "code_checks": "verification.output",
        "response_operating_quality": "native.response_operating_quality", "synthesis": "native.synthesis"}
    for role, key in stages.items():
        if key.startswith("native.") and key not in journal.state["results"]:
            continue  # This fixture does not call a role without qualified inputs.
        boundary = first_saved(store, run_id, key)
        result = project_reader_agent(store, run_id, role, through=boundary)
        assert result["availability"] == "stage_available", (role, result["reason_code"])
        assert result["source_sequence"] == boundary
        assert result["stage_record"].get("assessment") is None
        assert result["relations"] == []
        assert result["reason_code"] == "stage_qualified"
        assert "native_input" not in json.dumps(result)
        summary = _process(_context(store, run_id, boundary)).model_dump(mode="json")
        meta = next(r for r in summary["roles"] if r["role_key"] == role)
        assert meta["output_availability"] == "stage_available"
        assert meta["output_sequence"] is not None
        assert "stage_record" not in json.dumps(summary)
    assert store.read_events(run_id) == events


def test_evidence_is_readable_before_kernel_input_or_specialist_fan_in(tmp_path):
    journal, seed = setup(tmp_path)
    journal.put("native_seed", seed.model_dump(mode="json"))
    result = project_reader_agent(journal.observer.store, seed.run_id, "evidence")
    assert result["availability"] == "stage_available"
    assert result["stage_record"]["claims"] == seed.model_dump(mode="json")["claims"]
    assert "native_input" not in journal.state


@pytest.mark.parametrize("damage", ["reference", "numeric_context", "numeric_proof", "conditions"])
def test_bad_stage_never_hides_independent_evidence_or_another_specialist(tmp_path, damage):
    journal, seed = numeric_setup(tmp_path, full=True)
    run(journal, seed, NumericCaller())
    cp = journal.state
    cp["results"].pop("native.output")
    if damage == "reference":
        cp["results"]["native.operating_quality"]["proposal"]["hypotheses"][0]["supporting_fact_ids"] = ["foreign-fact"]
    elif damage == "numeric_context":
        cp["results"]["native.numeric.accepted.operating_quality"]["context"]["facts"].pop()
    elif damage == "numeric_proof":
        cp["results"]["native.numeric.accepted.operating_quality"]["proposal"]["unknowns"] = ["tampered"]
    else:
        cp["native_conditions"] = {}
    journal.persist()
    store = journal.observer.store
    assert project_reader_agent(store, seed.run_id, "operating_quality")["availability"] == "unavailable"
    assert project_reader_agent(store, seed.run_id, "evidence")["availability"] == "stage_available"
    if damage != "conditions":
        assert project_reader_agent(store, seed.run_id, "event_context")["availability"] == "stage_available"


def test_accepted_original_indices_are_preserved_before_fan_in(tmp_path):
    journal, seed = setup(tmp_path)
    run(journal, seed, UnifiedCaller())
    cp = journal.state
    cp["results"].pop("native.output")
    cp.pop("native_conditions")
    from tradingagents.research.native_versions import SPECIALIST_REFERENCE_POLICY
    cp["identity"]["specialist_reference_policy"] = SPECIALIST_REFERENCE_POLICY
    cp["native_input"]["specialist_reference_policy"] = SPECIALIST_REFERENCE_POLICY
    proposal = cp["results"]["native.operating_quality"]["proposal"]
    cp["native.prompt.operating_quality"] = "a" * 64
    cp["results"]["native.specialist_accepted.operating_quality"] = {
        "prompt_sha256": "a" * 64, "proposal": copy.deepcopy(proposal), "indices": [1],
        "rejections": [{"index": 0, "code": "condition_evidence_reference"}]}
    journal.persist()
    result = project_reader_agent(journal.observer.store, seed.run_id, "operating_quality")
    expected = "i." + canonical_sha256({"input": cp["native_input"], "role": "operating_quality",
        "index": 1, "proposal": proposal["hypotheses"][0]})
    assert result["availability"] == "stage_available"
    assert result["claim_ids"] == [expected]


def test_corrupt_final_output_cannot_fall_back_to_stage_success(tmp_path):
    journal, seed = setup(tmp_path)
    run(journal, seed, UnifiedCaller())
    journal.state["results"]["native.output"]["identity"] = {}
    journal.persist()
    result = project_reader_agent(journal.observer.store, seed.run_id, "evidence")
    assert result["availability"] == "unavailable"
    assert result["stage_record"] is None


def test_unfinished_stage_and_future_boundary_remain_explicit(tmp_path):
    journal, seed = setup(tmp_path)
    journal.put("native_seed", seed.model_dump(mode="json"))
    store = journal.observer.store
    result = project_reader_agent(store, seed.run_id, "operating_quality")
    assert result["availability"] == "not_recorded"
    assert result["reason_code"] == "stage_pending"
    with pytest.raises(ValueError, match="reader_sequence_unavailable"):
        project_reader_agent(store, seed.run_id, "evidence", through=99999)


@pytest.mark.parametrize("damage", [None, "missing_outcome", "plan_condition"])
def test_saved_executed_verification_requires_exact_plan_and_outcome_coverage(tmp_path, damage):
    class CheckedCaller(UnifiedCaller):
        def __call__(self, stage, context):
            proposal = super().__call__(stage, context)
            if stage == "operating_quality":
                fact = next(f for f in context["facts"] if "收入" in f["statement"])
                proposal["hypotheses"][0]["conditions"][0]["check"] = {
                    "kind": "financial", "operation": "value", "current": {
                        "evidence_id": fact["evidence_ids"][0], "table": "income",
                        "field": "revenue", "report_period": "2026-06-30"},
                    "predicate": {"operator": "lt", "threshold": "110", "unit": "CNY"}}
            elif stage == "challenge":
                proposal["challenges"][0]["condition_id"] = next(iter(context["conditions"]))
            return proposal
    journal, seed = setup(tmp_path)
    run(journal, seed, CheckedCaller())
    journal.state["results"].pop("native.output")
    if damage == "missing_outcome":
        journal.state["results"]["verification.output"]["output"]["outcomes"] = []
    elif damage == "plan_condition":
        journal.state["verification_input"]["plan"]["tasks"][0]["condition_text"] = "not the saved condition"
    journal.persist()
    result = project_reader_agent(journal.observer.store, seed.run_id, "code_checks")
    if damage is None:
        assert result["availability"] == "stage_available"
        assert len(result["stage_record"]["verifications"]) == 1
    else:
        assert result["availability"] == "unavailable"
        assert result["stage_record"] is None
