"""Offline numeric publication boundaries and native pipeline regression checks."""

import copy
import json
import time
from pathlib import Path

import pytest

from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.research.native_versions import (
    NUMERIC_NARRATIVE_POLICY,
    SPECIALIST_REFERENCE_POLICY,
)
from tradingagents.research.numeric_integration import (
    attach_numeric_attribution,
    validate_record_numeric,
)
from tradingagents.web.research_record_projection import project_research_record

POLICY = "anchored-narrative-v1"
OLD_V7_SHA256 = "9e9802c8933fef7402e92cea96011c4148870cb0dee91118805184c0739c0f61"


def test_existing_v7_record_serialization_retains_its_pre_numeric_digest():
    fixture = Path(__file__).resolve().parents[1] / "frontend/src/test/fixtures/unified-research-v7.json"
    record = ResearchRecordV1.model_validate_json(fixture.read_text())
    assert "numeric_attribution" not in record.model_dump(mode="json")
    assert canonical_sha256(record) == OLD_V7_SHA256
    assert len(record.model_dump_json()) == 9995


def test_numeric_retained_summary_never_truncates_a_quantity(monkeypatch):
    from types import SimpleNamespace

    from tradingagents.research import report_delivery

    statement = "经营观察 " + "持续核查 " * 85 + "18.40%（同比）"
    assert len("已保存基础观察：" + statement) > 400
    record = SimpleNamespace(
        claims=(SimpleNamespace(claim_id="fact.1", kind="fact", statement=statement),),
        hypotheses=(),
    )
    monkeypatch.setattr(report_delivery, "dimension_claim_ids", lambda _record: {"operating_quality": ("fact.1",)})
    monkeypatch.setattr(report_delivery, "dimension_policy", lambda _record, **_kwargs: {
        "operating_quality": ("conditional", "资料缺口")
    })
    monkeypatch.setattr(report_delivery, "excluded_support", lambda _record: set())
    monkeypatch.setattr(report_delivery, "gate_dimensions", lambda _record, dimensions, **_kwargs: tuple(dimensions))

    dimensions, claim_ids = report_delivery.retained_summary(record, numeric_policy=True)

    assert dimensions[0].judgement == "已保留本维度的有效专项产物；完整观点与数值依据见对应引用。"
    assert claim_ids == ("fact.1",)
    assert record.claims[0].statement.endswith("18.40%（同比）")


def test_legacy_retained_summary_keeps_its_existing_length_limit(monkeypatch):
    from types import SimpleNamespace

    from tradingagents.research import report_delivery

    statement = "经营观察 " + "持续核查 " * 45 + "18.40%（同比）"
    record = SimpleNamespace(
        claims=(SimpleNamespace(claim_id="fact.1", kind="fact", statement=statement),),
        hypotheses=(),
    )
    monkeypatch.setattr(report_delivery, "dimension_claim_ids", lambda _record: {"operating_quality": ("fact.1",)})
    monkeypatch.setattr(report_delivery, "dimension_policy", lambda _record, **_kwargs: {
        "operating_quality": ("conditional", "资料缺口")
    })
    monkeypatch.setattr(report_delivery, "excluded_support", lambda _record: set())
    monkeypatch.setattr(report_delivery, "gate_dimensions", lambda _record, dimensions, **_kwargs: tuple(dimensions))

    dimensions, _ = report_delivery.retained_summary(record)

    assert dimensions[0].judgement == ("已保存基础观察：" + statement)[:400]


def _numeric_publication_boundary(tmp_path, monkeypatch, *, damage=None):
    """Isolate barrier validation from the independently tested numeric verifier."""
    from tradingagents.research import numeric_integration

    journal, seed = setup(tmp_path)
    record = run(journal, seed, UnifiedCaller())
    candidate = record.model_dump(mode="json")
    journal.state["identity"]["numeric_narrative_policy"] = POLICY
    journal.state.update(native_publication_candidate=candidate,
                         native_publication_authorized_candidate_sha256=canonical_sha256(candidate),
                         publication_authorized=True)
    if damage == "candidate":
        journal.state["native_publication_candidate"] = copy.deepcopy(candidate)
        journal.state["native_publication_candidate"]["assessment"]["judgement"] = "different candidate"
    elif damage == "authorization":
        journal.state["native_publication_authorized_candidate_sha256"] = "0" * 64
    elif damage == "unauthorized":
        journal.state["publication_authorized"] = False
    elif damage == "policy":
        journal.state["identity"]["numeric_narrative_policy"] = "unknown-policy"
    journal.persist()
    barrier = journal.last_event
    store = journal.observer.store
    snapshot = store.read_snapshot(record.run_id)
    store.write_snapshot_atomic(snapshot.evolve(metadata={**snapshot.metadata, "numeric_narrative_policy": POLICY}))
    promote_derived_public_artifact(journal.observer, contract="research-record-v1", value=record,
        graph_task_id="native.final", checkpoint_event_id="missing-barrier" if damage == "parent" else barrier.event_id,
        committed_sequence=barrier.sequence + (1 if damage == "sequence" else 0), promoted=set())
    seen = []

    def validated(value, identity):
        assert value == record
        assert identity["numeric_narrative_policy"] == POLICY
        seen.append(copy.deepcopy(identity))

    monkeypatch.setattr(numeric_integration, "validate_record_numeric", validated)
    return journal, record, barrier, seen


def test_numeric_reader_uses_publication_barrier_without_read_side_effects(tmp_path, monkeypatch):
    journal, record, _, seen = _numeric_publication_boundary(tmp_path, monkeypatch)
    store = journal.observer.store
    publication_sequence = store.read_snapshot(record.run_id).latest_sequence
    before = store.read_events(record.run_id)
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("Reader cannot write"))
    response = project_research_record(store, record.run_id, through=publication_sequence)
    assert response["state"] == "ready"
    assert response["record"] == record.model_dump(mode="json")
    assert seen and store.read_events(record.run_id) == before


@pytest.mark.parametrize("damage", ["candidate", "authorization", "unauthorized", "policy", "parent", "sequence"])
def test_numeric_reader_rejects_detached_or_unauthorized_publication(tmp_path, monkeypatch, damage):
    journal, record, _, seen = _numeric_publication_boundary(tmp_path, monkeypatch, damage=damage)
    response = project_research_record(journal.observer.store, record.run_id)
    assert response["state"] == "unavailable" and response["reason_code"] == "corrupt"
    assert seen == []


def test_numeric_reader_old_sequence_ignores_newer_checkpoint_state(tmp_path, monkeypatch):
    journal, record, _, seen = _numeric_publication_boundary(tmp_path, monkeypatch)
    store = journal.observer.store
    sequence = store.read_snapshot(record.run_id).latest_sequence
    journal.state["identity"]["numeric_narrative_policy"] = "future-policy"
    journal.persist()
    response = project_research_record(store, record.run_id, through=sequence)
    assert response["state"] == "ready"
    assert seen[0]["numeric_narrative_policy"] == POLICY


def numeric_setup(tmp_path, *, full=False):
    journal, seed = setup(tmp_path, full=full, delivery=True)
    journal.state["identity"].update(numeric_narrative_policy=NUMERIC_NARRATIVE_POLICY,
        specialist_reference_policy=SPECIALIST_REFERENCE_POLICY)
    return journal, attach_numeric_attribution(seed, journal)


class NumericCaller(UnifiedCaller):
    def __init__(self, *, invalid_stage=None, **kwargs):
        super().__init__(**kwargs)
        self.invalid_stage = invalid_stage

    def __call__(self, stage, context):
        proposal = super().__call__(stage, context)
        if stage == self.invalid_stage:
            if stage in {"operating_quality", "event_context", "market_context"}:
                proposal["hypotheses"][0]["statement"] = "营收增长25%"
            elif stage == "challenge":
                proposal["challenges"][0]["statement"] = "营收增长25%"
            elif stage.startswith("response_"):
                proposal["responses"][0]["rationale"] = "营收增长25%"
            else:
                proposal["judgement"] = "营收增长25%"
        return {"proposal": proposal, "plans": [], "structured_bindings": []}


def test_numeric_whole_chain_publication_replay_and_old_bytes(tmp_path):
    journal, seed = numeric_setup(tmp_path, full=True)
    caller = NumericCaller()
    record = run(journal, seed, caller)
    assert record.assessment.report_status == "synthesized"
    assert {s.stage for s in record.numeric_attribution.stages} == {
        stage for stage, _ in caller.calls
    }
    validate_record_numeric(record, journal.state["identity"])
    before_calls = len(caller.calls)
    assert run(journal, seed, lambda *_: pytest.fail("replay must not invoke")) == record
    assert len(caller.calls) == before_calls
    from tradingagents.execution.native_publication import publish_native_record
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
                         publication_authorizer=lambda j: j.put("publication_authorized", True))
    projected = project_research_record(journal.observer.store, record.run_id)
    assert projected["state"] == "ready"
    assert projected["record"] == record.model_dump(mode="json")


@pytest.mark.parametrize("damage", [None, "duplicate", "missing", "changed"])
def test_final_numeric_field_bindings_use_paths_not_process_iteration_order(tmp_path, damage):
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, NumericCaller())
    raw = record.model_dump(mode="json")
    fields = raw["numeric_attribution"]["final_fields"]
    fields.reverse()  # Historic processes emitted different set iteration orders.
    if damage == "duplicate":
        fields.append(copy.deepcopy(fields[0]))
    elif damage == "missing":
        fields.pop()
    elif damage == "changed":
        fields[0]["text_sha256"] = "0" * 64
    if damage is None:
        restored = ResearchRecordV1.model_validate(raw)
        assert restored.model_dump(mode="json") == raw  # Do not rewrite history.
    else:
        with pytest.raises(ValueError, match="numeric final field binding changed"):
            ResearchRecordV1.model_validate(raw)


@pytest.mark.parametrize("stage", ["operating_quality", "challenge", "response_operating_quality", "synthesis"])
def test_invalid_quantity_degrades_own_stage_and_keeps_saved_basics(tmp_path, stage):
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, NumericCaller(invalid_stage=stage))
    assert "25%" not in json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
    assert record.company_basics == seed.company_basics
    assert record.assessment.quality == "LOW_CONFIDENCE"
    if stage == "synthesis":
        assert record.assessment.investment_stance is None
        assert record.assessment.report_status == "specialist_summary"


def test_receipt_and_record_prose_tamper_are_both_rejected(tmp_path):
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, NumericCaller())
    for mutate in (
        lambda raw: raw["numeric_attribution"]["stages"][0]["proof"].update(fields=[]),
        lambda raw: raw["claims"][-1].update(statement="营收增长25%"),
        lambda raw: raw["assessment"].update(judgement="营收增长25%"),
    ):
        raw = record.model_dump(mode="json")
        mutate(raw)
        with pytest.raises(ValueError):
            changed = ResearchRecordV1.model_validate(raw)
            validate_record_numeric(changed, journal.state["identity"])


def test_focus_uses_independent_numeric_receipt_and_invalid_focus_keeps_baseline(tmp_path):
    from tradingagents.execution.native_focus import execute_focus_response
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, NumericCaller())
    before = canonical_sha256(record)
    def good(stage, context):
        return {"proposal": {"answer": "经营持续性仍待核查", "answerability": "partial",
            "claim_ids": [record.claims[0].claim_id], "limitations": ["仅依据保存资料"]}}
    response = execute_focus_response(record, "增长是否持续？", ledger=journal.ledger, caller=good,
        cancelled=lambda: False, deadline=lambda: time.monotonic()+30)
    assert response.status == "available" and response.numeric_attribution is not None
    assert canonical_sha256(record) == before
    from tradingagents.agents.schemas._research_focus import validate_focus_response
    validate_focus_response(record, response)
    journal, seed = numeric_setup(tmp_path / "invalid")
    record = run(journal, seed, NumericCaller())
    def bad(stage, context):
        return {"proposal": {"answer": "营收增长25%", "answerability": "partial",
            "claim_ids": [record.claims[0].claim_id], "limitations": ["仅依据保存资料"]}}
    response = execute_focus_response(record, "增长是否持续？", ledger=journal.ledger, caller=bad,
        cancelled=lambda: False, deadline=lambda: time.monotonic()+30)
    assert response.status == "unavailable" and response.reason_code == "invalid_response"
    assert response.numeric_attribution is None


def test_sdk_repair_failure_isolates_original_numeric_sibling_and_replays(tmp_path, monkeypatch):
    from tests.test_native_model import caller, main, sdk
    from tests.test_numeric_narrative import envelope, numeric_context
    from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict
    journal, _ = numeric_setup(tmp_path)
    context, anchor, alias = numeric_context()
    value = envelope("营收增长25%", anchor["required_fact_ids"])
    good = copy.deepcopy(value["proposal"]["hypotheses"][0])
    good["statement"] = "{{num:" + alias + "}}"
    value["proposal"]["hypotheses"].append(good)
    main(journal)
    stub, _ = sdk(monkeypatch, [value, "invalid json"])
    model = caller(journal)
    result = model("operating_quality", context)
    saved = journal.ledger.cached_result("native.numeric.accepted.operating_quality")
    assert saved["proof"]["indices"] == [1] and "18.40%" in result["hypotheses"][0]["statement"]
    assert len(stub.factories) == 2 and "25%" not in json.dumps(saved, ensure_ascii=False)
    assert model.recover_cached("operating_quality", context) == result
    journal.state["results"]["native.numeric.accepted.operating_quality"]["proof"]["fields"] = []
    with pytest.raises(CatalystCheckpointConflict):
        model.recover_cached("operating_quality", context)


def test_sdk_successful_repair_replaces_original_and_recovers_readonly(tmp_path, monkeypatch):
    from tests.test_native_model import caller, main, sdk
    from tests.test_numeric_narrative import envelope, numeric_context
    journal, _ = numeric_setup(tmp_path)
    context, anchor, alias = numeric_context()
    main(journal)
    stub, _ = sdk(monkeypatch, [envelope("营收增长25%", anchor["required_fact_ids"]),
                                envelope("{{num:" + alias + "}}", anchor["required_fact_ids"])])
    model = caller(journal)
    result = model("operating_quality", context)
    assert "18.40%" in result["hypotheses"][0]["statement"] and len(stub.factories) == 2
    saved = journal.ledger.cached_result("native.numeric.accepted.operating_quality")
    assert saved["proof"]["indices"] == [0] and not saved["proof"]["rejections"]
    before = copy.deepcopy(journal.state)
    assert model.recover_cached("operating_quality", context) == result
    assert journal.state == before


def test_fresh_custom_caller_cannot_return_bare_proposal(tmp_path):
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, UnifiedCaller())
    assert not record.hypotheses
    assert record.company_basics is not None and record.assessment.report_status == "basic_report"
    assert not record.numeric_attribution.stages


def test_catalog_overflow_keeps_basics_and_visible_qualitative_limit(tmp_path, monkeypatch):
    from tradingagents.research import numeric_catalog
    from tradingagents.research.numeric_integration import CATALOG_LIMIT_NOTICE
    monkeypatch.setattr(numeric_catalog, "NUMERIC_CATALOG_LIMIT", 1)
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, NumericCaller())
    assert record.company_basics == seed.company_basics
    assert record.numeric_attribution.catalog.availability == "unavailable"
    assert CATALOG_LIMIT_NOTICE in record.limitations
    validate_record_numeric(record, journal.state["identity"])
    raw = record.model_dump(mode="json")
    raw["limitations"].remove(CATALOG_LIMIT_NOTICE)
    with pytest.raises(ValueError):
        ResearchRecordV1.model_validate(raw)


def test_markdown_publication_binds_frozen_input_and_preserves_existing_report(tmp_path):
    from tradingagents.runtime.reports import ReportArtifactWriter, ReportPublicationError
    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, NumericCaller())
    writer = ReportArtifactWriter(journal.observer.store)
    state = {"native_research_record": record.model_dump(mode="json")}
    publication = writer.publish_final(record.run_id, state, record.ticker)
    before = publication.complete_report.read_bytes()
    journal.put("native_input", {**journal.state["native_input"], "seed_sha256": "0" * 64})
    with pytest.raises(ReportPublicationError, match="native numeric report input mismatch"):
        writer.publish_final(record.run_id, state, record.ticker)
    assert publication.complete_report.read_bytes() == before


def test_numeric_fragments_survive_dialogue_inherited_condition_reader_and_markdown(tmp_path):
    from tradingagents.execution.native_publication import publish_native_record
    from tradingagents.research.numeric_narrative import validate_numeric_field
    from tradingagents.runtime.reports import build_markdown_from_native_record

    class AnchoredCaller(NumericCaller):
        def __call__(self, stage, context):
            value = super().__call__(stage, context)
            proposal = value["proposal"]
            anchor = next(a for a in context["numeric_catalog"]["anchors"]
                          if a["definition_key"] == "official.financial.revenue.current")
            alias = next(k for k, aid in context["numeric_aliases"].items() if aid == anchor["anchor_id"])
            token = "{{num:" + alias + "}}"
            if stage == "operating_quality":
                item = proposal["hypotheses"][0]
                item.update(statement=token, supporting_fact_ids=anchor["required_fact_ids"])
                item["conditions"][0]["text"] = "未来经营若无法维持该观察则失效：" + token
            elif stage == "challenge":
                proposal["challenges"][0]["statement"] = "观察不证明持续性：" + token
            elif stage.startswith("response_"):
                item = proposal["responses"][0]
                item.update(rationale="仍需后续经营验证：" + token, supporting_fact_ids=anchor["required_fact_ids"])
            else:
                proposal.update(judgement="经营判断仍有条件：" + token, key_claim_ids=anchor["required_fact_ids"])
                h = context["record"]["hypotheses"][0]
                proposal["change_conditions"] = [{"hypothesis_id": h["hypothesis_id"],
                    "invalidation_index": 0, "text": "模型改写25%应被宿主原条件覆盖"}]
            return value

    journal, seed = numeric_setup(tmp_path)
    record = run(journal, seed, AnchoredCaller())
    assert record.assessment.report_status == "synthesized"
    original = record.hypotheses[0].invalidation_conditions[0]
    assert record.assessment.change_conditions[0].text == original
    assert "{{num:" not in original and "25%" not in record.model_dump_json()
    synthesis = next(s for s in record.numeric_attribution.stages if s.stage == "synthesis")
    field = next(f for f in synthesis.proof["fields"] if f["path"] == "change_conditions.0.text")
    metadata = {**synthesis.context["numeric_meta"], "inherited_conditions": {(record.hypotheses[0].hypothesis_id, 0): original}}
    assert validate_numeric_field(field, synthesis.context["numeric_catalog"], metadata=metadata) == original
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
                         publication_authorizer=lambda j: j.put("publication_authorized", True))
    assert project_research_record(journal.observer.store, record.run_id)["state"] == "ready"
    assert original in build_markdown_from_native_record(record, workflow_version=journal.state["identity"]["workflow_version"])


def test_v8_attribution_indexes_every_narrative_field_while_v1_keeps_its_limit():
    from pydantic import ValidationError

    from tradingagents.agents.schemas._numeric_attribution import (
        NumericAttributionV1,
        NumericAttributionV2,
    )
    field ={"path": ["claims", 0, "statement"], "text_sha256": "a" * 64, "kind": "host", "sources": []}
    payload = {"policy": "anchored-narrative-v1", "catalog": {}, "final_fields": [field] * 265}
    assert len(NumericAttributionV2.model_validate(payload).final_fields) == 265
    with pytest.raises(ValidationError):
        NumericAttributionV1.model_validate(payload)
