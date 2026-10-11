"""Closed transient-error classification and frozen native retry policy."""

import httpx

MODEL_RETRY_POLICY = {
    "version": "native-network-retry-v1",
    "delays_seconds": [2, 5, 10],
    "per_call_retries": 3,
    "run_retries": 3,
    "model_attempts": 12,
}

_PERMANENT_CODES = {
    "insufficient_quota", "quota_exceeded", "billing_hard_limit_reached",
    "authentication_error", "invalid_api_key", "invalid_request_error",
    "context_length_exceeded", "model_not_found",
}


def transient_model_error(exc):
    """No message matching: arbitrary upstream prose is neither policy nor log."""
    diagnostic = getattr(exc, "diagnostic", None)
    code = getattr(exc, "code", None)
    status = getattr(exc, "status_code", None)
    if diagnostic is not None:
        code, status = diagnostic.upstream_code, diagnostic.upstream_status
        # Subscription permission/quota/stream errors belong to their own
        # recovery flow; only generic HTTP errors qualify here.
        if diagnostic.category != "request_failed":
            return False
    if isinstance(code, str) and code in _PERMANENT_CODES:
        return False
    if type(status) is int:
        return status in {408, 429} or 500 <= status <= 599
    if isinstance(exc, (TimeoutError, ConnectionError, httpx.TimeoutException,
                        httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    # OpenAI-compatible clients expose transport errors without HTTP status.
    from openai import APIConnectionError

    return isinstance(exc, APIConnectionError)
