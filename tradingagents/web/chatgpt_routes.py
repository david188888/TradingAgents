"""Loopback-only credential-free Web adapter for SIWC."""

from urllib.parse import urlsplit

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from tradingagents.llm_clients.chatgpt_errors import ChatGPTError


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ref: str = Field(pattern=r"^cg_[0-9a-f]{32}$")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ref: str | None = Field(default=None, pattern=r"^cg_[0-9a-f]{32}$")


def _local(request, *, mutation=False):
    host = request.url.hostname
    if host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
        raise ChatGPTError("chatpass_v2_scope_not_authorized", status=403)
    origin = request.headers.get("origin")
    expected = (request.url.scheme, host, request.url.port or 80)
    if origin:
        parsed = urlsplit(origin)
        try:
            actual = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except ValueError:
            actual = None
        if actual != expected:
            raise ChatGPTError("chatpass_v2_scope_not_authorized", status=403)
    if mutation and (not origin or not request.headers.get("content-type", "").startswith("application/json")):
        raise ChatGPTError("chatpass_v2_scope_not_authorized", status=403)


def install_chatgpt_routes(app, auth):
    @app.get("/api/chatgpt/status")
    def status(request: Request):
        _local(request)
        return auth.status()

    @app.post("/api/chatgpt/login")
    def login(body: LoginRequest, request: Request):
        _local(request, mutation=True)
        return auth.begin_login(body.account_ref)

    @app.get("/api/chatgpt/login/{attempt_id}")
    def login_status(attempt_id: str, request: Request):
        _local(request)
        return auth.login_status(attempt_id)

    @app.post("/api/chatgpt/login/{attempt_id}/cancel")
    def cancel(attempt_id: str, request: Request):
        _local(request, mutation=True)
        auth.cancel_login(attempt_id)
        return {"status": "cancelled"}

    @app.post("/api/chatgpt/account")
    def account(body: AccountRequest, request: Request):
        _local(request, mutation=True)
        auth.select(body.account_ref)
        return auth.status()

    @app.post("/api/chatgpt/logout")
    def logout(body: AccountRequest, request: Request):
        _local(request, mutation=True)
        return auth.logout(body.account_ref)

    @app.post("/api/chatgpt/usage/retry")
    def retry_usage(body: AccountRequest, request: Request):
        _local(request, mutation=True)
        auth.retry_usage(body.account_ref)
        return auth.status()

    @app.get("/api/chatgpt/models")
    def models(account_ref: str, request: Request, refresh: bool = False):
        _local(request)
        return auth.models(account_ref, refresh=refresh)
