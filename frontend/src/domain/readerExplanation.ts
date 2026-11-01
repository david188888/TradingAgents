import type { AgentKey, ObservedCountDTO, OutputAvailability } from "../api/contracts";
export const AGENT_LABELS: Record<AgentKey, string> = { evidence: "证据冻结", operating_quality: "经营研究", event_context: "事件研究", market_context: "市场研究", challenge: "独立挑战", synthesis: "研究综合", code_checks: "代码核查与发布", response_operating_quality: "经营与估值回应", response_event_context: "事件回应", response_market_context: "市场回应", focus_response: "关注点回应" };
export const STATUS_LABELS: Record<string, string> = { pending: "等待", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断", skipped: "已跳过", not_reached: "未到达", not_recorded: "未记录", not_applicable: "代码工作" };
export function isTerminalRun(status: string): boolean {
  return ["completed", "failed", "cancelled", "interrupted"].includes(status);
}
export function outputLabel(value: OutputAvailability): string {
  return { insight_stage_available: "阶段观点已保存，尚未发布总体判断", available: "已发布，可回顾",
    not_recorded: "本环节未保存可读产物", unavailable: "未通过产物读取校验",
    unsupported: "该产物暂不支持回顾", not_applicable: "不适用" }[value];
}
export function countLabel(count: ObservedCountDTO | null | undefined): string {
  if (!count || count.value === null) return "未记录";
  return count.completeness === "complete" ? `${count.value}` : `至少 ${count.value}（记录不完整）`;
}

export const AGENT_PURPOSE: Record<AgentKey, string> = {
 evidence:"保存符合来源与时间要求的事实。", operating_quality:"依据经营与财务证据提出观点，明确依据和局限。",
 event_context:"研究公告与事件的影响及兑现条件。", market_context:"解释合格行情与市场背景。",
 challenge:"质疑已保存观点，指出证据缺口和替代解释。", synthesis:"权衡已保存观点、质疑和回应，形成总体判断。",
 code_checks:"核对引用、数值和有效版本，保存基础研究。", response_operating_quality:"回应经营与估值观点受到的质疑。",
 response_event_context:"回应事件观点受到的质疑。", response_market_context:"回应市场观点受到的质疑。",
 focus_response:"独立基础研究保存后，依据已有证据回应用户关注点。"
};
