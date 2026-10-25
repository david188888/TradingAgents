import type { RunSnapshotDTO, RunViewEnvelopeDTO } from "../api/contracts";

export function runSnapshot(run_id: string, status: RunSnapshotDTO["status"] = "running"): RunSnapshotDTO {
  return {
    run_id, status, ticker: "600803.SS", asset_type: "stock", analysis_date: "2026-10-25",
    selected_analysts: ["market"], max_debate_rounds: 1, max_risk_discuss_rounds: 1,
    output_language: "Chinese", llm_provider: "deepseek", quick_think_llm: "fast", deep_think_llm: "deep",
    configured_keys: {}, created_at: "2026-10-25T00:00:00Z", updated_at: "2026-10-25T00:00:00Z",
    latest_sequence: 0, artifacts: [], redaction_manifest: [], event_schema_version: 1, metadata: {},
  };
}

export function runView(run_id: string, pending = false): RunViewEnvelopeDTO {
  return {
    schema_version: 1, projection_status: "ready", reason_code: null, source_sequence: 0, terminal: true,
    view: {
      run: { run_id, ticker: "600803.SS", status: "interrupted", mode: "company_research", horizon: "medium",
        created_at: "2026-10-25T00:00:00Z", completed_at: null, latest_sequence: 0, final_signal: null,
        error_category: null, error_message: null, duration_ms: null, data_quality_level: "unknown" },
      brief: { availability: "unavailable", reason_code: "not_published", value: null },
      workflow: { total_roles: 0, completed_roles: 0, active_actor_id: null, stages: [] },
      debate_journey: { stages: [], research_rating: null, disagreement_count: 0,
        risk_consensus: { conviction: null, disagreement: "", abstained_roles: [] } },
      debate_summary: { availability: pending ? "pending" : "unavailable", reason_code: null, value: null },
      section_index: [], data_quality: { level: "unknown", degraded_capabilities: [], unavailable_capabilities: [], conflicts: [], checks: [] },
      available_audit_counts: { turns: 0, prompts: 0, tool_calls: 0, data_calls: 0, artifacts: 0, reports: 0 }, legacy_fallback: null,
    },
  };
}
