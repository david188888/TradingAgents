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
NUMERIC_NARRATIVE_POLICY = "anchored-narrative-v1"
STRUCTURED_FINANCIAL_POLICY = "structured-financial-checks-v1"
FINANCIAL_DETAIL_POLICY = "financial-detail-fields-v1"
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
    unified = version in {UNIFIED_WORKFLOW_VERSION, SEARCH_WORKFLOW_VERSION}
    if (version == SEARCH_WORKFLOW_VERSION) != (record.schema_version == 'research-record-v2'):
        raise ValueError('record workflow version mismatch')
    if unified != (record.assessment.schema_version == "research-assessment-v3"):
        raise ValueError("assessment workflow version mismatch")
    if unified != (record.dialogue is not None):
        raise ValueError("dialogue workflow version mismatch")

# V8 remains separately dispatched; saved V7 identities never change.
SEARCH_WORKFLOW_VERSION = 'evidence-production-v8'
SEARCH_KERNEL_VERSION = 'native-research-kernel-v7'
CHALLENGE_INPUT_POLICY = 'search-trace-summary-v1'
SEARCH_GAP_GUIDANCE_POLICY = 'supplied-gap-targets-v1'
MODEL_BINDING_POLICY = 'inline-bindings-v1'
RESEARCH_DELIVERY_POLICY = {
    'version': 'evidence-packets-v1',
    'repair_limits': {'structured_repair': 8, 'basic_model_attempts': 20, 'model_attempts': 29},
    'challenge_reviews': 'hypothesis-review-coverage-v1',
    'explanations': 'batched-explanations-v1',
}
SEARCH_RESEARCH_POLICY = {
    'version': 'dual-search-research-v1',
    'enabled': True,
    'endpoints': {'deepseek_search': 'https://api.deepseek.com/v1/tools/search',
        'deepseek_fetch': 'https://api.deepseek.com/v1/tools/fetch',
        'tavily_search': 'https://api.tavily.com/search', 'tavily_extract': 'https://api.tavily.com/extract'},
    'query_policy': 'identity-cutoff-preserving-v1', 'initial_topics': ['news', 'industry_policy', 'competitors'],
    'queries_per_gap_per_provider': 2, 'gaps_per_round': 3, 'count': 8,
    'deepseek_query_limit': 128, 'tavily_query_limit': 400, 'tavily_depth': 'basic',
    'source_admission': 'saved-original-cutoff-v1', 'field_recovery': 'exact-original-field-v1',
    'calculation': 'recovered-field-arithmetic-v1', 'record': 'research-record-v2',
}
