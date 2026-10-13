"""Versioned focus isolation; legacy workflow identities remain unchanged."""

FOCUS_WORKFLOW_VERSION = "evidence-production-v6"
FOCUS_KERNEL_VERSION = "native-research-kernel-v5"
FOCUS_BUDGET_POLICY = {"main_analysis": 5, "focus_response": 1, "model_attempts": 12}

BASE_QUESTIONS = {
    "company_research": "公司经营质量、估值定位与市场风险如何，哪些重要事件和证据可能改变判断，哪些关键问题尚未确定？",
    "catalyst_research": "未来84天哪些催化可能改变判断，经营基础、兑现与失效条件、市场背景和关键缺口是什么？",
    "holding_review": "原持仓假设受到哪些新证据支持或挑战，经营、估值与市场风险如何，哪些条件需要重新核查？",
}

# V7 is opt-in by saved workflow identity. Never redefine V6 constants.
UNIFIED_WORKFLOW_VERSION = "evidence-production-v7"
SPECIALIST_REFERENCE_POLICY = "bounded-repair-then-isolate-v1"
COMPANY_RESEARCH_POLICY = "timestamped-quote-cautious-judgement-v1"
REPORT_DELIVERY_POLICY = "company-basics-local-gaps-delivery-v1"
UNIFIED_KERNEL_VERSION = "native-research-kernel-v6"
UNIFIED_BUDGET_POLICY = {"main_analysis": 8, "focus_response": 1, "model_attempts": 12}
UNIFIED_QUESTION = "截至分析时点，结合公司经营、当前估值、事件与市场风险，这家公司是否具有投资吸引力，为什么，哪些反证和条件会改变判断？"
UNIFIED_DIMENSIONS = ("operating_quality", "valuation", "catalyst_delivery", "market_context")
RESPONSE_ROLES = tuple("response_" + role for role in ("operating_quality", "event_context", "market_context"))

def assessment_dimensions(mode, schema_version=None):
    from tradingagents.agents.schemas._research_assessment import DIMENSIONS_BY_MODE
    return UNIFIED_DIMENSIONS if schema_version == "research-assessment-v3" else DIMENSIONS_BY_MODE[mode]


def validate_assessment_version(record, version):
    """Saved workflow identity chooses its schema; new fields cannot impersonate old runs."""
    unified = version == UNIFIED_WORKFLOW_VERSION
    if unified != (record.assessment.schema_version == "research-assessment-v3"):
        raise ValueError("assessment workflow version mismatch")
    if unified != (record.dialogue is not None):
        raise ValueError("dialogue workflow version mismatch")
