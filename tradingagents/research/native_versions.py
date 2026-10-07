"""Versioned focus isolation; legacy workflow identities remain unchanged."""

FOCUS_WORKFLOW_VERSION = "evidence-production-v6"
FOCUS_KERNEL_VERSION = "native-research-kernel-v5"
FOCUS_BUDGET_POLICY = {"main_analysis": 5, "focus_response": 1, "model_attempts": 12}

BASE_QUESTIONS = {
    "company_research": "公司经营质量、估值定位与市场风险如何，哪些重要事件和证据可能改变判断，哪些关键问题尚未确定？",
    "catalyst_research": "未来84天哪些催化可能改变判断，经营基础、兑现与失效条件、市场背景和关键缺口是什么？",
    "holding_review": "原持仓假设受到哪些新证据支持或挑战，经营、估值与市场风险如何，哪些条件需要重新核查？",
}
