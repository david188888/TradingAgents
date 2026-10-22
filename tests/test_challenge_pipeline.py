"""Real V7 saved-stage, publication, Markdown and replay with synthetic models."""

import pytest

from tests.test_native_record import financials, fixture
from tests.test_numeric_pipeline import NumericCaller
from tests.test_unified_research import run
from tests.web.test_reader_stage import first_saved
from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
from tradingagents.execution.native_publication import publish_native_record
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.research.native_record import build_native_record
from tradingagents.research.native_versions import (
    COMPANY_RESEARCH_POLICY,
    NUMERIC_NARRATIVE_POLICY,
    REPORT_DELIVERY_POLICY,
    SPECIALIST_REFERENCE_POLICY,
    UNIFIED_BUDGET_POLICY,
    UNIFIED_WORKFLOW_VERSION,
)
from tradingagents.research.numeric_integration import (
    attach_numeric_attribution,
    validate_record_numeric,
)
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.reports import build_markdown_from_native_record
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.reader_process_projection import project_reader_agent
from tradingagents.web.research_record_projection import project_research_record


class DirectedCaller(NumericCaller):
    def __call__(self, stage, context):
        value = super().__call__(stage, context)
        if stage == "challenge":
            anchor = next(a for a in context["numeric_catalog"]["anchors"]
                if a["definition_key"] == "financial.income.revenue" and a["metadata"]["report_period"] == "2026-06-30")
            alias = next(key for key, aid in context["numeric_aliases"].items() if aid == anchor["anchor_id"])
            check = {"kind": "financial", "operation": "value", "current": {
                "evidence_id": anchor["input_evidence_ids"][0], "table": "income", "field": "revenue", "report_period": "2026-06-30"},
                "predicate": {"operator": "gt", "threshold": "0", "unit": "CNY"}}
            claims = {c["claim_id"]: c for c in context["record"]["claims"]}
            target = next(h for h in context["record"]["hypotheses"]
                if set(claims[h["claim_id"]]["evidence_ids"]).intersection(anchor["input_evidence_ids"]))
            for index, item in enumerate(value["proposal"]["challenges"]):
                item.update(hypothesis_id=target["hypothesis_id"], verifiability="computable_now", supporting_fact_ids=anchor["required_fact_ids"], check=check,
                    proposed_test=f"保存收入门槛：{{{{plan:p_{index}}}}}")
                root = f"challenges.{index}"
                value["plans"].append({"alias": f"p_{index}", "field_path": root + ".proposed_test", "kind": "quantity", **check["predicate"]})
                value["structured_bindings"].extend([
                    {"field_path": root + ".check.current", "kind": "num", "alias": alias},
                    {"field_path": root + ".check.predicate", "kind": "plan", "alias": f"p_{index}"}])
        if stage == "synthesis":
            value["proposal"]["key_claim_ids"] = [c["claim_id"] for c in context["record"]["claims"] if c["kind"] == "fact"][:1]
        if context.get("factual_premise_policy"):
            from tests.factual_premise_fixtures import bind
            value = bind(stage, value, context)
        return value


@pytest.mark.parametrize("premises", [False, True])
def test_directed_chain_preserves_inputs_stage_outputs_and_read_only_publication(tmp_path, monkeypatch, premises):
    snapshot = RunSnapshot.create(ticker="600519", analysis_date="2026-09-30", metadata={
        "research_profile": "evidence_v1", "native_workflow_version": UNIFIED_WORKFLOW_VERSION})
    store = RunStore(tmp_path)
    store.create_run(snapshot)
    identity = {"workflow_version": UNIFIED_WORKFLOW_VERSION, "focus_budget_policy": UNIFIED_BUDGET_POLICY,
        "ticker": snapshot.ticker, "mode": "company_research", "cutoff": snapshot.analysis_date,
        "numeric_narrative_policy": NUMERIC_NARRATIVE_POLICY, "challenge_check_policy": CHALLENGE_CHECK_POLICY,
        "company_research_policy": COMPANY_RESEARCH_POLICY, "report_delivery_policy": REPORT_DELIVERY_POLICY,
        "specialist_reference_policy": SPECIALIST_REFERENCE_POLICY}
    if premises:
        identity["factual_premise_policy"] = "factual-premises-v1"
    journal = CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False), identity)
    draft, context = fixture(financial_payload=financials(8))
    draft = draft.model_copy(update={"run_id": snapshot.run_id,
        "evidence": tuple({**e, "run_id": snapshot.run_id} for e in draft.evidence)})
    seed = build_native_record(draft, context, mode="company_research", include_coverage=True,
        include_valuation=True, include_minimum=True, include_basics=True)
    seed = attach_numeric_attribution(seed, journal)
    record = run(journal, seed, DirectedCaller())
    assert record.challenge_check_policy == CHALLENGE_CHECK_POLICY
    assert record.verifications[0].scope == "challenge_predicate_only"
    assert record.verifications[0].predicate_met is True
    assert record.assessment.adjudications
    validate_record_numeric(record, journal.state["identity"])
    store = journal.observer.store
    events = store.read_events(seed.run_id)
    monkeypatch.setattr("tradingagents.research.verification_tools.evaluate_condition",
        lambda *args: pytest.fail("Reader must not execute the verification tool"))
    for role, key in {"challenge": "native.challenge", "code_checks": "verification.output",
                      "response_operating_quality": "native.response_operating_quality", "synthesis": "native.synthesis"}.items():
        result = project_reader_agent(store, seed.run_id, role, through=first_saved(store, seed.run_id, key))
        assert result["availability"] == "stage_available", (role, result["reason_code"])
        if role != "challenge":
            assert result["stage_record"]["challenge_outcomes"][0]["state"] == "completed"
    assert store.read_events(seed.run_id) == events
    assert run(journal, seed, lambda *args: pytest.fail("replay called a model")) == record
    text = build_markdown_from_native_record(record, workflow_version="evidence-production-v7")
    assert "核查分类（模型提出）：当前可计算" in text and "任务去向：已实际执行" in text
    assert "独立命题" in text and "命题满足" in text
    publish_native_record(journal.observer, record=record, ledger=journal.ledger,
        publication_authorizer=lambda j: j.put("publication_authorized", True))
    assert project_research_record(store, seed.run_id)["state"] == "ready"
    events = store.read_events(seed.run_id)
    for role in ("operating_quality", "challenge", "code_checks", "response_operating_quality", "synthesis"):
        result = project_reader_agent(store, seed.run_id, role)
        assert result["availability"] == "available", (role, result["reason_code"])
    assert store.read_events(seed.run_id) == events
