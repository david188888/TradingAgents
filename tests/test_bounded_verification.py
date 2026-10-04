"""Offline counterexamples and real RunStore replay for the C1 substrate."""

import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas._research_record import (
    ResearchRecordV1,
    SourceEvidenceV1,
    make_evidence_snapshot,
)
from tradingagents.agents.schemas._verification_plan import VerificationPlanV1, canonical_sha256
from tradingagents.execution import verification_executor as executor
from tradingagents.execution.budget import AttemptOutcome, BudgetBucket, BudgetLedger
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.verification_tools import evaluate_condition
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict, CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

NECESSARY = "同比收入增长至少 10%"
INVALIDATION = "同比收入回落"


def source_text(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "kind": "source_fields",
        "text": text,
        "locator_label": "合并报表 CNY",
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def frozen(payload):
    payload = copy.deepcopy(payload)
    snapshot = make_evidence_snapshot(
        tuple(SourceEvidenceV1.model_validate(item) for item in payload["evidence"])
    )
    payload["snapshots"] = [snapshot.model_dump(mode="json")]
    for hypothesis in payload["hypotheses"]:
        hypothesis["input_snapshot_id"] = snapshot.snapshot_id
    return ResearchRecordV1.model_validate(payload)


def inputs(
    *,
    run_id="run-record",
    mode="company_research",
    role="necessary",
    operation="growth",
    threshold=None,
):
    payload = {
        "run_id": run_id,
        "ticker": "600519",
        "mode": mode,
        "analysis_date": "2026-09-30",
        "construction": "native",
        "evidence": [
            {
                "evidence_id": "e1",
                "source_name": "tushare.financial_statements",
                "source_kind": "vendor",
                "source_family_id": "tushare",
                "availability": "available",
                "usable_as_of": "2026-08-30T12:00:00+08:00",
                "content": source_text(
                    {
                        "income": [
                            {"end_date": "20260630", "ann_date": "20260830", "revenue": 120},
                            {"end_date": "20250630", "ann_date": "20250830", "revenue": 100},
                        ]
                    }
                ),
            }
        ],
        "claims": [
            {
                "claim_id": "f1",
                "kind": "fact",
                "statement": "已保存收入字段",
                "evidence_ids": ["e1"],
            },
            {
                "claim_id": "i1",
                "kind": "inference",
                "statement": "收入改善可能延续",
                "evidence_ids": ["e1"],
                "supporting_fact_ids": ["f1"],
            },
        ],
        "hypotheses": [
            {
                "hypothesis_id": "h1",
                "claim_id": "i1",
                "origin": "hypothesis_stage",
                "assumptions": [NECESSARY],
                "invalidation_conditions": [INVALIDATION],
            }
        ],
        "challenges": [
            {
                "challenge_id": "c1",
                "target_claim_ids": ["i1"],
                "statement": "收入是否持续改善",
                "severity": "critical",
                "risk_type": "operations",
                "proposed_test": "核查同期收入字段",
            }
        ],
    }
    record = frozen(payload)
    operand = {
        "evidence_id": "e1",
        "table": "income",
        "field": "revenue",
        "report_period": "2026-06-30",
    }
    check = {
        "kind": "financial",
        "operation": operation,
        "current": operand,
        "predicate": {
            "operator": "ge" if role == "necessary" else "lt",
            "threshold": threshold or ("0.1" if operation == "growth" else "110"),
            "unit": "ratio" if operation == "growth" else "CNY",
        },
    }
    if operation != "value":
        check["base"] = {**operand, "report_period": "2025-06-30"}
    plan = {
        "run_id": run_id,
        "ticker": record.ticker,
        "mode": mode,
        "analysis_date": "2026-09-30",
        "input_snapshot_id": record.snapshots[0].snapshot_id,
        "tasks": [
            {
                "task_id": "t1",
                "challenge_id": "c1",
                "hypothesis_id": "h1",
                "condition_role": role,
                "condition_text": NECESSARY if role == "necessary" else INVALIDATION,
                "check": check,
            }
        ],
    }
    return record, VerificationPlanV1.model_validate_json(json.dumps(plan))


def changed(record, plan, edit):
    payload = record.model_dump(mode="json")
    edit(payload)
    record = frozen(payload)
    plan = plan.model_copy(update={"input_snapshot_id": record.snapshots[0].snapshot_id})
    return record, plan


def fields_changed(record, plan, edit):
    def update(payload):
        fields = json.loads(payload["evidence"][0]["content"]["text"])
        edit(fields)
        payload["evidence"][0]["content"] = source_text(fields)

    return changed(record, plan, update)


def journal_for(tmp_path):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(
        ticker="600519",
        analysis_date="2026-09-30",
        llm_provider="openai",
        quick_think_llm="offline",
        deep_think_llm="offline",
        runtime_semantics_hash="a" * 64,
        metadata={"effective_config_artifact_id": "data:" + "b" * 64},
    )
    store.create_run(snapshot)
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    return CatalystJournal(observer, {"test": "bounded-verification"})


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_three_modes_create_real_v1_and_replay_without_work(tmp_path, monkeypatch, mode):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id, mode=mode)
    output = executor.execute_verification(record, plan, ledger=journal.ledger)
    verified = output.record
    assert verified.snapshots[0] == record.snapshots[0]
    assert verified.evidence[0] == record.evidence[0]
    assert (verified.claims, verified.hypotheses, verified.challenges, verified.metrics) == (
        record.claims,
        record.hypotheses,
        record.challenges,
        record.metrics,
    )
    assert verified.snapshots[1].parent_snapshot_id == record.snapshots[0].snapshot_id
    assert verified.verifications[0].scope == "predicate_only"
    assert verified.verifications[0].status == "supports"
    assert verified.verifications[0].hypothesis_id == "h1"
    assert verified.evidence[1].source_family_id == "tushare"
    assert verified.evidence[1].source_kind == "derived"
    assert "derived_not_an_independent_source" in verified.evidence[1].limitations
    assert json.loads(verified.evidence[1].content.text)["operands"][0]["evidence_id"] == "e1"
    assert output.output_record_sha256 == canonical_sha256(verified)
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_ROUNDS) == 1
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == 1
    assert journal.ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 1
    assert (
        journal.ledger.consumed(BudgetBucket.MODEL_ATTEMPTS)
        == journal.ledger.consumed(BudgetBucket.DATA_HTTP_ATTEMPTS)
        == 0
    )
    spent = len(journal.ledger.records())
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("replay dispatched tool")
    )
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    assert executor.execute_verification(record, plan, ledger=restored.ledger) == output
    assert len(restored.ledger.records()) == spent


@pytest.mark.parametrize(
    "role,current,expected",
    [
        ("necessary", 120, "supports"),
        ("necessary", 105, "contradicts"),
        ("invalidation", 80, "contradicts"),
        ("invalidation", 120, "inconclusive"),
    ],
)
def test_predicate_semantics_do_not_prove_hypothesis(role, current, expected):
    record, plan = inputs(role=role, threshold="0" if role == "invalidation" else "0.1")
    record, plan = fields_changed(
        record, plan, lambda data: data["income"][0].update(revenue=current)
    )
    result = evaluate_condition(record, plan.tasks[0])
    assert result.status == expected


@pytest.mark.parametrize(
    "operation,threshold,value",
    [("value", "110", "120"), ("difference", "10", "20"), ("growth", "0.1", "0.2")],
)
def test_allowlisted_arithmetic(operation, threshold, value):
    record, plan = inputs(operation=operation, threshold=threshold)
    result = evaluate_condition(record, plan.tasks[0])
    assert result.value == value and result.status == "supports"


@pytest.mark.parametrize(
    "defect",
    [
        "zero_base",
        "negative_base",
        "duplicate_period",
        "missing_period",
        "future_disclosure",
        "missing_disclosure",
        "future_amendment",
        "bad_date",
        "nan",
        "inf",
        "bool",
        "wrong_type",
        "null",
        "huge",
        "title",
        "summary",
        "truncated",
        "missing_content",
        "unavailable",
        "unverified",
        "no_usable_date",
        "wrong_source",
        "derived_source",
        "no_family",
        "future_published",
        "timezone_after_cutoff",
    ],
)
def test_unqualified_fields_never_resolve_a_condition(defect):
    record, plan = inputs()
    if defect in {
        "title",
        "summary",
        "truncated",
        "missing_content",
        "unavailable",
        "unverified",
        "no_usable_date",
        "wrong_source",
        "derived_source",
        "no_family",
        "future_published",
        "timezone_after_cutoff",
    }:

        def edit(payload):
            evidence = payload["evidence"][0]
            if defect == "title":
                evidence["content"]["kind"] = "excerpt"
            elif defect == "summary":
                evidence["content"]["kind"] = "saved_summary"
            elif defect == "truncated":
                evidence["content"]["truncated"] = True
            elif defect == "missing_content":
                evidence.update(content=None, limitations=["missing_body"])
            elif defect in {"unavailable", "unverified"}:
                evidence["availability"] = defect
            elif defect == "no_usable_date":
                evidence["usable_as_of"] = None
            elif defect == "wrong_source":
                evidence["source_name"] = "other.financial"
            elif defect == "derived_source":
                evidence["source_kind"] = "derived"
            elif defect == "no_family":
                evidence["source_family_id"] = None
            elif defect == "future_published":
                evidence["published_at"] = "2026-10-01T00:00:00+08:00"
            else:
                evidence["usable_as_of"] = "2026-09-30T23:30:00Z"

        record, plan = changed(record, plan, edit)
    else:

        def edit(data):
            row, base = data["income"]
            if defect == "zero_base":
                base["revenue"] = 0
            elif defect == "negative_base":
                base["revenue"] = -1
            elif defect == "duplicate_period":
                data["income"].append(row.copy())
            elif defect == "missing_period":
                data["income"].pop(0)
            elif defect == "future_disclosure":
                row["ann_date"] = "20261001"
            elif defect == "missing_disclosure":
                del row["ann_date"]
            elif defect == "future_amendment":
                row["f_ann_date"] = "20261001"
            elif defect == "bad_date":
                row["ann_date"] = "20260230"
            else:
                row["revenue"] = {
                    "nan": float("nan"),
                    "inf": float("inf"),
                    "bool": True,
                    "wrong_type": [],
                    "null": None,
                    "huge": "1e999",
                }[defect]

        record, plan = fields_changed(record, plan, edit)
    result = evaluate_condition(record, plan.tasks[0])
    assert result.status == "unavailable"
    assert result.evidence_ids == () and result.calculation is None


@pytest.mark.parametrize(
    "defect",
    [
        "field",
        "table",
        "units",
        "period",
        "reversed",
        "nan_threshold",
        "bool_threshold",
        "code",
        "four_tasks",
        "duplicate_task",
    ],
)
def test_plan_rejects_arbitrary_or_incomparable_calculation(defect):
    _record, plan = inputs()
    data = plan.model_dump(mode="json")
    check = data["tasks"][0]["check"]
    if defect == "field":
        check["current"]["field"] = "private_formula"
    elif defect == "table":
        check["current"]["table"] = "secret"
    elif defect == "units":
        check["predicate"]["unit"] = "CNY"
    elif defect == "period":
        check["base"]["report_period"] = "2025-03-31"
    elif defect == "reversed":
        check["base"]["report_period"] = "2027-06-30"
    elif defect == "nan_threshold":
        check["predicate"]["threshold"] = "NaN"
    elif defect == "bool_threshold":
        check["predicate"]["threshold"] = True
    elif defect == "code":
        check["expression"] = "__import__('os')"
    elif defect == "four_tasks":
        data["tasks"] *= 4
    else:
        data["tasks"] *= 2
    with pytest.raises(ValidationError):
        VerificationPlanV1.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "defect",
    ["condition", "role", "target", "adapted", "run", "ticker", "mode", "cutoff", "snapshot"],
)
def test_invalid_bindings_fail_before_spending(tmp_path, defect):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    if defect == "condition":
        plan = plan.model_copy(
            update={
                "tasks": (
                    plan.tasks[0].model_copy(update={"condition_text": "invented condition"}),
                )
            }
        )
    elif defect == "role":
        plan = plan.model_copy(
            update={"tasks": (plan.tasks[0].model_copy(update={"condition_role": "invalidation"}),)}
        )
    elif defect == "target":
        record, plan = changed(
            record, plan, lambda payload: payload["challenges"][0].update(target_claim_ids=["f1"])
        )
    elif defect == "adapted":
        record, plan = changed(
            record,
            plan,
            lambda payload: payload["hypotheses"][0].update(
                origin="adapted_inference", limitations=["compatibility"]
            ),
        )
    else:
        plan = plan.model_copy(
            update={
                {
                    "run": "run_id",
                    "ticker": "ticker",
                    "mode": "mode",
                    "cutoff": "analysis_date",
                    "snapshot": "input_snapshot_id",
                }[defect]: {
                    "run": "other",
                    "ticker": "000001",
                    "mode": "holding_review",
                    "cutoff": "2026-09-29",
                    "snapshot": "other",
                }[defect]
            }
        )
    with pytest.raises(ValueError):
        executor.execute_verification(record, plan, ledger=journal.ledger)
    assert journal.ledger.records() == ()
    assert "verification_input" not in journal.state


def test_existing_run_budget_denies_work_without_fabricating_v1(tmp_path, monkeypatch):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    for index in range(24):
        grant = journal.ledger.reserve_or_raise(
            BudgetBucket.DATA_CAPABILITY_CALLS,
            stage="existing",
            logical_call_id=f"existing.{index}",
        )
        journal.ledger.mark_dispatched(grant)
        journal.ledger.settle(grant, ok=True)
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("budget-denied dispatch")
    )
    output = executor.execute_verification(record, plan, ledger=journal.ledger)
    assert output.outcomes[0].state == "budget_refused" and output.outcomes[0].executed_at is None
    assert len(output.record.snapshots) == 1 and not output.record.verifications
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == 0
    assert journal.ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 24


def test_cancel_and_empty_round_spend_nothing(tmp_path, monkeypatch):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("cancelled dispatch")
    )
    output = executor.execute_verification(
        record, plan, ledger=journal.ledger, cancelled=lambda: True
    )
    assert output.outcomes[0].state == "cancelled" and output.outcomes[0].executed_at is None
    assert len(output.record.snapshots) == 1 and journal.ledger.records() == ()
    other = journal_for(tmp_path / "other")
    record, plan = inputs(run_id=other.ledger.run_id)
    output = executor.execute_verification(
        record, plan.model_copy(update={"tasks": ()}), ledger=other.ledger
    )
    assert output.record == record and output.outcomes == () and other.ledger.records() == ()


class Crash(BaseException):
    pass


@pytest.mark.parametrize("after_cache", [False, True])
@pytest.mark.parametrize("cancel_on_resume", [False, True])
def test_interruption_never_reexecutes_uncertain_task(
    tmp_path, monkeypatch, after_cache, cancel_on_resume
):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    with monkeypatch.context() as patch:
        if after_cache:
            original = journal.ledger.settle

            def interrupt(grant, **kwargs):
                if grant.bucket is BudgetBucket.SUPPLEMENT_CAPABILITIES:
                    raise Crash()
                return original(grant, **kwargs)

            patch.setattr(journal.ledger, "settle", interrupt)
        else:

            def interrupt(*_):
                raise Crash()

            patch.setattr(executor, "evaluate_condition", interrupt)
        with pytest.raises(Crash):
            executor.execute_verification(record, plan, ledger=journal.ledger)
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("uncertain dispatch repeated")
    )
    output = executor.execute_verification(
        record, plan, ledger=restored.ledger, cancelled=lambda: cancel_on_resume
    )
    assert output.outcomes[0].state == ("completed" if after_cache else "unknown")
    assert len(output.record.verifications) == (1 if after_cache else 0)
    assert restored.ledger.consumed(BudgetBucket.SUPPLEMENT_ROUNDS) == 1
    assert restored.ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 1
    assert (
        len([item for item in restored.ledger.records() if item.outcome is AttemptOutcome.UNKNOWN])
        == 2
    )


def test_persistence_failure_prevents_dispatch(tmp_path, monkeypatch):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)

    def fail(*_, **__):
        raise OSError("private/path secret")

    monkeypatch.setattr(journal.observer.store, "store_artifact", fail)
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("unpersisted dispatch")
    )
    with pytest.raises(OSError):
        executor.execute_verification(record, plan, ledger=journal.ledger)
    assert journal.failed and journal.ledger.records() == ()


def test_tool_exception_is_saved_as_unavailable_without_private_text(tmp_path, monkeypatch):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)

    def fail(*_):
        raise RuntimeError("private/path api_key=secret-value")

    monkeypatch.setattr(executor, "evaluate_condition", fail)
    output = executor.execute_verification(record, plan, ledger=journal.ledger)
    assert output.record.verifications[0].status == "unavailable"
    assert len(output.record.snapshots) == 2 and len(output.record.evidence) == 1
    assert "tool_failed" in output.record.verifications[0].result
    assert "private/path" not in json.dumps(journal.state)
    assert "secret-value" not in json.dumps(journal.state)


@pytest.mark.parametrize("change", ["plan", "record"])
def test_replay_rejects_changed_input_before_new_spend(tmp_path, change):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    executor.execute_verification(record, plan, ledger=journal.ledger)
    before = len(journal.ledger.records())
    if change == "plan":
        check = plan.tasks[0].check.model_copy(
            update={
                "predicate": plan.tasks[0].check.predicate.model_copy(update={"threshold": "0.15"})
            }
        )
        plan = plan.model_copy(
            update={"tasks": (plan.tasks[0].model_copy(update={"check": check}),)}
        )
    else:
        record = record.model_copy(update={"limitations": ("changed input",)})
    with pytest.raises(CatalystCheckpointConflict, match="input or plan changed"):
        executor.execute_verification(record, plan, ledger=journal.ledger)
    assert len(journal.ledger.records()) == before


def test_fresh_or_other_run_ledger_is_rejected(tmp_path):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    with pytest.raises(ValueError, match="existing durable ledger"):
        executor.execute_verification(record, plan, ledger=BudgetLedger(record.run_id))
    other = journal_for(tmp_path / "other")
    with pytest.raises(ValueError, match="existing durable ledger"):
        executor.execute_verification(record, plan, ledger=other.ledger)


def test_corrupt_output_cache_is_not_returned(tmp_path):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    executor.execute_verification(record, plan, ledger=journal.ledger)
    journal.state["results"]["verification.output"]["output"]["record"]["limitations"].append(
        "tampered"
    )
    with pytest.raises(ValidationError, match="hash mismatch"):
        executor.execute_verification(record, plan, ledger=journal.ledger)


def metric_inputs(*, run_id="run-record"):
    record, plan = inputs(run_id=run_id)
    payload = record.model_dump(mode="json")
    payload["metrics"] = [
        {
            "metric_id": "price.volatility",
            "label": "波动率",
            "availability": "available",
            "value": 0.2,
            "unit": "return_fraction",
            "method": "sample std",
            "calculation_version": "price-test-v1",
            "input_evidence_ids": ["e1"],
            "input_sha256": "a" * 64,
            "window_start": "2026-01-01",
            "window_end": "2026-09-30",
            "sample_size": 100,
        }
    ]
    record = frozen(payload)
    data = plan.model_dump(mode="json")
    data["input_snapshot_id"] = record.snapshots[0].snapshot_id
    data["tasks"][0]["check"] = {
        "kind": "metric",
        "metric_id": "price.volatility",
        "predicate": {"operator": "lt", "threshold": "0.3", "unit": "return_fraction"},
    }
    return record, VerificationPlanV1.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "defect", [None, "unit", "unavailable", "no_sample", "no_usable", "unavailable_source"]
)
def test_saved_metric_checks_qualification_and_preserves_recomputation_limit(defect):
    record, plan = metric_inputs()
    payload = record.model_dump(mode="json")
    if defect == "unit":
        payload["metrics"][0]["unit"] = "CNY/share"
    elif defect == "unavailable":
        payload["metrics"][0].update(
            availability="unavailable", value=None, unavailable_reason="missing"
        )
    elif defect == "no_sample":
        payload["metrics"][0]["sample_size"] = 0
    elif defect == "no_usable":
        payload["evidence"][0]["usable_as_of"] = None
    elif defect == "unavailable_source":
        payload["evidence"][0]["availability"] = "unavailable"
        payload["metrics"][0].update(
            availability="unavailable", value=None, unavailable_reason="missing"
        )
    record = frozen(payload)
    result = evaluate_condition(record, plan.tasks[0])
    assert result.status == ("supports" if defect is None else "unavailable")
    if defect is None:
        assert result.calculation["input_sha256"] == "a" * 64
        assert (
            result.calculation["limitation"] == "saved_metric_threshold_only_not_raw_recomputation"
        )


def test_metric_predicate_derivation_runs_without_raw_price_recomputation(tmp_path):
    journal = journal_for(tmp_path)
    record, plan = metric_inputs(run_id=journal.ledger.run_id)
    output = executor.execute_verification(record, plan, ledger=journal.ledger)
    assert output.record.verifications[0].status == "supports"
    assert output.record.metrics == record.metrics
    assert json.loads(output.record.evidence[-1].content.text)["kind"] == "metric"


@pytest.mark.parametrize(
    "operator,threshold,met",
    [
        ("lt", "0.2", False),
        ("le", "0.2", True),
        ("eq", "0.2", True),
        ("ge", "0.2", True),
        ("gt", "0.2", False),
    ],
)
def test_threshold_boundary_uses_exact_decimal(operator, threshold, met):
    record, plan = inputs()
    check = plan.tasks[0].check.model_copy(
        update={
            "predicate": plan.tasks[0].check.predicate.model_copy(
                update={"operator": operator, "threshold": threshold}
            )
        }
    )
    result = evaluate_condition(record, plan.tasks[0].model_copy(update={"check": check}))
    assert result.predicate_met is met


def three_tasks(record, plan):
    payload = record.model_dump(mode="json")
    original = payload["challenges"][0]
    payload["challenges"] += [
        {**original, "challenge_id": "c2", "severity": "minor"},
        {**original, "challenge_id": "c3", "severity": "material"},
    ]
    record = frozen(payload)
    original = plan.tasks[0].model_dump(mode="json")
    data = plan.model_dump(mode="json")
    data["tasks"] = [
        {**original, "task_id": "a", "challenge_id": "c2"},
        {**original, "task_id": "b", "challenge_id": "c3"},
        {**original, "task_id": "z", "challenge_id": "c1"},
    ]
    return record, VerificationPlanV1.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("cancel_after_one", [False, True])
def test_critical_tasks_run_first_and_cancellation_preserves_completed_work(
    tmp_path, monkeypatch, cancel_after_one
):
    journal = journal_for(tmp_path)
    record, plan = three_tasks(*inputs(run_id=journal.ledger.run_id))
    called = []

    def tool(record, task):
        called.append(task.task_id)
        return evaluate_condition(record, task)

    monkeypatch.setattr(executor, "evaluate_condition", tool)
    output = executor.execute_verification(
        record, plan, ledger=journal.ledger, cancelled=lambda: cancel_after_one and len(called) == 1
    )
    assert called == (["z"] if cancel_after_one else ["z", "b", "a"])
    assert len(output.record.verifications) == len(called)
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_ROUNDS) == 1
    assert journal.ledger.consumed(BudgetBucket.SUPPLEMENT_CAPABILITIES) == len(called)
    assert [item.state for item in output.outcomes] == (
        ["completed", "cancelled", "cancelled"] if cancel_after_one else ["completed"] * 3
    )


def test_round_refusal_uses_existing_supplement_consumption(tmp_path, monkeypatch):
    journal = journal_for(tmp_path)
    grant = journal.ledger.reserve_or_raise(
        BudgetBucket.SUPPLEMENT_ROUNDS, stage="existing", logical_call_id="already_spent"
    )
    journal.ledger.mark_dispatched(grant)
    journal.ledger.settle(grant, ok=True)
    record, plan = inputs(run_id=journal.ledger.run_id)
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("second supplement round")
    )
    output = executor.execute_verification(record, plan, ledger=journal.ledger)
    assert output.outcomes[0].state == "budget_refused"
    assert journal.ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 0


@pytest.mark.parametrize("when", ["reserve", "dispatch", "cache"])
def test_durable_permission_failure_and_lost_result_resume(tmp_path, monkeypatch, when):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    real_tool = executor.evaluate_condition
    called = []

    def tool(*args):
        called.append(True)
        return real_tool(*args)

    monkeypatch.setattr(executor, "evaluate_condition", tool)
    original = journal.persist

    def fail():
        task_records = [
            item
            for item in journal.ledger.records()
            if item.stage == "verification" and item.bucket is BudgetBucket.SUPPLEMENT_CAPABILITIES
        ]
        should_fail = bool(task_records) and (
            (when == "reserve" and task_records[-1].dispatched_at is None)
            or (when == "dispatch" and task_records[-1].dispatched_at is not None)
            or (
                when == "cache"
                and any(key.startswith("verification.task.") for key in journal.state["results"])
            )
        )
        if should_fail:
            journal.failed = True
            raise OSError("disk unavailable")
        return original()

    monkeypatch.setattr(journal, "persist", fail)
    with pytest.raises(OSError):
        executor.execute_verification(record, plan, ledger=journal.ledger)
    assert len(called) == (1 if when == "cache" else 0)
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    if when == "cache":
        monkeypatch.setattr(
            executor, "evaluate_condition", lambda *_: pytest.fail("lost result repeated")
        )
        output = executor.execute_verification(record, plan, ledger=restored.ledger)
        assert output.outcomes[0].state == "unknown"
        assert not output.record.verifications


@pytest.mark.parametrize(
    "defect", ["hypothesis", "condition", "role", "target", "scope", "falsifier_support"]
)
def test_persisted_predicate_records_cannot_drop_or_change_binding(tmp_path, defect):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    payload = executor.execute_verification(record, plan, ledger=journal.ledger).record.model_dump(
        mode="json"
    )
    verification = payload["verifications"][0]
    if defect == "hypothesis":
        verification["hypothesis_id"] = "other"
    elif defect == "condition":
        verification["condition_text"] = "other"
    elif defect == "role":
        verification["condition_role"] = None
    elif defect == "target":
        payload["challenges"][0]["target_claim_ids"] = ["f1"]
    elif defect == "scope":
        verification["scope"] = "unspecified"
    else:
        verification.update(
            condition_role="invalidation", condition_text=INVALIDATION, status="supports"
        )
    with pytest.raises(ValidationError):
        ResearchRecordV1.model_validate(payload)


def test_compatibility_case_cannot_upgrade_itself_to_native_verification(tmp_path):
    journal = journal_for(tmp_path)
    record, plan = inputs(run_id=journal.ledger.run_id)
    payload = record.model_dump(mode="json")
    payload.update(
        construction="adapted_case",
        source_case_contract="research-case-v2",
        source_case_sha256="a" * 64,
    )
    record = ResearchRecordV1.model_validate(payload)
    with pytest.raises(ValueError, match="unverified V0 record"):
        executor.execute_verification(record, plan, ledger=journal.ledger)
    assert not journal.ledger.records()


def test_future_report_period_is_unavailable_not_a_forecast():
    record, plan = inputs(operation="value")
    current = plan.tasks[0].check.current.model_copy(update={"report_period": "2026-12-31"})
    task = plan.tasks[0].model_copy(
        update={"check": plan.tasks[0].check.model_copy(update={"current": current})}
    )
    result = evaluate_condition(record, task)
    assert result.status == "unavailable" and result.reason == "period_unavailable"


def test_duplicate_json_field_is_not_silently_overwritten():
    record, plan = inputs()
    text = '{"income": [], "income": [{"end_date":"20260630","ann_date":"20260830","revenue":120}]}'

    def edit(payload):
        payload["evidence"][0]["content"].update(
            text=text, content_sha256=hashlib.sha256(text.encode()).hexdigest()
        )

    record, plan = changed(record, plan, edit)
    result = evaluate_condition(record, plan.tasks[0])
    assert result.status == "unavailable" and result.reason == "invalid_fields"


def test_financial_comparison_does_not_cross_source_families():
    record, plan = inputs()
    payload = record.model_dump(mode="json")
    payload["evidence"].append(
        {**payload["evidence"][0], "evidence_id": "e2", "source_family_id": "different-family"}
    )
    record = frozen(payload)
    check = plan.tasks[0].check
    task = plan.tasks[0].model_copy(
        update={
            "check": check.model_copy(
                update={"base": check.base.model_copy(update={"evidence_id": "e2"})}
            )
        }
    )
    assert evaluate_condition(record, task).reason == "source_unqualified"


def test_cancelled_recovery_keeps_completed_part_of_round(tmp_path, monkeypatch):
    journal = journal_for(tmp_path)
    record, plan = three_tasks(*inputs(run_id=journal.ledger.run_id))
    with monkeypatch.context() as patch:
        original = journal.ledger.settle

        def interrupt(grant, **kwargs):
            if grant.bucket is BudgetBucket.SUPPLEMENT_CAPABILITIES:
                raise Crash()
            return original(grant, **kwargs)

        patch.setattr(journal.ledger, "settle", interrupt)
        with pytest.raises(Crash):
            executor.execute_verification(record, plan, ledger=journal.ledger)
    restored = CatalystJournal(journal.observer, journal.state["identity"], require_existing=True)
    before = len(restored.ledger.records())
    monkeypatch.setattr(
        executor, "evaluate_condition", lambda *_: pytest.fail("cancelled recovery dispatched")
    )
    output = executor.execute_verification(
        record, plan, ledger=restored.ledger, cancelled=lambda: True
    )
    assert [item.state for item in output.outcomes] == ["completed", "cancelled", "cancelled"]
    assert len(output.record.verifications) == 1 and len(output.record.snapshots) == 2
    assert output.record.verifications[0].challenge_id == "c1"
    assert len(restored.ledger.records()) == before
    assert restored.ledger.consumed(BudgetBucket.DATA_CAPABILITY_CALLS) == 1
    assert (
        executor.execute_verification(record, plan, ledger=restored.ledger, cancelled=lambda: True)
        == output
    )
