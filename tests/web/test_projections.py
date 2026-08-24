import hashlib
import json

import pytest

from tradingagents.observability.events import PersistedEvent, RunEventDraft
from tradingagents.web.projections import (
    InvalidCursor,
    RunProjectionPublisher,
    build_debate_journey,
    build_workflow,
    data_quality_v1,
    recent_runs_page,
)
from tradingagents.web.run_models import RunSnapshot
from tradingagents.web.store import InvalidStorePath, RunStore


def _completed_turn(run_id: str, sequence: int, actor_id: str) -> PersistedEvent:
    return PersistedEvent(
        event_id=f"{run_id}:{sequence}",
        run_id=run_id,
        sequence=sequence,
        timestamp="2026-08-03T00:00:00Z",
        type="turn.completed",
        payload={
            "turn_id": f"{actor_id}-1",
            "turn_index": 1,
            "turn_status": "completed",
            "role_instance_id": actor_id,
            "graph_task_id": f"gt-{actor_id}",
            "graph_step": sequence,
            "reason": "test_complete",
            "duration_ms": 10,
        },
        actor_id=actor_id,
    )


def _snapshot(*, run_id: str, status: str = "completed", **kwargs) -> RunSnapshot:
    return RunSnapshot.create(
        run_id=run_id,
        ticker="AAPL",
        analysis_date="2026-08-03",
        selected_analysts=("market",),
        llm_provider="openai",
        quick_think_llm="fast",
        deep_think_llm="deep",
        **kwargs,
    ).evolve(status=status)


def test_recent_page_includes_failed_runs_with_error_category_and_stable_cursor(tmp_path):
    store = RunStore(tmp_path / "runs")
    failed = store.create_run(
        _snapshot(
            run_id="run_20260803T010101000000Z_aaaaaaaa",
            status="failed",
            error_category="provider_timeout",
            error_message="TimeoutError: upstream timed out",
        )
    )
    first = store.create_run(_snapshot(run_id="run_20260803T020202000000Z_bbbbbbbb"))
    second = store.create_run(_snapshot(run_id="run_20260803T030303000000Z_cccccccc"))

    page = recent_runs_page(store.list_runs(), limit=1, cursor=None)

    assert [item["run_id"] for item in page["items"]] == [second.run_id]
    assert page["next_cursor"]
    next_page = recent_runs_page(store.list_runs(), limit=1, cursor=page["next_cursor"])
    assert [item["run_id"] for item in next_page["items"]] == [first.run_id]
    final_page = recent_runs_page(store.list_runs(), limit=1, cursor=next_page["next_cursor"])
    assert [item["run_id"] for item in final_page["items"]] == [failed.run_id]
    assert final_page["items"][0]["error_category"] == "provider_timeout"
    with pytest.raises(InvalidCursor):
        recent_runs_page(store.list_runs(), limit=1, cursor="not-a-cursor")




def test_data_quality_deduplicates_repeated_capabilities():
    snapshot = _snapshot(
        run_id="run_20260803T070707000000Z_aaaaaaaa",
        degraded_data_sources=(
            {"capability": "fundamentals", "status": "degraded"},
            {"capability": "fundamentals", "status": "degraded"},
            {"capability": "company_news", "status": "degraded"},
            {"capability": "dragon_tiger", "status": "unavailable"},
            {"capability": "dragon_tiger", "status": "unavailable"},
        ),
    )

    quality = data_quality_v1(snapshot)

    assert quality["degraded_capabilities"] == ["fundamentals", "company_news"]
    assert quality["unavailable_capabilities"] == ["dragon_tiger"]


def test_run_view_is_a_cached_legacy_shell_without_markdown_parsing(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run(_snapshot(run_id="run_20260803T040404000000Z_dddddddd"))
    store.append_event(RunEventDraft(run.run_id, "run.started", {"run_status": "running"}))

    publisher = RunProjectionPublisher(store)
    first = publisher.read_or_rebuild_view(run.run_id)
    second = publisher.read_or_rebuild_view(run.run_id)

    assert first["projection_status"] == "partial"
    assert first["source_sequence"] == 1
    assert first["view"]["brief"] == {
        "availability": "unavailable",
        "reason_code": "legacy_no_typed_outputs",
        "value": None,
    }
    assert first == second
    assert (tmp_path / "runs" / run.run_id / "projections" / "run-view-v1.json").is_file()


def test_debate_journey_measures_rounds_from_completed_turns(tmp_path):
    run_id = "run_20260803T050505000000Z_eeeeeeee"
    events = [
        _completed_turn(run_id, seq, actor_id)
        for seq, actor_id in enumerate(
            (
                "researcher.bull",
                "researcher.bear",
                "researcher.bull",
                "researcher.bear",
                "manager.research",
                "trader",
                "risk.aggressive",
                "risk.neutral",
                "risk.conservative",
                "manager.portfolio",
            ),
            start=1,
        )
    ]
    workflow = build_workflow(events)
    journey = build_debate_journey(workflow, events, reader_brief=None)

    rounds = {stage["stage_id"]: stage["rounds"] for stage in journey["stages"]}
    assert rounds["research"] == 2
    assert rounds["risk"] == 1
    assert rounds["trading"] is None
    # No typed public outputs -> insight fields degrade without crashing.
    assert journey["research_rating"] is None
    assert journey["risk_consensus"] == {
        "conviction": None,
        "disagreement": "unavailable",
        "abstained_roles": [],
    }


def test_reader_brief_uses_committed_public_outputs_without_markdown_parsing(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run(_snapshot(run_id="run_20260803T060606000000Z_ffffffff"))
    portfolio = store.store_artifact(
        run.run_id,
        kind="public-portfolio",
        value={
            "schema_version": 1,
            "run_id": run.run_id,
            "turn_id": "turn_portfolio",
            "committed_sequence": 1,
            "rating": "Overweight",
            "executive_summary": "This Markdown-compatible field must not be promoted as a claim.",
            "investment_thesis": "Opaque narrative.",
            "price_target": 210.0,
            "time_horizon": "3 months",
            "execution_action": "Buy",
            "requested_quantity": 10,
            "risk_signals": [],
            "top_drivers": [],
        },
    )
    research = store.store_artifact(
        run.run_id,
        kind="public-research",
        value={
            "schema_version": 1,
            "run_id": run.run_id,
            "turn_id": "turn_research",
            "committed_sequence": 2,
            "recommendation": "Overweight",
            "rationale": "Opaque narrative.",
            "strategic_actions": "Opaque narrative.",
            "strategy_signals": [
                {"strategy_id": "market", "conviction": 0.4, "confidence": 0.8, "abstain": False, "rationale": "Public but uncited."}
            ],
            "delegation_tasks": [],
        },
    )
    for artifact, turn_id, kind in ((portfolio, "turn_portfolio", "portfolio"), (research, "turn_research", "research")):
        store.append_event(
            RunEventDraft(
                run.run_id,
                "artifact.written",
                {
                    "artifact_id": artifact.artifact_id,
                    "kind": artifact.kind,
                    "media_type": artifact.media_type,
                    "content_sha256": artifact.content_sha256,
                    "byte_size": artifact.byte_size,
                    "locator": artifact.locator,
                    "turn_id": turn_id,
                    "graph_task_id": f"task_{kind}",
                    "public_output_kind": kind,
                },
            )
        )

    view = RunProjectionPublisher(store).read_or_rebuild_view(run.run_id)

    brief = view["view"]["brief"]["value"]
    assert brief["availability"] == "partial"
    assert brief["research_rating"] == "Overweight"
    assert brief["price_target"] == 210.0
    assert brief["analyst_cards"][0]["lens"] == "market"
    assert brief["executive_summary"] is None
    assert "executive_summary_missing" in brief["omissions"]
    assert "This Markdown-compatible field" not in str(brief)



def test_reader_brief_promotes_only_claims_with_committed_same_run_refs(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run(_snapshot(run_id="run_20260803T070707000000Z_11111111"))
    evidence = store.store_artifact(run.run_id, kind="data", value={"fact": "committed"})
    store.append_event(
        RunEventDraft(
            run.run_id,
            "artifact.written",
            {
                "artifact_id": evidence.artifact_id,
                "kind": evidence.kind,
                "media_type": evidence.media_type,
                "content_sha256": evidence.content_sha256,
                "byte_size": evidence.byte_size,
                "locator": evidence.locator,
            },
        )
    )
    ref_id = hashlib.sha256(
        json.dumps({"kind": "artifact", "artifact_id": evidence.artifact_id}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    claim = {"text": "Committed public fact.", "evidence_ref_ids": [ref_id]}
    research = store.store_artifact(
        run.run_id,
        kind="public-research",
        value={
            "schema_version": 1, "run_id": run.run_id, "turn_id": "research_turn", "committed_sequence": 2,
            "recommendation": "Overweight", "rationale": "", "strategic_actions": "",
            "strategy_signals": [{"strategy_id": "market", "conviction": 0.2, "confidence": 0.7, "abstain": False, "rationale": "", "key_findings": [claim]}],
            "public_digest": {"agreed_facts": [claim], "key_disagreements": [], "changed_views": [], "remaining_uncertainties": []},
        },
    )
    portfolio = store.store_artifact(
        run.run_id,
        kind="public-portfolio",
        value={
            "schema_version": 1, "run_id": run.run_id, "turn_id": "portfolio_turn", "committed_sequence": 3,
            "rating": "Overweight", "price_target": None, "time_horizon": None,
            "execution_action": "Hold", "requested_quantity": 0,
            "top_drivers": [{"label": claim["text"], "evidence_ref_ids": [ref_id], "direction": "positive", "importance": 0.8}],
            "reader_fields": {"executive_summary": claim, "catalysts": [], "invalidation_conditions": []},
        },
    )
    for artifact, turn_id, kind in ((research, "research_turn", "research"), (portfolio, "portfolio_turn", "portfolio")):
        store.append_event(
            RunEventDraft(
                run.run_id,
                "artifact.written",
                {
                    "artifact_id": artifact.artifact_id,
                    "kind": artifact.kind,
                    "media_type": artifact.media_type,
                    "content_sha256": artifact.content_sha256,
                    "byte_size": artifact.byte_size,
                    "locator": artifact.locator,
                    "turn_id": turn_id,
                    "public_output_kind": kind,
                },
            )
        )

    brief = RunProjectionPublisher(store).read_or_rebuild_view(run.run_id)["view"]["brief"]["value"]

    assert brief["executive_summary"]["text"] == "Committed public fact."
    assert brief["drivers"][0]["evidence_ref_ids"] == [ref_id]
    assert brief["analyst_cards"][0]["findings"][0]["claim_id"]
    assert brief["evidence_refs"][0]["target"]["artifact_id"] == evidence.artifact_id



def test_fixed_projection_paths_are_allowlisted(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run(_snapshot(run_id="run_20260803T050505000000Z_eeeeeeee"))

    store.write_fixed_json(run.run_id, "projections/run-view-v1.json", {"schema_version": 1})
    assert store.read_fixed_json(run.run_id, "projections/run-view-v1.json") == {"schema_version": 1}
    with pytest.raises(InvalidStorePath):
        store.write_fixed_json(run.run_id, "projections/../escape.json", {})
