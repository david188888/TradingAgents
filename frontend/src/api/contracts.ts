/**
 * F2 — TradingAgents frontend/backend wire contracts.
 *
 * Single source of truth: backend Python
 *   tradingagents/observability/events.py
 *   tradingagents/observability/roles.py
 *   tradingagents/web/run_models.py
 *   tradingagents/web/schemas.py
 *   tradingagents/web/api.py
 *   tradingagents/web/reader_process_models.py
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
  batches: "/api/batches",
  batchValidate: "/api/batches/validate",
  batch: (batch_id: string) => `/api/batches/${batch_id}`,
  batchCancel: (batch_id: string) => `/api/batches/${batch_id}/cancel`,
  batchDelete: (batch_id: string) => `/api/batches/${batch_id}`,
  scheduler: "/api/scheduler",
  run: (run_id: string) => `/api/runs/${run_id}`,
  runView: (run_id: string) => `/api/runs/${run_id}/view`,
  reader: (run_id: string) => `/api/runs/${run_id}/reader`,
  readerPackage: (run_id: string) => `/api/runs/${run_id}/reader/package`,
  readerProcess: (run_id: string) => `/api/runs/${run_id}/reader/process`,
  readerAgent: (run_id: string, role: AgentKey) => `/api/runs/${run_id}/reader/agents/${role}`,
  readerRecord: (run_id: string) => `/api/runs/${run_id}/reader/record`,
  readerCompanion: (run_id: string) => `/api/runs/${run_id}/reader/companion`,
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

export const EVENT_SCHEMA_VERSION = 1 as const;

// Canonical: agents/schemas/_research_record.py and web/research_record_projection.py.
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

export interface QuantitativeMetricV1DTO {
  metric_id: string;
  label: string;
  availability: "available" | "unavailable";
  value: number | null;
  unit: string;
  method: string;
  calculation_version: string;
  input_evidence_ids: string[];
  input_sha256: string;
  window_start: string | null;
  window_end: string | null;
  sample_size: number | null;
  tail_sample_size: number | null;
  unavailable_reason: string | null;
  limitations: string[];
}

// Canonical: agents/schemas/_research_assessment.py.
export interface DimensionAssessmentV1DTO {
  dimension: "operating_quality" | "valuation" | "market_context" | "catalyst_delivery" | "holding_thesis";
  status: "supported" | "conditional" | "unresolved";
  judgement: string;
  claim_ids: string[];
  challenge_ids: string[];
  limitations: string[];
}

export interface ResearchAssessmentV1DTO {
  schema_version: "research-assessment-v1";
  input_snapshot_id: string;
  research_question: string;
  judgement: string;
  dimensions: DimensionAssessmentV1DTO[];
  key_claim_ids: string[];
  primary_challenge_id: string | null;
  next_check: string;
  challenge_assessments: Array<{ challenge_id: string; outcome: "unresolved"; rationale: string }>;
  completeness: "complete" | "partial";
  quality: "PASS" | "LOW_CONFIDENCE";
  forward_window_calendar_days: 84 | null;
  limitations: string[];
}

// Canonical: agents/schemas/_evidence_checks.py and _research_assessment.py.
export type EvidenceCheckId = "operating_disclosures" | "cash_conversion" | "valuation_context";
export type EvidenceQuestionScope = "operating_disclosures.current_period_coverage" | "cash_conversion.reported_bridge" | "valuation_context.supplementary_positioning";
export interface CheckObservationV1DTO {
  key: string; label: string; value: string; unit: string; method: string; evidence_ids: string[];
}
export interface ChallengeAssessmentV2DTO {
  challenge_id: string;
  outcome: "evidence_sufficient" | "risk_supported" | "future_observation" | "unresolved";
  economic_outcome: "unresolved";
  question_scope: EvidenceQuestionScope | null;
  answered_question: string | null;
  check_id: EvidenceCheckId | null;
  rationale: string;
  evidence_ids: string[];
  observed_risk: "cash_conversion.cfo_yoy_decline" | null;
  observation_date: string | null;
  observations: CheckObservationV1DTO[];
  limitations: string[];
}
export interface ResearchAssessmentV2DTO extends Omit<ResearchAssessmentV1DTO, "schema_version" | "challenge_assessments"> {
  schema_version: "research-assessment-v2";
  challenge_assessments: ChallengeAssessmentV2DTO[];
}
export interface EvidenceChecksV1DTO {
  schema_version: "evidence-checks-v1"; calculation_version: "minimum-evidence-v1";
  run_id: string; ticker: string; analysis_date: string; input_snapshot_id: string;
  input_evidence_ids: string[]; input_sha256: string;
  checks: Array<{
    check_id: EvidenceCheckId; question_scope: EvidenceQuestionScope; question: string;
    status: "passed" | "unavailable" | "conflict"; satisfied: string[]; missing: string[];
    evidence_ids: string[]; observations: CheckObservationV1DTO[]; limitations: string[];
  }>;
}

export interface NativeValuationV1DTO {
  inputs: {
    run_id: string; ticker: string; as_of: string;
    snapshot: { as_of: string; price: number | null; pe_ttm: number | null; pb: number | null; total_market_cap_yi: number | null } | null;
    net_income_annual: { metric_id: "net_income" | "equity"; value_yi: number; period: string } | null;
    equity_annual: { metric_id: "net_income" | "equity"; value_yi: number; period: string } | null;
    closing_prices: Array<[string, number]>;
    pe_history: Array<{ day: string; value: number }>;
    pb_history: Array<{ day: string; value: number }>;
    peers: { entity_ids: string[]; pe_ttm_values: number[] } | null;
  };
  assessment: ValuationAssessmentDTO;
  input_evidence_ids: string[];
  input_sha256: string;
  limitations: string[];
}

export interface ResearchRecordV1DTO {
  schema_version: "research-record-v1";
  run_id: string;
  ticker: string;
  mode: "company_research" | "catalyst_research" | "holding_review";
  analysis_date: string;
  construction: "adapted_case" | "native";
  source_case_contract: "research-case-v2" | "catalyst-research-case-v1" | null;
  source_case_sha256: string | null;
  snapshots: Array<{ version: 0 | 1; snapshot_id: string; parent_snapshot_id: string | null; evidence_ids: string[]; content_sha256: string }>;
  evidence: SourceEvidenceV1DTO[];
  claims: Array<{ claim_id: string; kind: "fact" | "inference" | "unknown"; statement: string; evidence_ids: string[]; supporting_fact_ids: string[]; limitations: string[] }>;
  hypotheses: Array<{ hypothesis_id: string; claim_id: string; input_snapshot_id: string; origin: "hypothesis_stage" | "adapted_inference"; assumptions: string[]; invalidation_conditions: string[]; limitations: string[] }>;
  challenges: Array<{ challenge_id: string; target_claim_ids: string[]; statement: string; severity: "minor" | "material" | "critical"; risk_type: "evidence_quality" | "operations" | "governance" | "market" | "valuation" | "unclassified"; evidence_ids: string[]; proposed_test: string; reported_disposition: string | null }>;
  verifications: Array<{ verification_id: string; challenge_id: string; input_snapshot_id: string; output_snapshot_id: string; method: "source_check" | "vendor_lookup" | "calculation"; status: "supports" | "contradicts" | "inconclusive" | "unavailable"; evidence_ids: string[]; executed_at: string; result: string; scope?: "unspecified" | "predicate_only"; hypothesis_id?: string | null; plan_sha256?: string | null; condition_role?: "necessary" | "invalidation" | null; condition_text?: string | null }>;
  metrics: QuantitativeMetricV1DTO[];
  assessment?: ResearchAssessmentV1DTO | ResearchAssessmentV2DTO | null;
  valuation?: NativeValuationV1DTO | null;
  evidence_checks?: EvidenceChecksV1DTO | null;
  challenge_bindings?: Array<{ challenge_id: string; check_id: EvidenceCheckId | null; observed_risk: "cash_conversion.cfo_yoy_decline" | null; observation_date: string | null }> | null;
  limitations: string[];
}

export type ResearchRecordResponseDTO =
  | { state: "ready"; schema_version: 1; run_id: string; record: ResearchRecordV1DTO }
  | { state: "unavailable"; schema_version: 1; run_id: string; reason_code: "not_published" | "publication_failed" | "corrupt" | "source_case_mismatch" };

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
  research_profile?: "evidence_v1";
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
  research_profiles?: Partial<Record<ResearchProfile, { supported: boolean; reason: string | null; checkpoint_available?: boolean }>>;
}

// ---------------------------------------------------------------------------
// Run create request (RunCreateRequest — pydantic, extra="forbid")
// ---------------------------------------------------------------------------

export type ResearchDepth = 1 | 3 | 5;
export type AssetTypeLiteral = "stock" | "crypto";
/** catalyst_research is admitted only by the explicit evidence_v1 profile. */
export type ResearchMode = "company_research" | "catalyst_research" | "holding_review";
export type ResearchHorizon = "short" | "medium" | "long";
// Legacy saved profiles remain supported for reading/recovery; Web creation
// defaults to evidence_v1 independently of the neutral AnalysisRequest default.

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
  /**
   * Web omission uses evidence_v1. Legacy profile values remain in saved
   * records; new Web creation rejects them with research_profile_retired.
   */
  research_profile?: ResearchProfile;
  research_question?: string | null;
  /** Frozen server policy; clients may omit it to use the profile default. */
  evidence_policy?: NativeEvidencePolicyV1DTO;
  holding?: HoldingInputDTO;
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
      /** Explicit producer identity for new projections; absent on old servers. */
      research_profile?: ResearchProfile;
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

/** run.queued: accepted but waiting for a concurrency slot (batch or busy manager). */
export interface RunQueuedPayload {
  run_status: "queued";
  summary?: string | null;
  ticker?: string;
  batch_id?: string | null;
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

/** Mirror of artifact.projection_unavailable required payload fields. */
export interface ArtifactProjectionUnavailablePayload {
  public_contract: string;
  graph_task_id: string;
  reason_code: string;
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
  | { type: "run.queued"; payload: RunQueuedPayload }
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
  | { type: "model.interrupted"; payload: ModelEndedPayload }
  | { type: "input.state_snapshot"; payload: InputStateSnapshotPayload }
  | { type: "input.config_snapshot"; payload: InputConfigSnapshotPayload }
  | { type: "input.prompt_snapshot"; payload: InputPromptSnapshotPayload }
  | { type: "input.data_snapshot"; payload: InputDataSnapshotPayload }
  | { type: "tool.requested"; payload: ToolRequestedPayload }
  | { type: "tool.execution_started"; payload: ToolExecutionStartedPayload }
  | { type: "tool.execution_completed"; payload: ToolExecutionCompletedPayload }
  | { type: "tool.execution_failed"; payload: ToolExecutionFailedPayload }
  | { type: "tool.execution_interrupted"; payload: ToolExecutionFailedPayload }
  | { type: "tool.committed"; payload: ToolCommittedPayload }
  | { type: "tool.cancelled"; payload: ToolCancelledPayload }
  | { type: "tool.cross_ticker_query"; payload: ToolCrossTickerQueryPayload }
  | { type: "data.progress"; payload: DataProgressPayload }
  | { type: "data.completed"; payload: DataCompletedPayload }
  | { type: "data.failed"; payload: DataFailedPayload }
  | { type: "data.interrupted"; payload: DataInterruptedPayload }
  | { type: "data.cache_hit"; payload: DataCacheHitPayload }
  | { type: "artifact.written"; payload: ArtifactWrittenPayload }
  | { type: "artifact.projection_unavailable"; payload: ArtifactProjectionUnavailablePayload };

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
  valuation: ValuationAssessmentDTO | null;
  audit_entry: ReaderAuditEntryDTO;
}

export interface PercentilePointDTO {
  window_label: string;
  percentile: number;
  sample_size: number;
  excluded_nonpositive: number;
  bucket:
    | "undervalued_band"
    | "lower_mid_band"
    | "upper_mid_band"
    | "elevated_band"
    | "not_assessable";
}

export interface EarningsBaseDTO {
  metric_id: "net_income" | "equity";
  value_yi: number;
  period: string;
}

export interface AnchorOutputDTO {
  anchor_id: string;
  method_label_zh: string;
  multiple_kind: "pe_ttm" | "pb_mrq";
  status: "available" | "partial" | "unavailable";
  reason_code: string | null;
  earnings_base: EarningsBaseDTO | null;
  multiple_low: number | null;
  multiple_high: number | null;
  implied_value_low_yi: number | null;
  implied_value_high_yi: number | null;
  per_share_low: number | null;
  per_share_high: number | null;
  assumptions: string[];
  invalidation: string | null;
}

export interface RangeSynthesisDTO {
  status: "available" | "partial" | "unavailable";
  reference_low_yi: number | null;
  reference_high_yi: number | null;
  per_share_low: number | null;
  per_share_high: number | null;
  contributing_anchor_ids: string[];
  disagreement_note_zh: string | null;
  method_note_zh: string;
}

export interface PositionVerdictDTO {
  range_position: "below_range" | "within_range" | "above_range" | "unavailable";
  deviation_pct: number | null;
  overall_label_zh: string;
  fact_notes_zh: string[];
}

export interface ValuationAssessmentDTO {
  schema_version: "valuation-assessment-v1";
  assessment_id: string;
  run_id: string;
  ticker: string;
  as_of: string;
  created_at_note: string;
  current_price: number | null;
  total_market_cap_yi: number | null;
  positions: PercentilePointDTO[];
  week52_position: PercentilePointDTO | null;
  peer_relation:
    | "discount_to_peers"
    | "in_line_with_peers"
    | "premium_to_peers"
    | "not_assessable";
  anchor_outputs: AnchorOutputDTO[];
  synthesis: RangeSynthesisDTO;
  verdict: PositionVerdictDTO;
  input_reasons: string[];
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

export interface ResearchEvidenceRefDTO {
  ref_id: string;
  run_id: string;
  source_label: string;
  resolution_status: "available" | "unavailable";
}

export interface MetricDefinitionDTO {
  metric_id: string;
  label_zh: string;
  label_en: string;
  plain_explanation: string;
  formula_text: string;
  unit: string;
  interpretation_mode: "higher_is_better" | "lower_is_better" | "descriptive";
  higher_is_better: boolean | null;
  required_inputs: string[];
  validity_conditions: string[];
  pitfalls: string[];
  source_capabilities: string[];
}

export interface MetricObservationDTO {
  observation_id: string;
  run_id: string;
  metric_id: string;
  entity_id: string;
  period: string;
  as_of: string;
  frequency: string;
  value: number | null;
  unit: string;
  availability: "available" | "partial" | "unavailable" | "not_applicable";
  unavailable_reason: string | null;
  source_evidence_ref_ids: string[];
  point_in_time: boolean;
  observation_kind: "observed" | "derived";
}

export interface ResearchPackageDTO {
  schema_version: "research-package-v1";
  package_id: string;
  run_id: string;
  ticker: string;
  target_entity_id: string | null;
  analysis_cutoff: string;
  created_at: string;
  evidence_refs: ResearchEvidenceRefDTO[];
  metric_definitions: MetricDefinitionDTO[];
  observations: MetricObservationDTO[];
  formula_evaluations: Array<{
    evaluation_id: string;
    run_id: string;
    metric_id: string;
    formula: string;
    input_observation_ids: string[];
    output_observation: MetricObservationDTO;
    status: "available" | "unavailable";
    limitations: string[];
  }>;
  peer_sets: Array<{
    peer_set_id: string;
    run_id: string;
    target_entity_id: string;
    selection_method: "user_specified" | "deterministic_rule" | "unavailable";
    criteria: string[];
    as_of: string;
    member_entity_ids: string[];
    source_evidence_ref_ids: string[];
    excluded_candidates: Array<{ entity_id: string; reason_code: string }>;
    unavailable_reason: string | null;
  }>;
  comparisons: Array<{
    comparison_id: string;
    run_id: string;
    metric_id: string;
    peer_set_id: string;
    target_observation_id: string;
    peer_observation_ids: string[];
    period: string;
    as_of: string;
    unit: string;
    target_value: number | null;
    peer_median: number | null;
    target_percentile: number | null;
    target_rank: number | null;
    sample_size: number;
    availability: "available" | "partial" | "unavailable" | "not_applicable";
    unavailable_reason: string | null;
  }>;
  logic_edges: Array<{
    edge_id: string;
    run_id: string;
    from_node: string;
    to_node: string;
    status: "supported" | "conditional" | "blocked" | "contradicted";
    input_observation_ids: string[];
    supporting_claim_keys: string[];
    evidence_ref_ids: string[];
    assumptions: string[];
    missing_evidence: string[];
    next_validation: string;
    invalidation: string;
  }>;
  unknowns: string[];
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
  mode: ResearchMode | null;
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
// Research profiles (classic | catalyst_v1 | evidence_v1)
// ---------------------------------------------------------------------------
// Mirrors, in this order of authority:
//   tradingagents/research/catalyst_evidence_policy.py  (profile + policy version)
//   tradingagents/agents/schemas/_catalyst_research.py (catalyst-research-case-v1)
//   tradingagents/web/catalyst_projection.py           (the read body below)
//
// NOT the horizon runtime contract. `horizon-policy-v2` / `horizon-policy-v3` in
// runtime/contracts.py is a horizon-gating enum read by five modules, and v3 is
// an already-active test gate. `catalyst-evidence-policy-v1` is a data-requirement
// version; the two must never share a field, a module, or a literal.

export type ResearchProfile = "classic" | "catalyst_v1" | "evidence_v1";
export const RESEARCH_PROFILES: readonly ResearchProfile[] = ["classic", "catalyst_v1", "evidence_v1"];

export const CATALYST_EVIDENCE_POLICY_VERSION = "catalyst-evidence-policy-v1" as const;
export type CatalystEvidencePolicyVersion = typeof CATALYST_EVIDENCE_POLICY_VERSION;
export const NATIVE_EVIDENCE_POLICY_VERSION = "evidence-policy-v1" as const;

/** Canonical: research/native_evidence_policy.py; these are source windows, not an outlook. */
export interface NativeEvidencePolicyV1DTO {
  policy_version: typeof NATIVE_EVIDENCE_POLICY_VERSION;
  profile: "evidence_v1";
  event_lookback_calendar_days: [7, 30, 90];
  price_history_trading_days: 250;
  fundamentals_quarters: 8;
}

export const CATALYST_CASE_SCHEMA_VERSION = "catalyst-research-case-v1" as const;
export const CATALYST_CASE_SCHEMA_NUMBER = 1 as const;

/** Endpoint contract version — distinct from the case contract version. */
export const CATALYST_ENDPOINT_VERSION = 1 as const;

/** Per-profile policy version. `classic` keeps horizon-policy-v2. */
export const PROFILE_POLICY_VERSIONS: Readonly<Record<ResearchProfile, string>> = {
  classic: "horizon-policy-v2",
  catalyst_v1: CATALYST_EVIDENCE_POLICY_VERSION,
  evidence_v1: NATIVE_EVIDENCE_POLICY_VERSION,
};

/**
 * Frozen evidence/budget parameters for one catalyst_v1 run. Every field here
 * participates in the resume fingerprint, so a client must never synthesize
 * this object locally — the server attaches it.
 */
export interface CatalystEvidencePolicyV1DTO {
  policy_version: CatalystEvidencePolicyVersion;
  profile: "catalyst_v1";
  /** Product research-lookahead window; NOT the historical fetch window. */
  forward_window_max_calendar_days: number;
  event_lookback_calendar_days: number[];
  price_history_trading_days: number;
  fundamentals_quarters: number;
  max_source_calls: number;
  max_model_calls: number;
  max_supplement_rounds: number;
  max_supplement_capabilities: number;
}

/**
 * Stable public error codes for the catalyst *request* boundary (T07). Frozen
 * because clients branch on them; mirrored from
 * tradingagents/research/catalyst_evidence_policy.py.
 */
export const CATALYST_REQUEST_ERROR_CODES = [
  "catalyst_profile_unavailable",
  "catalyst_mode_unsupported",
  "catalyst_market_unsupported",
  "catalyst_legacy_scheduling_params_not_applicable",
  "catalyst_horizon_not_supported",
  "catalyst_profile_mismatch",
] as const;
export type CatalystRequestErrorCode = (typeof CATALYST_REQUEST_ERROR_CODES)[number];

// ---------------------------------------------------------------------------
// The committed case: catalyst-research-case-v1
// ---------------------------------------------------------------------------
// Field names and Literal members below are copied from
// tradingagents/agents/schemas/_catalyst_research.py. That module is
// extra="forbid", so a renamed field is a contract break in both directions and
// this mirror is where it should be caught first.

/** 优先核查 / 持续观察 / 暂缓研究 / 信息不足. */
export type CatalystResearchPriority =
  | "verify_first"
  | "keep_watching"
  | "defer_research"
  | "insufficient_information";

export type CatalystClaimKind = "fact" | "inference" | "unknown";
export type CatalystSpecialistRole = "catalyst_events" | "operating_delivery" | "market_reaction";
export type CatalystEventStatus = "planned" | "in_progress" | "completed" | "cancelled";
export type CatalystDatePrecision = "unknown" | "day" | "month" | "quarter" | "range";
export type CatalystSourceTier = "official" | "vendor" | "media" | "derived";
export type CatalystChallengeSeverity = "minor" | "material" | "critical";
export type CatalystChallengeKind = "counter_evidence" | "missing_evidence";
export type CatalystDispositionOutcome =
  | "accepted"
  | "partially_accepted"
  | "refuted_by_evidence"
  | "unresolved";
export type CatalystCompleteness = "complete" | "partial" | "blocked";
export type CatalystResearchQuality = "PASS" | "LOW_CONFIDENCE" | "FAIL_STOP" | "GATE_ERROR";

/** Reason codes that forbid publishing `verify_first` (design 9.1). */
export const PRIORITY_BLOCKING_REASONS: readonly string[] = [
  "hard_error",
  "identity_conflict",
  "required_source_unqualified",
  "observation_window_unqualified",
  "refutation_stage_missing",
  "key_challenge_unresolved",
  "required_capability_unavailable",
  "required_coverage_insufficient",
  "pit_unverified",
  "required_specialist_failed",
  "synthesis_failed",
  "brief_safety_overflow",
];

export interface CatalystEvidenceDTO {
  evidence_id: string;
  run_id: string;
  ticker: string;
  capability: string;
  source_tier: CatalystSourceTier;
  source_name: string;
  public_url: string | null;
  /** Three aggregators copying one filing are one independent source. */
  source_family_id: string;
  republished_from_evidence_id: string | null;
  published_at: string | null;
  observed_at: string | null;
  captured_at: string;
  usable_as_of: string | null;
  time_basis: string;
  value_basis: string;
  availability: "available" | "unavailable" | "unverified";
}

export interface CatalystEventDTO {
  event_id: string;
  run_id: string;
  ticker: string;
  event_type: string;
  version: number;
  title: string;
  status: CatalystEventStatus;
  announced_at: string | null;
  /** Non-null only when date_precision !== "unknown" and evidence backs it. */
  occurred_on: string | null;
  occurred_period_end: string | null;
  date_precision: CatalystDatePrecision;
  date_evidence_ids: string[];
  updated_by_evidence_id: string | null;
  supersedes_event_id: string | null;
}

export interface CatalystNumericFactDTO {
  label: string;
  value: number;
  unit: string;
  period: string;
  basis: "reported" | "derived" | "forecast_range";
  period_start: string | null;
  period_end: string | null;
}

export interface CatalystFindingDTO {
  finding_id: string;
  run_id: string;
  role: CatalystSpecialistRole;
  kind: CatalystClaimKind;
  text: string;
  supporting_finding_ids: string[];
  evidence_ids: string[];
  event_ids: string[];
  numeric_facts: CatalystNumericFactDTO[];
  limitations: string[];
  next_checks: string[];
  /** Absent for kind === "unknown": a confident unknown is a disguised fact. */
  confidence: number | null;
  survives: boolean;
}

export interface CatalystChallengeDTO {
  challenge_id: string;
  run_id: string;
  kind: CatalystChallengeKind;
  severity: CatalystChallengeSeverity;
  target_finding_ids: string[];
  target_event_ids: string[];
  statement: string;
  /** Present for counter_evidence, absent for missing_evidence. */
  evidence_ids: string[];
  test_method: string;
  is_key: boolean;
}

export interface CatalystChallengeDispositionDTO {
  challenge_id: string;
  outcome: CatalystDispositionOutcome;
  rationale: string;
  evidence_ids: string[];
  retained_limitations: string[];
  finding_ids: string[];
}

/** One first-screen line, bound to the object it restates. */
export interface CatalystBriefLineDTO {
  text: string;
  finding_ids: string[];
  event_ids: string[];
  challenge_ids: string[];
}

export interface CatalystBriefDTO {
  kind: "ordinary" | "safety_overflow";
  judgement: string;
  priority: CatalystResearchPriority;
  primary_catalyst_event_id: string | null;
  primary_catalyst: CatalystBriefLineDTO | null;
  key_evidence: CatalystBriefLineDTO[];
  key_question: CatalystBriefLineDTO;
  next_check: CatalystBriefLineDTO;
  critical_limitations: CatalystBriefLineDTO[];
  overflow_reason: string | null;
}

export interface CatalystBudgetUsageDTO {
  model_attempts: number;
  structured_output_repairs: number;
  network_retries: number;
  data_capability_calls: number;
  http_attempts: number;
  semantic_preprocess_calls: number;
  model_usage_available: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  stage_durations_ms: Array<[string, number]>;
  termination_reason: string | null;
}

export interface CatalystPriorityDecisionDTO {
  priority: CatalystResearchPriority;
  candidate_priority: CatalystResearchPriority;
  proposed_by: "synthesis" | "code";
  blocking_reasons: string[];
  rationale: string;
}

/** The authoritative committed result of one catalyst_v1 run. */
export interface CatalystResearchCaseDTO {
  schema_version: typeof CATALYST_CASE_SCHEMA_VERSION;
  schema_number: typeof CATALYST_CASE_SCHEMA_NUMBER;
  run_id: string;
  ticker: string;
  research_profile: "catalyst_v1";
  evidence_policy: string;
  as_of: string;
  source_sequence: number;
  completeness: CatalystCompleteness;
  quality: CatalystResearchQuality;
  reason_codes: string[];
  research_question: string | null;
  evidence: CatalystEvidenceDTO[];
  events: CatalystEventDTO[];
  findings: CatalystFindingDTO[];
  challenges: CatalystChallengeDTO[];
  dispositions: CatalystChallengeDispositionDTO[];
  priority_decision: CatalystPriorityDecisionDTO;
  brief: CatalystBriefDTO;
  budget_usage: CatalystBudgetUsageDTO;
}

// ---------------------------------------------------------------------------
// The read body: GET /api/runs/{run_id}/catalyst
// ---------------------------------------------------------------------------
// Mirrors tradingagents/web/catalyst_projection.py. The discriminator is
// `state`, and every arm carries `schema_version` (the *endpoint* version), so a
// consumer can tell which contract it holds without inspecting the payload.

export type CatalystUnavailableReason = "run_running" | "not_committed" | "missing" | "corrupt";
export type CatalystUnsupportedReason = "classic_profile" | "unknown_profile";

export interface CatalystReadyV1DTO {
  stages?: Record<string, string>;
  state: "ready";
  schema_version: typeof CATALYST_ENDPOINT_VERSION;
  case_schema_version: typeof CATALYST_CASE_SCHEMA_VERSION;
  case_schema_number: typeof CATALYST_CASE_SCHEMA_NUMBER;
  run_id: string;
  ticker: string;
  run_status: string;
  completeness: CatalystCompleteness;
  quality: CatalystResearchQuality;
  priority: CatalystResearchPriority;
  research_question: string | null;
  brief: Record<string, unknown>;
  limitations: string[];
  /** Derived by the server from the brief text; never asserted by a producer. */
  brief_character_count: number;
  case: Record<string, unknown>;
}

export interface CatalystUnavailableV1DTO {
  stages?: Record<string, string>;
  state: "unavailable";
  schema_version: typeof CATALYST_ENDPOINT_VERSION;
  run_id: string;
  ticker: string;
  run_status: string;
  reason_code: CatalystUnavailableReason;
  reason_codes: string[];
}

export interface CatalystUnsupportedV1DTO {
  state: "unsupported";
  schema_version: typeof CATALYST_ENDPOINT_VERSION;
  run_id: string;
  ticker: string;
  reason_code: CatalystUnsupportedReason;
}

export type CatalystReadState = CatalystReadyV1DTO | CatalystUnavailableV1DTO | CatalystUnsupportedV1DTO;
export type CatalystReadStateKind = CatalystReadState["state"];

export function isCatalystReady(state: CatalystReadState): state is CatalystReadyV1DTO {
  return state.state === "ready";
}

/** Transient: the run *could* have a catalyst artifact and does not yet. */
export function isCatalystUnavailable(state: CatalystReadState): state is CatalystUnavailableV1DTO {
  return state.state === "unavailable";
}

/** Permanent: this run's profile will never have one. Never rendered as failure. */
export function isCatalystUnsupported(state: CatalystReadState): state is CatalystUnsupportedV1DTO {
  return state.state === "unsupported";
}

/**
 * A readable response is NOT a sufficient result. `ready` means the committed
 * artifact parses; the case may still be `blocked`. Run lifecycle and research
 * quality stay two separate axes.
 */
export function isResearchSufficient(state: CatalystReadState | null): boolean {
  return (
    state !== null &&
    isCatalystReady(state) &&
    state.completeness === "complete" &&
    state.quality === "PASS"
  );
}

/**
 * The priority ceiling (design 9.1), mirrored from ResearchPriorityDecision.
 * Only a case whose blocking_reasons are disjoint from PRIORITY_BLOCKING_REASONS
 * may publish `verify_first`.
 */
export function isVerifyFirstPermitted(blockingReasons: readonly string[]): boolean {
  return blockingReasons.every((reason) => !PRIORITY_BLOCKING_REASONS.includes(reason));
}

/**
 * Brief budgets, mirrored from _catalyst_research.py. Overflow degrades to the
 * safety template; a line is never truncated to fit.
 */
export const BRIEF_CHARACTER_BUDGET = 420;
export const BRIEF_CHARACTER_TARGET_MIN = 200;
export const BRIEF_CHARACTER_TARGET_MAX = 300;
export const SAFETY_OVERFLOW_TEMPLATE_BUDGET = 120;
export const SAFETY_OVERFLOW_REASON = "brief_safety_overflow";

/** The budget a given brief kind is measured against. */
export function briefBudgetFor(kind: CatalystBriefDTO["kind"]): number {
  return kind === "ordinary" ? BRIEF_CHARACTER_BUDGET : SAFETY_OVERFLOW_TEMPLATE_BUDGET;
}

/**
 * Version routing. The endpoint is selected by explicit path, never by content
 * sniffing: a caller either asks for the catalyst contract or does not. Legacy
 * callers keep using API.runView / API.reader unchanged.
 */
export const CATALYST_CASE_PATH = (runId: string) => `/api/runs/${runId}/catalyst` as const;

/**
 * Legacy pre-catalyst record, read through the existing classic reader
 * contract. It carries no profile, no priority, and no catalyst fields: a reader
 * upgrade must read it without recomputation and must not synthesize a research
 * priority from its prose.
 */
export interface CatalystLegacyRecordDTO {
  kind: "legacy";
  run_id: string;
  mode: string;
  ticker: string;
  horizon: string;
  as_of: string;
  availability: string;
  decision_eligibility: string;
  evidence_verdict: string;
  research_tilt: string | null;
  rating_confidence: number | null;
  /** Always null: a reader upgrade must not manufacture a priority. */
  research_priority: null;
  claims: Array<Record<string, unknown>>;
  catalysts: unknown[];
  invalidation_conditions: unknown[];
  evidence_refs: Array<{ ref_id: string; label: string; resolution_status: string }>;
}

// Canonical: web/reader_process_models.py; proposals: agents/schemas/_native_stage.py.
export type AgentKey = "evidence" | "operating_quality" | "event_context" | "market_context" | "challenge" | "synthesis" | "code_checks";
export type OutputAvailability = "available" | "pending_publication" | "not_recorded" | "unavailable" | "unsupported" | "not_applicable";
export interface ObservedCountDTO { value: number | null; completeness: "complete" | "known_lower_bound" | "not_recorded" | "unavailable"; basis: string }
export interface NativeCountsDTO { main_budget: ObservedCountDTO; repair_budget: ObservedCountDTO; sdk_main: ObservedCountDTO; sdk_repair: ObservedCountDTO; sdk_total: ObservedCountDTO; data_capability: ObservedCountDTO; data_http: ObservedCountDTO }
export interface ReaderRoleDTO {
  role_key: AgentKey; actor_id: string; label: string; origin: "model" | "code"; purpose: string; status: string;
  output_availability: OutputAvailability; reason_code: string | null; output_count: number | null; output_sequence: number | null;
  main_budget: ObservedCountDTO; sdk_main: ObservedCountDTO; sdk_repair: ObservedCountDTO;
}
export interface ReaderProcessDTO {
  schema_version: 1; run_id: string; source_sequence: number; profile: string; workflow_version: string | null;
  availability: "ready" | "partial" | "unavailable" | "not_applicable"; reason_code: string | null;
  question_origin: "user" | "default" | "not_recorded"; primary_selection: "synthesis" | "code" | "not_recorded";
  counts: NativeCountsDTO; roles: ReaderRoleDTO[]; claim_origins: Array<{claim_id: string; role_key: AgentKey}>; source_failures: string[];
}
export interface SpecialistProposalDTO { hypotheses: Array<{ statement: string; supporting_fact_ids: string[]; conditions: Array<{condition_role: "necessary" | "invalidation"; text: string; check: VerificationConditionDTO | null}>; alternative_explanation: string }>; unknowns: string[] }
export interface NumericPredicateDTO { operator: "lt" | "le" | "eq" | "ge" | "gt"; threshold: string; unit: string }
export interface FinancialOperandDTO { evidence_id: string; table: "income" | "balancesheet" | "cashflow"; field: string; report_period: string }
export type VerificationConditionDTO = { kind: "financial"; operation: "value" | "difference" | "growth"; current: FinancialOperandDTO; base: FinancialOperandDTO | null; predicate: NumericPredicateDTO } | { kind: "metric"; metric_id: string; predicate: NumericPredicateDTO };
export interface ChallengesProposalDTO { challenges: Array<{ hypothesis_id: string; statement: string; severity: "minor" | "material" | "critical"; risk_type: "evidence_quality" | "operations" | "governance" | "market" | "valuation" | "unclassified"; proposed_test: string; condition_id: string | null; check_id?: EvidenceCheckId | null; observed_risk?: "cash_conversion.cfo_yoy_decline" | null; observation_date?: string | null }> }
export interface SynthesisProposalDTO { judgement: string; dimensions: DimensionAssessmentV1DTO[]; key_claim_ids: string[]; primary_challenge_id: string | null; next_check: string; challenge_assessments: Array<{ challenge_id: string; outcome: "unresolved"; rationale: string }> }
export interface ReaderAgentDTO {
  schema_version: 1; run_id: string; source_sequence: number; role_key: AgentKey; availability: OutputAvailability; reason_code: string | null; origin: "model" | "code"; input_description: string;
  proposal: SpecialistProposalDTO | ChallengesProposalDTO | SynthesisProposalDTO | null;
  relations: Array<{entity_id: string; kind: "claim" | "challenge"; in_record: boolean; is_key: boolean; dimensions: string[]; challenge_ids: string[]}>;
  claim_ids: string[]; input_fact_ids: string[]; challenge_ids: string[]; code_sections: Array<"facts" | "sources" | "checks" | "verifications" | "publication">;
}
