"""Native profile reads its assessed record in all three modes, without backfill."""

import json
from pathlib import Path

import pytest

from tradingagents.agents.schemas._research_assessment import DIMENSIONS_BY_MODE
from tradingagents.agents.schemas._research_record import ResearchRecordV1
from tradingagents.execution.output_publisher import promote_derived_public_artifact
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore
from tradingagents.web.research_record_projection import project_research_record

RUN_ID = "run_20261002T010203000000Z_abcd1234"


def record(mode="company_research", *, assessed=True, adapted=False):
    payload = json.loads((Path(__file__).resolve().parents[2] / "shared_fixtures/research-record.json").read_text())["record"]
    payload.update(run_id=RUN_ID, mode=mode)
    if assessed:
        payload["assessment"] = {
            "input_snapshot_id": payload["snapshots"][0]["snapshot_id"],
            "research_question": "经营事实能否支持持续改善？", "judgement": "持续性尚待核查。",
            "dimensions": [{"dimension": name, "status": "unresolved", "judgement": "资料有限。",
                            "limitations": ["覆盖不足"]} for name in DIMENSIONS_BY_MODE[mode]],
            "key_claim_ids": ["f1"], "primary_challenge_id": "c1", "next_check": "核对下一期经营分项。",
            "challenge_assessments": [{"challenge_id": "c1", "rationale": "条件核查不足以关闭经济挑战。"}],
            "completeness": "partial", "quality": "LOW_CONFIDENCE",
            "forward_window_calendar_days": 84 if mode == "catalyst_research" else None,
        }
    if adapted:
        payload.update(construction="adapted_case", source_case_contract="research-case-v2", source_case_sha256="a" * 64)
    return ResearchRecordV1.model_validate(payload)


def publish(store, *, snapshot_mode="company_research", value=None):
    snapshot = RunSnapshot.create(run_id=RUN_ID, ticker="600519", analysis_date="2026-09-30",
        llm_provider="openai", quick_think_llm="quick", deep_think_llm="deep", mode=snapshot_mode,
        holding_context={"ticker": "600519", "quantity": 100, "average_cost": 10} if snapshot_mode == "holding_review" else None,
        metadata={"research_profile": "evidence_v1"})
    store.create_run(snapshot)
    observer = DurableRunObserver(store, RUN_ID, development_assertions=False)
    promote_derived_public_artifact(observer, contract="research-record-v1", value=value or record(snapshot_mode),
        graph_task_id="native.final", checkpoint_event_id="native-barrier", committed_sequence=5, promoted=set())


@pytest.mark.parametrize("mode", tuple(DIMENSIONS_BY_MODE))
def test_native_profile_reads_assessed_record_without_paired_case_or_write(tmp_path, monkeypatch, mode):
    store = RunStore(tmp_path)
    publish(store, snapshot_mode=mode)
    before = list(store.read_events(RUN_ID))
    monkeypatch.setattr(store, "store_artifact", lambda *a, **k: pytest.fail("record read wrote an artifact"))
    for _ in range(3):
        result = project_research_record(store, RUN_ID)
        assert result["state"] == "ready"
        assert result["record"]["mode"] == mode
        assert result["record"]["assessment"]["quality"] == "LOW_CONFIDENCE"
        assert result["record"]["assessment"]["completeness"] == "partial"
        assert result["record"]["source_case_contract"] is None
    assert list(store.read_events(RUN_ID)) == before


@pytest.mark.parametrize("adapted", [False, True])
def test_native_profile_never_accepts_an_assessment_free_or_adapted_case_record(tmp_path, adapted):
    store = RunStore(tmp_path)
    publish(store, value=record(assessed=False, adapted=adapted))
    assert project_research_record(store, RUN_ID)["reason_code"] == "corrupt"


def test_native_profile_does_not_reinterpret_company_mode_as_catalyst(tmp_path):
    store = RunStore(tmp_path)
    publish(store, value=record("catalyst_research"))
    assert project_research_record(store, RUN_ID)["reason_code"] == "corrupt"
