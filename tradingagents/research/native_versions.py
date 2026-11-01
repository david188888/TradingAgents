"""Frozen current research workflow and source policy identities."""

COMPANY_RESEARCH_POLICY = "timestamped-quote-cautious-judgement-v1"

REPORT_DELIVERY_POLICY = "company-basics-local-gaps-delivery-v1"

STRUCTURED_FINANCIAL_POLICY = "structured-financial-checks-v1"

FINANCIAL_DETAIL_POLICY = "financial-detail-fields-v1"

INSIGHT_WORKFLOW_VERSION = 'evidence-production-v9'

INSIGHT_POLICY = 'insight-first-v1'

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
    'calculation': 'recovered-field-arithmetic-v1', 'record': 'evidence-record-v1',
}
