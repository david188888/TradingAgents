"""FastAPI boundary for the localhost-only TradingAgents workbench."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from tradingagents.dataflows.company_resolution import resolve_input_candidates
from tradingagents.dataflows.symbol_utils import normalize_symbol
from tradingagents.dataflows.ticker_utils import normalize_ticker_symbol
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.models import AnalysisRequest
from tradingagents.execution.native_runner import NEW_STUDY_TIMEOUT_SECONDS
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
from tradingagents.llm_clients.stage_models import EFFORT_CONFIG_KEYS
from tradingagents.research.native_evidence_policy import is_native_stock_ticker
from tradingagents.runtime.batch_models import BatchItem
from tradingagents.runtime.run_models import generate_run_id
from tradingagents.runtime.store import (
    InvalidStorePath,
    RunNotFound,
    RunStore,
    RunStoreCorruption,
)
from tradingagents.web.focus_projection import project_reader_focus
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
from .broker import EventBroker, Keepalive, SubscriptionClosed
from .manager import (
    RunNotActive,
    RunNotResumable,
    RunNotRetryable,
    SingleRunManager,
)
from .projections import InvalidCursor, recent_runs_page
from .schemas import (
    SUPPORTED_OUTPUT_LANGUAGES,
    BatchCreateRequest,
    BatchValidateRequest,
    RunCreateRequest,
)

TERMINAL_STREAM_EVENTS = frozenset(
    {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}
)
TERMINAL_STREAM_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted"}
)
DATA_CREDENTIAL_ENV = {
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
    chatgpt_auth=None,
) -> FastAPI:
    """Compose the local V9 research API and workbench."""
    from tradingagents.llm_clients.chatgpt_auth import ChatGPTAuth
    from tradingagents.llm_clients.chatgpt_errors import ChatGPTError
    from tradingagents.web.chatgpt_routes import install_chatgpt_routes

    manager_auth = getattr(manager, "chatgpt_auth", None)
    if manager_auth is not None and chatgpt_auth is not None and manager_auth is not chatgpt_auth:
        raise ValueError("manager and Web must use the same ChatGPT authentication service")
    selected_auth = chatgpt_auth or manager_auth or ChatGPTAuth()
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
        selected_manager.chatgpt_auth = selected_auth
        if hasattr(selected_manager, "_explanations"):
            selected_manager._explanations.chatgpt_auth = selected_auth
        selected_store = store or getattr(manager, "store", None) or RunStore()
        selected_broker = broker or manager_broker or EventBroker(selected_store)
    else:
        selected_store = store or RunStore()
        selected_broker = broker or EventBroker(selected_store)
        selected_manager = SingleRunManager(selected_store, selected_broker, chatgpt_auth=selected_auth)
    selected_environment = os.environ if environment is None else environment
    assets_root = Path(static_dir or Path(__file__).with_name("static")).resolve()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if recover_startup:
            recover = getattr(selected_manager, "recover_startup", None)
            if callable(recover):
                application.state.recovered_runs = recover()
        yield
        if hasattr(selected_manager, "_explanations"):
            selected_manager._explanations.close()
        selected_auth.close()

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
    app.state.chatgpt_auth = selected_auth
    install_chatgpt_routes(app, selected_auth)

    @app.exception_handler(ChatGPTError)
    async def handle_chatgpt_error(_request: Request, exc):
        d = exc.diagnostic
        return _error_response(
            d.upstream_status or 422, d.category, d.safe_message,
            diagnostic=d.model_dump(mode="json"),
        )

    @app.middleware("http")
    async def add_response_headers(request: Request, call_next):
        from .local_boundary import is_local_request

        if not is_local_request(request):
            response = _error_response(
                403, "local_origin_required", "Use the local workbench origin."
            )
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        # Cache policy: the SPA entry must revalidate on every load so a
        # rebuilt frontend takes effect without manual cache clearing, while
        # content-hashed build assets under /assets are safe to cache for a
        # year because their URLs change on every rebuild.
        path = request.url.path
        if path.startswith("/api/chatgpt/"):
            response.headers["Cache-Control"] = "no-store"
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

    from tradingagents.runtime.run_models import UnsupportedResearchVersion

    @app.exception_handler(UnsupportedResearchVersion)
    async def handle_unsupported_version(_request: Request, _exc):
        return _error_response(409, "unsupported_research_version", "This run uses an unsupported research version.")

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



    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        return _configuration_payload(
            selected_environment,
            checkpoint_available=checkpoint_available,
            chatgpt_auth=selected_auth,
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
        configured_keys = _configured_keys(selected_environment)
        prepared = []
        seen = set()
        for index, entry in enumerate(body.entries):
            resolved = _resolve_batch_input(entry.input, index)
            ticker = resolved["ticker"]
            if ticker in seen:
                raise ApiBoundaryError(422, "duplicate_ticker", "Duplicate company.", fields=(f"entries.{index}.input",))
            seen.add(ticker)
            request_body = RunCreateRequest(ticker=ticker, **entry.config.model_dump())
            request_model, keys = _analysis_request(request_body, selected_environment, chatgpt_auth=selected_auth)
            configured_keys.update(keys)
            prepared.append((request_model, BatchItem(input_value=entry.input,
                company_name=resolved["company_name"], ticker=ticker, market="A-share",
                run_id=generate_run_id(), ordinal=index, config=request_body.model_dump(mode="json"))))
        return selected_manager.start_batch(tuple(prepared), configured_keys=configured_keys,
            concurrency=body.concurrency).as_dict()


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
        summaries = [item for item in selected_store.list_runs() if _is_current_run(selected_store, item.run_id)]
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
        request_model, configured_keys = _analysis_request(
            body,
            selected_environment,
            checkpoint_available=checkpoint_available,
            chatgpt_auth=selected_auth,
        )
        return selected_manager.start(
            request_model,
            configured_keys=configured_keys,
        ).as_dict()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return _current_snapshot(selected_store, run_id).as_dict()





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

    @app.get("/api/runs/{run_id}/reader/explanations")
    def get_reader_explanations(run_id: str) -> dict[str, Any]:
        from tradingagents.web.report_explanation import project_report_explanation
        return project_report_explanation(selected_store, run_id,
            service=getattr(selected_manager, "_explanations", None))

    @app.post("/api/runs/{run_id}/reader/explanations", status_code=202)
    def retry_reader_explanations(run_id: str) -> dict[str, Any]:
        from tradingagents.web.report_explanation import project_report_explanation
        try:
            selected_manager.explanations.start(run_id, retry=True)
        except ValueError:
            raise ApiBoundaryError(409, "explanation_unavailable", "This report cannot generate a plain-language explanation.") from None
        return project_report_explanation(selected_store, run_id, service=selected_manager.explanations)

    @app.get("/api/runs/{run_id}/reader/focus")
    def get_reader_focus(run_id: str, source_sequence: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
        try:
            return project_reader_focus(selected_store, run_id, through=source_sequence)
        except ValueError:
            raise ApiBoundaryError(409, "reader_sequence_unavailable", "Requested Reader boundary is unavailable") from None


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


    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> dict[str, Any]:
        return selected_manager.cancel(run_id).as_dict()

    @app.post("/api/runs/{run_id}/retry", status_code=201)
    def retry_run(run_id: str) -> dict[str, Any]:
        _current_snapshot(selected_store, run_id)
        if not evidence_profile_enabled():
            raise ApiBoundaryError(403, "evidence_profile_unavailable", "此服务已关闭新建研究。")
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
        with selected_manager.deletion_guard() as protected_ids:
            active_batches: set[str] = set()
            for batch in selected_store.list_batches():
                if batch.status in {"queued", "running"}:
                    active_batches.add(batch.batch_id)
            removed = 0
            skipped_active = bool(protected_ids)
            for summary in selected_store.list_runs():
                if summary.run_id in protected_ids:
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
        with selected_manager.deletion_guard() as protected_ids:
            if run_id in protected_ids:
                raise ApiBoundaryError(
                    409, "run_active", "An active analysis or batch member cannot be deleted."
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
    if not is_native_stock_ticker(canonical):
        raise ApiBoundaryError(422, "evidence_market_unsupported", "Research requires an A-share common stock.", fields=(f"entries.{index}.input",))
    return {"input": raw.strip(), "company_name": company_name, "ticker": canonical, "market": "A-share"}


def _analysis_request(body, environment, *, checkpoint_available=True, chatgpt_auth=None):
    _require_native_creation(body.research_profile)
    if not evidence_profile_enabled():
        raise ApiBoundaryError(403, "evidence_profile_unavailable", "此服务已关闭新建研究。")
    provider = body.llm_provider.lower()
    if provider not in PROVIDER_API_KEY_ENV and provider != "chatgpt":
        raise ApiBoundaryError(422, "unsupported_provider", "Unsupported LLM provider.", fields=("llm_provider",))
    stages = {key: value.model_dump(exclude_none=True) for key, value in body.stage_models.items()}
    # Each selection is (provider, model, catalog mode, request field); stages accept either tier.
    selections = [(provider, body.quick_think_llm, "quick", "quick_think_llm"),
                  (provider, body.deep_think_llm, "deep", "deep_think_llm")]
    selections += [(v["provider"], v["model"], None, f"stage_models.{key}.model")
                   for key, v in stages.items()]
    for selected, model, mode, field in selections:
        if selected == "chatgpt":
            continue
        _validate_model(selected, model, field, mode)
        if not _provider_configured(selected, environment):
            raise ApiBoundaryError(422, "missing_configuration", "The selected provider is not configured.",
                fields=("llm_provider" if field.endswith("_llm") else field.replace(".model", ".provider"),))
    subscription = [model for selected, model, _mode, _field in selections if selected == "chatgpt"]
    if subscription:
        from tradingagents.llm_clients.chatgpt_errors import ChatGPTError
        if chatgpt_auth is None:
            raise ChatGPTError("not_signed_in")
        chatgpt_auth.access(body.chatgpt_account_ref, for_inference=True)
        available = {item["id"] for item in chatgpt_auth.models(body.chatgpt_account_ref)["models"]}
        if not set(subscription) <= available:
            raise ChatGPTError("model_not_available")
    config = {"llm_provider": provider, "quick_think_llm": body.quick_think_llm,
        "deep_think_llm": body.deep_think_llm, "output_language": body.output_language,
        "evidence_timeout_seconds": NEW_STUDY_TIMEOUT_SECONDS}
    if stages:
        config["stage_models"] = stages
    if body.jev_verification_enabled:
        if not _provider_configured("openrouter", environment):
            raise ApiBoundaryError(422, "missing_configuration", "Jev verification requires OPENROUTER_API_KEY.",
                fields=("jev_verification_enabled",))
        config["jev_verification_enabled"] = True
        config["jev_model"] = body.jev_model
    if subscription:
        config["chatgpt_account_ref"] = body.chatgpt_account_ref
    if provider == "chatgpt":
        config["backend_url"] = None
    configured = _configured_keys(environment)
    if subscription:
        configured["chatgpt"] = True
    return AnalysisRequest(ticker=body.ticker, analysis_date=body.analysis_date,
        effective_config=config, research_question=body.research_question), configured









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




_A_SHARE_SUFFIXES = (".SS", ".SZ", ".BJ", ".SH")
















def _validate_model(provider: str, model: str, field: str, mode: str | None) -> None:
    options = MODEL_OPTIONS.get(provider)
    if options is None:
        return
    mode_options = options[mode] if mode else (*options["quick"], *options["deep"])
    allowed = {value for _label, value in mode_options if value != "custom"}
    custom_allowed = any(value == "custom" for _label, value in mode_options)
    if model == "custom" or (not custom_allowed and model not in allowed):
        raise ApiBoundaryError(
            422,
            "unsupported_model",
            "The selected model is not available for this provider and mode.",
            fields=(field,),
        )




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


_EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


def _configuration_payload(
    environment: Mapping[str, str],
    *,
    checkpoint_available: bool,
    chatgpt_auth=None,
) -> dict[str, Any]:
    configured = _configured_keys(environment)
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
    if chatgpt_auth is not None:
        accounts = chatgpt_auth.status()
        active = next((a for a in accounts["accounts"] if a["account_ref"] == accounts["active_account_ref"]), None)
        configured["chatgpt"] = bool(active and active["plan_enabled"])
        providers.append({"id": "chatgpt", "configured": configured["chatgpt"], "requires_api_key": False,
                          "authentication": "oauth", "models": {"quick": [], "deep": []}, "custom_model_allowed": False})
    return {
        "providers": providers,
        "configured_keys": configured,
        "output_languages": list(SUPPORTED_OUTPUT_LANGUAGES),
        # Providers absent here reject a stage effort.
        "stage_model_efforts": {provider: [e for e in _EFFORT_ORDER if e in values]
                                for provider, (_key, values) in EFFORT_CONFIG_KEYS.items()},
        "checkpoint_available": checkpoint_available,
        "research_profiles": {
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


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: tuple[str, ...] = (),
    active_run_id: str | None = None,
    diagnostic: dict[str, Any] | None = None,
) -> JSONResponse:
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
        "fields": list(fields),
    }
    if active_run_id is not None:
        detail["active_run_id"] = active_run_id
    if diagnostic is not None:
        detail["diagnostic"] = diagnostic
    return JSONResponse({"detail": detail}, status_code=status_code)


def _is_current_run(store, run_id):
    from tradingagents.execution.native_runner import WORKFLOW_VERSION
    snapshot = store.read_snapshot(run_id)
    return (snapshot.metadata.get("research_profile") == "evidence_v1"
        and snapshot.metadata.get("native_workflow_version") == WORKFLOW_VERSION)


def _current_snapshot(store, run_id):
    if not _is_current_run(store, run_id):
        raise ApiBoundaryError(409, "unsupported_research_version", "This run uses an unsupported research version.")
    return store.read_snapshot(run_id)
