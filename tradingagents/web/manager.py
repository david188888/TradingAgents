"""Single-writer lifecycle owner for localhost analysis workers."""

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from tradingagents.dataflows.config import config_scope
from tradingagents.dataflows.interface import news_cache_scope
from tradingagents.dataflows.progress import DataProgressEvent, progress_sink
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.config_identity import prepare_effective_config
from tradingagents.execution.models import (
    AnalysisCancelled,
    AnalysisRequest,
    AnalysisResult,
    CancellationToken,
)
from tradingagents.observability.events import PersistedEvent, RunEventDraft
from tradingagents.observability.observer import DurableRunObserver
from tradingagents.observability.provenance import provenance_scope
from tradingagents.observability.roles import role_instance_id, roles_for_profile
from tradingagents.runtime.batch_models import BatchItem, BatchSnapshot
from tradingagents.runtime.reports import ReportArtifactWriter, ReportPublicationError
from tradingagents.runtime.run_models import RunSnapshot, utc_timestamp
from tradingagents.runtime.store import RunStore

from .broker import EventBroker
from .degradations import summarize_data_degradations
from .scheduler import RunScheduler

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
RETRYABLE_RUN_STATUSES = TERMINAL_RUN_STATUSES | {"interrupted"}
ORPHANED_RUN_STATUSES = frozenset({"running", "cancel_requested"})
QUEUEABLE_RUN_STATUSES = frozenset({"created", "queued"})


class ManagedRunner(Protocol):
    def run(
        self,
        request: AnalysisRequest,
        *,
        cancellation_token: CancellationToken,
        publication_authorizer: Any,
        checkpoint_guard: Any,
    ) -> AnalysisResult: ...


RunnerFactory = Callable[[AnalysisRequest, DurableRunObserver], ManagedRunner]
CheckpointGuardFactory = Callable[
    [RunStore, str, AnalysisRequest, Mapping[str, Any]],
    Any,
]
RequestResolver = Callable[[RunSnapshot], AnalysisRequest]
ResumePreflight = Callable[[RunSnapshot, AnalysisRequest], Any]
StartupReconciler = Callable[[RunSnapshot, DurableRunObserver], None]


class RunManagerError(RuntimeError):
    pass


class RunNotActive(RunManagerError):
    pass


class RunNotRetryable(RunManagerError):
    pass


class RunNotResumable(RunManagerError):
    pass




class SingleRunManager:
    """Own exactly one background analysis and every durable lifecycle edge."""

    def __init__(
        self,
        store: RunStore,
        broker: EventBroker | None = None,
        runner_factory: RunnerFactory | None = None,
        *,
        report_writer: ReportArtifactWriter | None = None,
        checkpoint_guard_factory: CheckpointGuardFactory | None = None,
        startup_reconciler: StartupReconciler | None = None,
        request_resolver: RequestResolver | None = None,
        resume_preflight: ResumePreflight | None = None,
        chatgpt_auth=None,
    ) -> None:
        self.store = store
        self.broker = broker or EventBroker(store)
        self._uses_default_runner_factory = runner_factory is None
        self.chatgpt_auth = chatgpt_auth
        self.runner_factory = runner_factory or self._runner_factory
        self.report_writer = report_writer or ReportArtifactWriter(store)
        self.checkpoint_guard_factory = (
            checkpoint_guard_factory or _default_checkpoint_guard_factory
        )
        self.startup_reconciler = startup_reconciler
        self.request_resolver = request_resolver
        self.resume_preflight = resume_preflight
        self._guard = threading.RLock()
        self.scheduler = RunScheduler(
            store=store,
            lock=self._guard,
            resolve_request=self._request_for_snapshot,
            thread_target=self._worker,
            on_admitted=self._on_run_admitted,
            on_launch_failure=self._finish_failure,
        )
        self._requests: dict[str, AnalysisRequest] = {}

    def _runner_factory(self, request, observer):
        return _default_runner_factory(request, observer, chatgpt_auth=self.chatgpt_auth)

    @property
    def explanations(self):
        from tradingagents.execution.report_explanation import ExplanationService
        from tradingagents.web.report_explanation import load_explanation_record
        with self._guard:
            if not hasattr(self, "_explanations"):
                self._explanations = ExplanationService(self.store,
                    lambda run_id: load_explanation_record(self.store, run_id), chatgpt_auth=self.chatgpt_auth)
            return self._explanations

    @property
    def active_run_id(self) -> str | None:
        return self.scheduler.active_run_id

    @property
    def active_run_ids(self) -> tuple[str, ...]:
        return self.scheduler.active_run_ids

    @property
    def max_concurrency(self) -> int:
        return self.scheduler.max_concurrency

    def set_concurrency(self, value: int) -> int:
        return self.scheduler.set_concurrency(value)

    @contextlib.contextmanager
    def deletion_guard(self):
        """Keep deletion policy and disk mutation atomic with worker admission."""
        with self._guard:
            protected = set(self.active_run_ids)
            protected.update(self.scheduler.pending)
            for batch in self.store.list_batches():
                if batch.status in {"queued", "running"}:
                    protected.update(item.run_id for item in batch.items)
            yield protected

    @property
    def _pending(self) -> deque[str]:
        """Compatibility handle for the frozen manager test suite, which
        drives the FIFO through this attribute; production code must go
        through ``self.scheduler`` instead."""
        return self.scheduler.pending

    def start(
        self,
        request: AnalysisRequest,
        *,
        configured_keys: Mapping[str, bool] | None = None,
        batch_id: str | None = None,
        batch_ordinal: int | None = None,
        batch_item: BatchItem | None = None,
    ) -> RunSnapshot:
        normalized = _complete_request(request)
        with self._guard:
            snapshot = self._create_run(
                normalized,
                configured_keys=configured_keys,
                batch_id=batch_id,
                batch_ordinal=batch_ordinal,
                batch_item=batch_item,
                queued=self.scheduler.queued_by_occupancy(),
            )
            self.scheduler.queue_run(snapshot.run_id)
            self.scheduler.drain()
            return self.store.read_snapshot(snapshot.run_id)

    def start_batch(
        self,
        requests: tuple[tuple[AnalysisRequest, BatchItem], ...],
        *,
        configured_keys: Mapping[str, bool] | None = None,
        concurrency: int = 3,
    ) -> BatchSnapshot:
        if not 1 <= len(requests) <= 8:
            raise ValueError("batch must contain between 1 and 8 requests")
        self.set_concurrency(concurrency)
        with self._guard:
            batch_items: list[BatchItem] = []
            for ordinal, (_request, item) in enumerate(requests):
                batch_items.append(
                    item if item.ordinal == ordinal else replace(item, ordinal=ordinal)
                )
            batch = BatchSnapshot.create(items=tuple(batch_items), concurrency=concurrency)
            self.store.create_batch(batch)
            for (request, _original_item), item in zip(requests, batch.items, strict=True):
                snapshot = self._create_run(
                    _complete_request(request),
                    configured_keys=configured_keys,
                    batch_id=batch.batch_id,
                    batch_ordinal=item.ordinal,
                    batch_item=item,
                    run_id=item.run_id,
                    queued=self.scheduler.queued_by_capacity(),
                )
                self.scheduler.queue_run(snapshot.run_id)
            self.scheduler.drain()
            return self.store.read_batch(batch.batch_id)

    def cancel(self, run_id: str) -> RunSnapshot:
        with self._guard:
            active = self.scheduler.active_entry(run_id)
            if active is not None:
                if active.phase != "running":
                    raise RunNotActive(f"run is already terminalizing: {run_id}")
                snapshot = self.store.read_snapshot(run_id)
                if snapshot.status == "cancel_requested":
                    return snapshot
                self.broker.publish(
                    RunEventDraft(
                        run_id,
                        "run.cancel_requested",
                        {
                            "run_status": "cancel_requested",
                            "summary": "Cancellation requested by the local user.",
                        },
                        status="cancel_requested",
                    )
                )
                active.token.cancel()
                return self.store.read_snapshot(run_id)

            snapshot = self.store.read_snapshot(run_id)
            if snapshot.status not in {"created", "queued"}:
                raise RunNotActive(f"run cannot be cancelled from {snapshot.status}")
            self.scheduler.discard_queued(run_id)
            summary = "Analysis cancelled before execution started."
            self.broker.publish(
                RunEventDraft(
                    run_id,
                    "run.cancelled",
                    {"run_status": "cancelled", "summary": summary},
                    status="cancelled",
                )
            )
            self.scheduler.sync_batch_for_run(run_id)
            self.scheduler.drain()
            return self.store.read_snapshot(run_id)

    def cancel_batch(self, batch_id: str) -> BatchSnapshot:
        with self._guard:
            batch = self.store.read_batch(batch_id)
            for item in batch.items:
                snapshot = self.store.read_snapshot(item.run_id)
                if snapshot.status in {"created", "queued", "running"}:
                    self.cancel(item.run_id)
            return self.store.read_batch(batch_id)

    def batch(self, batch_id: str) -> BatchSnapshot:
        return self.store.read_batch(batch_id)

    def list_batches(self) -> tuple[BatchSnapshot, ...]:
        return tuple(self.store.list_batches())

    def retry(self, run_id: str) -> RunSnapshot:
        source = self.store.read_snapshot(run_id)
        if source.status not in RETRYABLE_RUN_STATUSES:
            raise RunNotRetryable(
                f"run cannot be retried from status {source.status}: {run_id}"
            )
        request = self._request_for_snapshot(source)
        with self._guard:
            snapshot = self._create_run(
                request,
                configured_keys=source.configured_keys,
                retry_of=source.run_id,
            )
            self.scheduler.queue_run(snapshot.run_id)
            self.scheduler.drain()
            return self.store.read_snapshot(snapshot.run_id)

    def resume(self, run_id: str) -> RunSnapshot:
        snapshot = self.store.read_snapshot(run_id)
        if snapshot.status != "interrupted":
            raise RunNotResumable(
                f"run cannot be resumed from status {snapshot.status}: {run_id}"
            )
        request = self._request_for_snapshot(snapshot)
        with self._guard:
            checkpoint_guard = self._validate_resume(snapshot, request)
            resumed_from = snapshot.latest_sequence
            checkpoint_sequence = _checkpoint_sequence(
                self.store.read_events(run_id)
            )
            self.store.write_snapshot_atomic(
                snapshot.evolve(resumed_from_sequence=resumed_from)
            )
            self.broker.publish(
                RunEventDraft(
                    run_id,
                    "run.resumed",
                    {
                        "run_status": "running",
                        "checkpoint_sequence": checkpoint_sequence,
                        "resumed_from_sequence": resumed_from,
                    },
                    status="running",
                )
            )
            self.scheduler.queue_run(
                run_id,
                resume=True,
                checkpoint_guard=checkpoint_guard,
                resumed_from=resumed_from,
            )
            self.scheduler.drain()
            return self.store.read_snapshot(run_id)

    def recover_startup(self) -> tuple[RunSnapshot, ...]:
        recovered: list[RunSnapshot] = []
        with self._guard:
            for summary in self.store.list_runs():
                if summary.status not in ORPHANED_RUN_STATUSES:
                    continue
                snapshot = self.store.read_snapshot(summary.run_id)
                request = self._request_for_snapshot(snapshot)
                observer = DurableRunObserver(
                    self.store,
                    snapshot.run_id,
                    event_sink=self.broker.publish,
                    development_assertions=False,
                )
                reconciliation_error: BaseException | None = None
                try:
                    self._reconcile_startup(snapshot, request, observer)
                except Exception as exc:
                    reconciliation_error = exc
                reason = (
                    "startup_reconciliation_failed"
                    if reconciliation_error is not None
                    else "server_restarted"
                )
                self._terminalize_open_lifecycles(
                    snapshot.run_id,
                    mode="interrupted",
                    reason=reason,
                )
                events = self.store.read_events(snapshot.run_id)
                current = self.store.read_snapshot(snapshot.run_id)
                self.store.write_snapshot_atomic(
                    current.evolve(
                        summary="The local server stopped before this analysis finished.",
                        error_category=(
                            _error_category(reconciliation_error)
                            if reconciliation_error is not None
                            else None
                        ),
                    )
                )
                self.broker.publish(
                    RunEventDraft(
                        snapshot.run_id,
                        "run.interrupted",
                        {
                            "run_status": "interrupted",
                            "checkpoint_sequence": _checkpoint_sequence(events),
                            "summary": "The local server stopped before this analysis finished.",
                            **(
                                {
                                    "error_category": _error_category(
                                        reconciliation_error
                                    )
                                }
                                if reconciliation_error is not None
                                else {}
                            ),
                        },
                        status="interrupted",
                    )
                )
                recovered.append(self.store.read_snapshot(snapshot.run_id))
            for summary in self.store.list_runs():
                if summary.status in {"created", "queued"}:
                    self._requests.setdefault(
                        summary.run_id,
                        self._request_for_snapshot(self.store.read_snapshot(summary.run_id)),
                    )
                    if not self.scheduler.is_queued(summary.run_id):
                        self.scheduler.queue_run(summary.run_id)
            for batch in self.store.list_batches():
                for item in batch.items:
                    self.scheduler.sync_batch_for_run(item.run_id)
            self.scheduler.drain()
        return tuple(recovered)

    def wait(self, run_id: str, timeout: float | None = None) -> RunSnapshot:
        active = self.scheduler.active_entry(run_id)
        if active is not None:
            active.thread.join(timeout)
        return self.store.read_snapshot(run_id)

    def _create_run(self, request, *, configured_keys, retry_of=None, batch_id=None,
            batch_ordinal=None, batch_item=None, run_id=None, queued=True):
        from tradingagents.execution.native_runner import WORKFLOW_VERSION
        config = dict(request.effective_config)
        snapshot = RunSnapshot.create(ticker=request.ticker, analysis_date=request.analysis_date,
            output_language=str(config.get("output_language") or "English"),
            llm_provider=str(config.get("llm_provider") or ""),
            quick_think_llm=str(config.get("quick_think_llm") or ""),
            deep_think_llm=str(config.get("deep_think_llm") or ""),
            configured_keys=dict(configured_keys or {}), run_id=run_id, retry_of=retry_of,
            metadata={"effective_config": prepare_effective_config(config), **request.profile_identity(),
                "native_workflow_version": WORKFLOW_VERSION,
                "report_explanation_policy": "plain-language-report-v1",
                **({"batch_id": batch_id, "batch_ordinal": batch_ordinal,
                    "batch_input": batch_item.input_value, "company_name": batch_item.company_name,
                    "market": batch_item.market} if batch_id is not None and batch_item is not None else {})})
        self.store.create_run(snapshot)
        if queued:
            self.broker.publish(RunEventDraft(snapshot.run_id, "run.queued", {
                "run_status": "queued", "summary": "Research is queued for execution.",
                "ticker": snapshot.ticker, "batch_id": batch_id}, status="queued"))
        else:
            self._publish_run_started(snapshot.run_id, request)
        self._initialize_roles(snapshot.run_id)
        self._requests[snapshot.run_id] = request
        return self.store.read_snapshot(snapshot.run_id)

    def _initialize_roles(self, run_id):
        for role in self._roles_for_run(run_id):
            self.broker.publish(RunEventDraft(run_id, "role.status_changed", {
                "role_instance_id": role_instance_id(run_id, role.actor_id),
                "previous_status": "uninitialized", "new_status": "pending", "reason": "research_started"},
                team_id=role.team_id, actor_id=role.actor_id, node_id=role.node_id, status="pending"))

    def _on_run_admitted(self, run_id: str, request: AnalysisRequest) -> None:
        """Scheduler hook: publish the started edge and sync the manifest."""
        snapshot = self.store.read_snapshot(run_id)
        if snapshot.status in {"created", "queued"}:
            self._publish_run_started(run_id, request)
        self.scheduler.sync_batch_for_run(run_id)

    def _publish_run_started(self, run_id, request):
        snapshot = self.store.read_snapshot(run_id)
        self.broker.publish(RunEventDraft(run_id, "run.started", {
            "run_status": "running", "ticker": snapshot.ticker, "analysis_date": snapshot.analysis_date,
            "output_language": snapshot.output_language, "llm_provider": snapshot.llm_provider,
            "quick_think_llm": snapshot.quick_think_llm, "deep_think_llm": snapshot.deep_think_llm,
            "research_profile": "evidence_v1", "native_workflow_version": snapshot.metadata["native_workflow_version"],
            "focus_requested": bool(request.research_question)}, status="running"))

    def _worker(
        self,
        run_id: str,
        request: AnalysisRequest,
        token: CancellationToken,
        resume: bool,
        checkpoint_guard_override: Any | None,
        resumed_from_sequence: int | None,
    ) -> None:
        observer = DurableRunObserver(
            self.store,
            run_id,
            event_sink=self.broker.publish,
            development_assertions=False,
        )
        try:
            with config_scope(request.effective_config), progress_sink(
                self._progress_sink(observer)
            ), news_cache_scope(run_id), provenance_scope(observer):
                config_artifact = observer.store_artifact(
                    "data",
                    prepare_effective_config(request.effective_config),
                )
                self._record_config_artifact(run_id, config_artifact.artifact_id)
                if resume:
                    if resumed_from_sequence is None:
                        raise RunNotResumable("resume sequence is missing")
                    self._resume_open_turns(observer, resumed_from_sequence)
                runner = self.runner_factory(request, observer)
                checkpoint_guard = checkpoint_guard_override
                if checkpoint_guard is None:
                    checkpoint_guard = self.checkpoint_guard_factory(
                        self.store,
                        run_id,
                        request,
                        request.effective_config,
                    )
                result = runner.run(request, cancellation_token=token,
                    checkpoint_guard=checkpoint_guard,
                    publication_authorizer=lambda journal: self._authorize_publication(run_id, token, journal))
                status = self._begin_terminalization(run_id)
                if status == "cancel_requested":
                    self._finish_cancelled(run_id)
                else:
                    self._finish_success(run_id, request, result)
        except AnalysisCancelled:
            self._begin_terminalization(run_id)
            self._finish_cancelled(run_id)
        except BaseException as exc:
            self._begin_terminalization(run_id)
            if self.store.read_snapshot(run_id).status not in TERMINAL_RUN_STATUSES:
                self._finish_failure(run_id, exc)
        finally:
            self.scheduler.release(run_id)

    def _begin_terminalization(self, run_id: str) -> str:
        self.scheduler.mark_terminalizing(run_id)
        return self.store.read_snapshot(run_id).status

    def _authorize_publication(self, run_id, token, journal) -> None:
        with self._guard:
            token.raise_if_cancelled()
            if self.store.read_snapshot(run_id).status == "cancel_requested":
                raise AnalysisCancelled()
            # Durable authorization is the linearization point shared with cancel().
            journal.put("publication_authorized", True)
            self.scheduler.mark_terminalizing(run_id)

    def _roles_for_run(self, run_id):
        metadata = self.store.read_snapshot(run_id).metadata
        return roles_for_profile(metadata.get("research_profile", "evidence_v1"),
                                 workflow_version=metadata.get("native_workflow_version"),
                                 focus_requested=bool(metadata.get("research_question")))

    def _finish_success(
        self,
        run_id: str,
        request: AnalysisRequest,
        result: AnalysisResult,
    ) -> None:
        # Learning/holding-review runs leave skipped roles pending. Only those
        # roles are expected on success; a running role still indicates an
        # incomplete lifecycle and must fail the invariant below.
        self._terminalize_pending_roles(run_id, reason="analysis_completed")
        invalid_roles = {
            actor_id: status
            for actor_id, (status, _event) in _reduce_open_lifecycles(
                self.store.read_events(run_id)
            ).roles.items()
            if status in {"pending", "running", "interrupted"}
        }
        if invalid_roles:
            raise RunManagerError(
                "successful analysis left non-terminal aggregate roles"
            )
        publication = self.report_writer.publish_final(
            run_id,
            dict(result.final_state),
            request.ticker,
        )
        complete_artifacts = [
            artifact
            for artifact in publication.artifacts
            if artifact.locator == "reports/complete_report.md"
        ]
        if len(complete_artifacts) != 1:
            raise ReportPublicationError(
                "canonical publication must contain exactly one complete report artifact"
            )
        degraded_data_sources = summarize_data_degradations(
            self.store.read_events(run_id)
        )
        completed_at = utc_timestamp()
        terminal_timestamp = datetime.fromisoformat(
            completed_at.replace("Z", "+00:00")
        )
        artifact_ids: list[str] = []
        for artifact in publication.artifacts:
            artifact_ids.append(artifact.artifact_id)
            self.broker.publish(
                RunEventDraft(
                    run_id,
                    "artifact.written",
                    {
                        "artifact_id": artifact.artifact_id,
                        "kind": artifact.kind,
                        "media_type": artifact.media_type,
                        "content_sha256": artifact.content_sha256,
                        "byte_size": artifact.byte_size,
                        "locator": artifact.locator,
                    },
                )
            )
        current = self.store.read_snapshot(run_id)
        record = result.final_state["native_research_record"]
        completion_summary = "研究流程已完成；部分结果与资料限制已保留。" if record["gaps"] else "研究流程已完成。"
        self.store.write_snapshot_atomic(
            current.evolve(
                final_signal=result.final_signal,
                summary=completion_summary,
                error_category=None,
                artifacts=tuple(dict.fromkeys((*current.artifacts, *artifact_ids))),
            )
        )
        self.broker.publish(
            RunEventDraft(
                run_id,
                "run.completed",
                {
                    "run_status": "completed",
                    "summary": completion_summary,
                    "final_signal": result.final_signal,
                    "report_artifact_ids": artifact_ids,
                    "final_report_artifact_id": complete_artifacts[0].artifact_id,
                    "completed_at": completed_at,
                    "degraded_data_sources": degraded_data_sources,
                },
                status="completed",
                timestamp=terminal_timestamp,
            )
        )
        with contextlib.suppress(Exception):
            self.explanations.start(run_id)

    def _finish_cancelled(self, run_id: str) -> None:
        snapshot = self.store.read_snapshot(run_id)
        if snapshot.status == "running":
            self.broker.publish(
                RunEventDraft(
                    run_id,
                    "run.cancel_requested",
                    {
                        "run_status": "cancel_requested",
                        "summary": "Cancellation reached a safe execution boundary.",
                    },
                    status="cancel_requested",
                )
            )
        self._terminalize_open_lifecycles(
            run_id,
            mode="cancelled",
            reason="user_cancelled",
        )
        summary = "Analysis cancelled by the local user."
        current = self.store.read_snapshot(run_id)
        self.store.write_snapshot_atomic(current.evolve(summary=summary))
        self.broker.publish(
            RunEventDraft(
                run_id,
                "run.cancelled",
                {"run_status": "cancelled", "summary": summary},
                status="cancelled",
            )
        )

    def _finish_failure(self, run_id: str, error: BaseException) -> None:
        self._terminalize_open_lifecycles(
            run_id,
            mode="failed",
            reason="analysis_failed",
        )
        category = _error_category(error)
        error_message = f"{type(error).__name__}: {error}"
        error_traceback = _format_traceback(error)
        summary = f"Analysis failed in the {category.replace('_', ' ')} stage."
        current = self.store.read_snapshot(run_id)
        self.store.write_snapshot_atomic(
            current.evolve(
                summary=summary,
                error_category=category,
                error_message=error_message,
                error_traceback=error_traceback,
            )
        )
        self.broker.publish(
            RunEventDraft(
                run_id,
                "run.failed",
                {
                    "run_status": "failed",
                    "summary": summary,
                    "error_category": category,
                    "error_message": error_message,
                },
                status="failed",
            )
        )

    def _terminalize_open_lifecycles(
        self,
        run_id: str,
        *,
        mode: str,
        reason: str,
    ) -> None:
        reduced = _reduce_open_lifecycles(self.store.read_events(run_id))
        model_terminal = "model.failed" if mode == "failed" else "model.interrupted"
        for event in reduced.models.values():
            payload = {
                **event.payload,
                "duration_ms": 0,
                "usage": {},
                "reason": reason,
            }
            self.broker.publish(_terminal_draft(event, model_terminal, payload, mode))

        data_terminal = "data.failed" if mode == "failed" else "data.interrupted"
        for event in reduced.data_calls.values():
            payload = {
                **event.payload,
                "stage": "failed" if mode == "failed" else "interrupted",
                "data_status": "failed" if mode == "failed" else "interrupted",
                "duration_ms": 0,
                "reason": reason,
            }
            self.broker.publish(_terminal_draft(event, data_terminal, payload, mode))

        execution_terminal = (
            "tool.execution_failed"
            if mode == "failed"
            else "tool.execution_interrupted"
        )
        for event in reduced.tool_executions.values():
            payload = {**event.payload, "duration_ms": 0, "reason": reason}
            self.broker.publish(
                _terminal_draft(event, execution_terminal, payload, mode)
            )

        if mode != "interrupted":
            for event in reduced.logical_tools.values():
                self.broker.publish(
                    _terminal_draft(
                        event,
                        "tool.cancelled",
                        {**event.payload, "reason": reason},
                        "cancelled",
                    )
                )

        turn_status = mode
        for event in reduced.turns.values():
            self.broker.publish(
                _terminal_draft(
                    event,
                    f"turn.{turn_status}",
                    {
                        **event.payload,
                        "turn_status": turn_status,
                        "duration_ms": 0,
                        "reason": reason,
                    },
                    turn_status,
                )
            )

        for actor_id, (status, event) in reduced.roles.items():
            if status != "running":
                continue
            role = next(role for role in self._roles_for_run(run_id) if role.actor_id == actor_id)
            self.broker.publish(
                RunEventDraft(
                    run_id,
                    "role.status_changed",
                    {
                        "role_instance_id": role_instance_id(run_id, actor_id),
                        "previous_status": "running",
                        "new_status": mode,
                        "reason": reason,
                        **(
                            {"turn_id": event.payload.get("turn_id")}
                            if event.payload.get("turn_id")
                            else {}
                        ),
                    },
                    team_id=role.team_id,
                    actor_id=actor_id,
                    node_id=role.node_id,
                    status=mode,
                    parent_event_id=event.event_id,
                )
            )
        if mode != "interrupted":
            self._terminalize_pending_roles(run_id, reason=reason)

    def _terminalize_pending_roles(self, run_id: str, *, reason: str) -> None:
        reduced = _reduce_open_lifecycles(self.store.read_events(run_id))
        for actor_id, (status, event) in reduced.roles.items():
            if status != "pending":
                continue
            role = next(role for role in self._roles_for_run(run_id) if role.actor_id == actor_id)
            self.broker.publish(
                RunEventDraft(
                    run_id,
                    "role.status_changed",
                    {
                        "role_instance_id": role_instance_id(run_id, actor_id),
                        "previous_status": "pending",
                        "new_status": "not_reached",
                        "reason": reason,
                    },
                    team_id=role.team_id,
                    actor_id=actor_id,
                    node_id=role.node_id,
                    status="not_reached",
                    parent_event_id=event.event_id,
                )
            )

    def _record_config_artifact(self, run_id: str, artifact_id: str) -> None:
        with self.store.lock_for(run_id):
            current = self.store.read_snapshot(run_id)
            metadata = dict(current.metadata)
            metadata["effective_config_artifact_id"] = artifact_id
            self.store.write_snapshot_atomic(
                current.evolve(
                    metadata=metadata,
                    artifacts=tuple(
                        dict.fromkeys((*current.artifacts, artifact_id))
                    ),
                )
            )

    def _progress_sink(
        self,
        observer: DurableRunObserver,
    ) -> Callable[[DataProgressEvent], None]:
        def emit(event: DataProgressEvent) -> None:
            if (
                event.run_id == observer.run_id
                and event.turn_id
                and event.graph_task_id
                and event.vendor_call_id
            ):
                observer.emit(
                    RunEventDraft(
                        observer.run_id,
                        "data.progress",
                        {
                            "turn_id": event.turn_id,
                            "graph_task_id": event.graph_task_id,
                            "tool_call_id": event.tool_call_id,
                            "vendor_call_id": event.vendor_call_id,
                            "method": event.method,
                            "vendor": event.vendor,
                            "stage": event.stage,
                            "data_status": "progress",
                            "message": event.message,
                            "artifact_id": event.artifact_id,
                        },
                        status="progress",
                    )
                )

        return emit

    def _resume_open_turns(
        self,
        observer: DurableRunObserver,
        resumed_from_sequence: int,
    ) -> None:
        reduced = _reduce_open_lifecycles(
            self.store.read_events(observer.run_id)
        )
        for turn_id in reduced.interrupted_turns:
            observer.resume_turn(turn_id, resumed_from_sequence)

    def _request_for_snapshot(self, snapshot: RunSnapshot) -> AnalysisRequest:
        request = self._requests.get(snapshot.run_id)
        if request is not None:
            return request
        if self.request_resolver is not None:
            return _complete_request(self.request_resolver(snapshot))
        resolved = _request_from_snapshot(snapshot)
        return _complete_request(resolved) if self._uses_default_runner_factory else resolved

    def _validate_resume(self, snapshot, request):
        guard = _default_resume_preflight(self.store, snapshot, request, self.runner_factory, self.checkpoint_guard_factory)
        return self.resume_preflight(snapshot, request) if self.resume_preflight is not None else guard

    def _reconcile_startup(
        self,
        snapshot: RunSnapshot,
        request: AnalysisRequest,
        observer: DurableRunObserver,
    ) -> None:
        if self.startup_reconciler is not None:
            self.startup_reconciler(snapshot, observer)
            return
        _default_startup_reconciler(snapshot, request, observer)


@dataclass(frozen=True)
class _OpenLifecycles:
    models: dict[str, PersistedEvent]
    tool_executions: dict[str, PersistedEvent]
    data_calls: dict[str, PersistedEvent]
    logical_tools: dict[str, PersistedEvent]
    turns: dict[str, PersistedEvent]
    interrupted_turns: dict[str, PersistedEvent]
    roles: dict[str, tuple[str, PersistedEvent]]


def _reduce_open_lifecycles(events: list[PersistedEvent]) -> _OpenLifecycles:
    models: dict[str, PersistedEvent] = {}
    executions: dict[str, PersistedEvent] = {}
    data_calls: dict[str, PersistedEvent] = {}
    logical_tools: dict[str, PersistedEvent] = {}
    turns: dict[str, PersistedEvent] = {}
    interrupted_turns: dict[str, PersistedEvent] = {}
    roles: dict[str, tuple[str, PersistedEvent]] = {}
    for event in events:
        payload = event.payload
        if event.type == "model.started":
            models[str(payload["model_call_id"])] = event
        elif event.type in {"model.completed", "model.failed", "model.interrupted"}:
            models.pop(str(payload["model_call_id"]), None)
        elif event.type == "tool.execution_started":
            executions[str(payload["tool_execution_id"])] = event
        elif event.type in {
            "tool.execution_completed",
            "tool.execution_failed",
            "tool.execution_interrupted",
        }:
            executions.pop(str(payload["tool_execution_id"]), None)
        elif event.type == "data.progress":
            data_calls[str(payload["vendor_call_id"])] = event
        elif event.type in {"data.completed", "data.failed", "data.interrupted"}:
            data_calls.pop(str(payload["vendor_call_id"]), None)
        elif event.type == "tool.requested":
            logical_tools[str(payload["tool_call_id"])] = event
        elif event.type in {"tool.committed", "tool.cancelled"}:
            logical_tools.pop(str(payload["tool_call_id"]), None)
        elif event.type in {"turn.started", "turn.resumed", "turn.output_ready"}:
            turn_id = str(payload["turn_id"])
            turns[turn_id] = event
            interrupted_turns.pop(turn_id, None)
        elif event.type == "turn.interrupted":
            turn_id = str(payload["turn_id"])
            turns.pop(turn_id, None)
            interrupted_turns[turn_id] = event
        elif event.type in {"turn.completed", "turn.failed", "turn.cancelled"}:
            turn_id = str(payload["turn_id"])
            turns.pop(turn_id, None)
            interrupted_turns.pop(turn_id, None)
        if event.type == "role.status_changed" and event.actor_id:
            roles[event.actor_id] = (str(payload["new_status"]), event)
    return _OpenLifecycles(
        models,
        executions,
        data_calls,
        logical_tools,
        turns,
        interrupted_turns,
        roles,
    )


def _terminal_draft(
    source: PersistedEvent,
    event_type: str,
    payload: dict[str, Any],
    status: str,
) -> RunEventDraft:
    return RunEventDraft(
        source.run_id,
        event_type,
        payload,
        team_id=source.team_id,
        actor_id=source.actor_id,
        node_id=source.node_id,
        status=status,
        parent_event_id=source.event_id,
    )


def _complete_request(request):
    config = deepcopy(DEFAULT_CONFIG)
    for key, value in request.effective_config.items():
        if isinstance(value, Mapping) and isinstance(config.get(key), dict):
            config[key].update(deepcopy(dict(value)))
        else:
            config[key] = deepcopy(value)
    return replace(request, effective_config=config)


def _request_from_snapshot(snapshot):
    from tradingagents.execution.config_identity import restore_endpoint_identity
    from tradingagents.execution.native_runner import WORKFLOW_VERSION
    if snapshot.metadata.get("research_profile") != "evidence_v1" or snapshot.metadata.get("native_workflow_version") != WORKFLOW_VERSION:
        raise RunNotResumable("unsupported research version")
    config = deepcopy(snapshot.metadata.get("effective_config", {}))
    if isinstance(config.get("backend_url"), Mapping):
        config["backend_url"] = restore_endpoint_identity(config["backend_url"])
    config.update(llm_provider=snapshot.llm_provider, quick_think_llm=snapshot.quick_think_llm,
        deep_think_llm=snapshot.deep_think_llm, output_language=snapshot.output_language)
    return AnalysisRequest(ticker=snapshot.ticker, analysis_date=snapshot.analysis_date,
        effective_config=config, research_question=snapshot.metadata.get("research_question"))












def _default_runner_factory(request, observer, *, chatgpt_auth=None):
    from tradingagents.execution.native_runner import NativeRunner
    return NativeRunner(observer, chatgpt_auth=chatgpt_auth)


def _default_checkpoint_guard_factory(store, run_id, request, effective_config):
    return None


def _default_resume_preflight(store, snapshot, request, runner_factory, guard_factory):
    from tradingagents.execution.native_runner import NativeResumeGuard, validate_native_resume
    try:
        validate_native_resume(store, snapshot.run_id, request)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise RunNotResumable("research checkpoint missing, corrupt or incompatible") from exc
    return NativeResumeGuard()


def _default_startup_reconciler(snapshot, request, observer):
    from tradingagents.execution.native_runner import validate_native_resume
    validate_native_resume(observer.store, snapshot.run_id, request)




def _checkpoint_sequence(events: list[PersistedEvent]) -> int:
    return max(
        (
            event.sequence
            for event in events
            if event.type == "graph.checkpoint_committed"
        ),
        default=0,
    )


def _error_category(error: BaseException | None) -> str:
    from pydantic import ValidationError

    from tradingagents.dataflows.native_qualification import NativeSourceUnavailable
    from tradingagents.dataflows.tushare_price_history import PriceHistoryQualificationError
    from tradingagents.execution.config_identity import SemanticConfigError
    from tradingagents.execution.native_publication import NativePublicationError

    if error is None:
        return "unexpected_internal_failure"
    if isinstance(error, (ReportPublicationError, NativePublicationError)):
        return "report_publication"
    if isinstance(error, SemanticConfigError):
        return "missing_configuration"
    if isinstance(error, (NativeSourceUnavailable, PriceHistoryQualificationError, ValidationError)):
        return "evidence_rejection"
    name = type(error).__name__.lower()
    if "checkpoint" in name or "fingerprint" in name:
        return "checkpoint_incompatibility"
    if "auth" in name or "credential" in name:
        return "provider_authentication"
    if "timeout" in name:
        return "provider_timeout"
    if "rate" in name and "limit" in name:
        return "vendor_rate_limit"
    if "evidence" in name:
        return "evidence_rejection"
    # ValueError/KeyError also arise from data parsing and internal invariants.
    # Only a typed configuration failure can instruct the user to fix settings.
    return "unexpected_internal_failure"


def _format_traceback(error: BaseException, *, limit: int = 8000) -> str:
    """Render a truncated traceback string for durable persistence.

    The full traceback can be large (nested research calls); ``limit`` keeps
    the persisted run.json bounded while preserving the failing frame and the
    immediate caller stack.
    """
    import traceback

    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    if len(rendered) > limit:
        rendered = rendered[:limit] + "\n... [truncated]"
    return rendered
