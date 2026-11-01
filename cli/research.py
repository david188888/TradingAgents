"""Synchronous terminal lifecycle over the same runner used by the workbench."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tradingagents.execution.config_identity import (
    normalize_endpoint_identity,
    prepare_effective_config,
    restore_endpoint_identity,
)
from tradingagents.execution.models import AnalysisRequest, CancellationToken
from tradingagents.execution.native_runner import WORKFLOW_VERSION, NativeResumeGuard, NativeRunner
from tradingagents.observability.events import RunEventDraft
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.runtime.ownership import own_run_store
from tradingagents.runtime.reports import ReportArtifactWriter
from tradingagents.runtime.run_models import RunSnapshot, utc_timestamp
from tradingagents.runtime.store import RunStore

DEFAULT_RUN_ROOT = Path.home() / ".tradingagents" / "cli" / "runs"


@dataclass(frozen=True)
class TerminalResult:
    run_id: str
    report: Path
    record: dict


def _saved_request(snapshot, resume_backend_url=None) -> AnalysisRequest:
    if snapshot.metadata.get("native_workflow_version") != WORKFLOW_VERSION:
        raise ValueError("仅支持恢复 V9 研究；旧版本记录不再支持。")
    config = dict(snapshot.metadata["effective_config"])
    if isinstance(config.get("backend_url"), dict):
        config["backend_url"] = restore_endpoint_identity(config["backend_url"])
    if resume_backend_url is not None:
        if normalize_endpoint_identity(resume_backend_url) != normalize_endpoint_identity(config.get("backend_url")):
            raise ValueError("恢复使用的服务端点必须与已保存研究一致。")
        config["backend_url"] = resume_backend_url
    return AnalysisRequest(snapshot.ticker, snapshot.analysis_date, effective_config=config,
                           research_question=snapshot.metadata.get("research_question"))


def run_research(
    request: AnalysisRequest | None,
    root: Path = DEFAULT_RUN_ROOT,
    *,
    resume_run_id: str | None = None,
    on_event=None,
    runner_factory=NativeRunner,
    chatgpt_auth=None,
    resume_backend_url=None,
) -> TerminalResult:
    """Persist each stage and authorize publication before announcing completion."""
    with own_run_store(root):
        store = RunStore(root)
        if resume_run_id:
            snapshot = store.read_snapshot(resume_run_id)
            request = _saved_request(snapshot, resume_backend_url)
        else:
            if request is None:
                raise ValueError("新研究需要股票代码及模型配置。")
            config = request.effective_config
            snapshot = RunSnapshot.create(
                ticker=request.ticker, analysis_date=request.analysis_date,
                output_language=config.get("output_language", "Chinese"),
                llm_provider=config["llm_provider"], quick_think_llm=config["quick_think_llm"],
                deep_think_llm=config["deep_think_llm"],
                metadata={"research_profile": "evidence_v1", "native_workflow_version": WORKFLOW_VERSION,
                          "effective_config": prepare_effective_config(config),
                          "research_question": request.research_question, "entrypoint": "cli"},
            )
            store.create_run(snapshot)
        run_id = snapshot.run_id

        def emit(draft):
            event = store.append_event(draft)
            if on_event:
                on_event(event)
            return event

        if snapshot.status == "completed":
            from tradingagents.runtime.insight_artifacts import read_insight_publication

            record = read_insight_publication(store, run_id).model_dump(mode="json")
            publication = ReportArtifactWriter(store).publish_final(
                run_id, {"native_research_record": record}, request.ticker)
            return TerminalResult(run_id, publication.complete_report, record)
        token = CancellationToken()
        emit(RunEventDraft(run_id, "run.resumed" if resume_run_id else "run.started",
                          {"run_status": "running", "checkpoint_sequence": snapshot.latest_sequence}, status="running"))
        observer = DurableRunObserver(store, run_id, event_sink=emit, development_assertions=False)

        def authorize(journal):
            with store.lock_for(run_id):
                token.raise_if_cancelled()
                if store.read_snapshot(run_id).status != "running":
                    raise ValueError("研究状态不允许发布报告。")
                journal.put("publication_authorized", True)

        try:
            kwargs = {"chatgpt_auth": chatgpt_auth} if chatgpt_auth is not None else {}
            runner = runner_factory(observer, **kwargs)
            result = runner.run(request, cancellation_token=token,
                                checkpoint_guard=NativeResumeGuard() if resume_run_id else None,
                                publication_authorizer=authorize)
            with store.lock_for(run_id):
                publication = ReportArtifactWriter(store).publish_final(run_id, result.final_state, request.ticker)
                record = result.final_state["native_research_record"]
                complete = next(a for a in publication.artifacts if a.locator.endswith("/complete_report.md"))
                timestamp = utc_timestamp()
                emit(RunEventDraft(run_id, "run.completed", {
                    "run_status": "completed", "summary": "V9 公司研究已保存。", "final_signal": "research_only",
                    "final_report_artifact_id": complete.artifact_id, "completed_at": timestamp,
                    "degraded_data_sources": [],
                }, status="completed", timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00"))))
            return TerminalResult(run_id, publication.complete_report, record)
        except KeyboardInterrupt:
            token.cancel()
            emit(RunEventDraft(run_id, "run.interrupted", {"run_status": "interrupted",
                              "checkpoint_sequence": store.read_snapshot(run_id).latest_sequence}, status="interrupted"))
            raise
        except Exception as exc:
            emit(RunEventDraft(run_id, "run.failed", {"run_status": "failed",
                              "summary": f"研究执行失败：{type(exc).__name__}"}, status="failed"))
            raise
