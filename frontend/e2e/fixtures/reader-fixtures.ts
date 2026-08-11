import type {
  AuditDetailDTO,
  AuditSelectionDTO,
  AuditSummaryDTO,
  CompanionDTO,
  CompanionSelectionDTO,
  ConfigResponseDTO,
  LearningReaderV2DTO,
  ReaderBriefDTO,
  ReaderResponseDTO,
  RecentRunsPageDTO,
  RunSnapshotDTO,
  RunStatusLiteral,
  RunViewEnvelopeDTO,
} from "../../src/api/contracts";

export type ReaderFixtureKind = "typed" | "partial" | "failed" | "legacy";

export const FIXED_NOW = "2026-08-11T08:00:00+08:00";
export const FIXED_DATE = "2026-08-11";

export const PRIVATE_SENTINELS = {
  prompt: "PRIVATE_PROMPT_SENTINEL_DO_NOT_RENDER",
  locator: "private/run/raw/research-case.json",
  hash: "f".repeat(64),
  csv: "ticker,secret_signal\nQLNY.FX,private-row",
  raw: "PRIVATE_RAW_ARTIFACT_DO_NOT_RENDER",
} as const;

const RUN_IDS: Record<ReaderFixtureKind, string> = {
  typed: "run_golden_typed",
  partial: "run_golden_partial",
  failed: "run_golden_failed",
  legacy: "run_golden_legacy",
};

const TICKERS: Record<ReaderFixtureKind, string> = {
  typed: "QLNY.FX",
  partial: "XHCL.FX",
  failed: "YLTK.FX",
  legacy: "HIST.FX",
};

export const configFixture: ConfigResponseDTO = {
  providers: [
    {
      id: "local-fixture",
      configured: true,
      requires_api_key: false,
      models: {
        quick: [{ label: "Fixture Quick", id: "fixture-quick" }],
        deep: [{ label: "Fixture Deep", id: "fixture-deep" }],
      },
      custom_model_allowed: false,
    },
  ],
  configured_keys: { "local-fixture": true },
  analysts: [
    { id: "market" },
    { id: "fundamentals" },
    { id: "news" },
    { id: "social" },
  ],
  presets: [
    {
      id: "balanced",
      label: "平衡研究",
      analysts: ["market", "fundamentals", "news", "social"],
    },
  ],
  depths: [1, 3, 5],
  output_languages: ["Chinese"],
  checkpoint_available: false,
  defaults: {
    llm_provider: "local-fixture",
    quick_think_llm: "fixture-quick",
    deep_think_llm: "fixture-deep",
    output_language: "Chinese",
    research_depth: 3,
    checkpoint_enabled: false,
  },
};

const healthyDataQuality = {
  level: "healthy" as const,
  degraded_capabilities: [],
  unavailable_capabilities: [],
  conflicts: [],
  checks: [{ check: "fixture_integrity", status: "passed", reason_code: null }],
};

const limitedDataQuality = {
  level: "limited" as const,
  degraded_capabilities: ["news_depth"],
  unavailable_capabilities: ["social_sentiment"],
  conflicts: [],
  checks: [{ check: "fixture_integrity", status: "limited", reason_code: "source_gap" }],
};

const briefValue: ReaderBriefDTO = {
  schema_version: 2,
  run_id: RUN_IDS.typed,
  ticker: TICKERS.typed,
  source_sequence: 18,
  generated_at: "2026-08-11T00:04:30Z",
  availability: "full",
  omissions: [],
  research_rating: "中性偏积极",
  execution: {
    availability: "unavailable",
    requested_action: null,
    requested_quantity: null,
    effective_action: null,
    effective_quantity: null,
    reason_code: "learning_only",
  },
  executive_summary: {
    claim_id: "brief-growth",
    text: "青岚能源的订单可见度改善，但利润兑现仍取决于下一期交付节奏。",
    evidence_ref_ids: ["evidence-filing"],
  },
  price_target: null,
  time_horizon: "中期",
  drivers: [
    {
      claim_id: "brief-driver",
      text: "已披露订单覆盖未来两个交付窗口。",
      evidence_ref_ids: ["evidence-filing"],
      direction: "positive",
      importance: 0.82,
    },
  ],
  risks: [
    {
      claim_id: "brief-risk",
      text: "若原材料成本持续上升，新增收入可能无法转化为利润。",
      evidence_ref_ids: ["evidence-cost"],
    },
  ],
  catalysts: [],
  invalidation_conditions: [],
  analyst_cards: [],
  debate_digest: {
    agreed_facts: [],
    key_disagreements: [],
    changed_views: [],
    remaining_uncertainties: [],
  },
  risk_consensus: { conviction: 0.63, disagreement: "medium", abstained_roles: [] },
  data_quality: healthyDataQuality,
  evidence_refs: [
    { ref_id: "evidence-filing", label: "虚构公司中期经营说明", resolution_status: "available" },
  ],
  holding_review: null,
  learning_summary: {
    research_tilt: "favorable",
    confidence: 0.68,
    facts: ["订单规模同比增加，披露口径保持一致。"],
    inferences: ["交付稳定时，收入增长具有延续可能。"],
    unknowns: ["成本传导速度仍缺少连续两个季度的数据。"],
    upside: { title: "交付提速", condition: "按期完成新增订单", implication: "盈利能见度提高" },
    base: { title: "平稳兑现", condition: "交付与成本同步", implication: "维持中性偏积极" },
    downside: { title: "成本挤压", condition: "材料成本上行", implication: "下调研究倾向" },
    catalysts: ["下一期经营数据"],
    invalidation_conditions: ["订单延期超过一个交付窗口"],
    next_review: "下一份经营数据发布后复核。",
    holding_thesis_assessment: null,
  },
};

function statusFor(kind: ReaderFixtureKind): RunStatusLiteral {
  return kind === "failed" ? "failed" : "completed";
}

function makeSnapshot(kind: ReaderFixtureKind): RunSnapshotDTO {
  const status = statusFor(kind);
  return {
    run_id: RUN_IDS[kind],
    status,
    ticker: TICKERS[kind],
    asset_type: "stock",
    analysis_date: FIXED_DATE,
    selected_analysts: ["market", "fundamentals", "news", "social"],
    max_debate_rounds: 2,
    max_risk_discuss_rounds: 1,
    output_language: "Chinese",
    llm_provider: "local-fixture",
    quick_think_llm: "fixture-quick",
    deep_think_llm: "fixture-deep",
    configured_keys: { "local-fixture": true },
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:04:30Z",
    mode: "company_research",
    horizon: "medium",
    holding_context: null,
    latest_sequence: 1,
    final_signal: status === "completed" ? "HOLD" : null,
    final_report_artifact_id: status === "completed" ? "artifact-report" : null,
    completed_at: "2026-08-11T00:04:30Z",
    degraded_data_sources: kind === "partial" ? [
      {
        capability: "social_sentiment",
        status: "unavailable",
        attempted_vendors: ["fixture-vendor"],
        selected_vendors: [],
        reasons: [{ vendor: "fixture-vendor", code: "not_recorded" }],
        affected_sections: ["sentiment"],
      },
    ] : [],
    summary: status === "completed" ? "虚构研究运行已完成。" : null,
    error_category: status === "failed" ? "model_error" : null,
    error_message: status === "failed" ? "结构化输出未通过公开字段校验。" : null,
    retry_of: null,
    resumed_from_sequence: null,
    resume_fingerprint: null,
    runtime_semantics_hash: null,
    agent_state_schema_sha256: null,
    artifacts: status === "completed" ? ["artifact-report"] : [],
    redaction_manifest: [],
    event_schema_version: 1,
    metadata: {},
  };
}

function makeView(kind: ReaderFixtureKind): RunViewEnvelopeDTO {
  const snapshot = makeSnapshot(kind);
  const limited = kind === "partial" || kind === "failed" || kind === "legacy";
  const isLegacy = kind === "legacy";
  const value = kind === "typed"
    ? briefValue
    : kind === "partial"
      ? {
          ...briefValue,
          run_id: RUN_IDS.partial,
          ticker: TICKERS.partial,
          availability: "partial" as const,
          omissions: ["社交情绪来源未记录"],
          research_rating: "证据受限",
          data_quality: limitedDataQuality,
        }
      : null;
  return {
    schema_version: 2,
    projection_status: isLegacy ? "legacy_fallback" : kind === "partial" ? "partial" : "ready",
    reason_code: isLegacy ? "legacy_run" : kind === "partial" ? "terminal_data_incomplete" : null,
    source_sequence: 18,
    terminal: true,
    view: {
      run: {
        run_id: snapshot.run_id,
        ticker: snapshot.ticker,
        status: snapshot.status,
        mode: "company_research",
        horizon: "medium",
        created_at: snapshot.created_at,
        completed_at: snapshot.completed_at ?? null,
        latest_sequence: snapshot.latest_sequence,
        final_signal: snapshot.final_signal ?? null,
        error_category: snapshot.error_category ?? null,
        error_message: snapshot.error_message ?? null,
        duration_ms: 270_000,
        data_quality_level: limited ? "limited" : "healthy",
      },
      brief: {
        availability: value ? value.availability : "unavailable",
        reason_code: value ? null : isLegacy ? "legacy_run" : "run_failed",
        value,
      },
      workflow: {
        total_roles: 13,
        completed_roles: kind === "failed" ? 4 : 13,
        active_actor_id: null,
        stages: [],
      },
      debate_journey: {
        stages: [
          { stage_id: "analysts", status: kind === "failed" ? "failed" : "completed", rounds: null },
          { stage_id: "evidence", status: kind === "failed" ? "skipped" : "completed", rounds: null },
          { stage_id: "research", status: kind === "failed" ? "skipped" : "completed", rounds: 2 },
          { stage_id: "trading", status: kind === "failed" ? "skipped" : "completed", rounds: null },
          { stage_id: "risk", status: kind === "failed" ? "skipped" : "completed", rounds: 1 },
          { stage_id: "portfolio", status: kind === "failed" ? "skipped" : "completed", rounds: null },
        ],
        research_rating: value?.research_rating ?? null,
        disagreement_count: kind === "failed" ? 0 : 1,
        risk_consensus: { conviction: value ? 0.63 : null, disagreement: value ? "medium" : "unknown", abstained_roles: [] },
      },
      debate_summary: { availability: "unavailable", reason_code: "fixture_not_recorded", value: null },
      section_index: [],
      data_quality: limited ? limitedDataQuality : healthyDataQuality,
      market_projection_version: 1,
      available_audit_counts: {
        turns: kind === "failed" ? 4 : 12,
        prompts: kind === "legacy" ? 0 : 4,
        tool_calls: kind === "failed" ? 2 : 6,
        data_calls: kind === "failed" ? 2 : 8,
        artifacts: kind === "failed" ? 1 : 5,
        reports: kind === "failed" ? 0 : 1,
      },
      legacy_fallback: isLegacy
        ? { final_signal: "HOLD", portfolio_artifact_id: null, complete_report_artifact_id: "legacy-report" }
        : null,
    },
  };
}

const typedReader: LearningReaderV2DTO = {
  kind: "typed",
  schema_version: 2,
  run_id: RUN_IDS.typed,
  mode: "company_research",
  ticker: TICKERS.typed,
  horizon: "medium",
  as_of: "2026-08-11T00:04:30Z",
  availability: "full",
  decision_eligibility: "limited",
  evidence_verdict: "PASS",
  research_tilt: "favorable",
  rating_confidence: 0.68,
  claims: [
    {
      claim_key: "claim-growth",
      claim_type: "fact",
      text: "虚构订单数据表明未来两个交付窗口的可见度提高，但这不是对收入兑现的保证。",
      evidence_ref_ids: ["evidence-filing"],
      source_dates: ["2026-08-01"],
      supporting_claim_keys: [],
      coverage_ref_ids: [],
      confidence: 0.82,
      action_impact: { severity: "medium", direction: "positive", reason: "订单覆盖改善" },
      lifecycle_status: "active",
    },
    {
      claim_key: "claim-cost",
      claim_type: "inference",
      text: "成本传导可能滞后于交付确认，需要下一期数据验证利润率是否同步改善。",
      evidence_ref_ids: ["evidence-cost"],
      source_dates: ["2026-07-31"],
      supporting_claim_keys: ["claim-growth"],
      coverage_ref_ids: [],
      confidence: 0.61,
      action_impact: { severity: "high", direction: "negative", reason: "成本兑现待验证" },
      lifecycle_status: "active",
    },
    {
      claim_key: "claim-long-token",
      claim_type: "unknown",
      text: "LONG_IDENTIFIER_FOR_REFLOW_QINGLAN_ENERGY_DELIVERY_WINDOW_2026_WITHOUT_PRIVATE_LOCATOR_OR_HASH",
      evidence_ref_ids: [],
      source_dates: [],
      supporting_claim_keys: [],
      coverage_ref_ids: [],
      confidence: null,
      action_impact: { severity: "low", direction: "neutral", reason: "用于验证窄屏断行" },
      lifecycle_status: "active",
    },
  ],
  scenarios: {
    upside: {
      scenario_id: "upside",
      title: "交付提速",
      condition_claim_keys: ["claim-growth"],
      research_implication: "盈利可见度提高",
      trigger_claim_keys: ["claim-growth"],
      invalidation_claim_keys: ["claim-cost"],
      confidence: 0.62,
    },
    base: {
      scenario_id: "base",
      title: "平稳兑现",
      condition_claim_keys: ["claim-growth"],
      research_implication: "维持中性偏积极",
      trigger_claim_keys: ["claim-growth"],
      invalidation_claim_keys: ["claim-cost"],
      confidence: 0.68,
    },
    downside: {
      scenario_id: "downside",
      title: "成本挤压",
      condition_claim_keys: ["claim-cost"],
      research_implication: "研究倾向转为谨慎",
      trigger_claim_keys: ["claim-cost"],
      invalidation_claim_keys: ["claim-growth"],
      confidence: 0.44,
    },
  },
  catalysts: [
    {
      item_id: "catalyst-results",
      text: "下一期经营数据发布",
      claim_keys: ["claim-growth"],
      trigger_kind: "filing",
      trigger_value: "next-operating-update",
      due_at: "2026-10-31T00:00:00Z",
      status: "pending",
      evidence_ref_ids: [],
    },
  ],
  invalidation_conditions: [
    {
      item_id: "risk-margin",
      text: "连续两个观察窗口未能兑现交付，或成本率显著高于已披露区间。",
      claim_keys: ["claim-growth", "claim-cost"],
      trigger_kind: "filing",
      trigger_value: "next-two-updates",
      due_at: null,
      status: "pending",
      evidence_ref_ids: ["evidence-cost"],
    },
  ],
  review_plan: {
    next_review_at: "2026-10-31T00:00:00Z",
    item_ids: ["catalyst-results", "risk-margin"],
    reason: "等待下一期经营与成本数据",
  },
  analyst_cards: [
    {
      lens: "fundamentals",
      availability: "ready",
      summary: "订单覆盖改善，利润率仍是最重要的验证点。",
      confidence: 0.72,
      finding_claim_keys: ["claim-growth", "claim-cost"],
      capability_statuses: [{ capability: "fundamentals", status: "ok", coverage_ref_ids: [] }],
    },
    {
      lens: "news",
      availability: "limited",
      summary: "公开事件样本有限，未把单条新闻当作趋势。",
      confidence: 0.48,
      finding_claim_keys: ["claim-growth"],
      capability_statuses: [{ capability: "news_depth", status: "degraded", coverage_ref_ids: [] }],
    },
  ],
  data_quality: {
    level: "healthy",
    degraded_capabilities: [],
    unavailable_capabilities: [],
    conflicts: [],
    coverage_ref_ids: [],
  },
  evidence_refs: [
    { ref_id: "evidence-filing", source_label: "虚构公司中期经营说明", resolution_status: "available" },
    { ref_id: "evidence-cost", source_label: "虚构成本观察表", resolution_status: "available" },
  ],
  coverage_refs: [],
  omissions: [],
  thesis_diff: {
    schema_version: 1,
    run_id: RUN_IDS.typed,
    ticker: TICKERS.typed,
    horizon: "medium",
    previous_run_id: "run_golden_previous",
    baseline_completed_at: "2026-07-11T00:04:30Z",
    entries: [
      {
        claim_key: "claim-growth",
        diff_kind: "maintained",
        previous_claim_type: "fact",
        current_claim_type: "fact",
        previous_text: "订单覆盖改善。",
        current_text: "订单覆盖未来两个交付窗口。",
        previous_confidence: 0.72,
        current_confidence: 0.82,
        previous_lifecycle_status: "active",
        current_lifecycle_status: "active",
        change_flags: ["text_changed", "confidence_changed"],
        counter_evidence_ref_ids: [],
      },
      {
        claim_key: "claim-cost",
        diff_kind: "new",
        previous_claim_type: null,
        current_claim_type: "inference",
        previous_text: null,
        current_text: "成本传导仍需验证。",
        previous_confidence: null,
        current_confidence: 0.61,
        previous_lifecycle_status: null,
        current_lifecycle_status: "active",
        change_flags: ["text_changed", "status_changed"],
        counter_evidence_ref_ids: [],
      },
    ],
  },
  audit_entry: { route: "reader", artifact_count: 5, tool_call_count: 6, degradation_count: 0 },
};

function makeReader(kind: ReaderFixtureKind): ReaderResponseDTO | null {
  if (kind === "failed") return null;
  if (kind === "typed") return typedReader;
  if (kind === "partial") {
    return {
      ...typedReader,
      run_id: RUN_IDS.partial,
      ticker: TICKERS.partial,
      availability: "partial",
      decision_eligibility: "none",
      evidence_verdict: "LOW_CONFIDENCE",
      research_tilt: "insufficient_evidence",
      rating_confidence: 0.39,
      analyst_cards: typedReader.analyst_cards.map((card) => ({ ...card, availability: "limited" as const })),
      data_quality: {
        level: "limited",
        degraded_capabilities: ["news_depth"],
        unavailable_capabilities: ["social_sentiment"],
        conflicts: [],
        coverage_ref_ids: [],
      },
      omissions: ["社交情绪来源未记录", "新闻深度仅覆盖摘要"],
      thesis_diff: null,
      audit_entry: { route: "reader", artifact_count: 3, tool_call_count: 4, degradation_count: 2 },
    };
  }
  return {
    kind: "legacy",
    schema_version: 1,
    run_id: RUN_IDS.legacy,
    ticker: TICKERS.legacy,
    as_of: "2025-12-01T00:00:00Z",
    final_signal: "HOLD",
    portfolio_report_markdown: null,
    data_quality: { level: "unknown", summary: "历史运行未记录类型化数据质量。", degradation_count: 0 },
    stage_refs: [],
    audit_entry: { route: "reader", artifact_count: 1, tool_call_count: 0, degradation_count: 0 },
    reason_codes: ["legacy_run"],
  };
}

function makeAuditSummary(kind: ReaderFixtureKind): AuditSummaryDTO {
  const snapshot = makeSnapshot(kind);
  const availability = kind === "legacy" ? "legacy" : kind === "partial" || kind === "failed" ? "partial" : "ready";
  const partialReason = kind === "legacy" ? "legacy_event_gap" : availability === "partial" ? "terminal_data_incomplete" : null;
  const promptRecorded = kind !== "legacy";
  return {
    schema_version: 1,
    run_id: snapshot.run_id,
    source_sequence: 18,
    availability,
    reason_code: partialReason,
    run: {
      item_id: "run",
      status: snapshot.status === "failed" ? "failed" : "completed",
      ticker: snapshot.ticker,
      mode: kind === "legacy" ? null : "company_research",
      horizon: kind === "legacy" ? null : "medium",
      created_at: snapshot.created_at,
      completed_at: snapshot.completed_at ?? null,
      duration_ms: 270_000,
      llm_provider: kind === "legacy" ? "legacy" : "local-fixture",
      quick_think_llm: kind === "legacy" ? "not-recorded" : "fixture-quick",
      deep_think_llm: kind === "legacy" ? "not-recorded" : "fixture-deep",
      data_quality: kind === "typed" ? "healthy" : "limited",
    },
    counts: {
      stages: 6,
      roles: kind === "failed" ? 4 : 13,
      turns: kind === "failed" ? 4 : 12,
      model_calls: kind === "failed" ? 3 : 14,
      tool_calls: kind === "legacy" ? 0 : kind === "failed" ? 2 : 6,
      artifacts: kind === "failed" ? 1 : kind === "legacy" ? 1 : 5,
      prompts: promptRecorded ? 1 : 0,
      configs: promptRecorded ? 1 : 0,
      reports: kind === "failed" ? 0 : 1,
    },
    sections: [
      { section_id: "overview", availability: "ready", reason_code: null, item_count: 1 },
      { section_id: "roles", availability: "ready", reason_code: null, item_count: kind === "failed" ? 4 : 13 },
      { section_id: "capabilities", availability: kind === "typed" ? "ready" : "partial", reason_code: partialReason, item_count: kind === "typed" ? 0 : 1 },
      { section_id: "tools", availability: kind === "legacy" ? "not_recorded" : "ready", reason_code: kind === "legacy" ? "not_recorded" : null, item_count: kind === "legacy" ? 0 : 1 },
      { section_id: "artifacts", availability: "ready", reason_code: null, item_count: 1 },
      { section_id: "prompt_config", availability: promptRecorded ? "ready" : "not_recorded", reason_code: promptRecorded ? null : "not_recorded", item_count: promptRecorded ? 2 : 0 },
    ],
    stage_navigation: [
      { stage_id: "analysts", label: "分析师研究", status: kind === "failed" ? "failed" : "completed", availability: "ready", reason_code: null, related_selections: [{ kind: "role", id: "analyst.fundamentals" }] },
      { stage_id: "research", label: "研究辩论", status: kind === "failed" ? "not_started" : "completed", availability: kind === "legacy" ? "not_recorded" : "ready", reason_code: kind === "legacy" ? "legacy_event_gap" : null, related_selections: [] },
      { stage_id: "risk", label: "风险评估", status: kind === "failed" ? "not_started" : "completed", availability: kind === "legacy" ? "not_recorded" : "ready", reason_code: kind === "legacy" ? "legacy_event_gap" : null, related_selections: [] },
    ],
    roles: [
      { item_id: "analyst.fundamentals", actor_id: "analyst.fundamentals", label: "基本面分析师", status: kind === "failed" ? "failed" : "completed", turn_count: 1, model_call_count: 1, duration_ms: 42_000 },
    ],
    capabilities: kind === "typed" ? [] : [
      { item_id: "capability-social", label: "社交情绪覆盖", status: "unavailable", reason_codes: ["not_recorded"], affected_sections: ["sentiment"] },
    ],
    tools: kind === "legacy" ? [] : [
      { item_id: "tool-market", tool_name: "get_fixture_market_context", status: "committed", execution_count: 1, cache_status: "fixture", failure_code: null },
    ],
    artifacts: [
      { item_id: "artifact-report", label: "脱敏研究报告", artifact_kind: "report-final", media_type: "text/markdown", byte_size: 512, producer_stage: "portfolio", content_exposure: "safe_inline", is_report: true },
    ],
    prompts: promptRecorded ? [
      { item_id: "prompt-redacted", label: "Prompt snapshot（已脱敏）", actor_id: "analyst.fundamentals", model_call_id: "model-fixture", redaction_status: "redacted", byte_size: 96 },
    ] : [],
    configs: promptRecorded ? [
      { item_id: "config-redacted", label: "Effective config（已脱敏）", actor_id: null, model_call_id: null, redaction_status: "redacted", byte_size: 64 },
    ] : [],
  };
}

function makeAuditDetail(kind: ReaderFixtureKind, selection: AuditSelectionDTO): AuditDetailDTO {
  const titles: Record<AuditSelectionDTO["kind"], string> = {
    run: "运行事实",
    role: "基本面分析师",
    capability: "社交情绪覆盖",
    tool: "get_fixture_market_context",
    artifact: "脱敏研究报告",
    prompt: "Prompt snapshot（已脱敏）",
    config: "Effective config（已脱敏）",
    report: "脱敏研究报告",
  };
  const inline = selection.kind === "artifact" || selection.kind === "report";
  return {
    schema_version: 1,
    run_id: RUN_IDS[kind],
    source_sequence: 18,
    selection,
    availability: "ready",
    reason_code: null,
    title: titles[selection.kind],
    facts: [
      { label: "状态", value: kind === "failed" ? "failed" : "completed" },
      { label: "来源", value: "synthetic-fixture" },
    ],
    related_selections: [],
    content: inline
      ? {
          mode: "inline",
          media_type: "text/markdown",
          byte_size: 196,
          redaction_status: "redacted",
          text: "## 已脱敏研究摘要\n\n该内容只包含虚构事实，用于验证安全 Markdown 与中文断行。",
          download_url: null,
        }
      : {
          mode: "none",
          media_type: null,
          byte_size: null,
          redaction_status: "redacted",
          text: null,
          download_url: null,
        },
  };
}

function makeCompanion(kind: ReaderFixtureKind, selection: CompanionSelectionDTO): CompanionDTO {
  return {
    schema_version: 1,
    run_id: RUN_IDS[kind],
    selection,
    summary: "这是一条基于虚构公开证据生成的伴读摘要。",
    actual_coverage: ["虚构经营说明", "虚构成本观察表"],
    conclusion_impact: "支持保留当前结论，同时维持成本验证条件。",
    next_validation: "在下一期经营数据发布后复核交付与成本是否同步。",
  };
}

export interface ScenarioFixture {
  kind: ReaderFixtureKind;
  runId: string;
  ticker: string;
  snapshot: RunSnapshotDTO;
  recentRuns: RecentRunsPageDTO;
  view: RunViewEnvelopeDTO;
  reader: ReaderResponseDTO | null;
  auditSummary: AuditSummaryDTO;
  auditDetail(selection: AuditSelectionDTO): AuditDetailDTO;
  companion(selection: CompanionSelectionDTO): CompanionDTO;
}

export function scenarioFixture(kind: ReaderFixtureKind): ScenarioFixture {
  const snapshot = makeSnapshot(kind);
  return {
    kind,
    runId: RUN_IDS[kind],
    ticker: TICKERS[kind],
    snapshot,
    recentRuns: {
      schema_version: 1,
      items: [
        {
          run_id: snapshot.run_id,
          ticker: snapshot.ticker,
          status: snapshot.status,
          created_at: snapshot.created_at,
          completed_at: snapshot.completed_at ?? null,
          latest_sequence: snapshot.latest_sequence,
          final_signal: snapshot.final_signal ?? null,
          error_category: snapshot.error_category ?? null,
          duration_ms: 270_000,
          data_quality_level: kind === "typed" ? "healthy" : "limited",
        },
      ],
      next_cursor: null,
    },
    view: makeView(kind),
    reader: makeReader(kind),
    auditSummary: makeAuditSummary(kind),
    auditDetail: (selection) => makeAuditDetail(kind, selection),
    companion: (selection) => makeCompanion(kind, selection),
  };
}

export function terminalEvent(fixture: ScenarioFixture): string {
  const eventType = fixture.kind === "failed" ? "run.failed" : "run.completed";
  const event = {
    event_id: `event-${fixture.kind}-terminal`,
    run_id: fixture.runId,
    sequence: 1,
    timestamp: "2026-08-11T00:04:30Z",
    schema_version: 1,
    type: eventType,
    payload: {
      run_status: fixture.snapshot.status,
      summary: fixture.snapshot.summary ?? null,
      final_signal: fixture.snapshot.final_signal ?? null,
      final_report_artifact_id: fixture.snapshot.final_report_artifact_id ?? null,
      completed_at: fixture.snapshot.completed_at ?? null,
      ...(fixture.kind === "failed"
        ? {
            error_category: fixture.snapshot.error_category ?? null,
            error_message: fixture.snapshot.error_message ?? null,
          }
        : {}),
    },
  };
  return `id: 1\nevent: ${eventType}\ndata: ${JSON.stringify(event)}\n\n`;
}
