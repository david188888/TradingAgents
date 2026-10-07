"""Offline Reader provenance, publication boundaries and truthful native counts."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from tests.test_native_research import Caller, seed_for
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.graph.native_research import run_native_research
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.native_observation import establish_sdk_observation
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.api import create_app
from tradingagents.web.audit_projection import project_audit_summary
from tradingagents.web.native_reader_versions import saved_dimensions_match, saved_fact_views
from tradingagents.web.reader_process_projection import (
    native_counts,
    project_reader_agent,
    project_reader_process,
)

pytestmark = pytest.mark.unit


def saved(tmp_path, *, mode="company_research", publish=True, challenge=True):
    store = RunStore(tmp_path)
    snapshot = RunSnapshot.create(
        ticker="600519",
        analysis_date="2026-09-30",
        mode=mode,
        holding_context={"ticker": "600519", "quantity": 100, "average_cost": 10}
        if mode == "holding_review"
        else None,
        llm_provider="mock",
        quick_think_llm="mock",
        deep_think_llm="mock",
        metadata={"research_profile": "evidence_v1", "research_question": "改善是否持续？"},
    )
    # Terminal synthetic fixtures cannot be mistaken for resumable paid work.
    store.create_run(snapshot.evolve(status="failed"))
    observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
    journal = CatalystJournal(
        observer,
        {
            "workflow_version": "evidence-production-v2",
            "ticker": snapshot.ticker,
            "mode": mode,
            "cutoff": snapshot.analysis_date,
            "config": {"api_key": "PRIVATE_SENTINEL"},
        },
    )
    output = run_native_research(
        seed_for(journal, mode),
        caller=Caller(challenge=challenge, check=False),
        ledger=journal.ledger,
        research_question="改善是否持续？",
    )
    sequence = store.read_snapshot(snapshot.run_id).latest_sequence
    if publish:
        promote_derived_public_artifact(
            observer,
            contract="research-record-v1",
            value=output,
            graph_task_id="native.final",
            checkpoint_event_id="native-barrier",
            committed_sequence=sequence,
            promoted=set(),
        )
    return store, snapshot.run_id, journal, output


@pytest.mark.parametrize("mode", ["company_research", "catalyst_research", "holding_review"])
def test_readonly_exact_origin_and_safe_role_outputs(tmp_path, monkeypatch, mode):
    store, run, journal, record = saved(tmp_path, mode=mode)
    before = list(store.read_events(run))
    monkeypatch.setattr(
        store, "store_artifact", lambda *a, **k: pytest.fail("Reader must not write")
    )
    p = project_reader_process(store, run)
    assert len(p["roles"]) == 7  # six runtime roles plus explicitly code-only checks
    assert p["question_origin"] == "user"
    assert p["primary_selection"] == "code"  # critical protection overrides unselected primary
    assert p["claim_origins"] == [
        {"claim_id": record.hypotheses[0].claim_id, "role_key": "operating_quality"}
    ]
    assert p["counts"]["main_budget"]["value"] == 3
    assert p["counts"]["sdk_main"]["value"] is None  # custom caller isn't an observed SDK adapter
    agent = project_reader_agent(store, run, "operating_quality", through=p["source_sequence"])
    assert agent["availability"] == "available"
    assert agent["proposal"] == journal.state["results"]["native.operating_quality"]["proposal"]
    assert agent["claim_ids"] == [record.hypotheses[0].claim_id]
    assert agent["relations"][0]["is_key"]
    event = project_reader_agent(store, run, "event_context")
    assert event["availability"] == "not_applicable"
    assert event["reason_code"] == "no_qualified_facts_not_called"
    for key in ["challenge", "synthesis", "evidence", "code_checks"]:
        value = project_reader_agent(store, run, key)
        assert value["availability"] == "available"
        assert "PRIVATE_SENTINEL" not in json.dumps(value)
        assert "native_input" not in json.dumps(value)
    assert store.read_events(run) == before


def test_publication_qualification_and_exact_earlier_boundary(tmp_path):
    store, run, journal, _ = saved(tmp_path, publish=False)
    boundary = store.read_snapshot(run).latest_sequence
    pending = project_reader_agent(store, run, "operating_quality", through=boundary)
    assert pending["availability"] == "pending_publication" and pending["proposal"] is None
    output = journal.state["results"]["native.output"]["record"]
    promote_derived_public_artifact(
        journal.observer,
        contract="research-record-v1",
        value=ResearchRecordV1.model_validate(output),
        graph_task_id="native.final",
        checkpoint_event_id="native-barrier",
        committed_sequence=boundary,
        promoted=set(),
    )
    assert (
        project_reader_agent(store, run, "operating_quality", through=boundary)["availability"]
        == "pending_publication"
    )
    assert project_reader_agent(store, run, "operating_quality")["availability"] == "available"
    with pytest.raises(ValueError):
        project_reader_agent(store, run, "operating_quality", through=999999)


def test_invalid_single_role_degrades_without_losing_final_record_or_other_roles(tmp_path):
    store, run, journal, _ = saved(tmp_path)
    journal.state["results"]["native.operating_quality"]["proposal"]["hypotheses"][0][
        "statement"
    ] = "mismatched proposal"
    journal.persist()
    process = project_reader_process(store, run)
    assert process["availability"] == "partial"
    assert not process["claim_origins"]
    assert project_reader_agent(store, run, "operating_quality")["availability"] == "unavailable"
    assert project_reader_agent(store, run, "synthesis")["availability"] == "available"


def test_missing_unknown_version_and_corrupt_checkpoint_do_not_expose_cached_text(
    tmp_path, monkeypatch
):
    store, run, journal, _ = saved(tmp_path)
    del journal.state["results"]["native.operating_quality"]
    journal.persist()
    assert project_reader_agent(store, run, "operating_quality")["availability"] == "not_recorded"
    journal.state["identity"]["workflow_version"] = "unknown-version"
    journal.persist()
    assert project_reader_agent(store, run, "synthesis")["availability"] == "unsupported"
    real = store.read_artifact

    def corrupt(r, artifact):
        value = real(r, artifact)
        return b"{}" if b'"native_seed"' in value else value

    monkeypatch.setattr(store, "read_artifact", corrupt)
    assert project_reader_process(store, run)["reason_code"] == "checkpoint_unavailable"


def test_zero_challenges_distinct_from_missing_and_no_hypotheses(tmp_path):
    store, run, _, _ = saved(tmp_path, challenge=False)
    output = project_reader_agent(store, run, "challenge")
    assert output["availability"] == "available" and output["proposal"] == {"challenges": []}


def test_empty_saved_challenge_cannot_be_presented_as_zero_when_record_contains_challenges(
    tmp_path,
):
    store, run, journal, record = saved(tmp_path)
    assert record.challenges
    journal.state["results"]["native.challenge"]["proposal"]["challenges"] = []
    journal.persist()
    value = project_reader_agent(store, run, "challenge")
    assert value["availability"] == "unavailable" and value["proposal"] is None
    assert project_reader_agent(store, run, "operating_quality")["availability"] == "available"


def test_count_coverage_sdk_is_not_budget_and_replay_does_not_double_count(tmp_path):
    _, _, journal, _ = saved(tmp_path)
    cp = copy.deepcopy(journal.state)
    cp["native.model.operating_quality.dispatched"] = True
    old = native_counts(cp)
    assert old.sdk_main.value == old.sdk_total.value == 1
    assert old.sdk_main.completeness == "known_lower_bound"
    assert old.sdk_repair.value is None
    assert native_counts(cp) == old
    cp["native_sdk_observation"] = {
        "protocol": "native-sdk-authorization-observation-v1",
        "start_sequence": 0,
        "prior_main_authorizations": 0,
        "prior_repair_authorizations": 0,
    }
    complete = native_counts(cp)
    assert complete.sdk_main.value == 1 and complete.sdk_repair.value == 0
    assert complete.sdk_total.completeness == "complete"
    cp["native_sdk_observation"]["prior_main_authorizations"] = 1
    assert native_counts(cp).sdk_total.completeness == "known_lower_bound"
    assert native_counts(None).sdk_total.value is None


def test_observation_initializes_before_main_and_resume_cannot_certify_prior_calls(tmp_path):
    _, _, journal, _ = saved(tmp_path)
    establish_sdk_observation(journal.ledger)
    assert journal.state["native_sdk_observation"]["prior_main_authorizations"] == 3
    assert native_counts(journal.state).sdk_main.completeness != "complete"
    original = dict(journal.state["native_sdk_observation"])
    establish_sdk_observation(journal.ledger)
    assert journal.state["native_sdk_observation"] == original


def test_http_fixed_roles_bounds_and_audit_native_registry(tmp_path):
    store, run, _, _ = saved(tmp_path)
    with TestClient(create_app(store=store, recover_startup=False, environment={})) as client:
        assert client.get(f"/api/runs/{run}/reader/process").status_code == 200
        assert client.get(f"/api/runs/{run}/reader/agents/challenge").status_code == 200
        assert client.get(f"/api/runs/{run}/reader/agents/config").status_code == 422
        assert (
            client.get(f"/api/runs/{run}/reader/agents/synthesis?source_sequence=99999").status_code
            == 409
        )
    audit = project_audit_summary(store, run)
    assert len(audit["roles"]) == len(audit["stage_navigation"]) == 6
    assert all(r["actor_id"].startswith("native.") for r in audit["roles"])
    assert audit["counts"]["turns"] is None and audit["counts"]["model_calls"] is None


def test_historical_partitions_cannot_admit_later_source_families(tmp_path, monkeypatch):
    _, _, journal, record = saved(tmp_path)
    seed = ResearchRecordV1.model_validate(journal.state["native_seed"])
    financial = next(s for s in seed.evidence if s.source_name == "tushare.financial_statements")

    def with_source(name):
        return seed.model_copy(
            update={
                "evidence": tuple(
                    s.model_copy(update={"source_name": name})
                    if s.evidence_id == financial.evidence_id
                    else s
                    for s in seed.evidence
                )
            }
        )

    sina = with_source("sina.financial_statements")
    assert not saved_fact_views(sina, "evidence-production-v1")["operating_quality"]
    assert saved_fact_views(sina, "evidence-production-v2")["operating_quality"]
    body = with_source("cninfo.document_excerpt")
    assert not saved_fact_views(body, "evidence-production-v2")["event_context"]
    assert saved_fact_views(body, "evidence-production-v3")["event_context"]
    valuation = with_source("tencent.valuation_snapshot")
    assert not saved_fact_views(valuation, "evidence-production-v3")["operating_quality"]
    assert saved_fact_views(valuation, "evidence-production-v4")["operating_quality"]
    # A future live collector/policy expansion cannot change saved-role attribution.
    monkeypatch.setattr(
        "tradingagents.research.native_policy.FINANCIAL_SOURCES", {"future.finance"}
    )
    assert not saved_fact_views(with_source("future.finance"), "evidence-production-v5")[
        "operating_quality"
    ]
    proposal = journal.state["results"]["native.synthesis"]["proposal"]
    from tradingagents.agents.schemas._native_stage import SynthesisProposalV1

    assert saved_dimensions_match(
        record, SynthesisProposalV1.model_validate(proposal).dimensions, "evidence-production-v2"
    )
