"""Premise structure, arithmetic, isolation and honest semantic limits."""

from copy import deepcopy

import pytest

from tests.factual_premise_fixtures import bind
from tests.test_numeric_catalog import growth_record
from tests.test_numeric_narrative import envelope
from tests.test_numeric_pipeline import NumericCaller, numeric_setup, run
from tradingagents.agents.schemas._factual_premise import FACTUAL_PREMISE_POLICY
from tradingagents.agents.schemas._native_stage import SpecialistProposalV1
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.research.factual_premises import (
    public_premises,
    validate_context,
)
from tradingagents.research.numeric_integration import (
    attach_numeric_attribution,
    validate_record_numeric,
)
from tradingagents.research.numeric_narrative import (
    NumericNarrativeError,
    compile_numeric_stage,
    prepare_numeric_context,
    validate_numeric_stage,
)

IDENTITY = {"numeric_narrative_policy": "anchored-narrative-v1",
            "factual_premise_policy": FACTUAL_PREMISE_POLICY}


@pytest.fixture(scope="module")
def context():
    record = growth_record()
    return prepare_numeric_context("operating_quality",
        {"facts": [c.model_dump(mode="json") for c in record.claims if c.kind == "fact"], "metrics": []},
        record, identity=IDENTITY)


def proposal(context):
    obs = next(o for o in context["factual_observations"] if o["kind"] == "comparison" and "营业收入" in o["text"])
    value = envelope("收入扩张尚未转化为盈利的原因仍待识别", obs["fact_ids"])
    value = bind("operating_quality", value, context)
    value["premises"][0].update(observation_ids=[obs["observation_id"]],
        pending_questions=["销售费用是否增加，若增加，是否抵消部分规模收益？"])
    return value


def test_jianghuai_missing_expense_is_a_question_not_a_host_observation(context):
    assert not any("销售费用" in o["text"] for o in context["factual_observations"])
    value, proof = compile_numeric_stage("operating_quality", proposal(context), context, SpecialistProposalV1)
    field = next(f for f in proof["fields"] if f["path"] == "hypotheses.0.statement")
    assert value["hypotheses"][0]["statement"].startswith("解释假设：")
    assert field["premise"]["pending_questions"] == ["销售费用是否增加，若增加，是否抵消部分规模收益？"]
    assert "增加" in field["premise"]["observations"][0]["text"]
    validate_numeric_stage("operating_quality", value, proof, context, SpecialistProposalV1)


@pytest.mark.parametrize("damage,code", [
    ("missing", "premise_binding_missing"), ("unknown", "premise_observation_unknown"),
    ("scope", "premise_observation_scope"), ("empty", "premise_support_missing"),
    ("duplicate", "numeric_manifest_binding"), ("raw_quantity", "numeric_literal_unbound"),
])
def test_invalid_premises_are_rejected(context, damage, code):
    value = proposal(context)
    binding = value["premises"][0]
    if damage == "missing":
        value["premises"].pop(0)
    elif damage == "unknown":
        binding["observation_ids"] = ["o.invented_sales_expense_increase"]
    elif damage == "scope":
        fid = value["proposal"]["hypotheses"][0]["supporting_fact_ids"]
        other = next(o for o in context["factual_observations"] if not set(o["fact_ids"]) <= set(fid))
        binding["observation_ids"] = [other["observation_id"]]
    elif damage == "empty":
        binding["observation_ids"] = []
    elif damage == "duplicate":
        binding["observation_ids"] *= 2
    else:
        binding["pending_questions"] = ["费用是否增长25%？"]
    with pytest.raises(NumericNarrativeError) as caught:
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
    assert caught.value.code == code


def test_legacy_envelope_not_silently_admitted_and_legacy_bytes_unchanged(context):
    value = proposal(context)
    value.pop("premises")
    with pytest.raises(NumericNarrativeError, match="premise_binding_missing"):
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
    old = {k: v for k, v in context.items() if k not in {"factual_premise_policy", "factual_observations"}}
    _, proof = compile_numeric_stage("operating_quality", value, old, SpecialistProposalV1)
    assert "premises" not in proof["envelope"]
    assert all("premise" not in f for f in proof["fields"])


def test_bad_sibling_isolated_and_pending_text_not_leaked(context):
    value = proposal(context)
    good = deepcopy(value["proposal"]["hypotheses"][0])
    value["proposal"]["hypotheses"].append(good)
    value["premises"] += [{**p, "field_path": p["field_path"].replace(".0.", ".1.")}
                          for p in deepcopy(value["premises"])]
    value["premises"][0]["observation_ids"] = ["o.invented"]
    compiled, proof = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)
    assert proof["indices"] == [1]
    assert proof["rejections"] == [{"index": 0, "code": "premise_observation_unknown"}]
    assert "o.invented" not in str(proof)
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)


def two_hypotheses(context):
    value = proposal(context)
    value["proposal"]["hypotheses"].append(deepcopy(value["proposal"]["hypotheses"][0]))
    value["premises"] += [{**p, "field_path": p["field_path"].replace(".0.", ".1.")}
                          for p in deepcopy(value["premises"])]
    return value


@pytest.mark.parametrize("damage,issue", [
    ("unknown", "unknown_path"), ("duplicate", "duplicate_path"),
])
def test_wrong_premise_path_inside_one_hypothesis_rejects_only_that_sibling(context, damage, issue):
    value = two_hypotheses(context)
    first = next(p for p in value["premises"] if p["field_path"].startswith("hypotheses.0."))
    path = {"unknown": "hypotheses.0.invented",
            "duplicate": first["field_path"]}[damage]
    value["premises"].append({**first, "field_path": path})
    issues = []
    compiled, proof = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1,
                                            isolate=True, issues=issues)
    assert proof["indices"] == [1]
    assert proof["rejections"] == [{"index": 0, "code": "premise_binding_invalid"}]
    assert issues == [{"index": 0, "binding_issue": issue}]
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)
    with pytest.raises(NumericNarrativeError) as caught:  # whole-stage callers keep the strict contract
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
    assert (caught.value.code, caught.value.binding_issue) == ("premise_binding_invalid", issue)


@pytest.mark.parametrize("isolate", [False, True])
@pytest.mark.parametrize("path", ["unknowns", "unknowns.0", "hypotheses.0.conditions.0.text"])
def test_redundant_premises_on_existing_non_premise_fields_are_discarded(context, isolate, path):
    value = two_hypotheses(context)
    value["proposal"]["unknowns"] = ["费用变化仍待核查"]
    expected, expected_proof = compile_numeric_stage(
        "operating_quality", value, context, SpecialistProposalV1, isolate=isolate)
    original = deepcopy(value)
    value["premises"].append({**value["premises"][0], "field_path": path,
                              "observation_ids": ["o.unused"], "pending_questions": ["unused question"]})
    compiled, proof = compile_numeric_stage(
        "operating_quality", value, context, SpecialistProposalV1, isolate=isolate)
    assert compiled == expected
    assert proof == expected_proof
    assert proof["indices"] == [0, 1]
    assert proof["rejections"] == []
    assert value["premises"][:-1] == original["premises"]  # caller input stays intact
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)


def test_ignored_unknown_binding_does_not_admit_unbound_quantity(context):
    value = proposal(context)
    value["proposal"]["unknowns"] = ["费用增长25%仍待核查"]
    value["premises"].append({**value["premises"][0], "field_path": "unknowns.0"})
    with pytest.raises(NumericNarrativeError, match="numeric_literal_unbound"):
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)


@pytest.mark.parametrize("path", ["unknowns.0", "hypotheses.0.conditions.0.text"])
@pytest.mark.parametrize("damage", ["observations", "questions", "type"])
def test_redundant_premise_contents_are_discarded_before_envelope_validation(context, path, damage):
    value = proposal(context)
    value["proposal"]["unknowns"] = ["经营持续性仍待查"]
    expected, expected_proof = compile_numeric_stage(
        "operating_quality", value, context, SpecialistProposalV1, isolate=True)
    extra = {**value["premises"][0], "field_path": path}
    if damage == "observations":
        extra["observation_ids"] = ["o.unused"] * 7
    elif damage == "questions":
        extra["pending_questions"] = ["unused question"] * 4
    else:
        extra["observation_ids"] = "not an array"
    value["premises"].append(extra)
    before = deepcopy(value)
    compiled, proof = compile_numeric_stage(
        "operating_quality", value, context, SpecialistProposalV1, isolate=True)
    assert (compiled, proof) == (expected, expected_proof)
    assert value == before
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)


@pytest.mark.parametrize("path", ["hypotheses.0.statement", "proposal.unknowns.0",
                                  "unknowns.9", "unknowns_typo"])
def test_malformed_required_or_unaddressable_premises_still_reject(context, path):
    value = proposal(context)
    value["proposal"]["unknowns"] = ["经营持续性仍待查"]
    value["premises"].append({"field_path": path, "observation_ids": ["o.unused"] * 7,
                              "pending_questions": []})
    with pytest.raises(NumericNarrativeError):
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)


def test_challenge_discards_redundant_binding_before_item_validation(context):
    from tradingagents.agents.schemas._native_stage import ChallengesProposalV3
    ctx = {**context, "challenge_check_policy": "hypothesis-directed-checks-v1"}
    value = {"proposal": {"challenges": []}, "premises": []}
    expected = compile_numeric_stage("challenge", value, ctx, ChallengesProposalV3, isolate=True)
    value["premises"] = [{"field_path": "challenges", "observation_ids": "unused malformed content"}]
    compiled, proof = compile_numeric_stage("challenge", value, ctx, ChallengesProposalV3, isolate=True)
    assert (compiled, proof) == expected
    validate_numeric_stage("challenge", compiled, proof, ctx, ChallengesProposalV3)


@pytest.mark.parametrize("path", ["proposal.challenges", "challenges.9.rationale", "unknowns_typo"])
def test_challenge_rejects_unaddressable_premise_before_item_partition(context, path):
    from tradingagents.agents.schemas._native_stage import ChallengesProposalV3
    ctx = {**context, "challenge_check_policy": "hypothesis-directed-checks-v1"}
    value = {"proposal": {"challenges": []}, "premises": [
        {"field_path": path, "observation_ids": [], "pending_questions": []}]}
    with pytest.raises(NumericNarrativeError):
        compile_numeric_stage("challenge", value, ctx, ChallengesProposalV3, isolate=True)


@pytest.mark.parametrize("path,issue", [
    ("hypotheses.2.statement", "index_out_of_range"), ("proposal.hypotheses.0.statement", "proposal_prefix"),
    ("summary", "unknown_path"), ("unknowns.0", "index_out_of_range"),
    ("proposal.unknowns", "proposal_prefix"), ("unknowns_typo", "unknown_path"),
    ("hypotheses.0.conditions.5.text", "index_out_of_range"),
])
def test_unaddressable_premise_paths_still_reject_the_stage(context, path, issue):
    value = two_hypotheses(context)
    value["premises"].append({**value["premises"][0], "field_path": path})
    with pytest.raises(NumericNarrativeError) as caught:
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)
    assert (caught.value.code, caught.value.binding_issue) == ("premise_binding_invalid", issue)


def test_wrong_structured_binding_inside_one_hypothesis_rejects_only_that_sibling(context):
    value = two_hypotheses(context)
    value["structured_bindings"] = [{"field_path": "hypotheses.0.conditions.0.check.predicate",
                                     "kind": "num", "alias": "n_invented"}]
    issues = []
    compiled, proof = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1,
                                            isolate=True, issues=issues)
    assert proof["indices"] == [1]
    assert proof["rejections"] == [{"index": 0, "code": "numeric_plan_mismatch"}]
    assert issues == [{"index": 0, "binding_issue": "unknown_path"}]
    validate_numeric_stage("operating_quality", compiled, proof, context, SpecialistProposalV1)
    value["structured_bindings"][0]["field_path"] = "hypotheses.5.conditions.0.check.predicate"
    with pytest.raises(NumericNarrativeError) as caught:
        compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1, isolate=True)
    assert (caught.value.code, caught.value.binding_issue) == ("numeric_plan_mismatch", "index_out_of_range")


def test_binding_issue_diagnostic_is_a_closed_label():
    from tradingagents.execution.native_model_diagnostics import safe_model_diagnostic
    error = NumericNarrativeError("premise_binding_invalid", binding_issue="index_out_of_range")
    assert safe_model_diagnostic("operating_quality", "main", "x", error)["binding_issue"] == "index_out_of_range"
    error.binding_issue = "hypotheses.0.model text"
    assert "binding_issue" not in safe_model_diagnostic("operating_quality", "main", "x", error)


def test_tampered_observation_direction_is_not_a_saved_fact(context):
    record = growth_record()
    changed = deepcopy(context)
    obs = next(o for o in changed["factual_observations"] if o["kind"] == "comparison")
    obs["text"] += "反向叙述"
    with pytest.raises(ValueError, match="observations changed"):
        validate_context(record, "operating_quality", changed, IDENTITY)


@pytest.mark.parametrize("base", ["0", "-1000000000", "1184000000", "2000000000"])
def test_direction_uses_difference_even_with_nonpositive_base(base):
    record = growth_record(base=base)
    ctx = prepare_numeric_context("operating_quality",
        {"facts": [c.model_dump(mode="json") for c in record.claims]}, record, identity=IDENTITY)
    observations = [o for o in ctx["factual_observations"] if o["kind"] == "comparison" and "营业收入" in o["text"]]
    expected = "增加" if base in {"0", "-1000000000"} else "不变" if base == "1184000000" else "减少"
    assert observations and all(expected in o["text"] for o in observations)
    assert all("改善" not in o["text"] for o in observations)


def test_free_prose_entailment_is_explicitly_outside_machine_guarantee(context):
    # Known semantic false negative, deliberately NOT advertised as a rejection.
    value = proposal(context)
    value["proposal"]["hypotheses"][0]["statement"] = "销售费用增加可能抵消规模收益"
    compiled, proof = compile_numeric_stage("operating_quality", value, context, SpecialistProposalV1)
    assert compiled["hypotheses"][0]["statement"].startswith("解释假设：")
    field = next(f for f in proof["fields"] if f["path"] == "hypotheses.0.statement")
    assert not any("销售费用" in o["text"] for o in field["premise"]["observations"])


class PremiseCaller(NumericCaller):
    def __call__(self, stage, context):
        value = super().__call__(stage, context)
        if stage == "synthesis":
            value["proposal"]["key_claim_ids"] = value["proposal"]["opposing_arguments"][0]["claim_ids"]
        value = bind(stage, value, context)
        if "unknowns" in value["proposal"]:
            value["premises"].append({"field_path": "unknowns", "observation_ids": ["o.unused"],
                                      "pending_questions": []})
        return value


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    journal, seed = numeric_setup(tmp_path_factory.mktemp("premises"), full=True)
    journal.state["identity"].update(IDENTITY)
    seed = attach_numeric_attribution(seed, journal)
    caller = PremiseCaller()
    record = run(journal, seed, caller)
    return journal, seed, caller, record


def test_pipeline_replay_publication_and_export(completed):
    from tradingagents.execution.native_publication import publish_native_record
    from tradingagents.runtime.reports import build_markdown_from_native_record
    from tradingagents.web.research_record_projection import project_research_record
    journal, seed, caller, record = completed
    assert record.assessment.report_status == "synthesized"
    assert all(ctx["factual_premise_policy"] == FACTUAL_PREMISE_POLICY for _, ctx in caller.calls)
    assert public_premises(record)
    assert "o.unused" not in record.model_dump_json()
    validate_record_numeric(record, journal.state["identity"])
    assert run(journal, seed, lambda *_: pytest.fail("replay invoked model")) == record
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
                         publication_authorizer=lambda j: j.put("publication_authorized", True))
    assert project_research_record(journal.observer.store, record.run_id)["state"] == "ready"
    markdown = build_markdown_from_native_record(record, workflow_version=journal.state["identity"]["workflow_version"])
    assert "观察、解释与待验证前提" in markdown
    assert "解释的含义和因果尚未证实" in markdown


def test_missing_or_modified_receipt_rejected(completed):
    _, _, _, record = completed
    raw = record.model_dump(mode="json")
    stage = next(s for s in raw["numeric_attribution"]["stages"] if s["proof"]["fields"])
    field = next(f for f in stage["proof"]["fields"] if f.get("premise"))
    field["premise"]["observations"][0]["text"] = "伪造观察"
    with pytest.raises(ValueError):
        ResearchRecordV1.model_validate(raw)


def test_sections_reject_bad_binding_without_erasing_siblings(completed):
    from tradingagents.research.synthesis_sections import (
        candidate_result,
        parse_sections,
        validate_sectioned_proof,
    )
    _, _, caller, _ = completed
    ctx = next(c for s, c in caller.calls if s == "synthesis")
    value = caller("synthesis", ctx)
    value["proposal"]["change_conditions"] = []
    bad = next(b for b in value["premises"] if b["field_path"] == "dimensions.0.judgement")
    bad["observation_ids"] = ["o.forged"]
    candidate = parse_sections(value, ctx, phase="main")
    assert candidate["failures"] == {"dimension:operating_quality": "premise_observation_unknown"}
    proposal, proof = candidate_result(candidate, ctx)
    validate_sectioned_proof(proposal, proof, ctx)
    assert proof["receipts"]


def test_sections_discard_overlong_redundant_premise_before_shared_validation(completed):
    from tradingagents.research.synthesis_sections import (
        candidate_result,
        parse_sections,
        validate_sectioned_proof,
    )
    _, _, caller, _ = completed
    ctx = next(c for s, c in caller.calls if s == "synthesis")
    value = caller("synthesis", ctx)
    value["proposal"]["change_conditions"] = []
    expected = parse_sections(value, ctx, phase="main")
    value["premises"].append({"field_path": "dimensions.0.limitations",
        "observation_ids": ["o.unused"] * 7, "pending_questions": ["unused"] * 4})
    candidate = parse_sections(value, ctx, phase="main")
    assert candidate == expected
    compiled, proof = candidate_result(candidate, ctx)
    validate_sectioned_proof(compiled, proof, ctx)


@pytest.mark.parametrize("path", ["proposal.judgement", "dimensions.99.judgement", "unknowns_typo"])
def test_sections_reject_unaddressable_premise_before_partition(completed, path):
    from tradingagents.research.synthesis_sections import parse_sections
    _, _, caller, _ = completed
    ctx = next(c for s, c in caller.calls if s == "synthesis")
    value = caller("synthesis", ctx)
    value["premises"].append({"field_path": path, "observation_ids": [], "pending_questions": []})
    with pytest.raises(NumericNarrativeError):
        parse_sections(value, ctx, phase="main")


def test_new_policy_stage_reader_retains_binding_without_writes(completed, monkeypatch):
    from tests.web.test_reader_stage import first_saved
    from tradingagents.web.reader_process_projection import project_reader_agent
    journal, seed, _, _ = completed
    store = journal.observer.store
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("stage read wrote data"))
    for role in ("operating_quality", "challenge", "response_operating_quality", "synthesis"):
        if "native." + role not in journal.state["results"]:
            continue
        boundary = first_saved(store, seed.run_id, "native." + role)
        response = project_reader_agent(store, seed.run_id, role, through=boundary)
        assert response["availability"] == "stage_available", (role, response["reason_code"])
        assert response["stage_record"].get("assessment") is None
        assert response["factual_premises"], role


def test_new_policy_resume_does_not_upgrade_historical_identity():
    from tests.web.test_native_production_wiring import request
    from tradingagents.execution.native_runner import native_identity
    old = native_identity(request(), factual_premise_policy=False)
    new = native_identity(request())
    assert new.pop("factual_premise_policy") == FACTUAL_PREMISE_POLICY
    assert "research_delivery_policy" not in old
    assert new.pop("research_delivery_policy")["version"] == "evidence-packets-v1"
    assert old == new


@pytest.mark.parametrize("damage", [None, "identity_policy", "missing_identity_policy", "missing_input_policy", "input_policy", "output_policy"])
def test_final_reader_requires_matching_premise_identity(completed, monkeypatch, damage):
    from tradingagents.execution.native_publication import publish_native_record
    from tradingagents.web import reader_process_projection as projection

    journal, seed, _, record = completed
    store = journal.observer.store
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    checkpoint = deepcopy(journal.state)
    checkpoint["results"]["native.output"]["identity"] = deepcopy(checkpoint["results"]["native.output"]["identity"])
    if damage == "identity_policy":
        checkpoint["identity"]["factual_premise_policy"] = "unknown-premise-policy"
    elif damage == "missing_identity_policy":
        checkpoint["identity"].pop("factual_premise_policy")
    elif damage == "missing_input_policy":
        checkpoint["native_input"].pop("factual_premise_policy")
    elif damage == "input_policy":
        checkpoint["native_input"]["factual_premise_policy"] = "unknown-premise-policy"
    elif damage == "output_policy":
        checkpoint["results"]["native.output"]["identity"]["factual_premise_policy"] = "unknown-premise-policy"
    monkeypatch.setattr(projection, "load_checkpoint", lambda *a, **k: checkpoint)
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("Reader must not write"))
    before = store.read_events(seed.run_id)
    result = projection.project_reader_agent(store, seed.run_id, "synthesis")
    assert result["availability"] == ("unavailable" if damage else "available"), result
    if damage:
        assert result["reason_code"] == "output_identity_unavailable"
        assert result["proposal"] is None and result["stage_record"] is None
        assert not result["factual_premises"]
    assert store.read_events(seed.run_id) == before


def test_structured_previous_sign_keeps_previous_period():
    from tests.test_structured_financial_checks import record as structured_record
    source = structured_record()
    ctx = prepare_numeric_context("operating_quality", {"facts": [c.model_dump(mode="json") for c in source.claims]},
                                  source, identity=IDENTITY)
    anchors = {a["anchor_id"]: a for a in ctx["numeric_catalog"]["anchors"]}
    previous = [o for o in ctx["factual_observations"] if o["anchor_id"]
                and anchors[o["anchor_id"]]["definition_key"].startswith("check.")
                and anchors[o["anchor_id"]]["definition_key"].endswith("_previous")]
    assert previous
    for observation in previous:
        meta = anchors[observation["anchor_id"]]["metadata"]
        assert f"（{meta['prior_period']}）" in observation["text"]
        assert f"（{meta['report_period']}）" not in observation["text"]


def test_conflicting_suppliers_retain_attributed_sources_without_direction():
    from tests.test_structured_financial_checks import payload, record as structured_record
    from tradingagents.research.evidence_freeze import CAP_FUNDAMENTALS
    second = payload()
    second["cashflow"][0]["n_cashflow_act"] = "31"
    source = structured_record(extra=((CAP_FUNDAMENTALS, "sina.financial_statements", second, None),))
    ctx = prepare_numeric_context("operating_quality", {"facts": [c.model_dump(mode="json") for c in source.claims]},
                                  source, identity=IDENTITY)
    conflicts = {e for c in source.evidence_checks.checks if c.status == "conflict" for e in c.evidence_ids}
    affected = [o for o in ctx["factual_observations"] if conflicts.intersection(o["evidence_ids"])]
    assert affected and all(o["kind"] == "source" for o in affected)
    assert all("相关来源存在冲突，不作为无争议的统一事实" in o["limitations"] for o in affected)
