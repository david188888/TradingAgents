"""OpenRouter Decisions API client for Jev verification."""
import os
import time

import requests

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
            last_error = str(exc)
            time.sleep(2 ** attempt)
            continue

        # 429 / 5xx 重试
        if response.status_code == 429 or response.status_code >= 500:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            last_error = f"{response.status_code}: {response.text[:200]}"
            time.sleep(wait)
            continue

        # 4xx 不可重试
        if response.status_code >= 400:
            raise JevVerificationError(
                f"Jev API {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        answers = data.get("answers", {})

        # 检查答案完整性
        missing = [k for k in questions if k not in answers]
        if missing:
            raise JevVerificationError(f"Missing answers: {missing}")

        scores = {}
        for name, ans in answers.items():
            ans_type = ans.get("type")
            if ans_type == "refusal":
                raise JevVerificationError(f"Provider refused to answer: {name}")
            if ans_type == "noul":
                prob = ans.get("noul")
                if not isinstance(prob, (int, float)) or not (0.0 <= prob <= 1.0):
                    raise JevVerificationError(
                        f"Invalid probability for {name}: {prob}"
                    )
                scores[name] = float(prob)
            else:
                raise JevVerificationError(f"Unexpected answer type: {ans_type}")

        meta = {
            "id": data.get("id"),
            "model": data.get("model"),
            "provider": data.get("provider"),
            "usage": data.get("usage")
        }
        return scores, meta

    raise JevVerificationUnavailable(
        f"Jev verification failed after {retries} attempts: {last_error}"
    )
