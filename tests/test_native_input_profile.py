"""F04 read-only sizes, frozen scope preservation and honest unknown usage."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.eval_benchmark import MeasurementUnavailable
from scripts.native_input_inventory import (
    compare_inventory,
    composition,
    digest,
    encoded,
    inventory,
    repetitions,
)
from scripts.profile_native_inputs import profile_run, profile_state, prompt_parts, usage_rows
from scripts.replay_synthesis_input import _MemoryJournal, capture_contexts
from tests.test_challenge_pipeline import DirectedCaller
from tests.test_native_record import financials, fixture
from tests.test_unified_research import run
from tradingagents.agents.schemas._challenge_verification import CHALLENGE_CHECK_POLICY
from tradingagents.agents.schemas._factual_premise import FACTUAL_PREMISE_POLICY
from tradingagents.execution.native_model import NativeModelCaller
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
from tradingagents.research.numeric_integration import attach_numeric_attribution
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    store = RunStore(tmp_path_factory.mktemp("input-profile"))
    snapshot = RunSnapshot.create(ticker="600519", analysis_date="2026-09-30")
    store.create_run(snapshot)
    identity = {"workflow_version": UNIFIED_WORKFLOW_VERSION, "focus_budget_policy": UNIFIED_BUDGET_POLICY,
        "ticker": snapshot.ticker, "mode": "company_research", "cutoff": snapshot.analysis_date,
        "numeric_narrative_policy": NUMERIC_NARRATIVE_POLICY,
        "company_research_policy": COMPANY_RESEARCH_POLICY, "report_delivery_policy": REPORT_DELIVERY_POLICY,
        "specialist_reference_policy": SPECIALIST_REFERENCE_POLICY, "challenge_check_policy": CHALLENGE_CHECK_POLICY,
        "factual_premise_policy": FACTUAL_PREMISE_POLICY,
        "config": {"llm_provider": "openai", "quick_think_llm": "offline", "deep_think_llm": "offline",
                   "api_key": "PRIVATE_CONFIG_SENTINEL"}}
    journal = CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False), identity)
    draft, context = fixture(financial_payload=financials(8))
    draft = draft.model_copy(update={"run_id": snapshot.run_id,
        "evidence": tuple({**e, "run_id": snapshot.run_id} for e in draft.evidence)})
    seed = build_native_record(draft, context, mode="company_research", include_coverage=True,
        include_valuation=True, include_minimum=True, include_basics=True)
    seed = attach_numeric_attribution(seed, journal)
    run(journal, seed, DirectedCaller())
    state = copy.deepcopy(journal.state)
    contexts = capture_contexts(state)
    # Freeze the same prompt-view markers selected for fresh SDK V7 calls.
    # Rendering remains offline; the custom caller produced no SDK usage.
    for stage in contexts:
        if stage != "challenge":
            state["native.binding_guidance." + stage] = 1
            state["native.reference_schema." + stage] = 3 if stage == "synthesis" else 1
            state["native.reference_aliases." + stage] = 2 if stage == "synthesis" else 1
    memory = _MemoryJournal(state)
    memory.last_event = SimpleNamespace(sequence=0)
    caller = NativeModelCaller(effective_config=state["identity"]["config"], run_id=seed.run_id,
        ledger=memory.ledger, cancelled=lambda: False, deadline=lambda: 0)
    for stage, context in contexts.items():
        state["native.prompt." + stage] = prompt_parts(caller._prompt(stage, context))[0]["sha256"]
    return state


def test_profile_new_policies_is_deterministic_private_and_never_executes(checkpoint, monkeypatch):
    before = copy.deepcopy(checkpoint)

    def forbidden(*args, **kwargs):
        pytest.fail("profiling must not construct stores, clients or execute requests")

    monkeypatch.setattr(RunStore, "__init__", forbidden)
    monkeypatch.setattr("tradingagents.execution.native_model.create_llm_client", forbidden)
    monkeypatch.setattr(NativeModelCaller, "_invoke", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    result = profile_state(checkpoint, include_inventory=True)
    assert result == profile_state(checkpoint, include_inventory=True)
    assert checkpoint == before
    assert result["identity"]["factual_premise_policy"] == FACTUAL_PREMISE_POLICY
    assert result["identity"]["challenge_check_policy"] == CHALLENGE_CHECK_POLICY
    assert result["usage"]["unknown_input_attempts"] == result["usage"]["dispatched_ledger_attempts"]
    assert result["usage"]["measured_input_tokens"] is None
    stages = {r["stage"]: r for r in result["stages"]}
    assert {"operating_quality", "challenge", "response_operating_quality", "synthesis"} <= stages.keys()
    for row in stages.values():
        prompt = row["prompts"]["main"]
        assert prompt["availability"] == "hash_verified"
        assert prompt["required_evidence"]["semantic_completeness"] == "not_assessed"
        for axis in ("characters", "utf8_bytes"):
            assert sum(part[axis] for part in prompt["parts"].values()) == prompt[axis]
    rendered = json.dumps(result)
    assert "PRIVATE_CONFIG_SENTINEL" not in rendered
    assert "收入兑现可能支撑经营改善" not in rendered


def test_prompt_layout_handles_source_markers_and_disjoint_utf8_sizes():
    context = {"text": "来源包含 Schema:\n 与 Saved research context:\n，保持原文"}
    prompt = "Rules\nSchema:\n{}\nSaved research context:\n" + encoded(context) + "\nGuidance"
    parts, schema, actual = prompt_parts(prompt)
    assert schema == {} and actual == context
    assert parts["utf8_bytes"] > parts["characters"]
    assert sum(v["utf8_bytes"] for v in parts["parts"].values()) == len(prompt.encode())


def test_composition_has_no_double_counted_nested_record():
    context = {"facts": ["事实"], "verification": {"record": {"claims": ["事实"]}, "outcomes": []}}
    report = composition(context)
    for axis in ("characters", "utf8_bytes"):
        assert sum(p[axis] for p in report["parts"]) + report["container_syntax"][axis] == report[axis]


def test_repetition_counts_whole_strings_without_calling_them_savings():
    text = "重复来源文本" * 20
    report = repetitions({"facts": [text, text], "record": {"text": text}, "other": "短文"})
    assert report["duplicate_string_groups"] == 1
    assert report["largest_groups"][0]["occurrences"] == 3
    assert report["repeated_payload_bytes"] == 2 * len(encoded(text).encode())
    assert text not in json.dumps(report)


def preservation_context():
    return {"facts": [{"claim_id": "f1", "statement": "反向事实", "evidence_ids": ["e1"]}],
        "sources": [{"evidence_id": "e1", "published_at": "2026-08-20", "usable_as_of": "2026-09-30",
            "content": {"text": "原文片段", "truncated": False}, "limitations": ["存在来源冲突"]}],
        "numeric_catalog": {"anchors": [{"anchor_id": "a1", "value": "1.0000001", "unit": "CNY",
            "metadata": {"report_period": "2026-06-30"}, "required_fact_ids": ["f1"]}]},
        "factual_observations": [{"observation_id": "o1", "text": "下降", "fact_ids": ["f1"]}],
        "allowed_fact_ids": ["f1"], "dimension_claim_ids": {"operating_quality": ["f1"]},
        "challenges": [{"challenge_id": "c1", "statement": "反证仍未排除", "required_inputs": ["新披露"]}]}


@pytest.mark.parametrize("damage", ["fact_binding", "source_text", "source_limit", "period", "precision",
    "observation", "challenge", "allowed_ids", "relocate"])
def test_inventory_rejects_lost_evidence_bindings_limits_and_scope(damage):
    base = preservation_context()
    candidate = copy.deepcopy(base)
    if damage == "fact_binding":
        candidate["facts"][0]["evidence_ids"] = ["another"]
    elif damage == "source_text":
        candidate["sources"][0]["content"]["text"] = "截短"
    elif damage == "source_limit":
        candidate["sources"][0]["limitations"] = []
    elif damage == "period":
        candidate["numeric_catalog"]["anchors"][0]["metadata"]["report_period"] = "2025-06-30"
    elif damage == "precision":
        candidate["numeric_catalog"]["anchors"][0]["value"] = "1.00"
    elif damage == "observation":
        candidate["factual_observations"][0]["text"] = "上升"
    elif damage == "challenge":
        candidate["challenges"] = []
    elif damage == "allowed_ids":
        candidate["allowed_fact_ids"] = []
    else:
        candidate["unrelated_receipt"] = {"facts": candidate.pop("facts")}
    result = compare_inventory(inventory(base), inventory(candidate))
    assert result["missing"] and result["retention_ratio"] < 1
    assert result["semantic_completeness"] == "not_assessed"


def test_exact_duplicate_entity_removal_does_not_hide_a_scope_change():
    base = preservation_context()
    base["facts"] *= 2
    candidate = copy.deepcopy(base)
    candidate["facts"].pop()
    assert compare_inventory(inventory(base), inventory(candidate))["retention_ratio"] == 1


def test_usage_counts_failed_retry_unknown_and_unmatched_once():
    state = {"records": [
        {"logical_call_id": "native.synthesis", "bucket": "main_analysis", "dispatched_at": "t"},
        {"logical_call_id": "native.synthesis.repair", "bucket": "structured_repair", "dispatched_at": "t"},
        {"logical_call_id": "native.synthesis.repair.retry.1", "bucket": "network_retry", "dispatched_at": "t"},
        {"logical_call_id": "native.operating_quality", "bucket": "main_analysis", "dispatched_at": None}],
        "native.model_usage": {"synthesis": {"input_tokens": 0, "output_tokens": 5},
            "synthesis.repair": {"input_tokens": 20}, "unmatched": {"input_tokens": 7, "output_tokens": 2}}}
    rows = usage_rows(state)
    assert len(rows) == 4
    assert sum(r["input_tokens"] or 0 for r in rows) == 27
    retry = next(r for r in rows if r["retry"])
    assert retry["input_tokens"] is None and retry["phase"] == "repair"
    assert sum(not r["ledger_dispatched"] for r in rows) == 1


def test_prompt_hash_mismatch_never_reports_candidate_as_actual_input(checkpoint):
    state = copy.deepcopy(checkpoint)
    state["native.prompt.synthesis"] = "0" * 64
    row = next(r for r in profile_state(state)["stages"] if r["stage"] == "synthesis")
    assert row["prompts"]["main"]["availability"] == "hash_mismatch"
    assert "characters" not in row["prompts"]["main"]


def test_changed_kernel_context_is_rejected(checkpoint):
    state = copy.deepcopy(checkpoint)
    state["native.synthesis.input"]["sha256"] = "0" * 64
    with pytest.raises(MeasurementUnavailable, match="kernel_input_hash_mismatch"):
        profile_state(state)


def test_missing_cached_work_never_generates_new_model_input(checkpoint):
    state = copy.deepcopy(checkpoint)
    state["results"].pop("native.operating_quality")
    state["records"] = [r for r in state["records"] if r["logical_call_id"] != "native.operating_quality"]
    with pytest.raises(MeasurementUnavailable):
        profile_state(state)


def test_missing_root_is_not_created(tmp_path):
    root = tmp_path / "absent"
    with pytest.raises(MeasurementUnavailable):
        profile_run(root, "run_missing")
    assert not root.exists()


def test_committed_checkpoint_read_is_hash_checked_and_does_not_write(tmp_path, checkpoint, monkeypatch):
    directory = tmp_path / checkpoint["run_id"]
    target = directory / "catalyst-checkpoint"
    target.mkdir(parents=True)
    raw = encoded(checkpoint).encode()
    sha = hashlib.sha256(raw).hexdigest()
    artifact = target / (sha + ".json")
    artifact.write_bytes(raw)
    event = {"run_id": checkpoint["run_id"], "sequence": 1, "type": "artifact.written",
        "status": "committed", "payload": {"kind": "catalyst-checkpoint",
            "artifact_id": "catalyst-checkpoint:" + sha, "content_sha256": sha}}
    (directory / "events.jsonl").write_text(json.dumps(event) + "\n")
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(RunStore, "__init__", lambda *a, **k: pytest.fail("must not construct a store"))
    assert profile_run(tmp_path, checkpoint["run_id"])["stages"]
    assert {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()} == before
    artifact.write_bytes(b"{}")
    with pytest.raises(MeasurementUnavailable, match="artifact_hash_mismatch"):
        profile_run(tmp_path, checkpoint["run_id"])


def test_unknown_inventory_policy_is_not_compared():
    base = inventory(preservation_context())
    changed = {**base, "policy": "unknown"}
    with pytest.raises(ValueError, match="inventory_policy_mismatch"):
        compare_inventory(base, changed)
    assert digest(base) == digest(copy.deepcopy(base))
