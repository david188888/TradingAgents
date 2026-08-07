"""Evidence gate, company identity, news relevance and rendering.

This module is the public facade for the evidence domain. The implementation
lives in ``evidence_identity`` / ``evidence_news`` / ``evidence_render`` /
``evidence_gate``; new code should import from the domain modules directly.

Two external-library names (``create_llm_from_config``, ``analyze_news_coverage``)
are re-exported here on purpose: tests monkeypatch them via the
``tradingagents.dataflows.evidence.*`` path, and ``evidence_gate`` looks them
up through this facade at call time to preserve that behaviour.
"""

from __future__ import annotations

import requests  # noqa: F401 - exposed so tests can patch evidence.requests.post

from .consistency import create_llm_from_config  # noqa: F401  - monkeypatched via evidence.* path
from .evidence_gate import (  # noqa: F401  - facade re-export
    _CREDIBILITY_WEIGHTS,
    _CROSS_SOURCE_BONUS,
    _LAYER1_DIRECTION_SCORES,
    DEGRADED_DATA_PATTERNS,
    FATAL_DATA_PATTERNS,
    TAVILY_SEARCH_URL,
    EvidenceGateError,
    EvidenceStatus,
    _assert_no_core_data_warnings,
    _assess_news_items,
    _assessment_pass,
    _attach_provenance_artifact_ids,
    _build_enrichment_queries,
    _build_tavily_payload,
    _configured_tavily_keys,
    _credibility_weighted_count,
    _date_window,
    _fail_or_return,
    _items_from_tavily_response,
    _layer1_direction_scores,
    _low_confidence_with_ledger,
    _pass_with_ledger,
    _publisher_from_url,
    _request_tavily_enrichment,
    _run_tavily_enrichment,
    _run_tavily_enrichment_with_queries,
    _save_enrichment_raw_response,
    _with_ledger,
    evaluate_and_enrich_evidence,
)
from .evidence_identity import (  # noqa: F401  - facade re-export
    _A_SHARE_CODE_NAME_CACHE,
    _apply_akshare_profile,
    _apply_eastmoney_profile,
    _apply_yfinance_profile,
    _complete_profile,
    _exchange_name,
    _first_nonempty,
    _lookup_a_share_name_from_code_list,
    resolve_canonical_company_profile,
)
from .evidence_news import (  # noqa: F401  - facade re-export
    OFFICIAL_A_SHARE_DOMAINS,
    WRONG_IDENTITY_HINTS,
    _annotate_entity_roles,
    _dedupe_news_items,
    _explicit_stock_codes,
    _extract_news_items_from_reports,
    _find_wrong_identity_hits,
    _get_wrong_identity_hints,
    _is_company_relevant,
    _is_industry_relevant,
    _is_official_item,
    _is_primary_identity_binding,
    _is_profile_alias,
    _item_text,
    _names_are_related,
    _news_dedupe_key,
    _profile_code_aliases,
    _profile_name_aliases,
    _wrong_names_bound_to_profile_code,
)
from .evidence_render import (  # noqa: F401  - facade re-export
    _format_evidence_news_package,
    _format_evidence_report,
    _format_item,
    format_company_profile,
)
from .news_advisor import analyze_news_coverage  # noqa: F401  - monkeypatched via evidence.* path
