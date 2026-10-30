"""Conditions are selected within their owning hypothesis, with stable legacy bytes."""

import json

import pytest
from pydantic import ValidationError

from tests import test_native_model as model_tests
from tradingagents.agents.schemas._native_stage import ChallengeProposalV1
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import native_identity, validate_native_resume

journal = model_tests.journal


def challenge(**updates):
    return {"hypothesis_id": "h.one", "statement": "经营假设待核查", "severity": "minor",
            "risk_type": "operations", "proposed_test": "核对原始披露", **updates}


CONDITIONS = {
    "condition.b": {"hypothesis_id": "h.one", "text": "条件乙"},
    "condition.foreign": {"hypothesis_id": "h.two", "text": "另一假设"},
    "condition.a": {"hypothesis_id": "h.one", "text": "条件甲"},
}


@pytest.mark.parametrize("index,expected", [(0, "condition.a"), (1, "condition.b")])
def test_index_resolves_only_inside_selected_hypothesis(index, expected):
    from tradingagents.research.challenge_checks import resolve_challenge_condition
    item = ChallengeProposalV1.model_validate(challenge(condition_index=index))
    assert resolve_challenge_condition(item, CONDITIONS) == expected
    assert resolve_challenge_condition(item, dict(reversed(list(CONDITIONS.items())))) == expected


@pytest.mark.parametrize("updates", [
    {"condition_index": 2}, {"condition_index": 0, "condition_id": "condition.b"},
    {"condition_index": 0, "condition_id": "condition.foreign"},
    {"condition_id": "condition.foreign"}, {"condition_id": "invented"},
])
def test_invalid_or_inconsistent_reference_is_rejected(updates):
    from tradingagents.research.challenge_checks import (
        ChallengeValidationError,
        resolve_challenge_condition,
    )
    item = ChallengeProposalV1.model_validate(challenge(**updates))
    with pytest.raises(ChallengeValidationError, match="challenge_condition_reference"):
        resolve_challenge_condition(item, CONDITIONS)


@pytest.mark.parametrize("index", [-1, True, "0", 0.5])
def test_index_must_be_nonnegative_integer(index):
    with pytest.raises(ValidationError):
        ChallengeProposalV1.model_validate(challenge(condition_index=index))


def test_id_only_legacy_shape_is_byte_stable():
    from tradingagents.research.challenge_checks import resolve_challenge_condition
    item = ChallengeProposalV1.model_validate(challenge(condition_id="condition.a"))
    assert item.model_dump(mode="json") == challenge(condition_id="condition.a")
    assert resolve_challenge_condition(item, CONDITIONS) == "condition.a"


def test_new_identity_selects_index_and_unmarked_history_still_resumes(journal):
    request = AnalysisRequest("600519", "2026-09-30", research_profile="evidence_v1",
                              effective_config=model_tests.CONFIG)
    fresh = native_identity(request, workflow_version="evidence-production-v8")
    assert fresh["challenge_reference_policy"] == "hypothesis-condition-index-v1"
    journal.put("identity", fresh)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    old = {k: v for k, v in fresh.items() if k != "challenge_reference_policy"}
    journal.put("identity", old)
    validate_native_resume(journal.observer.store, journal.ledger.run_id, request)
    assert journal.state["identity"] == old


def test_new_prompt_exposes_index_choices_and_legacy_schema_is_unchanged(journal):
    from scripts.profile_native_inputs import prompt_parts
    ctx = {"conditions": CONDITIONS, "record": {"hypotheses": []}}
    journal.put("identity", {"workflow_version": "evidence-production-v8"})
    _, old_schema, _ = prompt_parts(model_tests.caller(journal)._prompt("challenge", ctx))
    assert "condition_index" not in json.dumps(old_schema)
    journal.put("identity", {"workflow_version": "evidence-production-v8",
        "challenge_reference_policy": "hypothesis-condition-index-v1"})
    prompt = model_tests.caller(journal)._prompt("challenge", ctx)
    _, schema, payload = prompt_parts(prompt)
    props = next(d["properties"] for d in schema["$defs"].values()
                 if "condition_index" in d.get("properties", {}))
    assert "condition_index" in props and "condition_id" not in props
    assert payload["condition_choices"]["h.one"][0]["text"] == "条件甲"


@pytest.mark.parametrize("reference", ["id", "index"])
def test_kernel_and_both_reader_projections_accept_same_condition(tmp_path, reference):
    from tests.test_unified_research import UnifiedCaller, run, setup
    from tests.web.test_reader_stage import first_saved
    from tradingagents.execution.native_publication import publish_native_record
    from tradingagents.web.reader_process_projection import project_reader_agent

    class SelectedCaller(UnifiedCaller):
        def __call__(self, stage, context):
            value = super().__call__(stage, context)
            if stage == "challenge":
                item = value["challenges"][0]
                cid = sorted(cid for cid, cond in context["conditions"].items()
                             if cond["hypothesis_id"] == item["hypothesis_id"])[0]
                item.update({"condition_id": cid} if reference == "id" else {"condition_index": 0})
            return value

    journal, seed = setup(tmp_path)
    record = run(journal, seed, SelectedCaller())
    assert len(record.challenges) == 1
    assert record.challenges[0].statement == "持续性不足"
    store = journal.observer.store
    stage = project_reader_agent(store, seed.run_id, "challenge",
        through=first_saved(store, seed.run_id, "native.challenge"))
    assert stage["availability"] == "stage_available"
    assert stage["stage_record"]["challenges"][0]["statement"] == "持续性不足"
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    published = project_reader_agent(store, seed.run_id, "challenge")
    assert published["availability"] == "available"
