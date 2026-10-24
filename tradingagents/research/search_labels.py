"""Reader/report labels for closed search state, without transport diagnostics."""

STOP_LABELS = {
    'search_disabled': '本次研究已关闭联网搜索，未解决问题保留待查',
    'no_eligible_gaps': '没有需要继续搜索的明确缺口',
    'no_qualified_delta': '本轮未取得新的合格材料，停止补搜',
    'round_limit_reached': '已达到三轮补搜上限，剩余问题保留待查',
    'round_budget_exhausted': '补搜轮次额度已用完',
    'search_budget_or_time_exhausted': '搜索次数或活动时间已用完，剩余问题保留待查',
}
ROLE_LABELS = {'operating_quality': '经营研究', 'event_context': '事件研究', 'market_context': '市场研究'}
DISPOSITION_LABELS = {'maintained': '维持原有条件判断', 'revised': '修正原推断',
                      'withdrawn': '撤回原推断', 'unanswerable': '现有材料仍无法回答'}


def stop_label(reason):
    if reason.startswith('review_unavailable:'):
        return ROLE_LABELS.get(reason.split(':', 1)[1], '相关专项')+'未完成有效复核，保留待查'
    return STOP_LABELS.get(reason, '搜索已停止，未解决问题保留待查')
