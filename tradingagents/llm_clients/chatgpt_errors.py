"""Closed, secret-free diagnostics for ChatGPT plan requests."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelFailureDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(default="", max_length=64)
    category: str = Field(max_length=64)
    upstream_status: int | None = Field(default=None, ge=100, le=599)
    upstream_code: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    safe_message: str = Field(max_length=300)
    action: Literal[
        "sign_in", "manage_usage", "refresh_models", "retry_later",
        "check_permissions", "check_capability", "cancelled",
    ]


_MESSAGES = {
    "not_signed_in": ("请先登录 ChatGPT 并授权使用计划额度。", "sign_in"),
    "invalid_identity": ("ChatGPT 身份验证失败，请重新登录。", "sign_in"),
    "invalid_callback": ("登录回调无效、已使用或已过期，请重新登录。", "sign_in"),
    "access_denied": ("未完成 ChatGPT 授权。", "sign_in"),
    "session_changed": ("此运行绑定的 ChatGPT 会话已退出或更换，请重新登录。", "sign_in"),
    "invalid_grant": ("ChatGPT 登录已失效，请重新登录。", "sign_in"),
    "invalid_client": ("ChatGPT 注册已失效，请重新登录。", "sign_in"),
    "subscription_sharing_usage_limit_exceeded": ("ChatGPT 计划或此应用的用量达到限制，请管理用量后主动重新尝试。", "manage_usage"),
    "subscription_sharing_user_not_eligible": ("此账户或工作区暂不能授权计划用量。", "check_permissions"),
    "subscription_sharing_unsupported_capability": ("所选模型或请求能力不支持此订阅调用。", "check_capability"),
    "subscription_sharing_route_not_supported": ("此订阅请求路由不受支持。", "check_capability"),
    "subscription_sharing_invalid_user": ("ChatGPT 身份无法验证，请重新登录。", "sign_in"),
    "chatpass_v2_scope_not_authorized": ("ChatGPT 计划授权未启用，请检查权限。", "check_permissions"),
    "chatpass_v2_invalid_authorization_context": ("ChatGPT 计划授权上下文无效，请检查权限。", "check_permissions"),
    "authorization_rejected": ("ChatGPT 计划授权被拒绝，请检查账户权限或重新登录。", "sign_in"),
    "subscription_sharing_user_unavailable": ("ChatGPT 账户信息暂不可用，请稍后主动重新尝试。", "retry_later"),
    "subscription_sharing_usage_unavailable": ("ChatGPT 计划用量暂不可用，请稍后主动重新尝试。", "retry_later"),
    "catalog_unavailable": ("无法读取该账户模型列表，请刷新后重试。", "refresh_models"),
    "model_not_available": ("所选模型已不在账户目录，请刷新并重新选择。", "refresh_models"),
    "stream_incomplete": ("模型流未完整结束，本次输出未采用。", "retry_later"),
    "cancelled": ("模型调用已取消。", "cancelled"),
    "deadline_exceeded": ("模型调用超时，本次输出未采用。", "retry_later"),
    "refresh_temporarily_unavailable": ("ChatGPT 登录暂时无法续期，请稍后主动重新尝试。", "retry_later"),
}


class ChatGPTError(RuntimeError):
    def __init__(self, code="request_failed", *, status=None, request_id=None):
        message, action = _MESSAGES.get(code, ("ChatGPT 请求暂不可用，请检查账户权限或稍后重试。", "retry_later"))
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) else None
        safe_id = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) else None
        self.diagnostic = ModelFailureDiagnostic(
            category=code if code in _MESSAGES else "request_failed", upstream_status=status,
            upstream_code=safe_code, request_id=safe_id, safe_message=message, action=action,
        )
        super().__init__(message)


def response_error(response):
    """Do not persist/echo arbitrary upstream messages or raw response bodies."""
    try:
        body = response.json()
        error = body.get("error", {})
        # OAuth token endpoints use a string; inference APIs use an object.
        code = error if isinstance(error, str) else error.get("code", "request_failed")
        if not isinstance(code, str):
            code = "request_failed"
    except (ValueError, AttributeError, TypeError):
        code = "request_failed"
    if code == "request_failed" and response.status_code in {401, 403}:
        code = "authorization_rejected"
    return ChatGPTError(code, status=response.status_code, request_id=response.headers.get("x-request-id"))


def transient_refresh_error(error):
    """Only transport/generic service failures permit a still-valid token fallback."""
    diagnostic = error.diagnostic
    if diagnostic.category != "request_failed":
        return False
    if diagnostic.upstream_code in {"transport_timeout", "transport_connection_error"}:
        return True
    status = diagnostic.upstream_status
    return (diagnostic.upstream_code in {None, "request_failed", "server_error", "internal_server_error",
                                        "temporarily_unavailable", "rate_limit_exceeded"}
            and type(status) is int and (status in {408, 429} or 500 <= status <= 599))
