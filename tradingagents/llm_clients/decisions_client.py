"""OpenRouter Decisions API client and defaults for Insight verification."""
import math
import os
import time

import requests

DEFAULT_DECISION_MODEL = "perplexity/pplx-decider-flash-v1.3:free"
JEV_DECISION_MODEL = "typesafe/jev-1.14"
TARGETED_REVIEW_POLICY = "targeted-v1"


def decision_run_config(enabled, model, *, configured):
    """Freeze policy for a new study. Omitted enablement follows key availability."""
    if enabled is not None and type(enabled) is not bool:
        raise ValueError("jev_verification_enabled must be boolean")
    enabled = configured if enabled is None else enabled
    if enabled and not configured:
        raise ValueError("决策核验需要配置 OPENROUTER_API_KEY。")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("jev_model must be a nonempty model ID")
    model = model.strip()
    alternate = DEFAULT_DECISION_MODEL if model.removeprefix("~").startswith("typesafe/jev-") else JEV_DECISION_MODEL
    return {"insight_review_policy": TARGETED_REVIEW_POLICY, "jev_verification_enabled": enabled,
            "jev_model": model, "jev_fallback_model": alternate}


DECISIONS_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"


class JevVerificationError(Exception):
    """Jev 调用失败，不可重试的错误（4xx）。"""


class JevVerificationUnavailable(Exception):
    """Jev 调用失败，可能是暂时性的（5xx/timeout/网络）。"""


def verify_insight_risk(
    model: str,
    insight_state: dict,
    questions: dict,
    *,
    timeout: int = 30,
    retries: int = 3
) -> tuple[dict[str, float], dict]:
    """
    调用 OpenRouter Decisions API 对单条 insight 进行风险验证。

    Args:
        model: 模型 ID，如 "typesafe/jev-1.14" 或 "perplexity/pplx-decider-flash-v1.3:free"
        insight_state: 待判断的内容（包含 insight、evidence、global_catalog_summary）
        questions: 问题字典，每个问题是 {"type": "noul", "instructions": "...", "criteria": {...}}
        timeout: 单次请求超时（秒）
        retries: 重试次数

    Returns:
        (scores, meta):
            scores: {"evidence_sufficient": 0.92, "reasoning_sound": 0.88, ...}
            meta: {"id": "...", "model": "...", "usage": {...}}

    Raises:
        JevVerificationError: 4xx 错误，不可重试
        JevVerificationUnavailable: 5xx/timeout/网络错误，可能暂时性
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise JevVerificationError("OPENROUTER_API_KEY not set")

    body = {
        "model": model,
        "state": insight_state,
        "questions": questions,
        "provider": {"data_collection": "deny"}  # 隐私收紧
    }

    last_error = None
    for attempt in range(retries):
        try:
            response = requests.post(
                DECISIONS_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=body,
                timeout=timeout
            )
        except requests.RequestException as exc:
            last_error = type(exc).__name__
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
            continue

        # 429 / 5xx 重试
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            if attempt + 1 < retries:
                try:
                    wait = float(response.headers.get("Retry-After", 2 ** attempt))
                except ValueError:
                    wait = 2 ** attempt
                time.sleep(min(30, max(0, wait)))
            continue

        # 4xx 不可重试
        if response.status_code >= 400:
            raise JevVerificationError(
                f"Jev API HTTP {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError:
            raise JevVerificationError("Invalid Decisions JSON") from None
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict):
            raise JevVerificationError("Invalid Decisions answers")

        # 检查答案完整性
        missing = [k for k in questions if k not in answers]
        if missing:
            raise JevVerificationError(f"Missing answers: {missing}")

        scores = {}
        for name in questions:
            ans = answers[name]
            ans_type = ans.get("type") if isinstance(ans, dict) else None
            if ans_type == "refusal":
                raise JevVerificationError(f"Provider refused to answer: {name}")
            if ans_type == "noul":
                prob = ans.get("noul")
                if type(prob) not in (int, float) or not (0.0 <= prob <= 1.0):
                    raise JevVerificationError(
                        f"Invalid probability for {name}"
                    )
                scores[name] = float(prob)
            else:
                raise JevVerificationError(f"Unexpected answer type for {name}")

        usage = data.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise JevVerificationError("Invalid Decisions usage")
        usage = usage or {}
        for field in ("input_tokens", "output_tokens"):
            value = usage.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise JevVerificationError("Invalid Decisions usage")
        meta = {}
        for field, default in (("id", ""), ("model", model), ("provider", "")):
            value = data.get(field)
            if value is not None and not isinstance(value, str):
                raise JevVerificationError("Invalid Decisions metadata")
            meta[field] = value or default
        meta["usage"] = {key: value for key, value in usage.items()
                         if type(value) is int or type(value) is float and math.isfinite(value)}
        return scores, meta

    raise JevVerificationUnavailable(
        f"Jev verification failed after {retries} attempts: {last_error}"
    )
