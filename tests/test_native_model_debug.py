"""Opt-in rejected final text stays outside durable/public model diagnostics."""

import json
import time
from types import SimpleNamespace

import pytest

from tradingagents.execution import native_model_debug as debug
from tradingagents.execution.native_model import NativeModelCaller, NativeModelUnavailable
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.catalyst_checkpoint import CatalystJournal
from tradingagents.runtime.run_models import RunSnapshot
from tradingagents.runtime.store import RunStore

RUN = "run_20261018T010000000000Z_ab123456"


def test_capture_is_disabled_by_default_and_restricted_to_synthesis(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "DEBUG_DIRECTORY", tmp_path / "debug")
    monkeypatch.delenv("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES", raising=False)
    assert debug.capture_synthesis_failure(RUN, "synthesis", "main", SimpleNamespace(content="invalid")) is None
    monkeypatch.setenv("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES", "1")
    assert debug.capture_synthesis_failure(RUN, "challenge", "main", SimpleNamespace(content="invalid")) is None
    assert debug.capture_synthesis_failure("../outside", "synthesis", "main", SimpleNamespace(content="invalid")) is None
    assert not (tmp_path / "debug").exists()


def test_capture_excludes_reasoning_metadata_and_preserves_final_text(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "DEBUG_DIRECTORY", tmp_path / "debug")
    monkeypatch.setenv("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES", "1")
    response = SimpleNamespace(content=[{"type": "reasoning", "text": "PRIVATE_REASONING"},
                                        {"type": "text", "text": '{"proposal":"invalid"}'}],
                               response_metadata={"authorization": "CREDENTIAL"})
    path = debug.capture_synthesis_failure(RUN, "synthesis", "repair", response)
    raw = path.read_text()
    assert "PRIVATE_REASONING" not in raw and "CREDENTIAL" not in raw
    assert json.loads(raw)["response_text"] == '{"proposal":"invalid"}'
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert debug.capture_synthesis_failure(RUN, "synthesis", "repair", response) == path


def test_unwritable_capture_does_not_change_model_failure(tmp_path, monkeypatch):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    monkeypatch.setattr(debug, "DEBUG_DIRECTORY", blocked)
    monkeypatch.setenv("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES", "1")
    assert debug.capture_synthesis_failure(RUN, "synthesis", "main", SimpleNamespace(content="invalid")) is None


def test_invalid_unicode_capture_cannot_mask_original_model_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "DEBUG_DIRECTORY", tmp_path / "debug")
    monkeypatch.setenv("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES", "1")
    assert debug.capture_synthesis_failure(RUN, "synthesis", "main", SimpleNamespace(content="\ud800")) is None
    assert not (tmp_path / "debug").exists()


def test_rejected_final_response_never_enters_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "DEBUG_DIRECTORY", tmp_path / "debug")
    monkeypatch.setenv("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES", "1")
    store = RunStore(tmp_path / "runs")
    snapshot = RunSnapshot.create(ticker="300750.SZ", analysis_date="2026-10-18",
        llm_provider="deepseek", quick_think_llm="quick", deep_think_llm="deep",
        runtime_semantics_hash="a" * 64, metadata={"effective_config_artifact_id": "data:" + "b" * 64})
    store.create_run(snapshot)
    journal = CatalystJournal(DurableRunObserver(store, snapshot.run_id, development_assertions=False),
                              {"test": "synthesis-debug"})
    caller = NativeModelCaller(effective_config={"llm_provider": "deepseek", "quick_think_llm": "quick",
        "deep_think_llm": "deep"}, run_id=snapshot.run_id, ledger=journal.ledger,
        cancelled=lambda: False, deadline=lambda: time.monotonic() + 30)
    with pytest.raises(NativeModelUnavailable):
        caller._parse("synthesis", SimpleNamespace(content="REJECTED_PRIVATE_FINAL_TEXT"))
    assert "REJECTED_PRIVATE_FINAL_TEXT" not in json.dumps(journal.state)
    files = list((tmp_path / "debug").rglob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["response_text"] == "REJECTED_PRIVATE_FINAL_TEXT"
