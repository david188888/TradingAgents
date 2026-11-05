"""Audit Center renders host-routed capability batches from the research journal."""

from tradingagents.web.audit_models import AuditSummaryDTO
from tradingagents.web.audit_projection import _capability_summaries


class _Snapshot:
    degraded_data_sources = ()


def _checkpoint():
    return {"results": {
        "capability.batch.admitted01": {
            "admitted": {"observations": [
                {"source": {"source_name": "cninfo.announcements"}},
                {"source": {"source_name": "eastmoney.insider_trades"}},
            ]},
            "gaps": ["capability_use_search_path:news_search"],
            "executed": ["disclosure_search"],
            "rejected": ["capability_request_truncated"],
        },
        "capability.batch.empty0002": {
            "admitted": {"observations": []},
            "gaps": ["capability_empty:disclosure_search"],
            "executed": ["disclosure_search"],
            "rejected": [],
        },
        "capability.batch.budget003": {
            "admitted": {"observations": []},
            "gaps": ["capability_budget_exhausted"],
            "executed": [],
            "rejected": [],
        },
        "capability.batch.failed0004": {
            "admitted": {"observations": []},
            "gaps": ["capability_unavailable:valuation_history:baostock"],
            "executed": [],
            "rejected": [],
        },
        "unrelated.result": {"ignored": True},
    }}


def test_capability_batches_render_admitted_empty_budget_and_failure_states():
    recorded = _capability_summaries(_Snapshot(), [], _checkpoint())
    by_id = {item.capability_result_id: item for item in recorded}
    admitted = by_id["capability.batch.admitted01"]
    assert admitted.status == "completed" and admitted.availability == "available"
    assert admitted.providers == ("cninfo", "eastmoney")
    assert "capability_use_search_path:news_search" in admitted.reason_codes

    statuses = sorted({item.status for item in recorded})
    assert statuses == ["completed", "degraded", "failed", "not_reached"]
    assert all("unrelated.result" not in (item.capability_result_id or "") for item in recorded)


def test_journal_capability_items_validate_through_the_summary_contract():
    snapshot = _Snapshot()
    summary = AuditSummaryDTO.model_validate({
        "run_id": "run_x", "source_sequence": 1, "availability": "ready",
        "run": {"status": "completed", "ticker": "002130.SZ", "mode": "company_research",
                "created_at": "2026-11-05T00:00:00Z", "completed_at": "2026-11-05T00:10:00Z",
                "duration_ms": 600000, "llm_provider": "deepseek",
                "quick_think_llm": "deepseek-flash", "deep_think_llm": "deepseek-flash",
                "data_quality": "healthy"},
        "counts": {"stages": 0, "roles": 0, "turns": None, "model_calls": None,
                   "native_counts": None, "tool_calls": 0, "artifacts": 0,
                   "prompts": 0, "configs": 0, "reports": 0},
        "sections": [{"section_id": section, "availability": "ready", "reason_code": None, "item_count": 1}
                     for section in ("overview", "roles", "capabilities", "tools", "artifacts", "prompt_config")],
        "stage_navigation": [],
        "roles": [],
        "capabilities": [item.model_dump(mode="json") for item in _capability_summaries(snapshot, [], _checkpoint())],
        "tools": [],
        "artifacts": [],
        "prompts": [],
        "configs": [],
    })
    assert len(summary.capabilities) == 4
