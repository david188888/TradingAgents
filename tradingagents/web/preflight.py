"""Dependency and durable-journal checks for the local Insight workbench."""
from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass
from importlib import metadata

INSTALL_COMMAND = "python -m pip install --upgrade 'tradingagents[web]'"
WEB_DEPENDENCY_REQUIREMENTS = {
    "fastapi": ">=0.115,<1",
    "uvicorn": ">=0.30,<1",
    "rfc8785": ">=0.1.4,<1",
}


@dataclass(frozen=True)
class WebCapabilityReport:
    versions: dict[str, str | None]
    requirements: dict[str, str]
    durable_journal: bool
    issues: tuple[str, ...] = ()
    install_command: str = INSTALL_COMMAND

    @property
    def ok(self) -> bool:
        return not self.issues and self.durable_journal

    def as_dict(self) -> dict[str, object]:
        return {**asdict(self), "ok": self.ok}


class WebRuntimeError(RuntimeError):
    def __init__(self, report: WebCapabilityReport):
        self.report = report
        super().__init__(f"TradingAgents web runtime preflight failed: {'; '.join(report.issues)}. "
            f"Install or upgrade with: {report.install_command}")


def _installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _version_satisfies(version: str, requirement: str) -> bool:
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    return Version(version) in SpecifierSet(requirement)


def _run_journal_probe() -> bool:
    from tradingagents.execution.budget import BudgetBucket
    from tradingagents.execution.models import AnalysisRequest
    from tradingagents.execution.native_runner import native_identity
    from tradingagents.observability.observer import DurableRunObserver
    from tradingagents.runtime.research_checkpoint import ResearchJournal, load_checkpoint
    from tradingagents.runtime.run_models import RunSnapshot
    from tradingagents.runtime.store import RunStore

    with tempfile.TemporaryDirectory(prefix="tradingagents-web-preflight-") as root:
        store = RunStore(root)
        snapshot = RunSnapshot.create(ticker="002130.SZ", analysis_date="2026-10-28")
        store.create_run(snapshot)
        observer = DurableRunObserver(store, snapshot.run_id, development_assertions=False)
        request = AnalysisRequest(snapshot.ticker, snapshot.analysis_date)
        journal = ResearchJournal(observer, native_identity(request))
        grant = journal.ledger.reserve(BudgetBucket.MAIN_ANALYSIS, stage="probe", logical_call_id="probe")
        journal.ledger.mark_dispatched(grant)
        saved = load_checkpoint(store, snapshot.run_id)
        return saved["identity"] == native_identity(request) and saved["records"][0]["phase"] == "dispatched"


def check_web_runtime(*, include_web_dependencies=True, run_probe=True) -> WebCapabilityReport:
    requirements = dict(WEB_DEPENDENCY_REQUIREMENTS) if include_web_dependencies else {}
    versions = {name: _installed_version(name) for name in requirements}
    issues = []
    for name, requirement in requirements.items():
        installed = versions[name]
        if installed is None:
            issues.append(f"missing distribution {name} ({requirement})")
        elif not _version_satisfies(installed, requirement):
            issues.append(f"unsupported {name} {installed} (requires {requirement})")
    durable = False
    if run_probe:
        try:
            durable = _run_journal_probe()
            if not durable:
                issues.append("durable research journal probe failed")
        except Exception as exc:
            issues.append(f"durable research journal probe failed: {type(exc).__name__}")
    return WebCapabilityReport(versions, requirements, durable, tuple(issues))


def ensure_web_runtime() -> WebCapabilityReport:
    report = check_web_runtime()
    if not report.ok:
        raise WebRuntimeError(report)
    return report
