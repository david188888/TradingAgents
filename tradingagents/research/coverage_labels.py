"""Display labels preserve the scope of persisted coverage and unknowns."""

CAPABILITY_LABELS = {
    "security_identity": "证券身份", "fundamentals": "财务三表", "event_coverage": "公告列表",
    "valuation": "估值输入", "price_history": "历史行情", "announcement_bodies": "公告正文", "operating_detail": "经营披露明细",
    "dated_forecasts": "有日期的机构预测", "peer_context": "行业候选估值背景",
}
ROLE_LABELS = {"operating_quality": "经营专项", "event_context": "事件专项", "market_context": "市场专项"}
STATUS_LABELS = {"qualified": "合格资料可用", "partial": "部分资料可用", "unavailable": "未取得合格资料",
                 "coverage_unknown": "覆盖未确定", "covered_no_match": "查询完成且无命中", "not_applicable": "本次不适用"}
REASON_LABELS = {
    "selected_disclosure_coverage_not_complete_business_verification": "已核对选取披露；仍需判断经营兑现和披露覆盖限制",
    "single_disclosure_family_no_supplier_crosscheck": "当前依据来自同一公司披露，尚无供应商同口径核对",
    "reported_accounting_bridge_not_economic_causation": "现金流桥解释报表调整，不证明经济原因",
    "two_periods_not_structural_persistence": "两个报告期不足以判断变化是否持续",
    "blank_cells_remain_undisclosed": "原表空白项保留为未披露，未补零",
    "supplementary_positioning_not_fair_value_proof": "同行和预测只补充估值背景，不能证明合理价值",
    "industry_candidates_not_business_equivalence": "同行由行业候选选取，业务模式可能不同",
    "selected_peers_not_full_industry_population": "选取同行样本未覆盖全部行业公司",
    "sample_not_complete_population_or_consensus": "样本未覆盖全行业或完整机构一致预期",
    "sample_not_complete_consensus": "机构样本不代表完整一致预期",
    "sampled_institution_forecasts_not_complete_consensus": "仅保存选取的有日期机构预测，非完整一致预期",
    "economic_parent_remains_unresolved": "经济原因、持续性及整体判断仍待核查",
    "economic_question_exceeds_closed_check_scope": "经济问题超出本次证据检查范围",
    "peers_fewer_than_three": "同日合格同行不足三家",
    "dated_institution_forecast_unavailable": "尚无合格的有日期机构预测",
    "historical_positioning_can_still_be_described": "仍可按合格历史数据描述历史定位",
    "qualified_target_snapshot": "当前证券估值快照未通过资格校验",
    "official_current_period": "未取得合格的当前报告期披露",
    "quantitative_operating_disclosure": "尚无合格的定量运营披露",
    "complete_reconciled_cash_bridge": "尚无完整且核对通过的现金流桥",
    "forecast_budget_exhausted": "预测取数额度已用尽，保留已有资料",
    "peer_budget_exhausted": "同行取数额度已用尽，保留已有资料",
    "forecast_identity_or_vintage_unqualified": "预测证券身份或历史版本未通过资格校验",
    "peer_identity_calendar_or_vintage_unqualified": "同行身份、交易日或历史版本未通过资格校验",
    "peer_quotes_unavailable": "尚无合格的同行报价",
    "official_numeric_layout_not_admitted": "原表布局未通过数字解析，仍可核对保存原文",
    "document_selected_excerpts_only": "仅取得选中文档的有限摘录，未覆盖全部公告正文",
    "document_selected_unavailable": "部分选中文档未能取得合格正文",
    "document_budget_exhausted": "文档补充额度已用尽，保留此前合格资料",
    "document_no_admitted_candidate": "未取得符合选择条件的文档",
    "document_source_disabled": "官方文档来源已禁用",
    "document_historical_vintage_unverified": "历史正文版本未经验证",
    "document_identity_unqualified": "证券身份未通过资格校验",
    "document_catalogue_partial": "经营报告检索目录覆盖不完整",
    "operating_detail_not_admitted": "尚未取得合格经营披露明细",
    "operating_table_layout_not_admitted": "经营表布局未通过解析校验，原文可能仍可读取",
    "dimension_judgement_requires_further_validation": "对应资料可用，判断仍需进一步核查",
    "qualified_financial_fields_missing": "未取得合格财务字段",
    "company-basics-local-gaps-delivery-v1": "基础资料与有效专项持续交付，具体缺口限制对应章节",
    "host_retained_findings_not_synthesis": "保留已保存事实或有效专项观点；综合阶段尚未完成",
    "profile_historical_vintage_unverified": "未取得研究截点对应的公司介绍版本",
    "profile_identity_or_source_unavailable": "公司介绍的证券身份或来源未取得",
    "profile_budget_exhausted": "公司介绍取数额度已用尽，保留其他已有资料",
    "timestamped-quote-cautious-judgement-v1": "使用带时间标记的行情；估值缺口限制估值项，整体判断仍需合格经营依据",
    "valuation_unsettled_session_snapshot": "使用采集时刻的当日行情，尚非已结算交易日收盘价",
    "valuation_history_precedes_quote": "历史倍数截至前一已结算交易日，当前行情保留自身日期",
    "qualified_valuation_inputs_missing": "未取得合格估值输入",
    "qualified_market_metrics_missing": "未取得合格市场指标",
    "valuation_identity_or_calendar_missing": "证券身份或对应交易所的日历未通过资格检查",
    "valuation_identity_calendar_or_vintage_unqualified": "证券身份、交易日或历史版本未通过资格检查",
    "valuation_identity_unavailable": "证券身份未通过资格校验，未取得估值输入",
    "valuation_calendar_unavailable": "对应交易所的交易日历未通过资格检查，未取得估值输入",
    "valuation_historical_vintage_unverified": "历史估值版本未经验证",
    "valuation_snapshot_unavailable": "本次未取得合格估值快照",
    "valuation_history_unavailable": "本次未取得合格历史倍数",
    "valuation_budget_exhausted": "估值取数额度已用尽，保留已有合格资料",
    "peer_identity_unavailable": "证券身份未通过资格校验，未取得同行估值背景",
    "peer_calendar_unavailable": "对应交易所的交易日历未通过资格检查，未取得同行估值背景",
    "peer_historical_vintage_unverified": "历史同行版本未经验证",
    "valuation_quote_not_last_settled_session": "行情快照不是最后一个已结算交易日，未作为估值输入",
    "qualified_event_evidence_missing": "未取得合格事件证据",
    "native_valuation_policy_v1": "估值参考由代码计算，并保留输入资格与假设限制",
}


def limitation_label(value):
    fields = {"revenue": "营业收入", "parent_net_income": "归母净利润", "consolidated_net_income": "合并净利润", "cfo": "经营现金流"}
    prefix, _, detail = value.partition(":")
    field = fields.get(detail.split(":")[0], detail)
    labels = {"official_pair": "未取得当前及上年同期间官方数字：", "official_financial_conflict": "官方披露数字冲突：",
        "supplier_financial_discrepancy": "供应商与官方披露口径核对不一致：", "cash_bridge_required_cells_or_duplicates": "现金流桥缺少必要数字或存在重复项；文档：",
        "cash_bridge_reconciliation": "现金流桥组件与合计不一致：", "cash_bridge_endpoint_discrepancy": "现金流桥端点与财务报表不一致：",
        "forecast_source_no_admitted_rows": "该来源未取得合格的有日期预测："}
    if prefix in labels:
        return labels[prefix]+field
    if value.startswith("specialist_unknown:"):
        detail = value.removeprefix("specialist_unknown:")
        role, _, message = detail.partition(":")
        if role in ROLE_LABELS:
            return ROLE_LABELS[role]+"待核查（仅代表该专项视图）："+message
        return "专项待核查（旧记录未保存专项范围，不能认定为全局缺失）："+detail
    if value.startswith("global_coverage:"):
        _, capability, status = value.split(":", 2)
        return "全局覆盖 · "+CAPABILITY_LABELS.get(capability, capability)+"："+STATUS_LABELS.get(status, status)
    if value.startswith("global_gap:"):
        _, capability, reason = value.split(":", 2)
        return "全局覆盖限制 · "+CAPABILITY_LABELS.get(capability, capability)+"："+REASON_LABELS.get(reason, "取数或资格受限（"+reason+"）")
    if value.startswith("native_stage_unavailable:"):
        return ROLE_LABELS.get(value.split(":")[1], "研究综合")+"未形成合格输出"
    if value.startswith("native_hypothesis_rejected:"):
        # One proposal cited outside its own view and was dropped on its own;
        # the rest of the run is unaffected, so the label says so.
        _, _, detail = value.partition(":")
        role, _, reason = detail.partition(":")
        _code, _, index = reason.partition(":")
        rejected = {"specialist_fact_reference": "引用了本专项视图之外的事实",
                    "condition_evidence_reference": "条件引用了该假设之外的证据",
                    "condition_metric_reference": "条件指标的来源不属于该假设"}
        position = "第"+str(int(index)+1)+"条" if index.isdigit() else "有"
        return ROLE_LABELS.get(role, role)+"："+position+"假设未通过引用校验已剔除（"+rejected.get(_code, _code)+"）"
    return REASON_LABELS.get(value, value)
