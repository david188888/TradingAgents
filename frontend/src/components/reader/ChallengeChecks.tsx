import type { ChallengeTestV1DTO, ChallengeVerifiabilityDTO, ResearchRecordV1DTO } from "../../api/contracts";

const CATEGORIES: Record<ChallengeVerifiabilityDTO, string> = {
  computable_now: "当前可计算", computable_unsupported: "当前工具不支持",
  needs_source: "需要补充资料", future_observation: "等待未来观察", not_testable: "尚无可检验定义",
};
const STATES = { not_generated: "未生成任务", completed: "已实际执行", budget_refused: "预算拒绝，未执行",
  cancelled: "执行前取消", unknown: "派发状态未知，未自动重试" };
const REASONS: Record<string, string> = {
  field_not_supported: "当前未支持所需字段", metric_not_supported: "当前未支持所需指标",
  operation_not_supported: "当前未提供所需运算", input_domain_unsupported: "输入不在现有公式的适用范围内",
  no_observable_counterevidence: "尚未提出可观察反证", undefined_measurement: "测量定义不明确",
  predicate_evaluated: "已得出命题结果", tool_failed: "核查工具执行失败",
  source_unqualified: "来源不符合本次研究资格", content_unusable: "保存内容不完整或不可用",
  invalid_fields: "保存字段缺失或不合格", period_unavailable: "未取得所需期次",
  disclosure_unqualified: "披露时点不符合资格", nonpositive_growth_base: "同比基数非正，现有增长公式不适用",
  metric_unqualified: "保存指标不符合核查资格",
};
const FIELDS: Record<string, string> = {
  revenue: "营业收入", n_income: "净利润", n_income_attr_p: "归母净利润", oper_cost: "营业成本",
  sell_exp: "销售费用", admin_exp: "管理费用", rd_exp: "研发费用", fin_exp: "财务费用",
  total_assets: "总资产", total_liab: "总负债", accounts_receiv: "应收账款", accounts_receiv_bill: "应收票据及应收账款",
  inventories: "存货", acct_payable: "应付账款", accounts_pay: "应付票据及应付账款",
  n_cashflow_act: "经营现金流净额", c_pay_acq_const_fiolta: "购建长期资产支付的现金",
};

export function ChallengeCheckSummary({ record, challengeId, test: proposal }: {
  record: ResearchRecordV1DTO; challengeId: string; test?: Partial<ChallengeTestV1DTO>;
}) {
  const challenge = record.challenges.find(c => c.challenge_id === challengeId);
  const test = proposal ?? challenge?.test;
  const outcome = record.challenge_outcomes?.find(o => o.challenge_id === challengeId);
  const result = record.verifications.find(v => v.challenge_id === challengeId && v.scope === "challenge_predicate_only");
  return <section className="qr-method-note" aria-label="假设导向核查去向">
    <p><strong>核查分类：{test?.verifiability ? CATEGORIES[test.verifiability] : record.challenge_check_policy ? "未分类（次要挑战）" : "未知（历史记录未保存）"}</strong></p>
    {test?.observation_date ? <p>后续观察日期：{test.observation_date}</p> : null}
    {test?.reason_code ? <p>{REASONS[test.reason_code]}</p> : null}
    {test?.required_inputs?.map((input, index) => {
      const saved = outcome?.inputs.find(i => i.input_index === index);
      const label = input.kind === "financial" ? `${FIELDS[input.field] ?? input.field}（${input.report_period}，合并报表人民币口径）`
        : input.kind === "metric" ? `保存指标：${input.metric_id}` : input.description;
      return <p key={index}>所需输入：{label}{saved ? ` · ${saved.availability === "available" ? "已保存" : saved.availability === "availability_unknown" ? "模型提出的资料需求，代码未确认可用性" : saved.availability === "missing" ? "未保存" : "保存输入不符合所需资格"}` : " · 尚未保存可用性核对"}</p>;
    })}
    {outcome ? <p>任务去向：{STATES[outcome.state]}</p> : test?.verifiability ? <p>任务去向尚未保存，不能视为已执行。</p> : null}
    {result ? <>
      <p>独立核查命题：{result.condition_text}</p>
      <p>命题结果：{result.predicate_met === true ? "满足" : result.predicate_met === false ? "不满足" : "无法得出结果"} · {REASONS[result.result_reason ?? ""] ?? "结果原因未记录"}</p>
      {result.value !== null && result.value !== undefined ? <p>保存的计算值：{result.value} {test?.check?.predicate.unit}</p> : null}
    </> : null}
    {test?.verifiability ? <p className="qr-meta">分类由模型提出，代码核对结构与数据边界。独立命题的结果不证明整条经济假设，也不自动消除风险。</p> : null}
    {outcome?.task_id ? <details><summary>任务绑定与执行时间</summary><p>{outcome.task_id}</p><p>计划校验：{outcome.plan_sha256}</p><p>执行时间：{result?.executed_at ?? "没有已保存的实际执行时间"}</p></details> : null}
  </section>;
}
