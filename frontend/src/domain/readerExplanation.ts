import type { AgentKey, ObservedCountDTO, OutputAvailability } from "../api/contracts";
export const AGENT_LABELS: Record<AgentKey, string> = { evidence: "证据冻结", operating_quality: "经营研究", event_context: "事件研究", market_context: "市场研究", challenge: "独立挑战", synthesis: "研究综合", code_checks: "代码核查与发布" };
export const DIMENSION_LABELS: Record<string, string> = { operating_quality: "经营质量", valuation: "估值定位", market_context: "市场背景", catalyst_delivery: "催化兑现", holding_thesis: "原持仓假设" };
export const STATUS_LABELS: Record<string, string> = { pending: "等待", running: "执行中", completed: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断", skipped: "已跳过", not_reached: "未到达", not_recorded: "未记录", not_applicable: "代码工作" };
export function outputLabel(value: OutputAvailability, reason: string | null): string {
  if (reason === "publication_pending" && value === "not_recorded") return "等待执行或公开产物发布";
  if (reason === "no_hypotheses_not_called") return "没有待挑战假设，本环节未调用";
  if (reason === "no_qualified_facts_not_called") return "没有本专项的合格输入事实，本环节未调用";
  return { available: "已发布，可回顾", pending_publication: "提议已保存，等待发布校验", not_recorded: "原提议未记录", unavailable: "未通过产物读取校验", unsupported: "历史版本暂不支持回顾", not_applicable: "不适用" }[value];
}
export function countLabel(count: ObservedCountDTO | null | undefined): string {
  if (!count || count.value === null) return "未记录";
  return count.completeness === "complete" ? `${count.value}` : `至少 ${count.value}（记录不完整）`;
}
export const TERMS: Record<string, string> = {
  "合并口径": "把母公司及纳入合并范围的子公司汇总，并抵销集团内部交易。公司总量不能自动说明某一业务的贡献。",
  "归母净利润": "公司净利润中，归属于母公司股东的部分；不同于现金流，也不等于可分配现金。",
  "经营现金流": "主营经营活动收到和付出的现金净额。与利润不同，应结合回款、存货及应付变化核对。",
  "估值锚点": "用于形成价格参考的盈利、净资产等基础和对应倍数。参考区间依赖这些输入与假设。",
  PE: "市盈率：股价相对于每股盈利的倍数。TTM 指最近十二个月；低倍数本身不能证明便宜。",
  PB: "市净率：市值相对于归属于股东的净资产的倍数。资产质量和盈利能力会影响解读。",
  "波动率": "历史价格变动的幅度。年化是统一比较口径，不是对未来波动的保证。",
  "回撤": "从此前高点到后续低点的跌幅。最大回撤描述已观察窗口内的历史损失，不是未来下限。",
  ATR: "平均真实波幅：结合日内高低及跳空的历史价格幅度，通常以每股价格单位表示。",
  "条件核查": "代码只检查指定条件是否满足，不能自动证明整条经济假设或关闭挑战。",
};

export const AGENT_PURPOSE: Record<AgentKey, string> = {
 evidence:"保存符合时间与来源要求的事实，计算固定证据子问题。",operating_quality:"从经营与财务证据提出假设、成立条件和替代解释。",event_context:"判断公告与事件可能带来什么变化，以及兑现条件。",market_context:"解释历史行情和量化背景，提出待核查假设。",challenge:"检查假设的证据缺口、替代解释及可检验条件。",synthesis:"回答研究问题，选择重点依据、主要疑点和下一步。",code_checks:"核对固定证据子问题和可执行条件，约束最终发布范围。"
};

export const AGENT_PRODUCTS: Record<AgentKey, string> = { evidence:"经过来源与时间资格检查的事实、保存来源及固定证据检查。", operating_quality:"经营假设、支撑事实、必要与推翻条件、替代解释及本专项待查项。",event_context:"事件假设、兑现与失效条件、替代解释及本专项待查项。",market_context:"市场假设、成立与失效条件、替代解释及本专项待查项。",challenge:"针对现有假设的挑战、缺口和核查办法；可以合法返回零挑战。",synthesis:"对研究问题的回答、全部维度、重点依据、主要疑点及完整下一步。",code_checks:"固定证据子问题、额外条件验证与最终发布资格。" };
