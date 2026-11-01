

export const API = {
  config: "/api/config",
  runs: "/api/runs",
  batches: "/api/batches",
  batchValidate: "/api/batches/validate",
  batch: (batch_id: string) => `/api/batches/${batch_id}`,
  batchCancel: (batch_id: string) => `/api/batches/${batch_id}/cancel`,
  batchDelete: (batch_id: string) => `/api/batches/${batch_id}`,
  scheduler: "/api/scheduler",
  run: (run_id: string) => `/api/runs/${run_id}`,
  readerProcess: (run_id: string) => `/api/runs/${run_id}/reader/process`,
  readerAgent: (run_id: string, role: AgentKey) => `/api/runs/${run_id}/reader/agents/${role}`,
  readerFocus: (run_id: string) => `/api/runs/${run_id}/reader/focus`,
  readerRecord: (run_id: string) => `/api/runs/${run_id}/reader/record`,
  audit: (run_id: string) => `/api/runs/${run_id}/audit`,
  auditDetail: (run_id: string) => `/api/runs/${run_id}/audit/detail`,
  cancel: (run_id: string) => `/api/runs/${run_id}/cancel`,
  retry: (run_id: string) => `/api/runs/${run_id}/retry`,
  resume: (run_id: string) => `/api/runs/${run_id}/resume`,
  artifacts: (run_id: string) => `/api/runs/${run_id}/artifacts`,
  artifact: (run_id: string, artifact_id: string) =>
    `/api/runs/${run_id}/artifacts/${artifact_id}`,
  events: (run_id: string, after?: number) =>
    `/api/runs/${run_id}/events${after != null ? `?after=${after}` : ""}`,
  recentRuns: (limit = 20, cursor?: string) =>
    `/api/runs?${new URLSearchParams({
      view: "recent",
      limit: String(limit),
      ...(cursor ? { cursor } : {}),
    }).toString()}`,
} as const;

// Canonical: agents/schemas/_evidence.py and web/research_record_projection.py.
export interface SourceContentV1DTO {
  kind: "excerpt" | "source_fields" | "saved_summary";
  text: string;
  locator_label: string;
  content_sha256: string;
  truncated: boolean;
}

export interface SourceEvidenceV1DTO {
  evidence_id: string;
  source_name: string;
  source_kind: "official" | "vendor" | "media" | "derived" | "analysis_report" | "unknown";
  source_family_id: string | null;
  availability: "available" | "unavailable" | "unverified";
  public_url: string | null;
  published_at: string | null;
  usable_as_of: string | null;
  captured_at: string | null;
  content: SourceContentV1DTO | null;
  limitations: string[];
}
export interface CompanyBasicsV1DTO {
  schema_version: "company-basics-v1";
  company_name: string | null;
  introduction: CompanyBasicFieldV1DTO[];
  fundamentals: CompanyBasicFieldV1DTO[];
  quantitative: CompanyBasicFieldV1DTO[];
  gaps: string[];
}
export interface CompanyBasicFieldV1DTO { label: string; claim_id: string; report_period: string | null }

/** Canonical: agents/schemas/_report_explanation.py; additive, read-only supplement. */
export interface IndicatorExplanationDTO {
  label: string; value: string | null; definition: string; interpretation: string;
  caution: string; professional: string; scope: string; raw_value: string | null; raw_unit: string | null;
}
export interface ExplanationEntryDTO {
  target: string; explanation: string; uncertainty: string; references: string[];
}
export interface ReportExplanationDTO {
  coverage?: {total: number; explained: number; unavailable: number; pending: number};
  schema_version: 1; run_id: string; base_record_sha256: string | null;
  state: "not_generated" | "generating" | "available" | "partial" | "failed" | "interrupted" | "unsupported" | "corrupt";
  reason_code: string | null; eligible: boolean;
  indicators: Record<string, IndicatorExplanationDTO>; entries: Record<string, ExplanationEntryDTO>;
  unavailable_targets: Record<string, string>; model: string | null; generated_at: string | null;
}

export interface NumericAnchorV1DTO {
  anchor_id: string; definition_key: string; label: string; subject: string;
  basis: "actual_reported" | "observed_quote" | "institution_forecast" | "computed_statistic" | "accounting_check" | "valuation_reference";
  value: string; unit: string; required_fact_ids: string[]; input_evidence_ids: string[]; snapshot_id: string;
  metadata: Record<string, string | number>;
  lineage: { kind: "source" | "calculation"; source_name?: string; source_family_id?: string;
    source_content_sha256?: string; calculation_version?: string; input_sha256?: string;
    source_selector?: Record<string, string | number>; operands?: string[] };
  limitations: string[];
}

/** Independent Insight wire contract, owned by agents/schemas/_insight.py. */
export interface InsightProposalDTO {
  claim: string; evidence_refs: string[]; reasoning: string; limitations: string;
}
export interface SavedInsightDTO {
  insight_id: string; role: string; index: number; revision: number; snapshot_id: string; catalog_id: string;
  status: "accepted" | "pending" | "excluded"; proposal: InsightProposalDTO;
  rendered: { claim: string; reasoning: string; limitations: string };
  fact_ids: string[]; source_ids: string[]; numeric_ids: string[]; issues: string[];
}
export interface InsightReportDTO {
  schema_version: "insight-research-v1"; construction: "native"; run_id: string; ticker: string;
  mode: "company_research"; analysis_date: string;
  catalogs: Record<string, { snapshot_id: string; sources: SourceEvidenceV1DTO[];
    evidence: Array<{ ref: string; fact_id: string; text: string; source_ids: string[] }>;
    numbers: Array<{ ref: string; anchor: NumericAnchorV1DTO }> }>;
  insights: SavedInsightDTO[];
  reviews: Array<{ target_id: string; status: "challenged" | "no_counterevidence" | "unreviewed" | "failed";
    concern: string | null; reasoning: string; source_ids: string[]; note: SavedInsightDTO | null }>;
  responses: Array<{ target_id: string; action: "maintain" | "revise" | "withdraw" | "uncertain";
    reasoning: string; source_ids: string[]; replacement_id: string | null; note: SavedInsightDTO }>;
  synthesis: { judgement: string; stance: "favorable" | "neutral" | "unfavorable" | null;
    reasoning: string; limitations: string; next_check: string; insight_ids: string[]; reference_ids: Record<string, string> } | null;
  gaps: string[]; stages: Record<string, string>;
  company_basics?: CompanyBasicsV1DTO | null;
  focus_question: string | null; focus_insights: SavedInsightDTO[];
  superseded_ids: string[]; search_requests: Record<string, string[]>;
}

export type ResearchRecordResponseDTO =
  | { state: "insight_ready"; schema_version: 1; run_id: string; record: InsightReportDTO }
  | { state: "unavailable"; schema_version: 1; run_id: string; reason_code: "not_published" | "publication_failed" | "corrupt" | "source_case_mismatch" };

/** SSE terminal events — the stream is closed by the server after these. */
export const TERMINAL_STREAM_EVENTS = [
  "run.completed",
  "run.failed",
  "run.cancelled",
  "run.interrupted",
] as const;

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
  authentication?: "oauth";
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
  research_profile?: "evidence_v1";
  llm_provider: string | null;
  quick_think_llm: string | null;
  deep_think_llm: string | null;
  output_language: string;
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
  research_profiles?: Partial<Record<ResearchProfile, { supported: boolean; reason: string | null; checkpoint_available?: boolean }>>;
}
export type AssetTypeLiteral = "stock" | "crypto";
/** Current company research mode. */
export type ResearchMode = "company_research";

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
  analysis_date?: string;
  llm_provider: string;
  chatgpt_account_ref?: string;
  quick_think_llm: string;
  deep_think_llm: string;
  output_language: string;
  /** Null means "let the server derive from normalized ticker". */
  /**
   * Web omission uses evidence_v1. Legacy profile values remain in saved
   * records; new Web creation rejects them with research_profile_retired.
   */
  research_profile?: ResearchProfile;
  research_question?: string | null;
  /** Frozen server policy; clients may omit it to use the profile default. */
  evidence_policy?: NativeEvidencePolicyV1DTO;
  /** Legacy-only input. New clients must use holding instead. */
  portfolio?: PortfolioDTO | null;
}

export interface BatchResolvedItemDTO {
  input: string;
  company_name: string;
  ticker: string;
  market: string;
}

export interface BatchValidationDTO {
  items: BatchResolvedItemDTO[];
  count: number;
  max_items: number;
}

export interface BatchEntryDTO {
  input: string;
  config: Omit<RunCreateRequestDTO, "ticker" | "mode" | "holding" | "portfolio">;
}

export interface BatchCreateRequestDTO {
  entries: BatchEntryDTO[];
  concurrency: 1 | 2 | 3;
}

export type BatchItemStatusDTO = "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
export type BatchStatusDTO = "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";

export interface BatchItemDTO extends BatchResolvedItemDTO {
  run_id: string;
  ordinal: number;
  status: BatchItemStatusDTO;
  error_message?: string | null;
  config: Record<string, unknown>;
}

export interface BatchSnapshotDTO {
  batch_id: string;
  status: BatchStatusDTO;
  created_at: string;
  updated_at: string;
  concurrency: 1 | 2 | 3;
  items: BatchItemDTO[];
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  running_count: number;
  queued_count: number;
  interrupted_count: number;
  summary?: string | null;
}

export interface SchedulerDTO {
  concurrency: 1 | 2 | 3;
  maximum: 3;
}



export type RunStatusLiteral =
  | "created"
  | "queued"
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



  output_language: string;
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  configured_keys: Record<string, boolean>;
  created_at: string;
  updated_at: string;
  /** Explicit for new snapshots; absent only on legacy snapshots. */
  mode?: ResearchMode | null;


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

/** DELETE /api/runs bulk-clear result. */
export interface DeleteAllRunsResultDTO {
  /** Number of persisted runs actually deleted. */
  removed: number;
  /** True when the currently active run was kept because it is executing. */
  skipped_active: boolean;
}

// ---------------------------------------------------------------------------
// Error shapes (api.py boundary + schemas.py)
// ---------------------------------------------------------------------------

/**
 * Every `detail.code` the backend error envelope can carry, extracted from
 * api.py's `_error_response` / `ApiBoundaryError` call sites, plus the
 * client-side "http_error" fallback used when a failure body is not JSON
 * (e.g. a proxy 502). Pinned by
 * tests/test_frontend_wire_contract.py::test_api_error_codes_match_backend.
 */
export type ApiErrorCode =
  | "local_origin_required"
  | "reader_sequence_unavailable"
  | "asset_type_mismatch"
  | "audit_item_not_found"
  | "audit_summary_stale"
  | "audit_terminal_required"
  | "batch_active"
  | "checkpoint_unavailable"
  | "companion_not_found"
  | "company_not_found"
  | "duplicate_ticker"
  | "evidence_horizon_not_supported"
  | "evidence_legacy_scheduling_params_not_applicable"
  | "evidence_market_unsupported"
  | "evidence_mode_unsupported"
  | "evidence_profile_unavailable"
  | "explanation_unavailable"
  | "event_cursor_mismatch"
  | "frontend_unavailable"
  | "history_corrupted"
  | "holding_as_of_invalid"
  | "holding_as_of_mismatch"
  | "holding_average_cost_invalid"
  | "holding_cash_invalid"
  | "holding_currency_invalid"
  | "holding_legacy_conflict"
  | "holding_nav_invalid"
  | "holding_not_allowed"
  | "holding_original_thesis_invalid"
  | "holding_quantity_invalid"
  | "holding_required"
  | "holding_ticker_mismatch"
  | "http_error"
  | "invalid_concurrency"
  | "invalid_cursor"
  | "invalid_event_cursor"
  | "invalid_limit"
  | "invalid_view"
  | "legacy_portfolio_not_allowed"
  | "legacy_resume_normalization_failed"
  | "legacy_target_position_ambiguous"
  | "legacy_target_position_invalid"
  | "legacy_target_position_missing"
  | "missing_configuration"
  | "not_found"
  | "ref_not_found"
  | "ref_target_missing"
  | "research_package_unavailable"
  | "unified_research_mode_required"
  | "research_profile_retired"
  | "resume_conflict"
  | "run_active"
  | "run_not_active"
  | "run_not_resumable"
  | "run_not_retryable"
  | "unsupported_analyst"
  | "unsupported_model"
  | "unsupported_provider"
  | "validation_error"
  | "yfinance_unreachable";

export interface ApiErrorDetail {
  code: string;
  message: string;
  fields: string[];
  active_run_id?: string;
  diagnostic?: ModelFailureDiagnosticDTO | null;
}

export interface ApiErrorResponse {
  detail: ApiErrorDetail;
}

export type ObservationTaskKind = "input" | "role" | "tool" | "maintenance";

/** Mirror of dataclass ObservationCommitV1. node_id/turn_id nullable; tool_call_ids ordered+unique. */
export interface ObservationCommitV1DTO {
  serializer_version: number;
  projection_version: number;

  task_kind: ObservationTaskKind;
  graph_task_id: string;
  graph_step: number;
  business_delta_sha256: string;
  node_id?: string | null;
  turn_id?: string | null;
  tool_call_ids: string[];
}

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
  mode: ResearchMode | null;

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
  turns: number | null;
  model_calls: number | null;
  native_counts?: NativeCountsDTO | null;
  tool_calls: number;
  artifacts: number;
  prompts: number;
  configs: number;
  reports: number;
}

export interface AuditStageSummaryDTO {
  stage_id: string;
  label: string;
  status: "not_started" | "running" | "completed" | "failed" | "cancelled" | "interrupted" | "skipped" | "unknown";
  availability: "ready" | "not_recorded";
  reason_code: "legacy_event_gap" | "not_recorded" | null;
  related_selections: AuditSelectionDTO[];
}

export interface AuditRoleSummaryDTO {
  item_id: string;
  actor_id: string;
  label: string;
  status: string;
  turn_count: number | null;
  model_call_count: number | null;
  model_observation?: ObservedCountDTO | null;
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

// ---------------------------------------------------------------------------
// Current research profile.
export type ResearchProfile = "evidence_v1";
export const NATIVE_EVIDENCE_POLICY_VERSION = "evidence-policy-v1" as const;

/** Canonical: research/native_evidence_policy.py; these are source windows, not an outlook. */
export interface NativeEvidencePolicyV1DTO {
  policy_version: typeof NATIVE_EVIDENCE_POLICY_VERSION;
  profile: "evidence_v1";
  event_lookback_calendar_days: [7, 30, 90];
  price_history_trading_days: 250;
  fundamentals_quarters: 8;
}

// Canonical: web/reader_process_models.py; proposals: agents/schemas/_native_stage.py.
export type AgentKey = "evidence" | "operating_quality" | "event_context" | "market_context" | "challenge" | "synthesis" | "code_checks" | "focus_response" | "response_operating_quality" | "response_event_context" | "response_market_context";
export type OutputAvailability = "available" | "stage_available" | "insight_stage_available" | "pending_publication" | "not_recorded" | "unavailable" | "unsupported" | "not_applicable";
export interface ObservedCountDTO { value: number | null; completeness: "complete" | "known_lower_bound" | "not_recorded" | "unavailable"; basis: string }
export interface NativeCountsDTO { main_budget: ObservedCountDTO; repair_budget: ObservedCountDTO; sdk_main: ObservedCountDTO; sdk_repair: ObservedCountDTO; sdk_total: ObservedCountDTO; data_capability: ObservedCountDTO; data_http: ObservedCountDTO; focus_budget?: ObservedCountDTO | null; sdk_focus?: ObservedCountDTO | null }
export interface ReaderRoleDTO {
  role_key: AgentKey; actor_id: string; label: string; origin: "model" | "code"; purpose: string; status: string;
  output_availability: OutputAvailability; reason_code: string | null; output_count: number | null; output_sequence: number | null;
  main_budget: ObservedCountDTO; sdk_main: ObservedCountDTO; sdk_repair: ObservedCountDTO;
  focus_budget?: ObservedCountDTO | null; sdk_focus?: ObservedCountDTO | null;
}
export interface SearchUsageV1DTO {
  deepseek_search: number; tavily_search: number; page_attempts: number;
  review_attempts: number; rounds: number; active_seconds: number;
}
export interface ReaderProcessDTO {
  search_usage?: SearchUsageV1DTO | null;
  schema_version: 1; run_id: string; source_sequence: number; profile: string; workflow_version: string | null;
  availability: "ready" | "partial" | "unavailable" | "not_applicable"; reason_code: string | null;
  question_origin: "user" | "default" | "not_recorded"; primary_selection: "synthesis" | "code" | "not_recorded";
  counts: NativeCountsDTO; roles: ReaderRoleDTO[]; claim_origins: Array<{claim_id: string; role_key: AgentKey}>; source_failures: string[];
  /** Safe provider failures and closed output-validation explanations for failed roles. */
  model_failures?: ModelFailureDiagnosticDTO[];
}
export interface ModelFailureDiagnosticDTO {
  stage: string; category: string; upstream_status: number | null; upstream_code: string | null;
  request_id: string | null; safe_message: string;
  action: "sign_in" | "manage_usage" | "refresh_models" | "retry_later" | "check_permissions" | "check_capability" | "cancelled";
}
export interface ReaderAgentDTO {
  insight_record: InsightReportDTO | null;
  schema_version: 1; run_id: string; source_sequence: number; role_key: AgentKey;
  availability: OutputAvailability; reason_code: string | null; origin: "model" | "code"; input_description: string;
}
