"""Human-readable F03 classifications and task states from saved records only."""

from tradingagents.agents.schemas._verification_plan import BASELINE_LABELS, DETAIL_LABELS

CATEGORIES = {
    "computable_now": "当前可计算", "computable_unsupported": "当前工具不支持",
    "needs_source": "需要补充资料", "future_observation": "等待未来观察", "not_testable": "尚无可检验定义",
}
STATES = {"not_generated": "未生成任务", "completed": "已实际执行", "budget_refused": "预算拒绝，未执行",
          "cancelled": "执行前取消", "unknown": "派发状态未知，未自动重试"}
REASONS = {"field_not_supported": "当前未支持所需字段", "metric_not_supported": "当前未支持所需指标",
           "operation_not_supported": "当前未提供所需运算", "input_domain_unsupported": "输入不在现有公式适用范围内",
           "no_observable_counterevidence": "尚未提出可观察反证", "undefined_measurement": "测量定义不明确"}


def challenge_check_lines(record, challenge, text):
    test = challenge.test
    if test is None or test.verifiability is None:
        return ["  核查分类：" + ("未分类（次要挑战）。" if record.challenge_check_policy else "未知（历史记录未保存）。")]
    lines = ["  核查分类（模型提出）：" + CATEGORIES[test.verifiability] + "。"]
    outcome = next((o for o in record.challenge_outcomes or () if o.challenge_id == challenge.challenge_id), None)
    if test.observation_date:
        lines.append("  后续观察日期：" + test.observation_date.isoformat() + "。")
    if test.reason_code:
        lines.append("  原因：" + REASONS[test.reason_code] + "。")
    labels = {**BASELINE_LABELS, **DETAIL_LABELS}
    for index, requirement in enumerate(test.required_inputs):
        label = (f"{labels.get(requirement.field, requirement.field)}（{requirement.report_period}，合并报表人民币口径）"
                 if requirement.kind == "financial" else requirement.metric_id if requirement.kind == "metric"
                 else requirement.description)
        availability = next((i for i in outcome.inputs if i.input_index == index), None) if outcome else None
        status = {"available": "已保存", "missing": "未保存", "unqualified": "不符合所需资格",
                  "availability_unknown": "模型提出的资料需求，代码未确认可用性"}.get(
                      availability.availability if availability else "", "可用性尚未记录")
        lines.append(f"  所需输入：{text(label)}；{status}。")
    lines.append("  任务去向：" + (STATES[outcome.state] if outcome else "尚未保存，不视为已执行") + "。")
    if outcome and outcome.task_id:
        lines.append(f"  任务：{text(outcome.task_id)}；计划校验：{outcome.plan_sha256}。")
    lines.append("  独立命题的结果不证明整条经济假设，也不自动消除风险。")
    return lines
