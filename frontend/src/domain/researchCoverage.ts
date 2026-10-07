const CAPABILITIES: Record<string, string> = {
  security_identity: "证券身份", fundamentals: "财务三表", event_coverage: "公告列表",
  valuation: "估值输入", price_history: "历史行情", announcement_bodies: "公告正文", operating_detail: "经营披露明细",
  dated_forecasts: "有日期的机构预测", peer_context: "行业候选估值背景",
};
const ROLES: Record<string, string> = { operating_quality: "经营专项", event_context: "事件专项", market_context: "市场专项" };
const STATUSES: Record<string, string> = { qualified: "合格资料可用", partial: "部分资料可用", unavailable: "未取得合格资料", coverage_unknown: "覆盖未确定", covered_no_match: "查询完成且无命中", not_applicable: "本次不适用" };
const REASONS: Record<string, string> = {
  source_fields_are_not_full_document_text: "这些是已保存的数据字段，不是公告全文。",
  selected_disclosure_coverage_not_complete_business_verification: "已核对选取披露；仍需判断经营兑现和披露覆盖限制",
  single_disclosure_family_no_supplier_crosscheck: "当前依据来自同一公司披露，尚无供应商同口径核对",
  reported_accounting_bridge_not_economic_causation: "现金流桥解释报表调整，不证明经济原因",
  two_periods_not_structural_persistence: "两个报告期不足以判断变化是否持续",
  blank_cells_remain_undisclosed: "原表空白项保留为未披露，未补零",
  supplementary_positioning_not_fair_value_proof: "同行和预测只补充估值背景，不能证明合理价值",
  industry_candidates_not_business_equivalence: "同行由行业候选选取，业务模式可能不同",
  selected_peers_not_full_industry_population: "选取同行样本未覆盖全部行业公司",
  sample_not_complete_population_or_consensus: "样本未覆盖全行业或完整机构一致预期",
  sample_not_complete_consensus: "机构样本不代表完整一致预期",
  sampled_institution_forecasts_not_complete_consensus: "仅保存选取的有日期机构预测，非完整一致预期",
  economic_parent_remains_unresolved: "经济原因、持续性及整体判断仍待核查",
  economic_question_exceeds_closed_check_scope: "经济问题超出本次证据检查范围",
  peers_fewer_than_three: "同日合格同行不足三家",
  dated_institution_forecast_unavailable: "尚无合格的有日期机构预测",
  historical_positioning_can_still_be_described: "仍可按合格历史数据描述历史定位",
  qualified_target_snapshot: "当前证券估值快照未通过资格校验",
  official_current_period: "未取得合格的当前报告期披露",
  quantitative_operating_disclosure: "尚无合格的定量运营披露",
  complete_reconciled_cash_bridge: "尚无完整且核对通过的现金流桥",
  forecast_budget_exhausted: "预测取数额度已用尽，保留已有资料",
  peer_budget_exhausted: "同行取数额度已用尽，保留已有资料",
  forecast_identity_or_vintage_unqualified: "预测证券身份或历史版本未通过资格校验",
  peer_identity_calendar_or_vintage_unqualified: "同行身份、交易日或历史版本未通过资格校验",
  peer_quotes_unavailable: "尚无合格的同行报价",
  official_numeric_layout_not_admitted: "原表布局未通过数字解析，仍可核对保存原文",
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
  const [prefix, detail = ""] = value.split(/:(.*)/s);
  const fields: Record<string, string> = { revenue: "营业收入", parent_net_income: "归母净利润", consolidated_net_income: "合并净利润", cfo: "经营现金流" };
  const local: Record<string, string> = { official_pair: "未取得当前及上年同期间官方数字：", official_financial_conflict: "官方披露数字冲突：",
    supplier_financial_discrepancy: "供应商与官方披露口径核对不一致：", cash_bridge_required_cells_or_duplicates: "现金流桥缺少必要数字或存在重复项；文档：",
    cash_bridge_reconciliation: "现金流桥组件与合计不一致：", cash_bridge_endpoint_discrepancy: "现金流桥端点与财务报表不一致：",
    forecast_source_no_admitted_rows: "该来源未取得合格的有日期预测：" };
  if (local[prefix]) return local[prefix] + (fields[detail.split(":")[0]] ?? detail);
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
