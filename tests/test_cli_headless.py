"""The machine CLI stays an adapter to committed V9 output."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import cli.research as research
from cli.main import app


def lines(result):
    return [json.loads(line) for line in result.stdout.splitlines()]


@pytest.fixture
def command(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-secret")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "llm": {"provider": "deepseek", "backend_url": "https://api.example/v1?key=offline-secret"},
        "run": {"display_report": True},
    }))
    return ["analyze", "--config", str(config), "--json", "--run-dir", str(tmp_path / "store")]


def test_json_plan_previews_local_request_without_dispatch_or_creating_store(command, monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.setattr(research, "run_research", lambda *a, **k: pytest.fail("plan started a run"))
    result = CliRunner().invoke(app, [*command, "--plan", "--ticker", "002130", "--date", "2026-10-30",
                                     "--focus", "private investor question"])
    row, = lines(result)
    assert result.exit_code == 0, result.output
    assert row["type"] == "command.result" and row["status"] == "planned" and row["run_id"] is None
    preview = row["plan"]
    assert preview["ticker"] == "002130.SZ" and preview["analysis_date"] == "2026-10-30"
    assert preview["has_focus"] is True and preview["decision_verification_enabled"] is False
    assert preview["workflow_version"] == "evidence-production-v9" and preview["provider"] == "deepseek"
    assert "offline-secret" not in result.stdout and "private investor question" not in result.stdout
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("options", [[], ["--plan"], ["--plan", "--resume", "unused"],
                                    ["--ticker", "002130", "--show"],
                                    ["--ticker", "002130", "--citation-style", "numbered"]])
def test_json_invalid_invocations_do_not_prompt_or_dispatch(command, monkeypatch, options):
    monkeypatch.setattr(research, "run_research", lambda *a, **k: pytest.fail("invalid invocation executed"))
    monkeypatch.setattr("typer.prompt", lambda *a, **k: pytest.fail("headless prompted"))
    result = CliRunner().invoke(app, [*command, *options])
    assert result.exit_code == 2, result.output
    assert lines(result) == [{"schema_version": 1, "type": "command.result", "status": "invalid_input",
                              "run_id": None, "reason": "bad_parameter"}]
    assert result.stderr


def test_json_projects_persisted_events_and_never_smuggles_stdout(command, monkeypatch, tmp_path):
    report = tmp_path / "canonical.md"
    report.write_text("完整报告不流到 stdout\n")

    def runner(request, root, *, on_event, **kwargs):
        assert request.ticker == "002130.SZ"
        print("stray provider text")
        on_event(SimpleNamespace(run_id="test-id", sequence=1, type="run.started", timestamp="2026-11-01T12:00:00Z",
                                 actor_id=None, status="running", payload={"secret": "do not send"}))
        return research.TerminalResult("test-id", report, {"synthesis": {"stance": "neutral"}})

    monkeypatch.setattr(research, "run_research", runner)
    output = tmp_path / "export.md"
    result = CliRunner().invoke(app, [*command, "--ticker", "002130", "--output", str(output)])
    assert result.exit_code == 0, result.output
    start, event, terminal = lines(result)
    assert start["type"] == "command.started" and start["run_id"] is None
    assert event["type"] == "run.started" and event["sequence"] == 1 and "payload" not in event
    assert terminal == {"schema_version": 1, "type": "command.result", "status": "completed", "run_id": "test-id",
                        "published": True, "report_path": str(report.resolve()), "export_path": str(output.resolve()),
                        "stance": "neutral"}
    assert "stray provider text" in result.stderr and "完整报告" not in result.output
    assert report.read_bytes() == output.read_bytes()


@pytest.mark.parametrize(("error", "code", "status"), [(RuntimeError, 1, "failed"), (KeyboardInterrupt, 130, "interrupted")])
def test_json_reports_run_failure_and_interrupt(command, monkeypatch, error, code, status):
    def runner(*args, **kwargs):
        raise error("sensitive provider exception")

    monkeypatch.setattr(research, "run_research", runner)
    result = CliRunner().invoke(app, [*command, "--ticker", "002130"])
    assert result.exit_code == code
    start, row = lines(result)
    assert start["type"] == "command.started"
    assert row["type"] == "command.result" and row["status"] == status
    assert "sensitive provider exception" not in result.output


def test_export_failure_does_not_claim_research_was_unpublished(command, monkeypatch, tmp_path):
    report = tmp_path / "canonical.md"
    report.write_text("published")
    monkeypatch.setattr(research, "run_research", lambda *a, **k: research.TerminalResult("test-id", report, {}))
    result = CliRunner().invoke(app, [*command, "--ticker", "002130", "--output", str(tmp_path)])
    assert result.exit_code == 1
    _, row = lines(result)
    assert row["status"] == "failed" and row["reason"] == "report_output" and row["published"] is True
    assert row["report_path"] == str(report.resolve())


def test_numbered_export_cannot_target_a_canonical_artifact(command, monkeypatch, tmp_path):
    monkeypatch.setattr(research, "run_research", lambda *a, **k: pytest.fail("invalid output dispatched"))
    target = tmp_path / "store" / "old-run" / "reports" / "complete_report.md"
    result = CliRunner().invoke(app, [*command, "--ticker", "002130", "--citation-style", "numbered",
                                     "--output", str(target)])
    assert result.exit_code == 2 and lines(result)[-1]["status"] == "invalid_input"
    assert not target.exists()


def test_preclosed_stdout_exits_cleanly_before_starting_research(command, tmp_path):
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-c", "from cli.main import app; app()", *command, "--ticker", "002130"],
            stdout=write_fd, stderr=subprocess.PIPE, text=True, check=False, timeout=10,
        )
    finally:
        os.close(write_fd)
    assert result.returncode == 1 and "JSONL 输出无法写入" in result.stderr
    assert "BrokenPipeError" not in result.stderr
    assert not (tmp_path / "store").exists()
