"""Offline full-prompt cost decisions, repair boundaries and honest failures."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.compare_native_prompt_views import compare_prompt, compare_run, compare_state, main
from scripts.eval_benchmark import MeasurementUnavailable
from scripts.native_input_inventory import encoded
from scripts.profile_native_inputs import prompt_parts
from scripts.replay_synthesis_input import _MemoryJournal, capture_contexts
from tests.test_native_input_profile import checkpoint as profile_checkpoint
from tests.test_native_prompt_view import context
from tradingagents.execution.native_model import NativeModelCaller
from tradingagents.execution.native_prompt_view import VIEW_GUIDANCE, encode_context
from tradingagents.runtime.store import RunStore

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    return profile_checkpoint.__wrapped__(tmp_path_factory)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def prompt(value):
    return "Rules\nSchema:\n{}\nSaved research context:\n" + encoded(value) + "\nExisting guidance"


def save_repair(state, *, sectioned=False):
    state.pop("native.prompt.synthesis.repair", None)
    if sectioned:
        state["results"]["native.synthesis_sections.main"] = {
            "failures": {"dimension:operating_quality": "numeric_literal_unbound"}}
    contexts = capture_contexts(state)
    journal = _MemoryJournal(state)
    journal.last_event = SimpleNamespace(sequence=0)
    caller = NativeModelCaller(effective_config=state["identity"]["config"], run_id=state["run_id"],
        ledger=journal.ledger, cancelled=lambda: False, deadline=lambda: 0)
    original = caller._prompt("synthesis", contexts["synthesis"])
    repair = caller._repair_prompt("synthesis", original, contexts["synthesis"])
    state["native.prompt.synthesis.repair"] = sha(repair)
    return original, repair


def write_checkpoint(root, state):
    directory = root / state["run_id"]
    target = directory / "catalyst-checkpoint"
    target.mkdir(parents=True)
    raw = encoded(state).encode()
    checksum = hashlib.sha256(raw).hexdigest()
    artifact = target / (checksum + ".json")
    artifact.write_bytes(raw)
    event = {"run_id": state["run_id"], "sequence": 1, "type": "artifact.written", "status": "committed",
        "payload": {"kind": "catalyst-checkpoint", "artifact_id": "catalyst-checkpoint:" + checksum,
                    "content_sha256": checksum}}
    (directory / "events.jsonl").write_text(json.dumps(event) + "\n")
    return artifact


def test_complete_prompt_counts_all_overhead_and_preserves_source_markers():
    value = context()
    original = prompt(value)
    row = compare_prompt(original, sha(original))
    expected = prompt(encode_context(value).context) + "\n" + VIEW_GUIDANCE
    assert row["decision"] == "packed" and row["roundtrip_equal"]
    assert row["candidate"]["sha256"] == sha(expected)
    assert row["candidate"]["utf8_bytes"] == len(expected.encode())
    assert row["saved_utf8_bytes"] == len(original.encode()) - len(expected.encode()) > 0
    assert row["required_evidence"]["retention_ratio"] == 1
    assert row["required_evidence"]["added"] == 0
    assert "完整元数据" not in json.dumps(row, ensure_ascii=False)


@pytest.mark.parametrize("value,reason", [({}, "not_applicable"), (context(0), "empty_metadata"),
                                         (context(1, "短"), "nonbeneficial")])
def test_noop_retains_exact_original_prompt_hash(value, reason):
    original = prompt(value)
    result = compare_prompt(original, sha(original))
    assert result["decision"] == "identity_noop" and result["reason"] == reason
    assert result["effective"] == result["baseline"] and result["saved_utf8_bytes"] == 0


def test_exact_zero_savings_keeps_original():
    # One metadata object has a one-byte cost slope, so exercise the actual
    # full-prompt break-even point instead of mocking a size comparison.
    for length in range(1, 500):
        original = prompt(context(1, "x" * length))
        result = compare_prompt(original, sha(original))
        if result["candidate"]["utf8_bytes"] == result["baseline"]["utf8_bytes"]:
            assert result["reason"] == "nonbeneficial"
            assert result["effective"]["sha256"] == sha(original)
            break
    else:
        pytest.fail("expected an exact break-even fixture")


def test_bad_original_hash_or_partial_numeric_is_failure_not_noop():
    original = prompt(context())
    bad_hash = compare_prompt(original, "0" * 64)
    assert bad_hash["decision"] == "error" and "effective" not in bad_hash
    malformed = prompt({"numeric_meta": {}})
    row = compare_prompt(malformed, sha(malformed))
    assert row["decision"] == "error" and row["reason"] == "numeric_policy_invalid"


def test_malformed_hash_cannot_export_arbitrary_saved_content():
    original = prompt(context())
    row = compare_prompt(original, {"api_key": "PRIVATE_HASH_SENTINEL"})
    assert row["reason"] == "prompt_hash_invalid"
    assert "PRIVATE_HASH_SENTINEL" not in json.dumps(row)


def test_state_is_private_deterministic_and_never_calls_models_or_stores(checkpoint, monkeypatch):
    before = copy.deepcopy(checkpoint)

    def forbidden(*args, **kwargs):
        pytest.fail("offline comparison must not create stores/clients or execute requests")

    monkeypatch.setattr(RunStore, "__init__", forbidden)
    monkeypatch.setattr("tradingagents.execution.native_model.create_llm_client", forbidden)
    monkeypatch.setattr(NativeModelCaller, "_invoke", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    result = compare_state(checkpoint)
    assert result == compare_state(checkpoint) and checkpoint == before
    assert result["comparison_complete"]
    assert not result["production_input_changed"] and not result["budget_policy_changed"]
    assert result["usage"]["measured_input_tokens"] is None
    assert all(r["candidate_input_tokens"] is None for r in result["prompts"] + result["requests"])
    assert all(r["roundtrip_equal"] for r in result["prompts"] if r["decision"] == "packed")
    rendered = json.dumps(result, ensure_ascii=False)
    assert "PRIVATE_CONFIG_SENTINEL" not in rendered and "收入兑现可能支撑经营改善" not in rendered


@pytest.mark.parametrize("sectioned", [False, True])
def test_saved_undispatched_and_sectioned_repairs_are_independent_samples(checkpoint, sectioned):
    state = copy.deepcopy(checkpoint)
    original, repair = save_repair(state, sectioned=sectioned)
    if sectioned:
        assert "synthesis_repair_sections" in prompt_parts(repair)[2]
        assert prompt_parts(original)[1] != prompt_parts(repair)[1]
    result = compare_state(state)
    assert result["comparison_complete"]
    rows = {r["phase"]: r for r in result["prompts"] if r["stage"] == "synthesis"}
    assert rows["repair"]["baseline"]["sha256"] == sha(repair)
    assert rows["main"]["baseline"]["sha256"] == sha(original)
    assert rows["repair"]["dispatched_ledger_attempts"] == 0
    assert rows["repair"]["required_evidence"]["retention_ratio"] == 1
    assert result["all_prompt_samples"]["sample_count"] == result["dispatched_ledger_attempts"]["sample_count"] + 1


def test_hash_mismatch_and_orphan_saved_prompt_stay_in_cohort(checkpoint):
    state = copy.deepcopy(checkpoint)
    state["native.prompt.synthesis"] = "0" * 64
    state["native.prompt.unknown_stage"] = "0" * 64
    result = compare_state(state)
    assert not result["comparison_complete"]
    assert result["all_prompt_samples"]["failed_count"] == 2
    assert result["dispatched_ledger_attempts"]["failed_count"] == 1
    assert len(result["prompts"]) == len(compare_state(checkpoint)["prompts"]) + 1
    assert {r["reason"] for r in result["prompts"] if r["decision"] == "error"} == {
        "prompt_hash_mismatch", "context_not_reconstructed"}


def test_missing_dispatched_context_stays_in_totals_without_saved_prompt(checkpoint):
    state = copy.deepcopy(checkpoint)
    request = copy.deepcopy(next(r for r in state["records"] if r["logical_call_id"] == "native.synthesis"))
    request["logical_call_id"] = "native.missing_context"
    state["records"].append(request)
    result = compare_state(state)
    assert not result["comparison_complete"]
    totals = result["dispatched_ledger_attempts"]
    assert totals["sample_count"] == result["usage"]["dispatched_ledger_attempts"]
    assert totals["failed_count"] == 1


def test_unknown_retry_usage_and_unmatched_entry_are_not_fabricated(checkpoint):
    state = copy.deepcopy(checkpoint)
    save_repair(state)
    request = copy.deepcopy(next(r for r in state["records"] if r["logical_call_id"] == "native.synthesis"))
    request.update(logical_call_id="native.synthesis.repair.retry.1", bucket="network_retry")
    state["records"].append(request)
    state["native.model_usage"] = {"unmatched": {"input_tokens": 7, "output_tokens": 2}}
    result = compare_state(state)
    retry = next(r for r in result["requests"] if r["retry"])
    assert retry["input_tokens"] is None and retry["candidate_input_tokens"] is None
    assert retry["comparison"] == "packed"
    assert result["usage"]["unmatched_usage_entries"] == 1 and not result["usage"]["usage_complete"]


def test_missing_work_and_bad_kernel_hash_cannot_trigger_fallback(checkpoint):
    state = copy.deepcopy(checkpoint)
    state["native.synthesis.input"]["sha256"] = "0" * 64
    with pytest.raises(MeasurementUnavailable, match="kernel_input_hash_mismatch"):
        compare_state(state)
    state = copy.deepcopy(checkpoint)
    state["results"].pop("native.operating_quality")
    state["records"] = [r for r in state["records"] if r["logical_call_id"] != "native.operating_quality"]
    with pytest.raises(MeasurementUnavailable):
        compare_state(state)


def test_cli_exit_codes_and_committed_read_do_not_change_files(tmp_path, checkpoint, capsys):
    artifact = write_checkpoint(tmp_path, checkpoint)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    args = ["--runs-root", str(tmp_path), "--run-id", checkpoint["run_id"]]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["comparison_complete"]
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    damaged = copy.deepcopy(checkpoint)
    damaged["native.prompt.synthesis"] = "0" * 64
    write_checkpoint(tmp_path / "mismatch", damaged)
    assert main(["--runs-root", str(tmp_path / "mismatch"), "--run-id", checkpoint["run_id"]]) == 1
    assert not json.loads(capsys.readouterr().out)["comparison_complete"]
    artifact.write_bytes(b"{}")
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "artifact_hash_mismatch"


def test_absent_root_is_not_created(tmp_path):
    root = tmp_path / "absent"
    with pytest.raises(MeasurementUnavailable):
        compare_run(root, "run_missing")
    assert not root.exists()
