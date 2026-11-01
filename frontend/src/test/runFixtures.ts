import type { RunSnapshotDTO } from "../api/contracts";

export function runSnapshot(run_id: string, status: RunSnapshotDTO["status"] = "running"): RunSnapshotDTO {
  return {
    run_id, status, ticker: "600803.SS", asset_type: "stock", analysis_date: "2026-10-25",

    output_language: "Chinese", llm_provider: "deepseek", quick_think_llm: "fast", deep_think_llm: "deep",
    configured_keys: {}, created_at: "2026-10-25T00:00:00Z", updated_at: "2026-10-25T00:00:00Z",
    latest_sequence: 0, artifacts: [], redaction_manifest: [], event_schema_version: 1, metadata: {},
  };
}
