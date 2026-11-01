/**
 * F2 — normalized reducer State types for a single TradingAgents run, plus the
 * V9 role registry. DESIGN ONLY: types + the registry array, no reducer logic.
 *
 * Field names are snake_case-matched to the backend wire format; the reducer
 * must not rename keys when projecting events into this state.
 */

import type { ArtifactMetadataDTO, AssetTypeLiteral, DegradedSourceSummaryDTO, ObservationCommitV1DTO, ObservationTaskKind, ResearchProfile } from "../api/contracts";

// ---------------------------------------------------------------------------
// Role status
// ---------------------------------------------------------------------------

export type RoleStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "skipped"
  | "not_reached";

// ---------------------------------------------------------------------------
// Turn
// ---------------------------------------------------------------------------

export type TurnStatus =
  | "started"
  | "output_ready"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "resumed";

export interface Turn {
  turn_id: string;
  role_instance_id: string;
  actor_id: string;
  /** Graph task that produced this turn, used to distinguish candidate output from applied output. */
  graph_task_id?: string;
  turn_index: number;
  status: TurnStatus;
  /** artifact_id emitted by turn.output_ready, if produced. */
  artifact_id?: string;
  /** child model_call_ids seen for this turn (across attempts). */
  model_call_ids: string[];
  /** child logical tool_call_ids initiated this turn. */
  tool_call_ids: string[];
  /** child vendor_call_ids observed via data.* events this turn. */
  vendor_call_ids: string[];
  reason?: string;
  duration_ms?: number;
  resumed_from_sequence?: number;
}

// ---------------------------------------------------------------------------
// Model call
// ---------------------------------------------------------------------------

export interface ModelCall {
  model_call_id: string;
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  provider: string;
  model: string;
  invocation_path: string;
  status: "started" | "completed" | "failed";
  duration_ms?: number;
  usage?: Record<string, unknown>;
  /** prompt-snapshot artifact_ids linked via input.prompt_snapshot. */
  prompt_artifact_ids: string[];
}

// ---------------------------------------------------------------------------
// Tool calls — logical + executions
// ---------------------------------------------------------------------------

export type ToolExecutionStatus = "started" | "completed" | "failed";

export interface ToolExecution {
  tool_execution_id: string;
  status: ToolExecutionStatus;
}

export type LogicalToolCallStatus =
  | "requested"
  | "running"
  | "committed"
  | "cancelled"
  | "failed";

export interface LogicalToolCall {
  tool_call_id: string;
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  tool_name: string;
  arguments?: Record<string, unknown>;
  status: LogicalToolCallStatus;
  executions: ToolExecution[];
  /** checkpoint_event_id once tool.committed observed. */
  checkpoint_event_id?: string;
  reason?: string;
}

// ---------------------------------------------------------------------------
// Vendor call provenance
// ---------------------------------------------------------------------------

export type DataStatus = string;

export interface VendorCall {
  vendor_call_id: string;
  turn_id: string;
  graph_task_id: string;
  method: string;
  vendor: string;
  stage: string;
  data_status: DataStatus;
  status: "progress" | "completed" | "failed" | "interrupted";
  duration_ms?: number;
  /** Stable backend reason category; detailed transport text stays local-only. */
  failure_code?: string;
  fallback_chain?: string[];
  /** cache_hit_ids that referenced this vendor call. */
  cache_hit_ids: string[];
}

// ---------------------------------------------------------------------------
// Artifacts + reports
// ---------------------------------------------------------------------------

export interface ArtifactRecord extends ArtifactMetadataDTO {
  /** sequence of the artifact.written event that introduced it. */
  written_sequence: number;
  /** input.* capture kinds that reference this artifact, if any. */
  input_capture_kinds: string[];
  /** turn_id from the input.* event that linked this artifact (G3 join key). */
  turn_id?: string;
  /** attempt_id from input.prompt_snapshot, if this is a prompt artifact. */
  attempt_id?: string;
  /** model_call_id from input.prompt_snapshot, if this is a prompt artifact. */
  model_call_id?: string;
}

export type ReportKind = string;

export interface Report {
  turn_id: string;
  report_kind: ReportKind;
  revision: number;
  artifact_id: string;
}

// ---------------------------------------------------------------------------
// Run meta + application status
// ---------------------------------------------------------------------------

/**
 * Application status derived from the join of:
 *   - run candidate events (run.*)
 *   - committed checkpoint events (graph.checkpoint_committed)
 *   - pending-apply observation commits (graph.task_output_ready not yet step_applied)
 *   - abandoned tasks (graph.task_abandoned)
 * Lowercased to mirror backend run status literals where they overlap.
 */
export type ApplicationStatus =
  | "created"
  | "queued"
  | "running"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "resuming"
  | "abandoned";

export interface RunMeta {
  native_workflow_version?: string;
  focus_requested?: boolean;
  research_profile?: ResearchProfile;

  run_id: string;
  status: ApplicationStatus;
  ticker: string;
  asset_type: AssetTypeLiteral;
  analysis_date: string;
  output_language: string;
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  configured_keys: Record<string, boolean>;
  created_at: string;
  updated_at: string;
  latest_sequence: number;
  final_signal?: string | null;
  final_report_artifact_id?: string | null;
  completed_at?: string | null;
  /** Canonical report locator when a V9 report has been published. */
  degraded_data_sources?: DegradedSourceSummaryDTO[];
  summary?: string | null;
  error_category?: string | null;
  error_message?: string | null;
  retry_of?: string | null;
  resumed_from_sequence?: number | null;



  redaction_manifest: string[];
  event_schema_version: number;
}

// ---------------------------------------------------------------------------
// Per-run reducer state
// ---------------------------------------------------------------------------

export interface RoleCard {
  actor_id: string;
  node_id: string;
  team_id: string;
  status: RoleStatus;
  /** role_instance_id = `${run_id}:${actor_id}`. */
  role_instance_id?: string;
  /** debate/research round currently active for this role, if any. */
  current_round?: number;
  /** latest turn_id emitted for this role instance. */
  latest_turn_id?: string;
  /** latest graph_task_id seen via turn.* / graph.task_* for this role. */
  latest_graph_task_id?: string;
  previous_status?: RoleStatus;
  reason?: string;
}

export interface GraphTaskRecord {
  graph_task_id: string;
  graph_step: number;
  node_id: string;
  task_kind?: ObservationTaskKind;
  status: "started" | "output_ready" | "abandoned";
  observation_commit?: ObservationCommitV1DTO;
  business_delta_artifact_id?: string;
  /** true once graph.step_applied applied this task id. */
  applied: boolean;
  /** checkpoint_id once graph.checkpoint_committed included this task. */
  checkpoint_id?: string;
  reason?: string;
}

export interface ReducerState {
  meta: RunMeta;
  roles: Record<string, RoleCard>;
  turns: Record<string, Turn>;
  model_calls: Record<string, ModelCall>;
  tool_calls: Record<string, LogicalToolCall>;
  vendor_calls: Record<string, VendorCall>;
  artifacts: Record<string, ArtifactRecord>;
  reports: Report[];
  /** ordered graph tasks keyed by graph_task_id. */
  graph_tasks: Record<string, GraphTaskRecord>;
  /** latest stats.updated payload, if any. */
  latest_stats?: {
    turn_id?: string;
    model_call_id?: string;
    [key: string]: unknown;
  };
  /** highest applied graph_step so far. */
  latest_graph_step: number;
  /** last seen checkpoint_id from graph.checkpoint_committed. */
  latest_checkpoint_id?: string;
}

// ---------------------------------------------------------------------------
// V9 role registry — mirrors tradingagents/observability/roles.py exactly.
// icon_id values are opaque string ids; G1 wires them to SVG path bundles.
// ---------------------------------------------------------------------------

export interface RoleDefinition {
  actor_id: string;
  node_id: string;
  team_id: string;
  display_name: string;
  icon_id: string;
}

/** Mirrors the V9 execution order in observability/roles.py. */
const ROLE_REGISTRY: readonly RoleDefinition[] = [
  ["evidence", "Evidence freeze"],
  ["operating_quality", "Operating quality"],
  ["event_context", "Event context"],
  ["market_context", "Market context"],
  ["challenge", "Evidence challenge"],
  ["response_operating_quality", "Operating reply"],
  ["response_event_context", "Event reply"],
  ["response_market_context", "Market reply"],
  ["synthesis", "Research synthesis"],
].map(([key, label]) => ({ actor_id: `native.${key}`, node_id: key, team_id: "native", display_name: label, icon_id: "verified-magnifier" }));
const FOCUS_ROLE: RoleDefinition = {actor_id:"native.focus_response",node_id:"focus_response",team_id:"native",display_name:"Focus response",icon_id:"verified-magnifier"};

export function rolesForRun(focusRequested=false): readonly RoleDefinition[] {
  return focusRequested ? [...ROLE_REGISTRY, FOCUS_ROLE] : ROLE_REGISTRY;
}
