/**
 * F2 — TradingAgents frontend/backend wire contracts.
 *
 * Single source of truth: backend Python
 *   tradingagents/observability/events.py
 *   tradingagents/observability/roles.py
 *   tradingagents/web/run_models.py
 *   tradingagents/web/schemas.py
 *   tradingagents/web/api.py
 *
 * Field names are snake_case-matched to the backend wire format. The reducer
 * MUST NOT rename keys. `any` is only used where the backend emits an opaque
 * blob that the frontend never interprets (explicitly justified inline).
 */

// ---------------------------------------------------------------------------
// Transport constants
// ---------------------------------------------------------------------------

/** Same-origin: the SPA is served by the FastAPI app itself. */
export const SERVER_HTTP_BASE = "";

export const API = {
  config: "/api/config",
  runs: "/api/runs",
  run: (run_id: string) => `/api/runs/${run_id}`,
  runView: (run_id: string) => `/api/runs/${run_id}/view`,
  reader: (run_id: string) => `/api/runs/${run_id}/reader`,
  readerCompanion: (run_id: string) => `/api/runs/${run_id}/reader/companion`,
  audit: (run_id: string) => `/api/runs/${run_id}/audit`,
  auditDetail: (run_id: string) => `/api/runs/${run_id}/audit/detail`,
  cancel: (run_id: string) => `/api/runs/${run_id}/cancel`,
  retry: (run_id: string) => `/api/runs/${run_id}/retry`,
  resume: (run_id: string) => `/api/runs/${run_id}/resume`,
  artifacts: (run_id: string) => `/api/runs/${run_id}/artifacts`,
  artifact: (run_id: string, artifact_id: string) =>
    `/api/runs/${run_id}/artifacts/${artifact_id}`,
  /** Read-only projection of already persisted OHLCV/news artifacts. */
  marketView: (run_id: string, sequence?: number) =>
    `/api/runs/${run_id}/market-view${sequence != null ? `?v=${sequence}` : ""}`,
  /** Read-only lookup of a public cached Layer 2 review for a captured marker. */
  marketEventLayer2: (run_id: string, event: Pick<MarketEventDTO, "artifact_id" | "timestamp" | "title">) =>
    `/api/runs/${run_id}/market-view/layer2?${new URLSearchParams({
      artifact_id: event.artifact_id,
      timestamp: event.timestamp,
      title: event.title,
    }).toString()}`,
  events: (run_id: string, after?: number) =>
    `/api/runs/${run_id}/events${after != null ? `?after=${after}` : ""}`,
  recentRuns: (limit = 20, cursor?: string) =>
    `/api/runs?${new URLSearchParams({
      view: "recent",
      limit: String(limit),
      ...(cursor ? { cursor } : {}),
    }).toString()}`,
} as const;

export const EVENT_SCHEMA_VERSION = 1 as const;

/** SSE terminal events — the stream is closed by the server after these. */
export const TERMINAL_STREAM_EVENTS = [
  "run.completed",
  "run.failed",
  "run.cancelled",
  "run.interrupted",
] as const;

export type TerminalStreamEventType = (typeof TERMINAL_STREAM_EVENTS)[number];

// ---------------------------------------------------------------------------
// /api/config
// ---------------------------------------------------------------------------

export interface ModelOptionDTO {
  label: string;
  id: string;
}

export interface ProviderModelOptionsDTO {
  quick: ModelOptionDTO[];
  deep: ModelOptionDTO[];
}

export interface ProviderDTO {
  id: string;
  configured: boolean;
  requires_api_key: boolean;
  models: ProviderModelOptionsDTO;
  custom_model_allowed: boolean;
}

export interface AnalystOptionDTO {
  id: string;
}

/** A safe YAML v1 preset: it only enables and orders existing analyst roles. */
export interface AnalystPresetDTO {
  id: string;
  label: string;
  analysts: string[];
}

export interface ConfigDefaultsDTO {
  llm_provider: string | null;
  quick_think_llm: string | null;
  deep_think_llm: string | null;
  output_language: string;
  research_depth: number;
  checkpoint_enabled: boolean;
}

export interface WindStatusDTO {
  enabled: boolean;
  configured: boolean;
  capabilities: string[];
}

export interface ConfigResponseDTO {
  providers: ProviderDTO[];
  configured_keys: Record<string, boolean>;
  analysts: AnalystOptionDTO[];
  presets: AnalystPresetDTO[];
  depths: number[];
  output_languages: string[];
  checkpoint_available: boolean;
  wind: WindStatusDTO;
  defaults: ConfigDefaultsDTO;
}

// ---------------------------------------------------------------------------
// Run create request (RunCreateRequest — pydantic, extra="forbid")
// ---------------------------------------------------------------------------

export type ResearchDepth = 1 | 3 | 5;
export type AssetTypeLiteral = "stock" | "crypto";
export type ResearchMode = "company_research" | "holding_review";
export type ResearchHorizon = "short" | "medium" | "long";

/** Minimal, user-provided facts for a learning-oriented holding review. */
export interface HoldingInputDTO {
  ticker: string;
  quantity: number;
  average_cost: number;
  cash?: number;
  total_account_value?: number;
  currency?: string;
  facts_as_of?: string;
  original_thesis?: string;
}

export interface PortfolioPositionDTO {
  ticker: string;
  quantity: number;
  average_cost: number;
  sellable_quantity: number | null;
}

export interface PortfolioLimitsDTO {
  max_position_weight: number;
  lot_size: number;
  fee_rate: number;
  minimum_fee: number;
  allow_short: boolean;
}

/** Optional non-secret inputs for deterministic PM execution constraints. */
export interface PortfolioDTO {
  cash: number;
  positions: PortfolioPositionDTO[];
  mark_prices: Record<string, number>;
  currency: string;
  limits: PortfolioLimitsDTO;
}

export interface RunCreateRequestDTO {
  ticker: string;
  analysis_date: string;
  selected_analysts: string[];
  research_depth: ResearchDepth;
  mode?: ResearchMode;
  horizon?: ResearchHorizon;
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  output_language: string;
  checkpoint_enabled: boolean;
  /** Null means "let the server derive from normalized ticker". */
  asset_type: AssetTypeLiteral | null;
  holding?: HoldingInputDTO;
  /** Legacy-only input. New clients must use holding instead. */
  portfolio?: PortfolioDTO | null;
}

// ---------------------------------------------------------------------------
// Run snapshot + summary + artifact metadata (run_models.py / schemas.py)
// ---------------------------------------------------------------------------

export type RunStatusLiteral =
  | "created"
  | "running"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface RunSnapshotDTO {
  run_id: string;
  status: RunStatusLiteral;
  ticker: string;
  asset_type: AssetTypeLiteral;
  analysis_date: string;
  selected_analysts: string[];
  max_debate_rounds: number;
  max_risk_discuss_rounds: number;
  output_language: string;
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  configured_keys: Record<string, boolean>;
  created_at: string;
  updated_at: string;
  /** Explicit for new snapshots; absent only on legacy snapshots. */
  mode?: ResearchMode | null;
  horizon?: ResearchHorizon | null;
  holding_context?: HoldingInputDTO & { source: "user_provided" | "legacy_portfolio" } | null;
  latest_sequence: number;
  final_signal?: string | null;
  /** Explicit for new completed runs; absent only on legacy snapshots. */
  final_report_artifact_id?: string | null;
  /** Terminal run.completed event time for new completed runs. */
  completed_at?: string | null;
  /** P0 preserves the contract shape; P2 populates normalized entries. */
  degraded_data_sources?: DegradedSourceSummaryDTO[];
  summary?: string | null;
  error_category?: string | null;
  error_message?: string | null;
  retry_of?: string | null;
  resumed_from_sequence?: number | null;
  /** Opaque resume-fingerprint blob the frontend never interprets. */
  resume_fingerprint?: Record<string, unknown> | null;
  runtime_semantics_hash?: string | null;
  agent_state_schema_sha256?: string | null;
  artifacts: string[];
  redaction_manifest: string[];
  event_schema_version: number;
  /** Opaque server-defined metadata bag. */
  metadata: Record<string, unknown>;
}

export interface DegradedSourceSummaryDTO {
  capability: string;
  status: "degraded" | "unavailable";
  attempted_vendors: string[];
  selected_vendors: string[];
  reasons: Array<{ vendor: string; code: string }>;
  affected_sections: string[];
}

export interface RunSummaryDTO {
  run_id: string;
  status: RunStatusLiteral;
  ticker: string;
  analysis_date: string;
  asset_type: string;
  created_at: string;
  updated_at: string;
  latest_sequence: number;
  final_signal?: string | null;
  summary?: string | null;
  error_category?: string | null;
}

export interface ArtifactMetadataDTO {
  artifact_id: string;
  kind: string;
  media_type: string;
  content_sha256: string;
  byte_size: number;
  locator: string;
}

export type DataQualityLevelDTO = "healthy" | "limited" | "conflicted" | "unknown";
export type BriefAvailabilityDTO = "full" | "partial" | "unavailable";

export interface DataQualityDTO {
  level: DataQualityLevelDTO;
  degraded_capabilities: string[];
  unavailable_capabilities: string[];
  conflicts: Array<{ severity: "medium" | "high" | "critical"; message_code: string }>;
  checks: Array<{ check: string; status: string; reason_code: string | null }>;
}

export interface PublicClaimDTO {
  claim_id: string;
  text: string;
  evidence_ref_ids: string[];
}

export interface ReaderBriefDTO {
  schema_version: number;
  run_id: string;
  ticker: string;
  source_sequence: number;
  generated_at: string;
  availability: BriefAvailabilityDTO;
  omissions: string[];
  research_rating: string | null;
  execution: {
    availability: "ready" | "unavailable";
    requested_action: string | null;
    requested_quantity: number | null;
    effective_action: string | null;
    effective_quantity: number | null;
    reason_code: string | null;
  };
  executive_summary: PublicClaimDTO | null;
  price_target: number | null;
  time_horizon: string | null;
  drivers: Array<PublicClaimDTO & { direction: "positive" | "negative" | "risk"; importance: number }>;
  risks: PublicClaimDTO[];
  catalysts: PublicClaimDTO[];
  invalidation_conditions: PublicClaimDTO[];
  analyst_cards: Array<{ lens: string; conviction: number | null; confidence: number; abstain: boolean; findings: PublicClaimDTO[] }>;
  debate_digest: { agreed_facts: PublicClaimDTO[]; key_disagreements: PublicClaimDTO[]; changed_views: PublicClaimDTO[]; remaining_uncertainties: PublicClaimDTO[] };
  risk_consensus: { conviction: number | null; disagreement: string; abstained_roles: string[] };
  data_quality: DataQualityDTO;
  evidence_refs: Array<{ ref_id: string; label: string; resolution_status: "available" | "target_missing" }>;
  holding_review?: {
    original_thesis: { status: string; text?: string; reason_code?: string };
    concentration: { status: string; reason_code?: string; weight?: number; position_market_value?: number; total_account_value?: number };
    unrealized_pnl: { status: string; reason_code?: string; amount?: number; return_ratio?: number; cost_basis?: number; market_value?: number };
    scenario_sensitivity: { status: string; reason_code?: string; market_price?: number; value_change_per_price_unit?: number; cost_gap_per_unit?: number };
  } | null;
  /** Validated learning synthesis. Evidence references remain explicitly unavailable until ResearchCase v2. */
  learning_summary?: {
    research_tilt: "favorable" | "neutral" | "cautious" | "insufficient_evidence";
    confidence: number;
    facts: string[];
    inferences: string[];
    unknowns: string[];
    upside: { title: string; condition: string; implication: string };
    base: { title: string; condition: string; implication: string };
    downside: { title: string; condition: string; implication: string };
    catalysts: string[];
    invalidation_conditions: string[];
    next_review: string;
    holding_thesis_assessment?: {
      status: "supported" | "challenged" | "not_assessable";
      rationale: string;
      current_research_hypothesis: string;
    } | null;
  } | null;
}

export interface WorkflowProjectionDTO {
  total_roles: number;
  completed_roles: number;
  active_actor_id: string | null;
  stages: Array<{ stage_id: string; status: string; actors: Array<{ actor_id: string; status: string; latest_turn_id: string | null; completed_turns: number }> }>;
}

export type JourneyStageId = "analysts" | "evidence" | "research" | "trading" | "risk" | "portfolio";
export type JourneyStageStatus = "waiting" | "running" | "completed" | "failed" | "cancelled" | "interrupted" | "skipped";

export interface DebateJourneyDTO {
  stages: Array<{ stage_id: JourneyStageId; status: JourneyStageStatus; rounds: number | null }>;
  research_rating: string | null;
  disagreement_count: number;
  risk_consensus: {
    conviction: number | null;
    disagreement: string;
    abstained_roles: string[];
  };
}

export interface ResearchRoundSummaryDTO {
  round_index: number;
  topic: string;
  summary: string;
  keywords: string[];
  bull_summary: string;
  bear_summary: string;
  bull_estimated_conviction: number | null;
  bear_estimated_conviction: number | null;
  /** Lane -> output artifact_id for L3 full-text loading (deterministic, not LLM). */
  sources?: Partial<Record<"bull" | "bear", string>>;
}

export interface RiskRoundSummaryDTO {
  round_index: number;
  topic: string;
  summary: string;
  keywords: string[];
  aggressive_summary: string;
  neutral_summary: string;
  conservative_summary: string;
  sources?: Partial<Record<"aggressive" | "neutral" | "conservative", string>>;
}

export interface DebateSummaryValueDTO {
  schema_version: 1;
  run_id: string;
  generated_at: string;
  model: string;
  global_summary: string;
  research_debate: ResearchRoundSummaryDTO[];
  risk_debate: RiskRoundSummaryDTO[];
}

export interface DebateSummaryEnvelopeDTO {
  availability: "ready" | "pending" | "unavailable";
  reason_code: string | null;
  value: DebateSummaryValueDTO | null;
}

export interface RunViewEnvelopeDTO {
  schema_version: number;
  projection_status: "ready" | "partial" | "legacy_fallback" | "unavailable";
  reason_code: string | null;
  source_sequence: number;
  terminal: boolean;
  view: {
    run: {
      run_id: string;
      ticker: string;
      status: RunStatusLiteral;
      mode: ResearchMode;
      horizon: ResearchHorizon;
      created_at: string;
      completed_at: string | null;
      latest_sequence: number;
      final_signal: string | null;
      error_category: string | null;
      error_message: string | null;
      duration_ms: number | null;
      data_quality_level: DataQualityLevelDTO;
    };
    brief: { availability: BriefAvailabilityDTO; reason_code: string | null; value: ReaderBriefDTO | null };
    workflow: WorkflowProjectionDTO;
    debate_journey: DebateJourneyDTO;
    debate_summary: DebateSummaryEnvelopeDTO;
    section_index: Array<{ section_id: string; label: string; availability: string; artifact_ids: string[]; turn_ids: string[] }>;
    data_quality: DataQualityDTO;
    market_projection_version: number;
    available_audit_counts: { turns: number; prompts: number; tool_calls: number; data_calls: number; artifacts: number; reports: number };
    legacy_fallback: { final_signal: string | null; portfolio_artifact_id: string | null; complete_report_artifact_id: string | null } | null;
  };
}

export interface RecentRunsPageDTO {
  schema_version: number;
  items: Array<{
    run_id: string;
    ticker: string;
    status: RunStatusLiteral;
    created_at: string;
    completed_at: string | null;
    latest_sequence: number;
    final_signal: string | null;
    error_category: string | null;
    duration_ms: number | null;
    data_quality_level: DataQualityLevelDTO;
  }>;
  next_cursor: string | null;
}

// ---------------------------------------------------------------------------
// Read-only market visualisation projection (/api/runs/{run_id}/market-view)
// ---------------------------------------------------------------------------

/** A validated OHLCV record captured during the run; never a synthetic quote. */
export interface MarketBarDTO {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  artifact_id: string;
}

/** A dated research/news record captured during the run. */
export interface MarketEventDTO {
  timestamp: string;
  title: string;
  artifact_id: string;
  url?: string;
  source?: string;
  sentiment?: string;
  score?: number;
}

export interface MarketViewCoverageDTO {
  bar_source_artifact_ids: string[];
  event_source_artifact_ids: string[];
  skipped_artifact_count: number;
  as_of_sequence: number;
}

/** The endpoint only reads existing artifacts and can validly return no bars. */
export interface MarketViewDTO {
  bars: MarketBarDTO[];
  events: MarketEventDTO[];
  coverage: MarketViewCoverageDTO;
}

/** Only the public fields that the durable Layer 2 cache permits. */
export interface Layer2ConclusionDTO {
  conclusion: string;
  evidence_gaps: string[];
  material_risks: string[];
  source_ids: string[];
}

export interface MarketEventLayer2DTO {
  /** A miss is normal: the chart must not start a vendor/model call. */
  status: "cached" | "not_available";
  event: Pick<MarketEventDTO, "artifact_id" | "timestamp" | "title">;
  trigger: { reasons: string[]; cache_key: string };
  cache_configured: boolean;
  conclusion?: Layer2ConclusionDTO;
}

// ---------------------------------------------------------------------------
// Error shapes (api.py boundary + schemas.py)
// ---------------------------------------------------------------------------

export interface ApiErrorDetail {
  code: string;
  message: string;
  fields: string[];
  active_run_id?: string;
}

export interface ApiErrorResponse {
  detail: ApiErrorDetail;
}

// ---------------------------------------------------------------------------
// Shared dataclasses (events.py)
// ---------------------------------------------------------------------------

/** Mirror of dataclass ArtifactRef (frozen, validated). */
export interface ArtifactRefDTO {
  artifact_id: string;
  kind: string;
  media_type: string;
  content_sha256: string;
  byte_size: number;
  locator: string;
}

export type ObservationTaskKind = "input" | "role" | "tool" | "maintenance";

/** Mirror of dataclass ObservationCommitV1. node_id/turn_id nullable; tool_call_ids ordered+unique. */
export interface ObservationCommitV1DTO {
  serializer_version: number;
  projection_version: number;
  agent_state_schema_sha256: string;
  task_kind: ObservationTaskKind;
  graph_task_id: string;
  graph_step: number;
  business_delta_sha256: string;
  node_id?: string | null;
  turn_id?: string | null;
  tool_call_ids: string[];
}

// ---------------------------------------------------------------------------
// Event payload variants — one per event type in required_payload_fields().
// Required fields are required keys; optionals are marked with `?`.
// ---------------------------------------------------------------------------

// --- run.* -----------------------------------------------------------------

export interface RunStartedPayload {
  run_status: RunStatusLiteral;
}

/** run.cancel_requested is a non-terminal intermediate state (only run_status). */
export interface RunCancelRequestedPayload {
  run_status: "cancel_requested";
}

export interface RunTerminalPayload {
  run_status: RunStatusLiteral;
  summary?: string | null;
  final_signal?: string | null;
  final_report_artifact_id?: string | null;
  completed_at?: string | null;
  degraded_data_sources?: DegradedSourceSummaryDTO[];
}

export interface RunInterruptedPayload {
  run_status: "interrupted";
  checkpoint_sequence: number;
  summary?: string | null;
}

export interface RunResumedPayload {
  run_status: "running";
  checkpoint_sequence: number;
}

// --- graph.* ---------------------------------------------------------------

export interface GraphTaskStartedPayload {
  graph_task_id: string;
  graph_step: number;
  node_id: string;
}

export interface GraphTaskAbandonedPayload {
  graph_task_id: string;
  graph_step: number;
  node_id: string;
  reason: string;
}

export interface GraphTaskOutputReadyPayload {
  observation_commit: ObservationCommitV1DTO;
  graph_step: number;
  node_id: string;
  business_delta_artifact_id: string;
  media_type: string;
  content_sha256: string;
}

export interface GraphStepAppliedPayload {
  graph_step: number;
  applied_task_ids: string[];
  state_sha256: string;
  next_nodes: string[];
}

export interface GraphCheckpointCommittedPayload {
  graph_step: number;
  applied_task_ids: string[];
  state_sha256: string;
  next_nodes: string[];
  checkpoint_id: string;
}

// --- role.* ----------------------------------------------------------------

export interface RoleStatusChangedPayload {
  role_instance_id: string;
  previous_status: string;
  new_status: string;
  reason: string;
}

// --- agent.* / state.* / report.* ------------------------------------------

export interface AgentMessagePayload {
  turn_id: string;
  graph_task_id: string;
  message_id: string;
  message_kind: string;
}

export interface StateUpdatedPayload {
  turn_id: string;
  changed_keys: string[];
}

export interface ReportUpdatedPayload {
  turn_id: string;
  report_kind: string;
  revision: number;
  artifact_id: string;
}

/**
 * stats.updated has no required keys per required_payload_fields(), but the
 * backend validator requires turn_id OR model_call_id to be present.
 */
export interface StatsUpdatedPayload {
  turn_id?: string;
  model_call_id?: string;
  [key: string]: unknown;
}

// --- turn.* ----------------------------------------------------------------

export interface TurnStartedPayload {
  role_instance_id: string;
  turn_id: string;
  graph_task_id: string;
  graph_step: number;
  turn_index: number;
  turn_status: "started";
}

export interface TurnOutputReadyPayload {
  role_instance_id: string;
  turn_id: string;
  graph_task_id: string;
  graph_step: number;
  turn_index: number;
  turn_status: "output_ready";
  artifact_id: string;
}

export interface TurnEndedPayload {
  role_instance_id: string;
  turn_id: string;
  graph_task_id: string;
  graph_step: number;
  turn_index: number;
  turn_status: "completed" | "failed" | "cancelled" | "interrupted";
  reason: string;
  duration_ms: number;
}

export interface TurnResumedPayload {
  role_instance_id: string;
  turn_id: string;
  graph_task_id: string;
  graph_step: number;
  turn_index: number;
  turn_status: "resumed";
  resumed_from_sequence: number;
}

// --- model.* ---------------------------------------------------------------

export interface ModelUsageDTO {
  /** Opaque token-usage shape; backend-defined. */
  [key: string]: unknown;
}

export interface ModelStartedPayload {
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  model_call_id: string;
  provider: string;
  model: string;
  invocation_path: string;
}

export interface ModelEndedPayload {
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  model_call_id: string;
  provider: string;
  model: string;
  invocation_path: string;
  duration_ms: number;
  usage: ModelUsageDTO;
}

// --- input.* ---------------------------------------------------------------

export type InputCaptureKind = "state_snapshot" | "config_snapshot" | "prompt_snapshot" | "data_snapshot";

export interface InputSnapshotPayloadBase {
  turn_id: string;
  graph_task_id: string;
  capture_kind: InputCaptureKind;
  artifact_id: string;
  content_sha256: string;
  redaction_manifest: string[];
}

export interface InputStateSnapshotPayload extends InputSnapshotPayloadBase {
  capture_kind: "state_snapshot";
}

export interface InputConfigSnapshotPayload extends InputSnapshotPayloadBase {
  capture_kind: "config_snapshot";
}

export interface InputPromptSnapshotPayload extends InputSnapshotPayloadBase {
  capture_kind: "prompt_snapshot";
  attempt_id: string;
  model_call_id: string;
}

export interface InputDataSnapshotPayload extends InputSnapshotPayloadBase {
  capture_kind: "data_snapshot";
}

// --- tool.* ----------------------------------------------------------------

export interface ToolRequestedPayload {
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ToolExecutionPayloadBase {
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  tool_call_id: string;
  tool_name: string;
  tool_execution_id: string;
}

export interface ToolExecutionStartedPayload extends ToolExecutionPayloadBase {}

export interface ToolExecutionCompletedPayload extends ToolExecutionPayloadBase {}

export interface ToolExecutionFailedPayload extends ToolExecutionPayloadBase {}

export interface ToolCommittedPayload {
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  tool_call_id: string;
  tool_name: string;
  checkpoint_event_id: string;
}

export interface ToolCancelledPayload {
  turn_id: string;
  graph_task_id: string;
  attempt_id: string;
  tool_call_id: string;
  tool_name: string;
  reason: string;
}

export interface ToolCrossTickerQueryPayload {
  turn_id: string;
  graph_task_id: string;
  tool_call_id: string;
  tool_name: string;
  requested_ticker: string;
  target_ticker: string;
}

// --- data.* ----------------------------------------------------------------

export interface DataCallPayloadBase {
  turn_id: string;
  graph_task_id: string;
  vendor_call_id: string;
  method: string;
  vendor: string;
  stage: string;
  data_status: string;
  /** Stable non-secret category for failed vendor calls. */
  failure_code?: string;
  fallback_chain?: string[];
}

export interface DataProgressPayload extends DataCallPayloadBase {}

export interface DataCompletedPayload extends DataCallPayloadBase {
  duration_ms: number;
}

export interface DataFailedPayload extends DataCallPayloadBase {
  duration_ms: number;
}

export interface DataInterruptedPayload extends DataCallPayloadBase {
  duration_ms: number;
}

export interface DataCacheHitPayload {
  turn_id: string;
  graph_task_id: string;
  cache_hit_id: string;
  cache_key_sha256: string;
  origin_vendor_call_ids: string[];
  origin_artifacts: ArtifactRefDTO[];
  age_ms: number;
}

// --- artifact.* ------------------------------------------------------------

export interface ArtifactWrittenPayload {
  artifact_id: string;
  kind: string;
  media_type: string;
  content_sha256: string;
  byte_size: number;
  locator: string;
}

// ---------------------------------------------------------------------------
// Discriminated payload union.
//
// Per F2 spec §9.5, event types not enumerated here (future, server-introduced
// types) MUST be ignored by the reducer and never throw. Consumers should
// narrow via the `type` discriminant and fall through for unknown variants.
// ---------------------------------------------------------------------------

/**
 * Union of every event payload the TradingAgents backend can emit today,
 * keyed by the envelope `type`. Unknown future event types are ignored per
 * spec §9.5 — see `UnknownEventType` at the bottom of this section.
 */
export type EventPayloadByType =
  | { type: "run.started"; payload: RunStartedPayload }
  | { type: "run.cancel_requested"; payload: RunCancelRequestedPayload }
  | { type: "run.completed"; payload: RunTerminalPayload }
  | { type: "run.failed"; payload: RunTerminalPayload }
  | { type: "run.cancelled"; payload: RunTerminalPayload }
  | { type: "run.interrupted"; payload: RunInterruptedPayload }
  | { type: "run.resumed"; payload: RunResumedPayload }
  | { type: "graph.task_started"; payload: GraphTaskStartedPayload }
  | { type: "graph.task_abandoned"; payload: GraphTaskAbandonedPayload }
  | { type: "graph.task_output_ready"; payload: GraphTaskOutputReadyPayload }
  | { type: "graph.step_applied"; payload: GraphStepAppliedPayload }
  | { type: "graph.checkpoint_committed"; payload: GraphCheckpointCommittedPayload }
  | { type: "role.status_changed"; payload: RoleStatusChangedPayload }
  | { type: "agent.message"; payload: AgentMessagePayload }
  | { type: "state.updated"; payload: StateUpdatedPayload }
  | { type: "report.updated"; payload: ReportUpdatedPayload }
  | { type: "stats.updated"; payload: StatsUpdatedPayload }
  | { type: "turn.started"; payload: TurnStartedPayload }
  | { type: "turn.output_ready"; payload: TurnOutputReadyPayload }
  | { type: "turn.completed"; payload: TurnEndedPayload }
  | { type: "turn.failed"; payload: TurnEndedPayload }
  | { type: "turn.cancelled"; payload: TurnEndedPayload }
  | { type: "turn.interrupted"; payload: TurnEndedPayload }
  | { type: "turn.resumed"; payload: TurnResumedPayload }
  | { type: "model.started"; payload: ModelStartedPayload }
  | { type: "model.completed"; payload: ModelEndedPayload }
  | { type: "model.failed"; payload: ModelEndedPayload }
  | { type: "input.state_snapshot"; payload: InputStateSnapshotPayload }
  | { type: "input.config_snapshot"; payload: InputConfigSnapshotPayload }
  | { type: "input.prompt_snapshot"; payload: InputPromptSnapshotPayload }
  | { type: "input.data_snapshot"; payload: InputDataSnapshotPayload }
  | { type: "tool.requested"; payload: ToolRequestedPayload }
  | { type: "tool.execution_started"; payload: ToolExecutionStartedPayload }
  | { type: "tool.execution_completed"; payload: ToolExecutionCompletedPayload }
  | { type: "tool.execution_failed"; payload: ToolExecutionFailedPayload }
  | { type: "tool.committed"; payload: ToolCommittedPayload }
  | { type: "tool.cancelled"; payload: ToolCancelledPayload }
  | { type: "tool.cross_ticker_query"; payload: ToolCrossTickerQueryPayload }
  | { type: "data.progress"; payload: DataProgressPayload }
  | { type: "data.completed"; payload: DataCompletedPayload }
  | { type: "data.failed"; payload: DataFailedPayload }
  | { type: "data.interrupted"; payload: DataInterruptedPayload }
  | { type: "data.cache_hit"; payload: DataCacheHitPayload }
  | { type: "artifact.written"; payload: ArtifactWrittenPayload };

/** Any payload shape, without the wrapping `type`. */
export type AnyEventPayload = EventPayloadByType["payload"];

/** Envelope core shared by every persisted event. */
export interface EventEnvelopeCore {
  event_id: string;
  run_id: string;
  sequence: number;
  timestamp: string;
  team_id?: string | null;
  actor_id?: string | null;
  node_id?: string | null;
  status?: string | null;
  parent_event_id?: string | null;
  schema_version: number;
}

/**
 * Loose SSE envelope: `type` is a string and `payload` is an opaque record.
 * Use this for raw transport decoding; narrow to `TypedPersistedEvent` once
 * the `type` is inspected.
 */
export interface PersistedEventDTO extends EventEnvelopeCore {
  type: string;
  payload: Record<string, unknown>;
}

/**
 * Strongly-typed envelope union discriminated on `type`. Unknown future event
 * types are ignored per spec §9.5 — narrow with a `switch` and provide a
 * `default` no-op branch rather than an exhaustive `never` check.
 */
export type TypedPersistedEvent = EventPayloadByType & EventEnvelopeCore;

/** Set of every known event `type` string emitted today. */
export type KnownEventType = EventPayloadByType["type"];

/**
 * Catch-all for server-introduced event types the frontend does not yet know.
 * The reducer receives this shape (loose envelope) and MUST skip it.
 */
export interface UnknownEventType extends EventEnvelopeCore {
  type: string;
  payload: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Learning Reader v2 (/api/runs/{run_id}/reader)
//
// Read-only discriminated projection of the evidence-bound research case
// (ResearchCase v2). The `kind` field discriminates the union:
//   - "typed": evidence-bound learning conclusion (no trading semantics)
//   - "legacy": pre-learning historical run, raw conclusion only
//   - "unavailable": no reader projection could be produced
// Field names are snake_case-matched to the backend wire format.
// ---------------------------------------------------------------------------

export type ReaderKind = "typed" | "legacy" | "unavailable";

export type CompanionKindDTO = "role" | "claim" | "evidence" | "risk";

export interface CompanionSelectionDTO {
  kind: CompanionKindDTO;
  id: string;
}

export interface CompanionDTO {
  schema_version: 1;
  run_id: string;
  selection: CompanionSelectionDTO;
  summary: string;
  actual_coverage: string[];
  conclusion_impact: string;
  next_validation: string;
}

export type ResearchTiltDTO = "favorable" | "neutral" | "cautious" | "insufficient_evidence";

export type ClaimTypeDTO = "fact" | "inference" | "unknown";

export type ClaimLifecycleDTO = "active" | "superseded" | "invalidated";

export interface ActionImpactDTO {
  severity: "low" | "medium" | "high";
  direction: "positive" | "negative" | "neutral";
  reason: string;
}

export interface PublicClaimV2DTO {
  claim_key: string;
  claim_type: ClaimTypeDTO;
  text: string;
  evidence_ref_ids: string[];
  source_dates: string[];
  supporting_claim_keys: string[];
  coverage_ref_ids: string[];
  confidence: number | null;
  action_impact: ActionImpactDTO;
  lifecycle_status: ClaimLifecycleDTO;
}

export interface ResearchScenarioDTO {
  scenario_id: "upside" | "base" | "downside";
  title: string;
  condition_claim_keys: string[];
  research_implication: string;
  trigger_claim_keys: string[];
  invalidation_claim_keys: string[];
  confidence: number;
}

export interface ScenarioSetDTO {
  upside: ResearchScenarioDTO;
  base: ResearchScenarioDTO;
  downside: ResearchScenarioDTO;
}

export interface ReviewItemDTO {
  item_id: string;
  text: string;
  claim_keys: string[];
  trigger_kind: "date" | "event" | "price" | "filing";
  trigger_value: string;
  due_at: string | null;
  status: "pending" | "met" | "invalidated";
  evidence_ref_ids: string[];
}

export interface ReviewPlanDTO {
  next_review_at: string | null;
  item_ids: string[];
  reason: string;
}

export interface CapabilityStatusDTO {
  capability: string;
  status: "ok" | "degraded" | "unavailable";
  coverage_ref_ids: string[];
}

export interface AnalystCardDTO {
  lens: "market" | "fundamentals" | "news" | "sentiment";
  availability: "ready" | "limited" | "unavailable";
  summary: string;
  confidence: number | null;
  finding_claim_keys: string[];
  capability_statuses: CapabilityStatusDTO[];
}

export interface ConflictRecordDTO {
  conflict_id: string;
  severity: "minor" | "material" | "critical";
  capability: string;
  evidence_ref_ids: string[];
  reason_code: string;
}

export interface DataQualityV2DTO {
  level: "healthy" | "limited" | "conflicted" | "blocked";
  degraded_capabilities: string[];
  unavailable_capabilities: string[];
  conflicts: ConflictRecordDTO[];
  coverage_ref_ids: string[];
}

export interface ReaderEvidenceRefDTO {
  ref_id: string;
  source_label: string;
  resolution_status: "available" | "target_missing";
}

/**
 * The backend emits a nested BundleCoverageV1 blob here. This thin slice does
 * not parse its internals, so it is modelled as an opaque record. No `any`.
 */
export interface CoverageRefV1DTO {
  coverage_ref_id: string;
  capability: string;
  envelope: Record<string, unknown>;
}

export interface ReaderAuditEntryDTO {
  route: string;
  artifact_count: number;
  tool_call_count: number;
  degradation_count: number;
}

export type ThesisDiffKindDTO =
  | "new"
  | "maintained"
  | "invalidated"
  | "unresolved"
  | "not_reassessed";

export type ThesisChangeFlagDTO =
  | "text_changed"
  | "evidence_changed"
  | "confidence_changed"
  | "status_changed";

export interface ThesisDiffEntryDTO {
  claim_key: string;
  diff_kind: ThesisDiffKindDTO;
  previous_claim_type: ClaimTypeDTO | null;
  current_claim_type: ClaimTypeDTO | null;
  previous_text: string | null;
  current_text: string | null;
  previous_confidence: number | null;
  current_confidence: number | null;
  previous_lifecycle_status: "active" | "resolved" | "invalidated" | null;
  current_lifecycle_status: "active" | "resolved" | "invalidated" | null;
  change_flags: ThesisChangeFlagDTO[];
  counter_evidence_ref_ids: string[];
}

export interface ThesisDiffDTO {
  schema_version: 1;
  run_id: string;
  ticker: string;
  horizon: "short" | "medium" | "long";
  previous_run_id: string | null;
  baseline_completed_at: string | null;
  entries: ThesisDiffEntryDTO[];
}

export interface LearningReaderV2DTO {
  kind: "typed";
  schema_version: 2;
  run_id: string;
  mode: "company_research" | "holding_review";
  ticker: string;
  horizon: "short" | "medium" | "long";
  as_of: string;
  availability: "full" | "partial";
  decision_eligibility: "full" | "limited" | "none";
  evidence_verdict: "PASS" | "LOW_CONFIDENCE" | "FAIL_STOP" | "GATE_ERROR";
  research_tilt: ResearchTiltDTO | null;
  rating_confidence: number | null;
  claims: PublicClaimV2DTO[];
  scenarios: ScenarioSetDTO | null;
  catalysts: ReviewItemDTO[];
  invalidation_conditions: ReviewItemDTO[];
  review_plan: ReviewPlanDTO | null;
  analyst_cards: AnalystCardDTO[];
  data_quality: DataQualityV2DTO;
  evidence_refs: ReaderEvidenceRefDTO[];
  coverage_refs: CoverageRefV1DTO[];
  omissions: string[];
  thesis_diff: ThesisDiffDTO | null;
  audit_entry: ReaderAuditEntryDTO;
}

export interface LegacyReaderV1DTO {
  kind: "legacy";
  schema_version: 1;
  run_id: string;
  ticker: string;
  as_of: string;
  final_signal: string | null;
  portfolio_report_markdown: string | null;
  data_quality: { level: "available" | "limited" | "unknown"; summary: string; degradation_count: number; };
  stage_refs: string[];
  audit_entry: ReaderAuditEntryDTO;
  reason_codes: string[];
}

export interface ReaderUnavailableV1DTO {
  kind: "unavailable";
  schema_version: 1;
  run_id: string;
  ticker: string | null;
  reason_code: "research_case_unavailable" | "reader_projection_failed" | "unsupported_research_case_major";
  audit_entry: ReaderAuditEntryDTO;
}

export type ReaderResponseDTO =
  | LearningReaderV2DTO
  | LegacyReaderV1DTO
  | ReaderUnavailableV1DTO;

// ---------------------------------------------------------------------------
// Terminal Audit Center summary/detail contracts
// ---------------------------------------------------------------------------

export type AuditKindDTO =
  | "run"
  | "role"
  | "capability"
  | "tool"
  | "artifact"
  | "prompt"
  | "config"
  | "report";

export interface AuditSelectionDTO {
  kind: AuditKindDTO;
  id: string;
}

export type AuditSummaryReasonDTO =
  | "projection_failed"
  | "terminal_data_incomplete"
  | "legacy_event_gap"
  | "not_recorded";

export type AuditDetailReasonDTO =
  | "not_recorded"
  | "unsupported_artifact"
  | "content_too_large"
  | "content_sensitive"
  | "detail_not_available";

export interface AuditSectionSummaryDTO {
  section_id: "overview" | "roles" | "capabilities" | "tools" | "artifacts" | "prompt_config";
  availability: "ready" | "partial" | "unavailable" | "not_recorded";
  reason_code: AuditSummaryReasonDTO | null;
  item_count: number;
}

export interface AuditRunSummaryDTO {
  item_id: "run";
  status: "completed" | "failed" | "cancelled" | "interrupted";
  ticker: string;
  mode: "company_research" | "holding_review" | null;
  horizon: "short" | "medium" | "long" | null;
  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  data_quality: "healthy" | "limited" | "conflicted" | "unknown";
}

export interface AuditCountsDTO {
  stages: number;
  roles: number;
  turns: number;
  model_calls: number;
  tool_calls: number;
  artifacts: number;
  prompts: number;
  configs: number;
  reports: number;
}

export interface AuditStageSummaryDTO {
  stage_id: string;
  label: string;
  status: "not_started" | "running" | "completed" | "failed" | "cancelled" | "interrupted" | "unknown";
  availability: "ready" | "not_recorded";
  reason_code: "legacy_event_gap" | "not_recorded" | null;
  related_selections: AuditSelectionDTO[];
}

export interface AuditRoleSummaryDTO {
  item_id: string;
  actor_id: string;
  label: string;
  status: string;
  turn_count: number;
  model_call_count: number;
  duration_ms: number | null;
}

export interface AuditCapabilitySummaryDTO {
  item_id: string;
  label: string;
  status: string;
  reason_codes: string[];
  affected_sections: string[];
  capability_result_id?: string | null;
  availability?: string | null;
  freshness?: string | null;
  effective_period?: string | null;
  providers?: string[];
  fallback_from?: string[];
}

export interface AuditToolSummaryDTO {
  item_id: string;
  tool_name: string;
  status: string;
  execution_count: number;
  cache_status: string;
  failure_code: string | null;
}

export interface AuditArtifactSummaryDTO {
  item_id: string;
  label: string;
  artifact_kind: string;
  media_type: string;
  byte_size: number;
  producer_stage: string | null;
  content_exposure: "safe_inline" | "download_only" | "prohibited";
  is_report: boolean;
}

export interface AuditPromptConfigSummaryDTO {
  item_id: string;
  label: string;
  actor_id: string | null;
  model_call_id: string | null;
  redaction_status: "clean" | "redacted" | "metadata_only";
  byte_size: number;
}

export interface AuditSummaryDTO {
  schema_version: 1;
  run_id: string;
  source_sequence: number;
  availability: "ready" | "partial" | "legacy" | "unavailable";
  reason_code: AuditSummaryReasonDTO | null;
  run: AuditRunSummaryDTO;
  counts: AuditCountsDTO;
  sections: AuditSectionSummaryDTO[];
  stage_navigation: AuditStageSummaryDTO[];
  roles: AuditRoleSummaryDTO[];
  capabilities: AuditCapabilitySummaryDTO[];
  tools: AuditToolSummaryDTO[];
  artifacts: AuditArtifactSummaryDTO[];
  prompts: AuditPromptConfigSummaryDTO[];
  configs: AuditPromptConfigSummaryDTO[];
}

export interface AuditFactDTO {
  label: string;
  value: string | number | boolean | null;
}

export interface AuditContentDTO {
  mode: "none" | "inline" | "download";
  media_type: string | null;
  byte_size: number | null;
  redaction_status: "clean" | "redacted" | "metadata_only";
  text: string | null;
  download_url: string | null;
}

export interface AuditDetailDTO {
  schema_version: 1;
  run_id: string;
  source_sequence: number;
  selection: AuditSelectionDTO;
  availability: "ready" | "unavailable";
  reason_code: AuditDetailReasonDTO | null;
  title: string;
  facts: AuditFactDTO[];
  related_selections: AuditSelectionDTO[];
  content: AuditContentDTO;
}
