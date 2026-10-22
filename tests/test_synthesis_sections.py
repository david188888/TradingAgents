"""Section isolation, bounded repair, numeric replay and publication."""

import copy
import json
import time
from types import SimpleNamespace

import pytest

from tests.test_numeric_pipeline import NumericCaller, numeric_setup, run
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution import native_model as adapter
from tradingagents.execution.budget import BudgetBucket
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.research.numeric_integration import validate_record_numeric
from tradingagents.research.numeric_narrative import numeric_validation_context
from tradingagents.research.synthesis_sections import (
    UNFINISHED_ADJUDICATION,
    UNFINISHED_JUDGEMENT,
    candidate_result,
    parse_sections,
    validate_sectioned_proof,
)
from tradingagents.web.research_record_projection import project_research_record


@pytest.fixture
def sample(tmp_path):
    journal, seed = numeric_setup(tmp_path)
    caller = NumericCaller()
    run(journal, seed, caller)
    context = next(ctx for stage, ctx in caller.calls if stage == "synthesis")
    value = caller("synthesis", context)
    value["proposal"]["change_conditions"] = []
    return context, value


def test_bad_numeric_dimension_does_not_erase_other_sections(sample):
    context, value = sample
    value["proposal"]["dimensions"][0]["judgement"] = "收入增长25%"
    candidate = parse_sections(value, context, phase="main")
    assert candidate["failures"] == {"dimension:operating_quality": "numeric_literal_unbound"}
    proposal, proof = candidate_result(candidate, context)
    assert "25%" not in json.dumps(candidate) + json.dumps(proof)
    assert len(proof["receipts"]) == 6
    validate_sectioned_proof(proposal, proof, numeric_validation_context(context, sectioned=True))


def test_overall_failure_keeps_dimensions_and_has_only_host_unrated_prose(sample):
    context, value = sample
    value["proposal"]["judgement"] = "收入增长25%"
    candidate = parse_sections(value, context, phase="main")
    proposal, _ = candidate_result(candidate, context)
    assert candidate["failures"] == {"overall": "numeric_literal_unbound"}
    assert proposal["judgement"] == UNFINISHED_JUDGEMENT
    assert proposal["supporting_arguments"] == proposal["opposing_arguments"] == []
    assert all(d["judgement"] == "有条件的判断" for d in proposal["dimensions"])


def test_repair_only_fills_failed_sections_and_cannot_rewrite_main(sample):
    context, value = sample
    value["proposal"].pop("adjudications")
    first = parse_sections(value, context, phase="main")
    repaired = copy.deepcopy(value)
    repaired["proposal"]["adjudications"] = NumericCaller()("synthesis", context)["proposal"]["adjudications"]
    repaired["proposal"]["dimensions"][0]["judgement"] = "收入增长25%"
    second = parse_sections(repaired, context, phase="repair", previous=first)
    proposal, proof = candidate_result(second, context)
    assert not second["failures"]
    assert proposal["dimensions"][0]["judgement"] == "有条件的判断"
    assert all(r in second["receipts"] for r in first["receipts"])
    assert [r["section_id"] for r in proof["receipts"] if r["phase"] == "repair"] == [
        "adjudication:" + context["record"]["challenges"][0]["challenge_id"]]


def test_interruption_after_first_receipt_preserves_only_verified_section(sample):
    context, value = sample
    checkpoints = []

    def interrupted(candidate):
        checkpoints.append(copy.deepcopy(candidate))
        raise RuntimeError("simulated persistence interruption")

    with pytest.raises(RuntimeError, match="simulated persistence"):
        parse_sections(value, context, phase="main", on_progress=interrupted)
    assert len(checkpoints) == 1
    proposal, proof = candidate_result(checkpoints[0], context)
    assert len(proof["receipts"]) == 1
    assert proposal["judgement"] == UNFINISHED_JUDGEMENT
    assert len(proof["delivery"]["sections"]) == 7
    validate_sectioned_proof(proposal, proof, numeric_validation_context(context, sectioned=True))


@pytest.mark.parametrize("damage", ["prose", "receipt", "status", "scope"])
def test_changed_receipt_or_delivery_or_scope_cannot_validate(sample, damage):
    context, value = sample
    candidate = parse_sections(value, context, phase="main")
    proposal, proof = candidate_result(candidate, context)
    if damage == "prose":
        proposal["dimensions"][0]["judgement"] = "修改过的分析"
    elif damage == "receipt":
        proof["receipts"][0]["proof"]["fields"] = []
    elif damage == "status":
        proof["delivery"]["sections"][0].update(status="unavailable", phase=None, reason_code="missing_section")
    else:
        context["dimension_claim_ids"]["operating_quality"] = []
    with pytest.raises(ValueError):
        validate_sectioned_proof(proposal, proof, context)


def sdk_run(tmp_path, monkeypatch, *, repair="invalid", damage="adjudication", critical=True):
    journal, seed = numeric_setup(tmp_path, full=True)
    proposer = NumericCaller()
    prompts = []
    contexts = []

    def invoke(prompt):
        prompts.append(prompt)
        encoded, _ = json.JSONDecoder().raw_decode(prompt.split("Saved research context:\n", 1)[1])
        envelope = proposer("synthesis", encoded)
        envelope["proposal"]["change_conditions"] = []
        if len(prompts) == 1:
            if damage == "adjudication":
                envelope["proposal"].pop("adjudications")
            elif damage == "dimension":
                envelope["proposal"]["dimensions"][0]["judgement"] = "收入增长25%"
            else:
                envelope["proposal"]["judgement"] = "收入增长25%"
        elif repair == "invalid":
            return SimpleNamespace(content="not JSON")
        return SimpleNamespace(content=json.dumps(envelope), usage_metadata={"input_tokens": 10, "output_tokens": 10})

    monkeypatch.setattr(adapter, "create_llm_client", lambda **_: SimpleNamespace(
        get_llm=lambda: SimpleNamespace(invoke=invoke)))
    model = adapter.NativeModelCaller(effective_config={"llm_provider": "deepseek", "quick_think_llm": "quick",
        "deep_think_llm": "deep"}, run_id=seed.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)

    def routed(stage, context):
        if stage == "synthesis":
            contexts.append(copy.deepcopy(context))
            return model(stage, context)
        value = proposer(stage, context)
        if stage == "challenge" and not critical:
            for item in value["proposal"]["challenges"]:
                item["severity"] = "material"
        return value

    record = run(journal, seed, routed)
    return journal, record, model, contexts[0], prompts


@pytest.mark.parametrize("damage", ["adjudication", "overall"])
def test_failed_repair_publishes_unrated_retained_sections_and_roundtrips_reader(tmp_path, monkeypatch, damage):
    journal, record, model, context, prompts = sdk_run(tmp_path, monkeypatch, damage=damage)
    assert len(prompts) == 2
    assert record.assessment.report_status == "analysis_unrated"
    assert record.assessment.investment_stance is None
    assert record.assessment.synthesis_sections is not None
    assert record.assessment.quality == "LOW_CONFIDENCE"
    assert journal.ledger.consumed(BudgetBucket.STRUCTURED_REPAIR) == 1
    if damage == "adjudication":
        assert record.assessment.adjudications[0].rationale == UNFINISHED_ADJUDICATION
        assert record.assessment.judgement == "基于现有资料偏谨慎"
    else:
        assert record.assessment.judgement == UNFINISHED_JUDGEMENT
    validate_record_numeric(record, journal.state["identity"])
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    assert project_research_record(journal.observer.store, record.run_id)["state"] == "ready"
    from tradingagents.web.reader_process_projection import (
        project_reader_agent,
        project_reader_process,
    )
    assert project_reader_process(journal.observer.store, record.run_id)["availability"] == "ready"
    assert project_reader_agent(journal.observer.store, record.run_id, "synthesis")["availability"] == "available"
    fields = record.numeric_attribution.model_dump(mode="json")["final_fields"]
    host_path = (["assessment", "judgement"] if damage == "overall" else
                 ["assessment", "adjudications", 0, "rationale"])
    host = next(field for field in fields if field["path"] == host_path)
    assert host["kind"] == "host" and host["sources"] == []
    before = json.dumps(journal.state, sort_keys=True)
    assert model.recover_cached("synthesis", context) is not None
    assert json.dumps(journal.state, sort_keys=True) == before
    assert len(prompts) == 2
    assert run(journal, ResearchRecordV1.model_validate(journal.state["native_seed"]),
               lambda *_: pytest.fail("saved recovery must never call a model")) == record
    from tradingagents.runtime.reports import build_markdown_from_native_record
    exported = build_markdown_from_native_record(record, workflow_version="evidence-production-v7")
    assert "综合未完成" in exported
    assert "暂未形成总体评级" in exported
    from tradingagents.research.report_explanation import explanation_targets
    targets, _ = explanation_targets(record, {})
    if damage == "adjudication":
        assert "adjudication:" + record.dialogue.responses[0].response_id not in targets
    else:
        assert "assessment:judgement" not in targets
    # A crash before the completed SDK result is saved can recover progress
    # without a model call or mutation, including an expired/cancelled caller.
    saved_state = copy.deepcopy(journal.state)
    for key in ("native.adapter.synthesis", "native.synthesis.repair", "native.numeric.accepted.synthesis",
                "native.synthesis_sections.main", "native.synthesis_sections.repair"):
        journal.state["results"].pop(key, None)
    before = copy.deepcopy(journal.state)
    model.cancelled = lambda: True
    assert model.recover_cached("synthesis", context) is not None
    assert journal.state == before
    assert len(prompts) == 2
    journal.state.clear()
    journal.state.update(saved_state)


def test_successful_targeted_repair_restores_rating_and_schema_requests_only_adjudication(tmp_path, monkeypatch):
    _, record, _, _, prompts = sdk_run(tmp_path, monkeypatch, repair="good")
    assert record.assessment.investment_stance == "unfavorable"
    assert all(s.status == "accepted" for s in record.assessment.synthesis_sections.sections)
    assert "The host owns challenge_assessments" in prompts[0]
    assert "does not replace your adjudication" in prompts[0]
    envelope_schema, _ = json.JSONDecoder().raw_decode(prompts[1].split("Schema:\n", 1)[1])
    # Numeric envelope wraps the shallow proposal schema.
    schema = envelope_schema["properties"]["proposal"]
    assert set(schema["properties"]) == {"adjudications"}
    assert "Return ONLY the requested" in prompts[1]


def test_failed_noncritical_adjudication_keeps_valid_stance_but_partial_delivery(tmp_path, monkeypatch):
    _, record, _, _, _ = sdk_run(tmp_path, monkeypatch, critical=False)
    assert record.assessment.investment_stance == "unfavorable"
    assert record.assessment.report_status == "synthesized"
    assert record.assessment.completeness == "partial"


def test_unfinished_dimension_retains_status_through_publication_and_agent_projection(tmp_path, monkeypatch):
    journal, record, _, _, _ = sdk_run(tmp_path, monkeypatch, damage="dimension")
    assert record.assessment.investment_stance == "unfavorable"
    index = next(i for i, d in enumerate(record.assessment.dimensions) if "synthesis_section_unavailable" in d.limitations)
    assert record.assessment.dimensions[index].limitations == ("synthesis_section_unavailable",)
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    assert project_research_record(journal.observer.store, record.run_id)["state"] == "ready"
    from tradingagents.web.reader_process_projection import project_reader_agent
    assert project_reader_agent(journal.observer.store, record.run_id, "synthesis")["availability"] == "available"
    fields = record.numeric_attribution.model_dump(mode="json")["final_fields"]
    host = next(field for field in fields if field["path"] == ["assessment", "dimensions", index, "judgement"])
    assert host["kind"] == "host" and host["sources"] == []
