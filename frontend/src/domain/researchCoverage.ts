const CAPABILITIES: Record<string, string> = {
  security_identity: "证券身份", fundamentals: "财务三表", event_coverage: "公告列表",
  valuation: "估值输入", price_history: "历史行情", announcement_bodies: "公告正文", operating_detail: "经营披露明细",
};
const ROLES: Record<string, string> = { operating_quality: "经营专项", event_context: "事件专项", market_context: "市场专项" };
const STATUSES: Record<string, string> = { qualified: "合格资料可用", partial: "部分资料可用", unavailable: "未取得合格资料", coverage_unknown: "覆盖未确定", covered_no_match: "查询完成且无命中", not_applicable: "本次不适用" };
const REASONS: Record<string, string> = {
  document_selected_excerpts_only: "仅取得选中文档的有限摘录，未覆盖全部公告正文",
  document_selected_unavailable: "部分选中文档未能取得合格正文",
  document_budget_exhausted: "文档补充额度已用尽，保留此前合格资料",
  document_no_admitted_candidate: "未取得符合选择条件的文档",
  document_source_disabled: "官方文档来源已禁用",
  document_historical_vintage_unverified: "历史正文版本未经验证",
  document_identity_unqualified: "证券身份未通过资格校验",
  document_catalogue_partial: "经营报告检索目录覆盖不完整",
  operating_detail_not_admitted: "尚未取得合格经营披露明细",
  operating_table_layout_not_admitted: "经营表布局未通过解析校验，原文可能仍可读取",
  dimension_judgement_requires_further_validation: "对应资料可用，判断仍需进一步核查",
  qualified_financial_fields_missing: "未取得合格财务字段",
  qualified_valuation_inputs_missing: "未取得合格估值输入",
  qualified_market_metrics_missing: "未取得合格市场指标",
  native_valuation_policy_v1: "估值参考由代码计算，并保留输入资格与假设限制",
  valuation_identity_or_calendar_missing: "证券身份或对应交易所的日历未通过资格检查",
  valuation_historical_vintage_unverified: "历史估值版本未经验证",
  valuation_snapshot_unavailable: "本次未取得合格估值快照",
  valuation_history_unavailable: "本次未取得合格历史倍数",
  valuation_budget_exhausted: "估值取数额度已用尽，保留已有合格资料",
  qualified_event_evidence_missing: "未取得合格事件证据",
};

export function limitationLabel(value: string): string {
  if (value.startsWith("specialist_unknown:")) {
    const detail = value.slice("specialist_unknown:".length);
    const boundary = detail.indexOf(":");
    const role = boundary >= 0 ? detail.slice(0, boundary) : "";
    return ROLES[role] ? `${ROLES[role]}待核查（仅代表该专项视图）：${detail.slice(boundary + 1)}`
      : `专项待核查（旧记录未保存专项范围，不能认定为全局缺失）：${detail}`;
  }
  const match = /^(global_coverage|global_gap):([^:]+):(.*)$/.exec(value);
  if (match) {
    const [, kind, capability, detail] = match;
    return kind === "global_coverage" ? `全局覆盖 · ${CAPABILITIES[capability] ?? capability}：${STATUSES[detail] ?? detail}`
      : `全局覆盖限制 · ${CAPABILITIES[capability] ?? capability}：${REASONS[detail] ?? `取数或资格受限（${detail}）`}`;
  }
  if (value.startsWith("native_stage_unavailable:")) return `${ROLES[value.split(":")[1]] ?? "研究综合"}未形成合格输出`;
  return REASONS[value] ?? value;
}
