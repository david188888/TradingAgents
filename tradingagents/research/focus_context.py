"""Canonical input binding for the optional focus interpretation."""

from tradingagents.agents.schemas._verification_plan import canonical_sha256

FOCUS_REASON_LABELS = {
    "base_synthesis_unavailable": "基础综合未形成有效提议，跳过补充回应。",
    "budget_exhausted": "剩余调用额度不足，未执行补充回应。",
    "deadline_exceeded": "剩余时间不足，补充回应未完成。",
    "response_unknown": "先前调用的结果未完整保存，未重复发出。",
    "model_failed": "补充回应调用失败。",
    "invalid_response": "补充回应未通过结构或证据引用校验。",
    "publication_failed": "补充回应未能发布。",
}


def focus_context(record, focus, output_language):
    return {"record": record.model_dump(mode="json"), "focus": focus,
            "base_record_sha256": canonical_sha256(record), "output_language": output_language,
            "instruction": "仅依据保存研究补充回应。不得修改基础结论、关键依据、挑战或质量，不得把用户提问当作事实。"}


def focus_identity(context, model_policy_sha256):
    return {"context_sha256": canonical_sha256(context), "schema_version": "focus-proposal-v1",
            "model_policy_sha256": model_policy_sha256}
