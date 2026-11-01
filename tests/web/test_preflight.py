"""Startup proves current durable journal availability without providers."""
import pytest

from tradingagents.web import preflight


def test_current_runtime_proves_durable_checkpoint_and_budget():
    report = preflight.check_web_runtime(include_web_dependencies=False)
    assert report.ok, report.issues
    assert report.durable_journal
    assert not any("langgraph" in name for name in report.requirements)


def test_missing_dependency_is_actionable(monkeypatch):
    monkeypatch.setattr(preflight, "_installed_version", lambda name: None)
    report = preflight.check_web_runtime()
    assert not report.ok
    assert "missing distribution fastapi" in ";".join(report.issues)


def test_failed_journal_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(preflight, "_run_journal_probe", lambda: False)
    with pytest.raises(preflight.WebRuntimeError, match="durable research journal"):
        preflight.ensure_web_runtime()


def test_probe_can_be_skipped_without_claiming_durability():
    report = preflight.check_web_runtime(include_web_dependencies=False, run_probe=False)
    assert not report.ok
    assert report.as_dict()["durable_journal"] is False
