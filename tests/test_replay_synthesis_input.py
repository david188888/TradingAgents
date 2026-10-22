"""Replay the real kernel against synthetic caches with no persistence/model."""

import copy

import pytest

from scripts.eval_benchmark import MeasurementUnavailable
from scripts.replay_synthesis_input import reconstruct
from tests.test_unified_research import UnifiedCaller, run, setup
from tradingagents.runtime.store import RunStore


@pytest.fixture
def checkpoint(tmp_path):
    journal, seed = setup(tmp_path)
    run(journal, seed, UnifiedCaller())
    return copy.deepcopy(journal.state)


def test_reconstruction_matches_saved_input_without_mutation_or_store(checkpoint, monkeypatch):
    original = copy.deepcopy(checkpoint)

    def forbidden(*args, **kwargs):
        pytest.fail("offline reconstruction must not construct a store")

    monkeypatch.setattr(RunStore, "__init__", forbidden)
    result = reconstruct(checkpoint)
    assert result["matches"] is True
    assert checkpoint == original


def test_changed_expected_input_is_reported_as_mismatch(checkpoint):
    checkpoint["native.synthesis.input"]["sha256"] = "0" * 64
    assert reconstruct(checkpoint)["matches"] is False


def test_changed_upstream_context_cannot_silently_replay(checkpoint):
    checkpoint["native.operating_quality.input"]["sha256"] = "0" * 64
    with pytest.raises(MeasurementUnavailable, match="reconstruction_failed"):
        reconstruct(checkpoint)


def test_missing_cache_never_triggers_a_model(checkpoint):
    checkpoint["results"].pop("native.operating_quality")
    checkpoint["records"] = [row for row in checkpoint["records"]
                              if row["logical_call_id"] != "native.operating_quality"]
    with pytest.raises(MeasurementUnavailable, match="replay_requires_uncached_stage"):
        reconstruct(checkpoint)
