"""FastAPI boundary for the localhost-only TradingAgents workbench."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from tradingagents.analysts import ANALYST_CONFIG, ANALYST_WIRE_KEYS
from tradingagents.dataflows.company_resolution import resolve_input_candidates
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.models import AnalysisRequest, HoldingContext
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
from tradingagents.presets import load_preset_catalog
from tradingagents.research.catalyst_evidence_policy import (
    CATALYST_HORIZON_NOT_SUPPORTED,
    CATALYST_LEGACY_SCHEDULING_PARAMS,
    CATALYST_MARKET_UNSUPPORTED,
    CATALYST_MODE_UNSUPPORTED,
    CATALYST_PROFILE_UNAVAILABLE,
    CATALYST_V1_PROFILE,
    CLASSIC_PROFILE,
    catalyst_evidence_policy_v1,
    normalize_research_profile,
)
from tradingagents.research.native_evidence_policy import (
    NativeEvidencePolicyV1,
    is_native_stock_ticker,
)
from tradingagents.runtime.run_models import generate_run_id
from tradingagents.web.reader_process_models import AgentKey
from tradingagents.web.reader_process_projection import project_reader_agent, project_reader_process
from tradingagents.web.research_record_projection import project_research_record

from .audit_models import AuditSelection
from .audit_projection import (
    AuditItemNotFound,
    AuditSummaryStale,
    AuditTerminalRequired,
    project_audit_detail,
    project_audit_summary,
)
from .batch_models import BatchItem
from .broker import EventBroker, Keepalive, SubscriptionClosed
from .catalyst_projection import project_catalyst
from .connectivity import YahooUnavailableError
from .manager import (
    LegacyResumeNormalizationFailed,
    ResumeRunConflict,
    RunNotActive,
    RunNotResumable,
    RunNotRetryable,
    SingleRunManager,
)
from .projections import InvalidCursor, RunProjectionPublisher, recent_runs_page
from .reader_models import CompanionSelection
from .reader_projection import (
    CompanionNotFound,
    ResearchPackageNotFound,
    project_companion,
    project_reader,
    project_research_package,
)
from .schemas import (
    RESEARCH_DEPTHS,
    SUPPORTED_OUTPUT_LANGUAGES,
    BatchCreateRequest,
    BatchValidateRequest,
    HoldingInputRequest,
    PortfolioRequest,
    RunCreateRequest,
)
from .store import (
    InvalidStorePath,
    RunNotFound,
    RunStore,
    RunStoreCorruption,
)

TERMINAL_STREAM_EVENTS = frozenset(
    {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}
)
TERMINAL_STREAM_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted"}
)
DATA_CREDENTIAL_ENV = {
    "alpha_vantage": ("ALPHA_VANTAGE_API_KEY",),
    "fred": ("FRED_API_KEY",),
    "tavily": ("TAVILY_API_KEY",),
    "tushare": ("TUSHARE_TOKEN", "TUSHARE_API_KEY"),
}
WIND_CAPABILITIES = (
    "指数快照与历史",
    "指数估值",
    "个股风险指标",
    "宏观 EDB",
)
AZURE_REQUIRED_ENV = ("AZURE_OPENAI_ENDPOINT", "OPENAI_API_VERSION")
SAFE_RESUME_MISMATCH_FIELDS = frozenset(
    {
        "abandoned_task_is_durable",
        "abandoned_task_missing",
        "abandoned_tool_already_committed",
        "analysis_date",
        "asset_type",
        "checkpoint_enabled",
        "checkpoint_event_content_mismatch",
        "checkpoint_event_frontier_mismatch",
        "checkpoint_event_frontier_too_far_behind",
        "checkpoint_event_shape",
        "checkpoint_frontier_drift",
        "checkpoint_missing",
        "checkpoint_not_committed",
        "checkpoint_shape",
        "commit_event_without_durable_task",
        "commit_map_shape",
        "commit_task_id_mismatch",
        "commit_token_changed",
        "commit_token_removed",
        "commit_token_schema",
        "commit_token_shape",
        "deep_think_llm",
        "duplicate_checkpoint_event",
        "duplicate_pending_commit",
        "duplicate_task_candidate",
        "duplicate_task_started",
        "durable_task_without_commit_event",
        "effective_config",
        "event_frontier_drift",
        "event_schema_version",
        "fingerprint_integrity",
        "fingerprint_missing",
        "fingerprint_version",
        "initial_context_hash",
        "llm_provider",
        "max_debate_rounds",
        "max_risk_discuss_rounds",
        "missing_task_candidate",
        "observation_frontier",
        "observation_schema",
        "output_language",
        "pending_business_write_without_commit",
        "pending_commit_shape",
        "pending_commit_task_id_mismatch",
        "pending_task_already_committed",
        "pending_write_shape",
        "quick_think_llm",
        "request",
        "resume_eligibility",
        "role_tool_route_mismatch",
        "runtime_environment",
        "runtime_semantics_hash",
        "selected_analysts",
        "task_abandoned_conflict",
        "task_abandoned_shape",
        "task_candidate_artifact",
        "task_candidate_content",
        "task_candidate_token_mismatch",
        "task_committed_twice",
        "task_started_candidate_mismatch",
        "task_started_shape",
        "ticker",
        "tokenless_application_channel_update",
        "tokenless_business_state_change",
        "tokenless_pending_business_write",
        "tool_role_route_mismatch",
        "unproven_initial_tokenless_checkpoint",
    }
)
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors "
        "'none'; form-action 'self'; script-src 'self'; style-src 'self' "
        "'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class ApiBoundaryError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: tuple[str, ...] = (),
        active_run_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.public_message = message
        self.fields = fields
        self.active_run_id = active_run_id
        super().__init__(message)


def create_app(
    *,
    store: RunStore | None = None,
    broker: EventBroker | None = None,
    manager: SingleRunManager | None = None,
    static_dir: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    checkpoint_available: bool = True,
    recover_startup: bool = True,
    connectivity_check: Callable[[str], None] | None = None,
) -> FastAPI:
    """Compose the HTTP layer without importing it from legacy CLI paths.

    ``connectivity_check`` is injected so tests can avoid a real Yahoo probe;
    production wires it to :func:`tradingagents.web.connectivity.check_yfinance_reachable`.
    """
    if manager is not None:
        # Reuse the manager's broker so worker persist (manager.broker) and
        # SSE subscribe (app.state.broker) share one _subscribers registry.
        # A mismatch here silently drops every live event because persist
        # never sees the subscriber registered on the other broker.
        manager_broker = getattr(manager, "broker", None)
        if broker is not None and manager_broker is not None and broker is not manager_broker:
            raise ValueError(
                "broker must match manager.broker when both are provided; "
                "a mismatch silently drops all live SSE events"
            )
        selected_manager = manager
        selected_store = store or getattr(manager, "store", None) or RunStore()
        selected_broker = broker or manager_broker or EventBroker(selected_store)
    else:
        selected_store = store or RunStore()
        selected_broker = broker or EventBroker(selected_store)
        selected_manager = SingleRunManager(selected_store, selected_broker)
    selected_environment = os.environ if environment is None else environment
    if connectivity_check is None:
        from .connectivity import check_yfinance_reachable

        connectivity_check = check_yfinance_reachable
    assets_root = Path(static_dir or Path(__file__).with_name("static")).resolve()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if recover_startup:
            recover = getattr(selected_manager, "recover_startup", None)
            if callable(recover):
                application.state.recovered_runs = recover()
        yield

    app = FastAPI(
        title="TradingAgents Local Workbench",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.store = selected_store
    app.state.broker = selected_broker
    app.state.manager = selected_manager
    app.state.environment = selected_environment
    app.state.checkpoint_available = checkpoint_available
    app.state.static_dir = assets_root

    @app.middleware("http")
    async def add_response_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        # Cache policy: the SPA entry must revalidate on every load so a
        # rebuilt frontend takes effect without manual cache clearing, while
        # content-hashed build assets under /assets are safe to cache for a
        # year because their URLs change on every rebuild.
        path = request.url.path
        if path.startswith("/assets/"):
            if response.status_code in (200, 206, 304):
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
        elif (
            response.status_code == 200
            and response.headers.get("content-type", "").startswith("text/html")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(ApiBoundaryError)
    async def handle_boundary_error(_request: Request, exc: ApiBoundaryError):
        return _error_response(
            exc.status_code,
            exc.code,
            exc.public_message,
            fields=exc.fields,
            active_run_id=exc.active_run_id,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request,
        exc: RequestValidationError,
    ):
        fields = tuple(
            dict.fromkeys(
                ".".join(str(part) for part in error.get("loc", ()) if part != "body")
                or "request"
                for error in exc.errors()
            )
        )
        return _error_response(
            422,
            "validation_error",
            "The request contains invalid fields.",
            fields=fields,
        )

    @app.exception_handler(RunNotFound)
    @app.exception_handler(InvalidStorePath)
    async def handle_missing_run(_request: Request, _exc: Exception):
        return _error_response(404, "not_found", "The requested run or artifact was not found.")

    @app.exception_handler(RunStoreCorruption)
    async def handle_store_corruption(_request: Request, _exc: RunStoreCorruption):
        return _error_response(
            500,
            "history_corrupted",
            "Stored run history failed an integrity check.",
        )

    @app.exception_handler(RunNotActive)
    async def handle_not_active(_request: Request, _exc: RunNotActive):
        return _error_response(409, "run_not_active", "The run is not active.")

    @app.exception_handler(RunNotRetryable)
    async def handle_not_retryable(_request: Request, _exc: RunNotRetryable):
        return _error_response(409, "run_not_retryable", "The run cannot be retried.")

    @app.exception_handler(RunNotResumable)
    async def handle_not_resumable(_request: Request, _exc: RunNotResumable):
        return _error_response(409, "run_not_resumable", "The run cannot be resumed.")

    @app.exception_handler(LegacyResumeNormalizationFailed)
    async def handle_legacy_resume_normalization(
        _request: Request,
        _exc: LegacyResumeNormalizationFailed,
    ):
        return _error_response(
            409,
            "legacy_resume_normalization_failed",
            "The stored legacy run cannot be safely resumed; create a new analysis.",
        )

    @app.exception_handler(YahooUnavailableError)
    async def handle_yahoo_unavailable(_request: Request, exc: YahooUnavailableError):
        # Global tickers need yfinance (VPN); the preflight failed. Surface a
        # distinct code so the frontend can prompt the user to enable a VPN.
        return _error_response(
            503,
            "yfinance_unreachable",
            "无法连接行情数据源（Yahoo Finance）。请开启 VPN 后重试。",
            fields=("ticker",),
        )

    @app.exception_handler(ResumeRunConflict)
    async def handle_resume_conflict(_request: Request, exc: ResumeRunConflict):
        return _error_response(
            409,
            "resume_conflict",
            "The stored run is incompatible with the current runtime.",
            fields=_safe_mismatch_fields(exc.fields),
        )

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return _configuration_payload(
            selected_environment,
            checkpoint_available=checkpoint_available,
        )

    @app.post("/api/batches/validate")
    def validate_batch(body: BatchValidateRequest) -> dict[str, Any]:
        items = [_resolve_batch_input(raw, index) for index, raw in enumerate(body.inputs)]
        return {"items": items, "count": len(items), "max_items": 8}

    @app.get("/api/batches")
    def list_batches() -> list[dict[str, Any]]:
        return [batch.as_dict() for batch in selected_manager.list_batches()]

    @app.get("/api/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        return selected_manager.batch(batch_id).as_dict()

    @app.post("/api/batches", status_code=201)
    def create_batch(body: BatchCreateRequest) -> dict[str, Any]:
        for entry in body.entries:
            _require_native_creation(entry.config.research_profile)
        if not evidence_profile_enabled():
            raise ApiBoundaryError(403, "evidence_profile_unavailable", "此服务已停用新建证据研究。", fields=("research_profile",))
        configured_keys = _configured_keys(selected_environment)
        prepared: list[tuple[AnalysisRequest, Any]] = []
        seen_tickers: set[str] = set()
        for index, entry in enumerate(body.entries):
            resolved = _resolve_batch_input(entry.input, index)
            canonical = str(resolved["ticker"])
            if canonical in seen_tickers:
                raise ApiBoundaryError(
                    422,
                    "duplicate_ticker",
                    "The batch contains duplicate companies after normalization.",
                    fields=(f"entries.{index}.input",),
                )
            seen_tickers.add(canonical)
            config = entry.config
            request_body = RunCreateRequest(
                ticker=canonical,
                analysis_date=config.analysis_date,
                selected_analysts=config.selected_analysts,
                research_depth=config.research_depth,
                mode="company_research",
                horizon=config.horizon,
                llm_provider=config.llm_provider,
                quick_think_llm=config.quick_think_llm,
                deep_think_llm=config.deep_think_llm,
                output_language=config.output_language,
                checkpoint_enabled=config.checkpoint_enabled,
                asset_type=config.asset_type,
                research_profile=config.research_profile,
                research_question=config.research_question,
                evidence_policy=config.evidence_policy,
            )
            request_model, _ = _analysis_request(
                request_body,
                selected_environment,
                checkpoint_available=checkpoint_available,
            )
            connectivity_check(canonical)
            prepared.append(
                (
                    request_model,
                    BatchItem(
                        input_value=entry.input,
                        company_name=str(resolved["company_name"]),
                        ticker=canonical,
                        market=str(resolved["market"]),
                        run_id=generate_run_id(),
                        ordinal=index,
                        config=request_body.model_dump(mode="json"),
                    ),
                )
            )
        batch = selected_manager.start_batch(
            tuple(prepared),
            configured_keys=configured_keys,
            concurrency=body.concurrency,
        )
        return batch.as_dict()

    @app.post("/api/batches/{batch_id}/cancel", status_code=202)
    def cancel_batch(batch_id: str) -> dict[str, Any]:
        return selected_manager.cancel_batch(batch_id).as_dict()

    @app.delete("/api/batches/{batch_id}", status_code=204)
    def delete_batch(batch_id: str) -> Response:
        batch = selected_manager.batch(batch_id)
        if batch.status in {"queued", "running"}:
            raise ApiBoundaryError(409, "batch_active", "An active batch cannot be deleted.")
        selected_store.delete_batch(batch_id)
        return Response(status_code=204)

    @app.get("/api/scheduler")
    def get_scheduler() -> dict[str, int]:
        return {"concurrency": selected_manager.max_concurrency, "maximum": 3}

    @app.put("/api/scheduler", status_code=200)
    def update_scheduler(payload: dict[str, Any]) -> dict[str, int]:
        value = payload.get("concurrency")
        if not isinstance(value, int) or isinstance(value, bool) or value not in (1, 2, 3):
            raise ApiBoundaryError(422, "invalid_concurrency", "concurrency must be 1, 2, or 3.", fields=("concurrency",))
        return {"concurrency": selected_manager.set_concurrency(value), "maximum": 3}

    @app.get("/api/runs")
    def list_runs(
        view: str | None = Query(default=None),
        limit: int = Query(default=20),
        cursor: str | None = Query(default=None),
    ) -> Any:
        summaries = selected_store.list_runs()
        if view is None:
            # Preserve the original array contract for existing clients.
            return [asdict(summary) for summary in summaries]
        if view != "recent":
            raise ApiBoundaryError(400, "invalid_view", "Unsupported run list view.")
        try:
            return recent_runs_page(summaries, limit=limit, cursor=cursor)
        except ValueError as exc:
            raise ApiBoundaryError(422, "invalid_limit", "limit must be between 1 and 100.") from exc
        except InvalidCursor as exc:
            raise ApiBoundaryError(400, "invalid_cursor", "The cursor is invalid for this run list.") from exc

    @app.post("/api/runs", status_code=201)
    def create_run(body: RunCreateRequest) -> dict[str, Any]:
        # Global (non-A-share) tickers route through yfinance, which is
        # unreachable from a mainland network without a VPN. Fail fast with a
        # 503 before creating the run instead of wasting the whole analysis.
        # Reject retired/disabled workflows and unsupported markets before
        # a connectivity probe or background work can run.
        request_model, configured_keys = _analysis_request(
            body,
            selected_environment,
            checkpoint_available=checkpoint_available,
        )
        connectivity_check(request_model.ticker)
        return selected_manager.start(
            request_model,
            configured_keys=configured_keys,
        ).as_dict()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return selected_store.read_snapshot(run_id).as_dict()

    @app.get("/api/runs/{run_id}/view")
    def get_run_view(run_id: str) -> dict[str, Any]:
        # A projection problem is represented inside the envelope. The raw run
        # and audit artifacts remain reachable through their existing routes.
        return RunProjectionPublisher(selected_store).read_or_rebuild_view(run_id)

    @app.get("/api/runs/{run_id}/catalyst")
    def get_catalyst(run_id: str) -> dict[str, Any]:
        # Read-only, committed-facts-only. The projection makes no model and no
        # provider call, so opening or refreshing this page cannot change what
        # the run concludes. A missing run still surfaces as 404; a run that
        # exists without a catalyst artifact is an HTTP 200 discriminated body.
        return project_catalyst(selected_store, run_id)

    @app.get("/api/runs/{run_id}/reader")
    def get_reader(run_id: str) -> dict[str, Any]:
        # Read-only learning reader; missing runs surface as 404 via the global
        # RunNotFound handler. Projection problems become an "unavailable" body.
        return project_reader(selected_store, run_id)

    @app.get("/api/runs/{run_id}/reader/package")
    def get_reader_package(run_id: str) -> dict[str, Any]:
        try:
            return project_research_package(selected_store, run_id)
        except ResearchPackageNotFound as exc:
            raise ApiBoundaryError(
                404,
                "research_package_unavailable",
                "The public research package is not available for this run.",
            ) from exc

    @app.get("/api/runs/{run_id}/reader/process")
    def get_reader_process(run_id: str) -> dict[str, Any]:
        return project_reader_process(selected_store, run_id)

    @app.get("/api/runs/{run_id}/reader/agents/{role_key}")
    def get_reader_agent(run_id: str, role_key: AgentKey, source_sequence: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
        try:
            return project_reader_agent(selected_store, run_id, role_key, through=source_sequence)
        except ValueError:
            raise ApiBoundaryError(409, "reader_sequence_unavailable", "Requested Reader boundary is unavailable") from None

    @app.get("/api/runs/{run_id}/reader/record")
    def get_reader_record(run_id: str) -> dict[str, Any]:
        return project_research_record(selected_store, run_id)

    @app.get("/api/runs/{run_id}/reader/companion")
    def get_reader_companion(
        run_id: str,
        kind: Literal["role", "claim", "evidence", "risk"] = Query(),
        selection_id: str = Query(alias="id", min_length=1, max_length=512),
    ) -> dict[str, Any]:
        selection = CompanionSelection(kind=kind, id=selection_id)
        try:
            return project_companion(selected_store, run_id, selection)
        except CompanionNotFound as exc:
            raise ApiBoundaryError(
                404,
                "companion_not_found",
                "The requested companion selection is not available for this run.",
            ) from exc

    @app.get("/api/runs/{run_id}/audit")
    def get_audit_summary(run_id: str) -> dict[str, Any]:
        try:
            return project_audit_summary(selected_store, run_id)
        except AuditTerminalRequired as exc:
            raise ApiBoundaryError(
                409,
                "audit_terminal_required",
                "Audit Center is available only for terminal runs.",
            ) from exc

    @app.get("/api/runs/{run_id}/audit/detail")
    def get_audit_detail(
        run_id: str,
        kind: Literal[
            "run",
            "role",
            "capability",
            "tool",
            "artifact",
            "prompt",
            "config",
            "report",
        ] = Query(),
        selection_id: str = Query(alias="id", min_length=1, max_length=512),
        source_sequence: int = Query(alias="v", ge=0),
    ) -> dict[str, Any]:
        try:
            return project_audit_detail(
                selected_store,
                run_id,
                AuditSelection(kind=kind, id=selection_id),
                source_sequence,
            )
        except AuditTerminalRequired as exc:
            raise ApiBoundaryError(
                409,
                "audit_terminal_required",
                "Audit Center is available only for terminal runs.",
            ) from exc
        except AuditSummaryStale as exc:
            raise ApiBoundaryError(
                409,
                "audit_summary_stale",
                "The Audit summary changed; refresh it before reading details.",
            ) from exc
        except AuditItemNotFound as exc:
            raise ApiBoundaryError(
                404,
                "audit_item_not_found",
                "The requested Audit item is not available for this run.",
            ) from exc

    @app.get("/api/runs/{run_id}/evidence-refs/{ref_id}")
    def get_evidence_ref(run_id: str, ref_id: str) -> dict[str, Any]:
        """Resolve a validated ReaderBrief reference without accepting a locator."""
        envelope = RunProjectionPublisher(selected_store).read_or_rebuild_view(run_id)
        brief = envelope["view"]["brief"].get("value")
        if not isinstance(brief, Mapping):
            raise ApiBoundaryError(404, "ref_not_found", "The requested evidence reference was not found.")
        reference = next(
            (item for item in brief.get("evidence_refs", []) if isinstance(item, Mapping) and item.get("ref_id") == ref_id),
            None,
        )
        if reference is None:
            raise ApiBoundaryError(404, "ref_not_found", "The requested evidence reference was not found.")
        target = reference.get("target")
        if not isinstance(target, Mapping) or target.get("kind") != "artifact" or not isinstance(target.get("artifact_id"), str):
            raise ApiBoundaryError(410, "ref_target_missing", "The evidence target is no longer available.")
        artifact_id = target["artifact_id"]
        metadata = {item["artifact_id"]: item for item in _artifact_metadata(selected_store, run_id)}
        if artifact_id not in metadata:
            raise ApiBoundaryError(410, "ref_target_missing", "The evidence target is no longer available.")
        return {
            "ref_id": ref_id,
            "label": reference.get("label"),
            "resolution_status": "available",
            "target": dict(target),
            "artifact": metadata[artifact_id],
            "read_url": f"/api/runs/{run_id}/artifacts/{artifact_id}",
        }

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> dict[str, Any]:
        return selected_manager.cancel(run_id).as_dict()

    @app.post("/api/runs/{run_id}/retry", status_code=201)
    def retry_run(run_id: str) -> dict[str, Any]:
        source = selected_store.read_snapshot(run_id)
        _require_native_creation(source.metadata.get("research_profile", "classic"))
        if not evidence_profile_enabled():
            raise ApiBoundaryError(403, "evidence_profile_unavailable", "此服务已关闭新建研究。")
        connectivity_check(source.ticker)
        return selected_manager.retry(run_id).as_dict()

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str) -> dict[str, Any]:
        return selected_manager.resume(run_id).as_dict()

    @app.delete("/api/runs", status_code=200)
    def delete_all_runs() -> dict[str, Any]:
        """Delete every persisted run except the currently active analysis.

        Returns ``{"removed": N, "skipped_active": bool}`` so the frontend
        can report partial success when a run is still executing.  Deleting a
        run removes its directory and full durable history, so this endpoint
        is the destructive bulk twin of ``DELETE /api/runs/{run_id}``.
        Finished batch manifests are cleared too; an active batch is kept
        intact together with its member runs (a half-deleted batch would
        reference runs that no longer exist).
        """
        active_ids = set(getattr(selected_manager, "active_run_ids", ()))
        if not active_ids:
            legacy_active = getattr(selected_manager, "active_run_id", None)
            if legacy_active:
                active_ids.add(legacy_active)
        active_batches: set[str] = set()
        protected_run_ids: set[str] = set()
        for batch in selected_store.list_batches():
            if batch.status in {"queued", "running"}:
                active_batches.add(batch.batch_id)
                protected_run_ids.update(item.run_id for item in batch.items)
        removed = 0
        skipped_active = bool(active_ids)
        for summary in selected_store.list_runs():
            if summary.run_id in active_ids:
                continue
            if summary.run_id in protected_run_ids:
                skipped_active = True
                continue
            try:
                selected_store.delete_run(summary.run_id)
                removed += 1
            except RunNotFound:
                # A concurrent deletion can win the race; treat it as removed.
                continue
        for batch in selected_store.list_batches():
            if batch.batch_id in active_batches:
                continue
            try:
                selected_store.delete_batch(batch.batch_id)
            except RunNotFound:
                # A concurrent deletion can win the race; nothing to do.
                continue
        return {"removed": removed, "skipped_active": skipped_active}

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(run_id: str) -> Response:
        active_ids = set(getattr(selected_manager, "active_run_ids", ()))
        if not active_ids:
            legacy_active = getattr(selected_manager, "active_run_id", None)
            if legacy_active:
                active_ids.add(legacy_active)
        if run_id in active_ids:
            raise ApiBoundaryError(
                409,
                "run_active",
                "A running analysis cannot be deleted.",
            )
        selected_store.delete_run(run_id)
        return Response(status_code=204)

    @app.get("/api/runs/{run_id}/artifacts")
    def list_artifacts(run_id: str) -> list[dict[str, Any]]:
        selected_store.read_snapshot(run_id)
        return _artifact_metadata(selected_store, run_id)

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    def read_artifact(run_id: str, artifact_id: str) -> Response:
        selected_store.read_snapshot(run_id)
        metadata = {
            item["artifact_id"]: item
            for item in _artifact_metadata(selected_store, run_id)
        }
        if artifact_id not in metadata:
            raise RunNotFound(f"artifact {artifact_id}")
        content = selected_store.read_artifact(run_id, artifact_id)
        return Response(
            content=content,
            media_type=str(metadata[artifact_id]["media_type"]),
            headers={"Content-Length": str(len(content))},
        )

    @app.get("/api/runs/{run_id}/events")
    async def stream_events(
        request: Request,
        run_id: str,
        after: int | None = Query(default=None, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        snapshot = selected_store.read_snapshot(run_id)
        cursor = _event_cursor(after, last_event_id)
        subscription = await selected_broker.subscribe(
            run_id,
            after=cursor,
            close_after_replay=snapshot.status in TERMINAL_STREAM_STATUSES,
        )

        async def event_stream():
            try:
                async for item in subscription:
                    if await request.is_disconnected():
                        break
                    if isinstance(item, Keepalive):
                        yield f": {item.comment}\n\n"
                        continue
                    encoded = json.dumps(
                        item.as_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"id: {item.sequence}\nevent: {item.type}\ndata: {encoded}\n\n"
                    if item.type in TERMINAL_STREAM_EVENTS:
                        break
            except SubscriptionClosed:
                return
            finally:
                await subscription.close("client_disconnected")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if (assets_root / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_root / "assets"),
            name="assets",
        )

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        if path == "api" or path.startswith("api/"):
            return _error_response(404, "not_found", "The API route does not exist.")
        index = assets_root / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html")
        return _error_response(
            503,
            "frontend_unavailable",
            "The local frontend assets have not been built yet.",
        )

    return app


def _resolve_batch_input(raw: str, index: int) -> dict[str, str]:
    candidates = resolve_input_candidates(raw)
    if len(candidates) != 1:
        code = "company_not_found" if not candidates else "company_ambiguous"
        message = (
            "The company input could not be resolved to a unique instrument."
            if not candidates
            else "The company input matched multiple instruments; use a ticker or a more precise name."
        )
        raise ApiBoundaryError(422, code, message, fields=(f"entries.{index}.input",))
    company_name, raw_ticker = candidates[0]
    canonical = normalize_symbol(normalize_ticker_symbol(raw_ticker))
    if not canonical:
        raise ApiBoundaryError(422, "company_not_found", "The company input has no valid ticker.", fields=(f"entries.{index}.input",))
    market = "A-share" if canonical.endswith((".SS", ".SH", ".SZ", ".BJ")) else "global"
    return {"input": raw.strip(), "company_name": company_name, "ticker": canonical, "market": market}


def _analysis_request(
    body: RunCreateRequest,
    environment: Mapping[str, str],
    *,
    checkpoint_available: bool,
) -> tuple[AnalysisRequest, dict[str, bool]]:
    _require_native_creation(body.research_profile)
    provider = body.llm_provider.lower()
    if provider not in PROVIDER_API_KEY_ENV:
        raise ApiBoundaryError(
            422,
            "unsupported_provider",
            "The selected LLM provider is not supported.",
            fields=("llm_provider",),
        )
    _validate_model(provider, body.quick_think_llm, "quick_think_llm", "quick")
    _validate_model(provider, body.deep_think_llm, "deep_think_llm", "deep")

    if not _provider_configured(provider, environment):
        raise ApiBoundaryError(
            422,
            "missing_configuration",
            "The selected LLM provider is not configured on this local server.",
            fields=("llm_provider",),
        )
    if body.checkpoint_enabled and not checkpoint_available and body.research_profile not in {"catalyst_v1", "evidence_v1"}:
        raise ApiBoundaryError(
            422,
            "checkpoint_unavailable",
            "Checkpoint resume is unavailable in the current runtime.",
            fields=("checkpoint_enabled",),
        )

    canonical_ticker = normalize_symbol(normalize_ticker_symbol(body.ticker))
    asset_type = _asset_type(canonical_ticker)
    if body.asset_type is not None and body.asset_type != asset_type:
        raise ApiBoundaryError(
            422,
            "asset_type_mismatch",
            "The asset type does not match the normalized ticker.",
            fields=("ticker", "asset_type"),
        )
    if asset_type == "crypto" and "fundamentals" in body.selected_analysts:
        raise ApiBoundaryError(
            422,
            "unsupported_analyst",
            "The fundamentals analyst is unavailable for crypto.",
            fields=("selected_analysts",),
        )

    effective_config = {
        "llm_provider": provider,
        "quick_think_llm": body.quick_think_llm,
        "deep_think_llm": body.deep_think_llm,
        "output_language": body.output_language,
        "checkpoint_enabled": body.checkpoint_enabled,
        "max_debate_rounds": body.research_depth,
        "max_risk_discuss_rounds": body.research_depth,
    }
    configured_keys = _configured_keys(environment)
    if body.research_profile == "evidence_v1" and body.holding is not None:
        thesis = body.holding.original_thesis
        if thesis is not None and (not isinstance(thesis, str) or len(thesis) > 4000):
            raise ApiBoundaryError(422, "holding_original_thesis_invalid",
                "The original holding thesis must be a string of at most 4000 characters.",
                fields=("holding.original_thesis",))
    mode, holding_context = _normalize_research_context(body, canonical_ticker)
    research_profile, catalyst_policy = _normalize_research_profile(
        body,
        mode=mode,
        asset_type=asset_type,
        canonical_ticker=canonical_ticker,
    )
    return (
        AnalysisRequest(
            ticker=canonical_ticker,
            analysis_date=body.analysis_date,
            asset_type=asset_type,
            selected_analysts=body.selected_analysts,
            max_debate_rounds=body.research_depth,
            max_risk_discuss_rounds=body.research_depth,
            horizon=body.horizon,
            mode=mode,
            holding_context=holding_context,
            effective_config=effective_config,
            research_profile=research_profile,
            catalyst_policy=catalyst_policy,
            research_question=body.research_question,
            evidence_policy=(body.evidence_policy or NativeEvidencePolicyV1()) if research_profile == "evidence_v1" else None,
        ),
        configured_keys,
    )


def _normalize_research_profile(
    body: RunCreateRequest,
    *,
    mode: str,
    asset_type: str,
    canonical_ticker: str,
) -> tuple[str, object]:
    """Validate the requested execution profile before anything is enqueued.

    The new profile is a strict subset of what exists today.  Every combination
    it cannot honor is rejected with a readable, field-addressed error naming
    the alternative entry point -- never silently downgraded to ``classic``,
    because a silent downgrade would show the user a bull/bear report while they
    believed they had asked a bounded catalyst question.
    """
    try:
        profile = normalize_research_profile(body.research_profile)
    except ValueError as exc:
        raise ApiBoundaryError(
            422,
            CATALYST_PROFILE_UNAVAILABLE,
            "The requested research profile is not supported. Use classic, catalyst_v1 or evidence_v1.",
            fields=("research_profile",),
        ) from exc

    if profile == CLASSIC_PROFILE:
        return CLASSIC_PROFILE, None

    if profile == "evidence_v1":
        if not evidence_profile_enabled():
            raise ApiBoundaryError(403, "evidence_profile_unavailable",
                "此服务已关闭新建证据研究；历史记录仍可读取。",
                fields=("research_profile",))
        if asset_type != "stock" or not is_native_stock_ticker(canonical_ticker):
            raise ApiBoundaryError(422, "evidence_market_unsupported",
                "当前 Web 研究支持 A 股普通股票，请输入 A 股代码。",
                fields=("research_profile", "ticker", "asset_type"))
        if body.horizon != "medium":
            raise ApiBoundaryError(422, "evidence_horizon_not_supported",
                "research_profile=evidence_v1 does not use the classic horizon setting. Send horizon=medium or omit it.",
                fields=("horizon",))
        if not _catalyst_legacy_scheduling_is_default(body):
            raise ApiBoundaryError(422, "evidence_legacy_scheduling_params_not_applicable",
                "research_profile=evidence_v1 fixes its own roles and one challenge stage. Omit selected_analysts and research_depth, or send their default values.",
                fields=("selected_analysts", "research_depth"))
        return "evidence_v1", None

    if not catalyst_profile_enabled():
        raise ApiBoundaryError(
            403,
            CATALYST_PROFILE_UNAVAILABLE,
            "The catalyst_v1 research profile is not enabled on this server. "
            "Use research_profile=classic.",
            fields=("research_profile",),
        )

    if mode != "company_research":
        raise ApiBoundaryError(
            422,
            CATALYST_MODE_UNSUPPORTED,
            "research_profile=catalyst_v1 supports company_research only. "
            "Use research_profile=classic for holding review.",
            fields=("research_profile", "mode"),
        )
    if asset_type != "stock" or not _is_a_share_ticker(canonical_ticker):
        raise ApiBoundaryError(
            422,
            CATALYST_MARKET_UNSUPPORTED,
            "research_profile=catalyst_v1 supports A-share common stocks only. "
            "Use research_profile=classic for other markets or asset types.",
            fields=("research_profile", "ticker", "asset_type"),
        )
    # The new flow has its own role set.  The classic medium plan's required
    # roles must not be copied onto it, and an explicit non-default selection
    # must not be accepted and then ignored.
    if body.horizon != "medium":
        raise ApiBoundaryError(
            422,
            CATALYST_HORIZON_NOT_SUPPORTED,
            "research_profile=catalyst_v1 does not use the classic horizon setting; "
            "its evidence policy fixes the window. Send horizon=medium or omit it.",
            fields=("horizon",),
        )
    if not _catalyst_legacy_scheduling_is_default(body):
        raise ApiBoundaryError(
            422,
            CATALYST_LEGACY_SCHEDULING_PARAMS,
            "research_profile=catalyst_v1 does not use selected_analysts or "
            "research_depth; the profile fixes its own roles. Omit them or use "
            "research_profile=classic.",
            fields=("selected_analysts", "research_depth"),
        )
    return CATALYST_V1_PROFILE, catalyst_evidence_policy_v1()


def catalyst_profile_enabled() -> bool:
    """Feature flag: may a new catalyst_v1 run be created at all?

    The code configuration owns the default (off).  An explicit
    ``TRADINGAGENTS_CATALYST_PROFILE_ENABLED`` override wins over it, which is
    the supported way to exercise the enabled path without mutating the shared
    DEFAULT_CONFIG for the rest of the suite.
    """
    override = os.environ.get("TRADINGAGENTS_CATALYST_PROFILE_ENABLED")
    if override is not None and override.strip():
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return bool(DEFAULT_CONFIG.get("catalyst_profile_enabled", False))


def _require_native_creation(profile: str) -> None:
    if profile != "evidence_v1":
        raise ApiBoundaryError(410, "research_profile_retired",
            "旧流程已退出新建研究。请使用新版证据研究；历史读取和已有运行恢复仍可用。",
            fields=("research_profile",))


def evidence_profile_enabled() -> bool:
    """Creation-only switch; existing durable runs remain readable/recoverable."""
    override = os.environ.get("TRADINGAGENTS_EVIDENCE_ENABLED")
    if override is not None and override.strip():
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return bool(DEFAULT_CONFIG.get("evidence_profile_enabled", True))


def _catalyst_legacy_scheduling_is_default(body: RunCreateRequest) -> bool:
    """True when the classic scheduling fields carry no explicit selection."""
    return (
        tuple(body.selected_analysts) == tuple(ANALYST_WIRE_KEYS)
        and body.research_depth == 1
    )


_A_SHARE_SUFFIXES = (".SS", ".SZ", ".BJ", ".SH")


def _is_a_share_ticker(canonical_ticker: str) -> bool:
    return canonical_ticker.upper().endswith(_A_SHARE_SUFFIXES)


def _normalize_research_context(
    body: RunCreateRequest,
    canonical_ticker: str,
) -> tuple[Literal["company_research", "catalyst_research", "holding_review"], HoldingContext | None]:
    """Resolve new and legacy holding input without inventing account facts."""
    holding = body.holding
    portfolio = body.portfolio
    if holding is not None and portfolio is not None:
        raise ApiBoundaryError(
            422,
            "holding_legacy_conflict",
            "Provide either holding or legacy portfolio, not both.",
            fields=("portfolio",),
        )

    mode = body.mode
    if mode is None:
        mode = "holding_review" if holding is not None or portfolio is not None else "company_research"

    if mode == "catalyst_research" and body.research_profile != "evidence_v1":
        raise ApiBoundaryError(422, "evidence_mode_unsupported",
            "mode=catalyst_research requires research_profile=evidence_v1. The existing catalyst_v1 entry point uses company_research.",
            fields=("research_profile", "mode"))

    if mode in {"company_research", "catalyst_research"}:
        if holding is not None:
            raise ApiBoundaryError(
                422,
                "holding_not_allowed",
                "Company research cannot include holding facts." if mode == "company_research" else "Catalyst research cannot include holding facts.",
                fields=("holding",),
            )
        if portfolio is not None:
            raise ApiBoundaryError(
                422,
                "legacy_portfolio_not_allowed",
                "Company research cannot include a legacy portfolio." if mode == "company_research" else "Catalyst research cannot include a legacy portfolio.",
                fields=("portfolio",),
            )
        return mode, None

    if holding is not None:
        return mode, _normalize_holding_input(holding, canonical_ticker, body.analysis_date)
    if portfolio is not None:
        return mode, _normalize_legacy_portfolio(portfolio, canonical_ticker, body.analysis_date)
    raise ApiBoundaryError(
        422,
        "holding_required",
        "Holding review requires target holding facts.",
        fields=("holding",),
    )


def _normalize_holding_input(
    holding: HoldingInputRequest,
    canonical_ticker: str,
    analysis_date: str,
) -> HoldingContext:
    try:
        holding_ticker = normalize_symbol(normalize_ticker_symbol(holding.ticker))
    except (TypeError, ValueError):
        holding_ticker = ""
    if holding_ticker != canonical_ticker:
        raise ApiBoundaryError(
            422,
            "holding_ticker_mismatch",
            "The holding ticker must match the analysis ticker.",
            fields=("holding.ticker",),
        )
    return _build_holding_context(
        ticker=canonical_ticker,
        quantity=holding.quantity,
        average_cost=holding.average_cost,
        cash=holding.cash,
        total_account_value=holding.total_account_value,
        currency=holding.currency,
        facts_as_of=holding.facts_as_of,
        original_thesis=holding.original_thesis,
        analysis_date=analysis_date,
        source="user_provided",
    )


def _normalize_legacy_portfolio(
    portfolio: PortfolioRequest,
    canonical_ticker: str,
    analysis_date: str,
) -> HoldingContext:
    matches = tuple(
        position
        for position in portfolio.positions
        if normalize_symbol(normalize_ticker_symbol(position.ticker)) == canonical_ticker
    )
    if not matches:
        raise ApiBoundaryError(
            422,
            "legacy_target_position_missing",
            "The legacy portfolio has no position for the analysis ticker.",
            fields=("portfolio.positions",),
        )
    if len(matches) > 1:
        raise ApiBoundaryError(
            422,
            "legacy_target_position_ambiguous",
            "The legacy portfolio has multiple target positions after normalization.",
            fields=("portfolio.positions",),
        )
    target = matches[0]
    if not _positive_finite(target.quantity) or not _positive_finite(target.average_cost):
        raise ApiBoundaryError(
            422,
            "legacy_target_position_invalid",
            "The legacy target position needs positive quantity and average cost.",
            fields=("portfolio.positions",),
        )
    return _build_holding_context(
        ticker=canonical_ticker,
        quantity=target.quantity,
        average_cost=target.average_cost,
        cash=portfolio.cash,
        total_account_value=None,
        currency=portfolio.currency,
        facts_as_of=None,
        original_thesis=None,
        analysis_date=analysis_date,
        source="legacy_portfolio",
    )


def _build_holding_context(
    *,
    ticker: str,
    quantity: object | None,
    average_cost: object | None,
    cash: object | None,
    total_account_value: object | None,
    currency: object | None,
    facts_as_of: object | None,
    original_thesis: object | None,
    analysis_date: str,
    source: Literal["user_provided", "legacy_portfolio"],
) -> HoldingContext:
    if not _positive_finite(quantity):
        raise ApiBoundaryError(
            422,
            "holding_quantity_invalid",
            "Holding quantity must be a finite positive number.",
            fields=("holding.quantity",),
        )
    if not _positive_finite(average_cost):
        raise ApiBoundaryError(
            422,
            "holding_average_cost_invalid",
            "Holding average cost must be a finite positive number.",
            fields=("holding.average_cost",),
        )
    if cash is not None and not _nonnegative_finite(cash):
        raise ApiBoundaryError(
            422,
            "holding_cash_invalid",
            "Holding cash must be a finite non-negative number.",
            fields=("holding.cash",),
        )
    if total_account_value is not None and not _positive_finite(total_account_value):
        raise ApiBoundaryError(
            422,
            "holding_nav_invalid",
            "Total account value must be a finite positive number.",
            fields=("holding.total_account_value",),
        )
    normalized_currency: str | None = None
    if currency is not None:
        normalized_currency = currency.upper() if isinstance(currency, str) else ""
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ApiBoundaryError(
                422,
                "holding_currency_invalid",
                "Holding currency must be a three-letter ISO-4217 code.",
                fields=("holding.currency",),
            )
    normalized_as_of = analysis_date if facts_as_of is None else facts_as_of
    if not isinstance(normalized_as_of, str):
        raise ApiBoundaryError(
            422,
            "holding_as_of_invalid",
            "Holding facts date must use YYYY-MM-DD.",
            fields=("holding.facts_as_of",),
        )
    try:
        date.fromisoformat(normalized_as_of)
    except ValueError as exc:
        raise ApiBoundaryError(
            422,
            "holding_as_of_invalid",
            "Holding facts date must use YYYY-MM-DD.",
            fields=("holding.facts_as_of",),
        ) from exc
    if normalized_as_of != analysis_date:
        raise ApiBoundaryError(
            422,
            "holding_as_of_mismatch",
            "Holding facts date must match the analysis date.",
            fields=("holding.facts_as_of",),
        )
    try:
        return HoldingContext(
            ticker=ticker,
            quantity=float(quantity),
            average_cost=float(average_cost),
            cash=float(cash) if cash is not None else None,
            total_account_value=(
                float(total_account_value) if total_account_value is not None else None
            ),
            currency=normalized_currency,
            facts_as_of=normalized_as_of,
            original_thesis=original_thesis if isinstance(original_thesis, str) and original_thesis else None,
            source=source,
        )
    except ValueError as exc:  # Defensive: public validation above owns known failures.
        raise ApiBoundaryError(
            422,
            "validation_error",
            "The request contains invalid holding facts.",
            fields=("holding",),
        ) from exc


def _positive_finite(value: object | None) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _nonnegative_finite(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return isfinite(float(value)) and float(value) >= 0
    except (TypeError, ValueError):
        return False


def _validate_model(provider: str, model: str, field: str, mode: str) -> None:
    options = MODEL_OPTIONS.get(provider)
    if options is None:
        return
    mode_options = options[mode]
    allowed = {value for _label, value in mode_options if value != "custom"}
    custom_allowed = any(value == "custom" for _label, value in mode_options)
    if model == "custom" or (not custom_allowed and model not in allowed):
        raise ApiBoundaryError(
            422,
            "unsupported_model",
            "The selected model is not available for this provider and mode.",
            fields=(field,),
        )


def _asset_type(ticker: str) -> str:
    crypto_suffixes = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")
    return "crypto" if ticker.upper().endswith(crypto_suffixes) else "stock"


def _configured_keys(environment: Mapping[str, str]) -> dict[str, bool]:
    configured = {
        provider: _provider_configured(provider, environment)
        for provider in PROVIDER_API_KEY_ENV
    }
    configured.update(
        {
            provider: any(environment.get(env_name) for env_name in env_names)
            for provider, env_names in DATA_CREDENTIAL_ENV.items()
        }
    )
    return configured


def _provider_configured(provider: str, environment: Mapping[str, str]) -> bool:
    env_name = PROVIDER_API_KEY_ENV[provider]
    if env_name is not None and not environment.get(env_name):
        return False
    return provider != "azure" or not any(
        not environment.get(required) for required in AZURE_REQUIRED_ENV
    )


def _configuration_payload(
    environment: Mapping[str, str],
    *,
    checkpoint_available: bool,
) -> dict[str, Any]:
    configured = _configured_keys(environment)
    presets = load_preset_catalog()
    providers = []
    for provider, env_name in PROVIDER_API_KEY_ENV.items():
        modes = MODEL_OPTIONS.get(provider)
        providers.append(
            {
                "id": provider,
                "configured": configured[provider],
                "requires_api_key": env_name is not None,
                "models": {
                    mode: [
                        {"label": label, "id": model_id}
                        for label, model_id in (modes or {}).get(mode, ())
                    ]
                    for mode in ("quick", "deep")
                },
                "custom_model_allowed": modes is None
                or any(
                    model_id == "custom"
                    for options in modes.values()
                    for _label, model_id in options
                ),
            }
        )
    return {
        "providers": providers,
        "configured_keys": configured,
        "analysts": [analyst.as_api_option() for analyst in ANALYST_CONFIG],
        "presets": [preset.as_config_option() for preset in presets.presets],
        "depths": list(RESEARCH_DEPTHS),
        "output_languages": list(SUPPORTED_OUTPUT_LANGUAGES),
        "checkpoint_available": checkpoint_available,
        "research_profiles": {
            "classic": {"supported": False, "reason": "仅保留历史读取和已有运行恢复"},
            "catalyst_v1": {"supported": False, "reason": "仅保留历史读取和已有运行恢复"},
            "evidence_v1": {"supported": evidence_profile_enabled(),
                "reason": None if evidence_profile_enabled() else "此服务已停用新建证据研究",
                "checkpoint_available": True},
        },
        "wind": {
            "enabled": bool(DEFAULT_CONFIG.get("wind_enabled", False)),
            "configured": bool(environment.get("WIND_API_KEY")),
            "capabilities": list(WIND_CAPABILITIES),
        },
        "defaults": {
            "research_profile": "evidence_v1",
            "llm_provider": DEFAULT_CONFIG.get("llm_provider"),
            "quick_think_llm": DEFAULT_CONFIG.get("quick_think_llm"),
            "deep_think_llm": DEFAULT_CONFIG.get("deep_think_llm"),
            "output_language": DEFAULT_CONFIG.get("output_language", "English"),
            "research_depth": DEFAULT_CONFIG.get("max_debate_rounds", 1),
            "checkpoint_enabled": bool(DEFAULT_CONFIG.get("checkpoint_enabled")),
        },
    }


def _artifact_metadata(store: RunStore, run_id: str) -> list[dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for event in store.read_events(run_id):
        if event.type != "artifact.written":
            continue
        payload = event.payload
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        artifacts.setdefault(
            artifact_id,
            {
                "artifact_id": artifact_id,
                "kind": str(payload.get("kind") or "data"),
                "media_type": str(payload.get("media_type") or "application/octet-stream"),
                "content_sha256": str(payload.get("content_sha256") or ""),
                "byte_size": int(payload.get("byte_size") or 0),
                "locator": str(payload.get("locator") or ""),
            },
        )
    return list(artifacts.values())


def _event_cursor(after: int | None, last_event_id: str | None) -> int:
    header_cursor = 0
    if last_event_id is not None:
        try:
            header_cursor = int(last_event_id)
        except ValueError as exc:
            raise ApiBoundaryError(
                400,
                "invalid_event_cursor",
                "Last-Event-ID must be a non-negative integer.",
                fields=("Last-Event-ID",),
            ) from exc
        if header_cursor < 0:
            raise ApiBoundaryError(
                400,
                "invalid_event_cursor",
                "Last-Event-ID must be a non-negative integer.",
                fields=("Last-Event-ID",),
            )
    if after is not None and last_event_id is not None and after != header_cursor:
        raise ApiBoundaryError(
            400,
            "event_cursor_mismatch",
            "The query and Last-Event-ID cursors do not match.",
            fields=("after", "Last-Event-ID"),
        )
    return after if after is not None else header_cursor


def _safe_mismatch_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(field for field in fields if field in SAFE_RESUME_MISMATCH_FIELDS)
    )


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: tuple[str, ...] = (),
    active_run_id: str | None = None,
) -> JSONResponse:
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
        "fields": list(fields),
    }
    if active_run_id is not None:
        detail["active_run_id"] = active_run_id
    return JSONResponse({"detail": detail}, status_code=status_code)
