"""Read-only current Insight stage material and budget observations."""
from dataclasses import dataclass
from typing import Any

from tradingagents.research.insight_report import parse_insight_report
from tradingagents.runtime.research_checkpoint import load_checkpoint
from tradingagents.web.reader_process_models import (
    AgentKey,
    NativeCounts,
    ObservedCount,
    ReaderAgentDTO,
    ReaderProcessDTO,
)
from tradingagents.web.research_record_projection import project_research_record

ROLE_INFO = {
    "evidence": (
        "证据冻结",
        "保存符合时间与来源要求的事实，计算固定证据子问题。",
        "公开资料、来源时间和保存内容；由代码整理，不调用研究模型。",
    ),
    "operating_quality": (
        "经营研究",
        "从经营与财务证据提出假设、成立条件和替代解释。",
        "冻结证据中的经营、财务及合格估值事实；只读取本专项允许的资料。",
    ),
    "event_context": (
        "事件研究",
        "判断公告与事件可能带来什么变化，以及兑现条件。",
        "冻结证据中的公告与事件事实；未在本专项看到不代表全局缺失。",
    ),
    "market_context": (
        "市场研究",
        "解释历史行情和量化背景，提出待核查假设。",
        "合格行情事实及代码计算的历史指标；价格联动不能证明业务联系。",
    ),
    "challenge": (
        "独立挑战",
        "检查假设的证据缺口、替代解释及可检验条件。",
        "保存的假设、支撑事实及条件；不提供专项作者身份。",
    ),
    "synthesis": (
        "研究综合",
        "回答研究问题，选择重点依据、主要疑点和下一步。",
        "事实、假设、挑战和已执行核查结果；最终发布受代码规则约束。",
    ),
    "code_checks": (
        "代码核查与发布",
        "核对固定证据子问题和可执行条件，约束最终发布范围。",
        "已保存事实、固定检查与条件验证；不额外创建一个 Agent。",
    ),
    "focus_response": ("关注点回应", "在独立研究保存之后，依据已有证据补充回应用户关注点。",
                       "已保存的基础研究与用户关注点；不参与基础专项、挑战或综合。"),
}
for _key in ("response_operating_quality", "response_event_context", "response_market_context"):
    ROLE_INFO[_key] = ({"response_operating_quality": "经营与估值回应", "response_event_context": "事件回应", "response_market_context": "市场回应"}[_key],
        "逐条回应独立挑战，修正或撤回观点并保留未知项。", "自己的冻结事实、定向挑战和已保存核查；只回应一次。")


def count(value=None, *, complete="not_recorded", basis="not_recorded"):
    return ObservedCount(value=value, completeness=complete, basis=basis)


def native_counts(checkpoint, *, role=None):
    records = [r for r in checkpoint.get("records", ()) if r.get("dispatched_at") is not None] if checkpoint else []
    scoped = [r for r in records if role is None or r.get("stage") == "native." + role]
    def budget(bucket, rows=scoped):
        return count(sum(r["bucket"] == bucket for r in rows), complete="complete" if checkpoint else "not_recorded",
            basis="budget_dispatch_authorization")
    # Each Insight transport has one durable dispatch authorization; no SDK retries.
    def sdk(buckets):
        return count(sum(r["bucket"] in buckets for r in scoped),
            complete="complete" if checkpoint else "not_recorded", basis="sdk_dispatch_authorization")
    return NativeCounts(main_budget=budget("main_analysis"), repair_budget=budget("structured_repair"),
        sdk_main=sdk({"main_analysis", "search_review"}), sdk_repair=sdk({"structured_repair"}),
        sdk_total=sdk({"main_analysis", "search_review", "structured_repair", "focus_response"}),
        data_capability=budget("data_capability_calls", records), data_http=budget("data_http_attempts", records),
        focus_budget=budget("focus_response"), sdk_focus=sdk({"focus_response"}))


@dataclass
class Context:
    snapshot: Any
    sequence: int
    events: list
    checkpoint: dict | None
    record: Any
    reason: str | None = None


def _context(store, run_id, through=None):
    snapshot = store.read_snapshot(run_id)
    sequence = snapshot.latest_sequence if through is None else through
    if not 0 <= sequence <= snapshot.latest_sequence:
        raise ValueError("reader_sequence_unavailable")
    events = store.read_events(run_id, through=sequence)
    if snapshot.metadata.get("native_workflow_version") != "evidence-production-v9":
        return Context(snapshot, sequence, events, None, None, "unsupported_version")
    try:
        cp = load_checkpoint(store, run_id, through=sequence)
        if cp is None:
            return Context(snapshot, sequence, events, None, None, "checkpoint_not_recorded")
        identity = cp["identity"]
        if (identity.get("workflow_version"), identity.get("ticker"), identity.get("mode"), identity.get("cutoff")) != (
                "evidence-production-v9", snapshot.ticker, "company_research", snapshot.analysis_date):
            raise ValueError("checkpoint_identity")
        public = project_research_record(store, run_id, through=sequence)
        record = parse_insight_report(public["record"]) if public["state"] == "insight_ready" else None
        return Context(snapshot, sequence, events, cp, record)
    except (ValueError, KeyError, TypeError, OSError):
        return Context(snapshot, sequence, events, None, None, "checkpoint_unavailable")


def project_reader_process(store, run_id):
    from tradingagents.web.insight_process import insight_process
    ctx = _context(store, run_id)
    if ctx.reason:
        return ReaderProcessDTO(run_id=run_id, source_sequence=ctx.sequence, profile="evidence_v1",
            workflow_version="evidence-production-v9", availability="unavailable", reason_code=ctx.reason,
            counts=native_counts(None)).model_dump(mode="json")
    return insight_process(ctx).model_dump(mode="json")


def project_reader_agent(store, run_id, role: AgentKey, *, through=None):
    from tradingagents.web.insight_process import insight_agent
    ctx = _context(store, run_id, through)
    if ctx.reason:
        return ReaderAgentDTO(run_id=run_id, source_sequence=ctx.sequence, role_key=role,
            availability="unavailable", reason_code=ctx.reason, origin="code" if role in {"evidence", "code_checks"} else "model",
            input_description="已保存的研究输出。").model_dump(mode="json")
    return insight_agent(ctx, role).model_dump(mode="json")
