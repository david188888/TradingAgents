"""Versioned request semantics, separate from mutable subscription credentials."""

from .chatgpt_errors import ChatGPTError

CHATGPT_REQUEST_POLICY = "siwc-reasoning-v1"
REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"})


def validate_request_policy(policy):
    if policy is not None and policy != CHATGPT_REQUEST_POLICY:
        raise ValueError("unsupported ChatGPT request policy")
    return policy


def validate_reasoning_effort(value):
    """Validate syntax only; the selected model decides its supported subset."""
    if value is not None and (not isinstance(value, str) or value not in REASONING_EFFORTS):
        raise ChatGPTError("subscription_sharing_unsupported_capability")
    return value
