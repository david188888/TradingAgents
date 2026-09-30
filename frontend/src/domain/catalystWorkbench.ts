/**
 * T28/T30/T31 — the catalyst workbench's pure reading layer.
 *
 * Everything a reader sees on the first screen is derived here, from the
 * committed `catalyst-research-case-v1` artifact only. Nothing in this file
 * fetches, calls a model, or reaches a data source: the values are exactly the
 * ones the server already committed, which is what design 7.4 means by
 * "reading calls nothing".
 *
 * Three rules are load-bearing and are asserted by the tests that sit next to
 * this file:
 *
 * 1. **The counting rule is the backend's.** `catalystBudgetedTexts` and
 *    `catalystCharacterCount` are a re-implementation, not an import, of
 *    `CatalystBrief.budgeted_texts()` in
 *    `tradingagents/agents/schemas/_catalyst_research.py`. They must agree
 *    with `catalystBriefBudget.test.ts` on the same fixture, otherwise the
 *    page would enforce a budget the server never applied.
 * 2. **A readable artifact is not a sufficient result.** `ready` means the
 *    artifact parses; the case may still be `blocked`. The screen state is
 *    derived from run lifecycle *and* case completeness, which are two
 *    separate axes, never from `state === "ready"` alone.
 * 3. **A percentage appears only when real work-completed data exists.**
 *    There is no synthesised total. When the stage data cannot be counted,
 *    `catalystStageProgress` returns no `percent` and the UI shows stage
 *    status instead of a fake 90%.
 */
import type {
  CatalystBriefDTO,
  CatalystBriefLineDTO,
  CatalystEvidenceDTO,
  CatalystEventDTO,
  CatalystResearchCaseDTO,
  CatalystResearchPriority,
  CatalystReadState,
  ResearchProfile,
} from "../api/contracts";

/** Re-exported so consumers never import the budget from two places. */
export const BRIEF_BUDGET = 420;
export const SAFETY_OVERFLOW_BUDGET = 120;

// ---------------------------------------------------------------------------
// Research priority (design 4.3 row 2)
// ---------------------------------------------------------------------------

/**
 * Four explanatory categories, never a number.
 *
 * The labels are the product's four buckets. `never` is the load-bearing part:
 * a priority that has to be rendered as a percentage is the uncalibrated
 * scoring design section 6 forbids, so there is deliberately no numeric
 * fallback path in this map.
 */
export const RESEARCH_PRIORITY_COPY: Readonly<
  Record<CatalystResearchPriority, { label: string; hint: string }>
> = {
  verify_first: {
    label: "优先核查",
    hint: "存在明确、可验证且与时间相关的问题，值得投入核查；不表示基本面好或应买入。",
  },
  keep_watching: {
    label: "持续观察",
    hint: "有线索，但触发条件、时间或兑现证据仍不完整。",
  },
  defer_research: {
    label: "暂缓研究",
    hint: "本次覆盖范围内未发现足够明确的近期待验证问题。",
  },
  insufficient_information: {
    label: "信息不足",
    hint: "身份、核心证据、时点或反证不足以支撑判断。",
  },
};

export function researchPriorityLabel(priority: CatalystResearchPriority): string {
  return RESEARCH_PRIORITY_COPY[priority]?.label ?? "信息不足";
}

export function researchPriorityHint(priority: CatalystResearchPriority): string {
  return RESEARCH_PRIORITY_COPY[priority]?.hint ?? RESEARCH_PRIORITY_COPY.insufficient_information.hint;
}

// ---------------------------------------------------------------------------
// The character budget — mirrors _catalyst_research.py
// ---------------------------------------------------------------------------

function textOf(line: CatalystBriefLineDTO | null | undefined): string | null {
  return typeof line?.text === "string" ? line.text : null;
}

/**
 * The strings the 420 budget is measured over, in the same order and with the
 * same membership the backend uses.
 *
 * An ordinary brief counts the judgement, the primary catalyst, one line per
 * key-evidence entry, the key question, the next check, and every critical
 * limitation. The safety-overflow brief counts only its code template
 * (judgement, key question, next check): the limitation list is the payload the
 * overflow rule exists to keep intact, and design 4.3 explicitly exempts it.
 */
export function catalystBudgetedTexts(brief: CatalystBriefDTO): string[] {
  if (brief.kind === "safety_overflow") {
    const template = [brief.judgement, textOf(brief.key_question), textOf(brief.next_check)];
    return template.filter((item): item is string => item !== null);
  }
  const texts: Array<string | null> = [brief.judgement, textOf(brief.primary_catalyst)];
  for (const line of brief.key_evidence) texts.push(textOf(line));
  texts.push(textOf(brief.key_question), textOf(brief.next_check));
  for (const line of brief.critical_limitations) texts.push(textOf(line));
  return texts.filter((item): item is string => item !== null);
}

/**
 * Unicode characters, not UTF-16 code units: `Array.from` iterates by code
 * point, which is what "Unicode 字符" means in the design and what `len()`
 * means in Python.
 */
export function catalystCharacterCount(brief: CatalystBriefDTO): number {
  return catalystBudgetedTexts(brief).reduce(
    (total, text) => total + Array.from(text).length,
    0,
  );
}

export function isSafetyOverflow(brief: CatalystBriefDTO): boolean {
  return brief.kind === "safety_overflow";
}

export function briefBudgetForKind(brief: CatalystBriefDTO): number {
  return isSafetyOverflow(brief) ? SAFETY_OVERFLOW_BUDGET : BRIEF_BUDGET;
}

// ---------------------------------------------------------------------------
// Runtime narrowing of the untyped projection bodies
// ---------------------------------------------------------------------------

/**
 * `CatalystReadyV1DTO.brief` and `.case` are `Record<string, unknown>` on the
 * wire because the endpoint returns whatever the committed artifact holds.
 * The page has to render them, so they are parsed here — with real field
 * checks, never with `as` casts that would make a renamed backend field look
 * like a working UI.
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function parseBriefLine(value: unknown): CatalystBriefLineDTO | null {
  if (!isRecord(value)) return null;
  const text = asString(value.text);
  if (text === null) return null;
  return {
    text,
    finding_ids: asStringArray(value.finding_ids),
    event_ids: asStringArray(value.event_ids),
    challenge_ids: asStringArray(value.challenge_ids),
  };
}

function parseBriefLines(value: unknown): CatalystBriefLineDTO[] {
  if (!Array.isArray(value)) return [];
  return value.map(parseBriefLine).filter((line): line is CatalystBriefLineDTO => line !== null);
}

const PRIORITIES: readonly CatalystResearchPriority[] = [
  "verify_first",
  "keep_watching",
  "defer_research",
  "insufficient_information",
];

function parsePriority(value: unknown): CatalystResearchPriority | null {
  return typeof value === "string" && (PRIORITIES as readonly string[]).includes(value)
    ? (value as CatalystResearchPriority)
    : null;
}

/** Returns null when the payload is not a brief this page can render. */
export function parseCatalystBrief(value: unknown): CatalystBriefDTO | null {
  if (!isRecord(value)) return null;
  const judgement = asString(value.judgement);
  const keyQuestion = parseBriefLine(value.key_question);
  const nextCheck = parseBriefLine(value.next_check);
  const priority = parsePriority(value.priority);
  if (judgement === null || keyQuestion === null || nextCheck === null || priority === null) {
    return null;
  }
  const kind = value.kind === "safety_overflow" ? "safety_overflow" : "ordinary";
  return {
    kind,
    judgement,
    priority,
    primary_catalyst_event_id: asString(value.primary_catalyst_event_id),
    primary_catalyst: parseBriefLine(value.primary_catalyst),
    key_evidence: parseBriefLines(value.key_evidence),
    key_question: keyQuestion,
    next_check: nextCheck,
    critical_limitations: parseBriefLines(value.critical_limitations),
    overflow_reason: asString(value.overflow_reason),
  };
}

function parseEvidence(value: unknown): CatalystEvidenceDTO | null {
  if (!isRecord(value)) return null;
  const evidence_id = asString(value.evidence_id);
  const source_name = asString(value.source_name);
  if (evidence_id === null || source_name === null) return null;
  return {
    evidence_id,
    run_id: asString(value.run_id) ?? "",
    ticker: asString(value.ticker) ?? "",
    capability: asString(value.capability) ?? "",
    source_tier: (asString(value.source_tier) ?? "derived") as CatalystEvidenceDTO["source_tier"],
    source_name,
    public_url: asString(value.public_url),
    source_family_id: asString(value.source_family_id) ?? evidence_id,
    republished_from_evidence_id: asString(value.republished_from_evidence_id),
    published_at: asString(value.published_at),
    observed_at: asString(value.observed_at),
    captured_at: asString(value.captured_at) ?? "",
    usable_as_of: asString(value.usable_as_of),
    time_basis: asString(value.time_basis) ?? "",
    value_basis: asString(value.value_basis) ?? "",
    availability: (asString(value.availability) ?? "unverified") as CatalystEvidenceDTO["availability"],
  };
}

function parseEvent(value: unknown): CatalystEventDTO | null {
  if (!isRecord(value)) return null;
  const event_id = asString(value.event_id);
  const title = asString(value.title);
  if (event_id === null || title === null) return null;
  return {
    event_id,
    run_id: asString(value.run_id) ?? "",
    ticker: asString(value.ticker) ?? "",
    event_type: asString(value.event_type) ?? "",
    version: typeof value.version === "number" ? value.version : 1,
    title,
    status: (asString(value.status) ?? "planned") as CatalystEventDTO["status"],
    announced_at: asString(value.announced_at),
    occurred_on: asString(value.occurred_on),
    occurred_period_end: asString(value.occurred_period_end),
    date_precision: (asString(value.date_precision) ?? "unknown") as CatalystEventDTO["date_precision"],
    date_evidence_ids: asStringArray(value.date_evidence_ids),
    updated_by_evidence_id: asString(value.updated_by_evidence_id),
    supersedes_event_id: asString(value.supersedes_event_id),
  };
}

/**
 * The narrow slice of the committed case the workbench needs. The full
 * `CatalystResearchCaseDTO` is not required to render the first screen or the
 * evidence drawer, and re-validating every finding and disposition here would
 * duplicate the server's job for no reader-visible gain.
 */
export interface CatalystCaseSlice {
  as_of: string | null;
  completeness: CatalystResearchCaseDTO["completeness"] | null;
  quality: CatalystResearchCaseDTO["quality"] | null;
  reason_codes: string[];
  evidence: CatalystEvidenceDTO[];
  events: CatalystEventDTO[];
  /** The committed findings, kept as opaque text lines keyed by id. */
  findings: Array<{ finding_id: string; role: string; kind: string; text: string; limitations: string[] }>;
  challenges: Array<{ challenge_id: string; kind: string; severity: string; statement: string; is_key: boolean }>;
  priority_candidate: CatalystResearchPriority | null;
  blocking_reasons: string[];
}

export function parseCatalystCase(value: unknown): CatalystCaseSlice | null {
  if (!isRecord(value)) return null;
  const priorityDecision = isRecord(value.priority_decision) ? value.priority_decision : null;
  return {
    as_of: asString(value.as_of),
    completeness: (asString(value.completeness) ?? null) as CatalystCaseSlice["completeness"],
    quality: (asString(value.quality) ?? null) as CatalystCaseSlice["quality"],
    reason_codes: asStringArray(value.reason_codes),
    evidence: Array.isArray(value.evidence)
      ? value.evidence.map(parseEvidence).filter((item): item is CatalystEvidenceDTO => item !== null)
      : [],
    events: Array.isArray(value.events)
      ? value.events.map(parseEvent).filter((item): item is CatalystEventDTO => item !== null)
      : [],
    findings: Array.isArray(value.findings)
      ? value.findings.flatMap((item) => {
          if (!isRecord(item)) return [];
          const finding_id = asString(item.finding_id);
          const text = asString(item.text);
          if (finding_id === null || text === null) return [];
          return [{
            finding_id,
            role: asString(item.role) ?? "",
            kind: asString(item.kind) ?? "",
            text,
            limitations: Array.isArray(item.limitations)
              ? item.limitations.filter((limitation): limitation is string => typeof limitation === "string")
              : [],
          }];
        })
      : [],
    challenges: Array.isArray(value.challenges)
      ? value.challenges.flatMap((item) => {
          if (!isRecord(item)) return [];
          const challenge_id = asString(item.challenge_id);
          const statement = asString(item.statement);
          if (challenge_id === null || statement === null) return [];
          return [{
            challenge_id,
            kind: asString(item.kind) ?? "",
            severity: asString(item.severity) ?? "",
            statement,
            is_key: item.is_key === true,
          }];
        })
      : [],
    priority_candidate: parsePriority(priorityDecision?.candidate_priority ?? null),
    blocking_reasons: asStringArray(priorityDecision?.blocking_reasons),
  };
}

// ---------------------------------------------------------------------------
// The seven first-screen rows (design 4.3)
// ---------------------------------------------------------------------------

export const CATALYST_ROW_IDS = [
  "judgement",
  "priority",
  "catalyst",
  "evidence",
  "doubt",
  "next_check",
  "limitations",
] as const;
export type CatalystRowId = (typeof CATALYST_ROW_IDS)[number];

/** Design 4.3 caps key evidence at 3 and allows exactly 1 primary catalyst. */
export const MAX_KEY_EVIDENCE = 3;

export const CATALYST_ROW_LABELS: Readonly<Record<CatalystRowId, string>> = {
  judgement: "研究判断",
  priority: "研究优先级",
  catalyst: "关键催化",
  evidence: "依据",
  doubt: "最大疑点",
  next_check: "下一验证",
  limitations: "关键限制",
};

export interface CatalystEvidenceRef {
  kind: "evidence" | "event" | "challenge";
  id: string;
  /** Present only when the id resolves inside this run's case. */
  label: string | null;
}

export interface CatalystBriefRow {
  id: CatalystRowId;
  label: string;
  /** Every line this row shows, in order. Never truncated by this module. */
  lines: string[];
  /** Per-line traceability, index-aligned with `lines`. */
  refs: CatalystEvidenceRef[][];
  /** A row that says so out loud instead of rendering nothing. */
  placeholder: string | null;
}

export interface CatalystFirstScreen {
  brief: CatalystBriefDTO;
  priority: CatalystResearchPriority;
  priority_label: string;
  priority_hint: string;
  overflow: boolean;
  /** The ≤120-character code template, shown when `overflow` is true. */
  overflow_reason: string | null;
  character_count: number;
  budget: number;
  rows: CatalystBriefRow[];
  /** The full limitation list, exempt from the budget and never truncated. */
  limitations: string[];
  limitation_refs: CatalystEvidenceRef[][];
}
/**
 * Whether a date may be stated.
 *
 * Design 4.3: a catalyst may carry an explicit range or be marked pending
 * confirmation, and a date must never be invented to fill the template. The
 * committed event carries `date_precision`; `unknown` is the only answer that
 * permits "待确认", and it never yields a rendered date.
 */
export function catalystDateNote(event: CatalystEventDTO | null): string {
  if (event === null || event.date_precision === "unknown" || event.occurred_on === null) {
    return "时间范围待确认";
  }
  return `时间：${event.occurred_on}`;
}

function buildRefs(
  line: CatalystBriefLineDTO,
  kase: CatalystCaseSlice | null,
  eventLabels: Map<string, string>,
): CatalystEvidenceRef[] {
  const refs: CatalystEvidenceRef[] = [];
  for (const id of line.finding_ids) {
    const found = kase?.findings.find((item) => item.finding_id === id);
    refs.push({ kind: "evidence", id, label: found === undefined ? null : found.text });
  }
  for (const id of line.event_ids) {
    refs.push({ kind: "event", id, label: eventLabels.get(id) ?? null });
  }
  for (const id of line.challenge_ids) {
    const found = kase?.challenges.find((item) => item.challenge_id === id);
    refs.push({ kind: "challenge", id, label: found === undefined ? null : found.statement });
  }
  return refs;
}

/**
 * Build the seven rows.
 *
 * The rules this enforces, each of which has a failing-before test:
 *  * priority renders as one of four labels, never a number;
 *  * at most one primary catalyst, and at most three evidence lines;
 *  * the doubt row always says something — either the challenge or an explicit
 *    "反证覆盖不足";
 *  * the limitation list is passed through whole, in order, with every entry
 *    still reachable.
 */
export function buildCatalystFirstScreen(
  brief: CatalystBriefDTO,
  kase: CatalystCaseSlice | null,
): CatalystFirstScreen {
  const eventLabels = new Map<string, string>();
  for (const event of kase?.events ?? []) eventLabels.set(event.event_id, event.title);

  const overflow = isSafetyOverflow(brief);
  const lines = (items: CatalystBriefLineDTO[]): { texts: string[]; refs: CatalystEvidenceRef[][] } => ({
    texts: items.map((item) => item.text),
    refs: items.map((item) => buildRefs(item, kase, eventLabels)),
  });

  const evidenceItems = brief.key_evidence.slice(0, MAX_KEY_EVIDENCE);
  const evidence = lines(evidenceItems);
  const limitationItems = brief.critical_limitations;
  const limitations = lines(limitationItems);

  const primaryEvent =
    brief.primary_catalyst_event_id === null
      ? null
      : kase?.events.find((event) => event.event_id === brief.primary_catalyst_event_id) ?? null;
  const primaryLine = brief.primary_catalyst;
  const catalystText = primaryLine === null ? null : primaryLine.text;
  const catalystRow: CatalystBriefRow = {
    id: "catalyst",
    label: CATALYST_ROW_LABELS.catalyst,
    lines: catalystText === null ? [] : [`${catalystText}。${catalystDateNote(primaryEvent)}`],
    refs: primaryLine === null ? [] : [buildRefs(primaryLine, kase, eventLabels)],
    placeholder: "本次覆盖窗口内未发现明确的近期主催化；不代表不存在事件。",
  };

  const doubtText = brief.key_question.text;
  const rows: CatalystBriefRow[] = [
    {
      id: "judgement",
      label: CATALYST_ROW_LABELS.judgement,
      lines: [brief.judgement],
      refs: [[]],
      placeholder: null,
    },
    {
      id: "priority",
      label: CATALYST_ROW_LABELS.priority,
      lines: [researchPriorityLabel(brief.priority)],
      refs: [[]],
      placeholder: null,
    },
    catalystRow,
    {
      id: "evidence",
      label: CATALYST_ROW_LABELS.evidence,
      lines: evidence.texts,
      refs: evidence.refs,
      placeholder: "本次没有可引用的关键依据；不以推测补足。",
    },
    {
      id: "doubt",
      label: CATALYST_ROW_LABELS.doubt,
      lines: [doubtText],
      refs: [buildRefs(brief.key_question, kase, eventLabels)],
      placeholder: null,
    },
    {
      id: "next_check",
      label: CATALYST_ROW_LABELS.next_check,
      lines: [brief.next_check.text],
      refs: [buildRefs(brief.next_check, kase, eventLabels)],
      placeholder: null,
    },
    {
      id: "limitations",
      label: CATALYST_ROW_LABELS.limitations,
      lines: limitations.texts,
      refs: limitations.refs,
      placeholder: "本次运行没有会改变优先级或可信度的已知限制。",
    },
  ];

  return {
    brief,
    priority: brief.priority,
    priority_label: researchPriorityLabel(brief.priority),
    priority_hint: researchPriorityHint(brief.priority),
    overflow,
    overflow_reason: overflow ? brief.overflow_reason : null,
    character_count: catalystCharacterCount(brief),
    budget: briefBudgetForKind(brief),
    rows,
    limitations: limitations.texts,
    limitation_refs: limitations.refs,
  };
}

// ---------------------------------------------------------------------------
// Four-stage progress (design 4.2, 4.5)
// ---------------------------------------------------------------------------

export const CATALYST_STAGE_IDS = [
  "evidence",
  "specialists",
  "refutation",
  "synthesis",
] as const;
export type CatalystStageId = (typeof CATALYST_STAGE_IDS)[number];

export const CATALYST_STAGE_COPY: Readonly<Record<CatalystStageId, { label: string; detail: string }>> = {
  evidence: { label: "准备证据", detail: "取数、去重与身份/覆盖校验" },
  specialists: { label: "专项分析", detail: "催化事件、经营兑现、市场反应" },
  refutation: { label: "反证核验", detail: "一次独立反证审查" },
  synthesis: { label: "综合发布", detail: "结构化简报与投影发布" },
};

export type CatalystStageStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "interrupted";

export interface CatalystStageProgressRow {
  id: CatalystStageId;
  label: string;
  detail: string;
  status: CatalystStageStatus;
  /** Per-stage elapsed milliseconds when the server measured it, else null. */
  duration_ms: number | null;
  /**
   * Real completed-work counts for this stage, or null when the run has
   * produced no countable work. Null is the honest answer and is what keeps
   * the page from rendering a synthesised percentage.
   */
  completed_units: number | null;
  total_units: number | null;
}

export interface CatalystStageProgress {
  stages: CatalystStageProgressRow[];
  /**
   * Overall completion, or null when it cannot be computed from real counts.
   * A null percent is rendered as stage status, never as a stand-in number.
   */
  percent: number | null;
  /**
   * Streaming candidates that have not been committed. They are in progress,
   * never a conclusion (design 4.2).
   */
  uncommitted_candidates: number;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseStageDurations(value: unknown): Map<string, number> {
  const out = new Map<string, number>();
  if (!Array.isArray(value)) return out;
  for (const entry of value) {
    if (!Array.isArray(entry) || entry.length < 2) continue;
    const key = asString(entry[0]);
    const ms = asNumber(entry[1]);
    if (key !== null && ms !== null) out.set(key, ms);
  }
  return out;
}

/**
 * Map a live run onto the four bounded stages.
 *
 * `counts` is what the server actually measured. When it is absent — which is
 * the normal case before agent E publishes stage counters — every stage reports
 * `completed_units: null`, so `percent` is null and the page shows stage
 * status. The 90% that a naive progress bar would show never appears.
 */
export function catalystStageProgress(input: {
  run_status: string;
  stage_status: Partial<Record<CatalystStageId, CatalystStageStatus>> | null;
  stage_durations_ms: unknown;
  counts?: Partial<Record<CatalystStageId, { completed: number; total: number }>> | null;
  uncommitted_candidates?: number;
}): CatalystStageProgress {
  const durations = parseStageDurations(input.stage_durations_ms);
  const stages = CATALYST_STAGE_IDS.map((id): CatalystStageProgressRow => {
    const count = input.counts?.[id] ?? null;
    return {
      id,
      label: CATALYST_STAGE_COPY[id].label,
      detail: CATALYST_STAGE_COPY[id].detail,
      status: input.stage_status?.[id] ?? statusForIdleRun(input.run_status),
      duration_ms: durations.get(id) ?? null,
      completed_units: count === null ? null : count.completed,
      total_units: count === null ? null : count.total,
    };
  });

  const withCounts = stages.filter(
    (stage) => stage.completed_units !== null && stage.total_units !== null && (stage.total_units ?? 0) > 0,
  );
  const percent =
    withCounts.length === CATALYST_STAGE_IDS.length
      ? Math.round(
          withCounts.reduce((total, stage) => total + (stage.completed_units ?? 0) / (stage.total_units ?? 1), 0) /
            CATALYST_STAGE_IDS.length *
            100,
        )
      : null;

  return {
    stages,
    percent,
    uncommitted_candidates:
      typeof input.uncommitted_candidates === "number" && input.uncommitted_candidates > 0
        ? Math.floor(input.uncommitted_candidates)
        : 0,
  };
}

function statusForIdleRun(runStatus: string): CatalystStageStatus {
  if (runStatus === "queued" || runStatus === "created") return "pending";
  if (runStatus === "cancelled") return "cancelled";
  if (runStatus === "interrupted") return "interrupted";
  if (runStatus === "failed") return "failed";
  return "pending";
}

// ---------------------------------------------------------------------------
// The eight screen states (design 4.5)
// ---------------------------------------------------------------------------

export type CatalystScreenStateId =
  | "queued"
  | "running"
  | "complete_sufficient"
  | "complete_limited"
  | "insufficient_evidence"
  | "blocked_or_error"
  | "cancelled_or_interrupted"
  | "legacy_record"
  | "projection_corrupt";

/**
 * Every reachable state, in the order design 4.5 lists them.
 *
 * This exists so a test can assert the union has no member without a
 * producing input. A union of ids is exactly the shape that lets an
 * unreachable row hide: TypeScript is happy, the id is distinct from its
 * neighbours, and nothing ever returns it.
 */
export const CATALYST_SCREEN_STATE_IDS: readonly CatalystScreenStateId[] = [
  "queued",
  "running",
  "complete_sufficient",
  "complete_limited",
  "insufficient_evidence",
  "blocked_or_error",
  "cancelled_or_interrupted",
  "legacy_record",
  "projection_corrupt",
] as const;

export interface CatalystScreenState {
  id: CatalystScreenStateId;
  title: string;
  body: string;
  /** What the page may offer, per design 4.5's "可执行操作" column. */
  actions: Array<"view_process" | "view_gaps" | "view_sources" | "retry" | "resume" | "audit" | "new_run" | "retry_read">;
  /** A colour must never be the only carrier of this state. */
  tone: "neutral" | "live" | "good" | "limited" | "bad";
}

export interface CatalystScreenInput {
  run_status: string;
  state: CatalystReadState | null;
  /**
   * Completeness and quality, as a caller may have them: the flat fields the
   * projection body carries, or nested inside a `ready` state.
   *
   * The two are read through `completenessOf` / `qualityOf` below rather than
   * off one arm of the union. Reading them off the `ready` arm only, while the
   * input type offers them flat, is how `complete_limited` ended up
   * unreachable: the branch that consumed `partial` came first, so the
   * priority-ceiling case underneath it could never run.
   */
  completeness: CatalystResearchCaseDTO["completeness"] | null;
  quality: CatalystResearchCaseDTO["quality"] | null;
  profile: ResearchProfile | null;
  error: Error | null;
}

function completenessOf(input: CatalystScreenInput): CatalystResearchCaseDTO["completeness"] | null {
  if (input.state !== null && input.state.state === "ready") return input.state.completeness;
  return input.completeness;
}

function qualityOf(input: CatalystScreenInput): CatalystResearchCaseDTO["quality"] | null {
  if (input.state !== null && input.state.state === "ready") return input.state.quality;
  return input.quality;
}

/**
 * One row of design 4.5's state matrix.
 *
 * Run lifecycle and research quality are two independent axes, so the state is
 * chosen from the pair. `state === "ready"` alone is never sufficient: a
 * `ready` + `blocked` case is rendered as blocked, not as a completed research
 * pass (design 7.4).
 */
export function catalystScreenState(input: CatalystScreenInput): CatalystScreenState {
  if (input.error !== null) {
    return {
      id: "projection_corrupt",
      title: "无法读取研究投影",
      body: "本次读取没有成功。重试只重新读取已提交事实，不会重新调用模型或数据源。",
      actions: ["retry_read", "audit"],
      tone: "bad",
    };
  }

  if (input.run_status === "cancelled" || input.run_status === "interrupted") {
    return {
      id: "cancelled_or_interrupted",
      title: input.run_status === "cancelled" ? "本次运行已取消" : "本次运行已中断",
      body: "这不是一次完整结果。已提交的资料只能作为研究过程查看，不构成研究结论。",
      actions: input.run_status === "interrupted" ? ["resume", "new_run", "view_process"] : ["new_run", "view_process"],
      tone: "limited",
    };
  }

  const state = input.state;
  if (state !== null && state.state === "unsupported") {
    return {
      id: "legacy_record",
      title: "旧记录，无新版研究产物",
      body:
        state.reason_code === "classic_profile"
          ? "这次运行使用旧版研究流程，没有研究优先级可展示。系统不会从旧文字反推优先级，也不会在后台重算。"
          : "这次运行的 profile 无法识别，按旧记录处理，不做任何推算。",
      actions: ["view_process", "new_run"],
      tone: "neutral",
    };
  }

  if (state !== null && state.state === "unavailable") {
    if (state.reason_code === "corrupt") {
      return {
        id: "projection_corrupt",
        title: "研究投影损坏",
        body: "已提交的产物无法确定性重建，因此不展示任何方向性结论。",
        actions: ["retry_read", "audit"],
        tone: "bad",
      };
    }
    if (state.reason_code === "run_running") {
      return {
        id: "running",
        title: "研究进行中",
        body: "研究产物尚未提交。此时不展示任何最终研究优先级。",
        actions: ["view_process"],
        tone: "live",
      };
    }
    return {
      id: "queued",
      title: state.reason_code === "not_committed" ? "排队中" : "本次运行没有研究产物",
      body:
        state.reason_code === "not_committed"
          ? "请求已接受，尚未开始执行研究阶段。"
          : "这次运行没有已提交的研究产物。不会在读取时补算。",
      actions: state.reason_code === "not_committed" ? ["view_process"] : ["new_run", "audit"],
      tone: state.reason_code === "not_committed" ? "live" : "neutral",
    };
  }

  if (state !== null && state.state === "ready") {
    const completeness = completenessOf(input);
    const quality = qualityOf(input);
    const priority = state.priority;

    if (completeness === "blocked" || quality === "FAIL_STOP" || quality === "GATE_ERROR") {
      return {
        id: "blocked_or_error",
        title: "研究被阻断",
        body: "必需门控未通过，因此不形成方向性结论。可以区分研究阻断与系统故障，并在审计中心查看原因。",
        actions: ["audit", "retry", "new_run"],
        tone: "bad",
      };
    }
    // `partial` means required evidence is missing — the axis that decides
    // "必需证据不足". A `low confidence` verdict on an otherwise complete case
    // is a *different* axis: it is what caps the priority at "keep watching"
    // and lands on `complete_limited` below. Conflating the two would swallow
    // design 4.5 row 3.
    if (completeness === "partial" || priority === "insufficient_information") {
      return {
        id: "insufficient_evidence",
        title: "信息不足",
        body: "本次可验证事实与关键缺口同时列出。要补做请以新的 run 运行，系统不会修改这次已提交的结果。",
        actions: ["view_gaps", "view_sources", "new_run"],
        tone: "limited",
      };
    }
    // Design 4.5 row 3 — complete, and the brief reads, but the evidence
    // ceiling holds the priority below "worth checking now". Checked by
    // category, not by a score: there is no numeric threshold here to drift.
    if (priority !== "verify_first" && priority !== "keep_watching") {
      return {
        id: "complete_limited",
        title: "研究受限",
        body: "简报可读，但研究优先级受到证据上限约束。缺口列在首屏，不隐藏在审计页。",
        actions: ["view_gaps", "view_sources", "new_run"],
        tone: "limited",
      };
    }
    return {
      id: "complete_sufficient",
      title: "研究已发布",
      body: "证据、来源与限制都可按需查看。",
      actions: ["view_sources", "new_run"],
      tone: "good",
    };
  }

  return {
    id: "queued",
    title: "尚未开始",
    body: "先选择一次运行，或发起新的公司研究。",
    actions: ["new_run"],
    tone: "neutral",
  };
}

// ---------------------------------------------------------------------------
// Legacy runs (T31)
// ---------------------------------------------------------------------------

export type LegacyLayerId = "summary" | "detail" | "process";

export const LEGACY_LAYER_COPY: Readonly<Record<LegacyLayerId, { label: string; hint: string }>> = {
  summary: { label: "概要", hint: "旧运行的结论摘要与评级，按原样展示" },
  detail: { label: "详情", hint: "旧运行的完整报告与阅读视图" },
  process: { label: "研究过程", hint: "角色产出、调用记录与审计入口" },
};

export const LEGACY_LAYER_IDS: readonly LegacyLayerId[] = ["summary", "detail", "process"];

/**
 * The new workbench's own tabs. Distinct from `LEGACY_LAYER_IDS` on purpose:
 * a legacy record is read in three layers, a catalyst case in three tabs, and
 * conflating them is how a reader ends up unsure which contract produced the
 * text in front of them.
 */
export type CatalystTabId = "brief" | "evidence" | "process";

export const CATALYST_TAB_COPY: Readonly<Record<CatalystTabId, string>> = {
  brief: "研究简报",
  evidence: "依据与事件",
  process: "研究过程",
};

export const CATALYST_TAB_IDS: readonly CatalystTabId[] = ["brief", "evidence", "process"];

/** A minimal shape so callers can pass either the legacy record or a view. */
export interface LegacyPrioritySource {
  research_priority?: unknown;
  research_rating?: unknown;
}

export interface LegacyPriorityView {
  /** Always absent: a legacy record must not gain a research priority. */
  priority: null;
  /** The old rating, relabelled as a rating and never as a priority. */
  rating: string | null;
}

/**
 * Read a legacy record without inventing a priority.
 *
 * Design 11.1: an old completed run is read under its old schema, and no new
 * priority is generated or recomputed. The old `research_rating` may be shown
 * because it already existed, but it is explicitly a rating of the old flow and
 * is never mapped onto the four new categories.
 */
export function legacyPriorityView(source: LegacyPrioritySource): LegacyPriorityView {
  const declared = source.research_priority;
  if (declared !== null && declared !== undefined) {
    // A legacy payload carrying a priority would be a contract violation, not a
    // value to render. Surface nothing rather than laundering it into a row.
    return { priority: null, rating: null };
  }
  const rating = typeof source.research_rating === "string" ? source.research_rating : null;
  return { priority: null, rating };
}

// ---------------------------------------------------------------------------
// Which contract produced the page (T26 / T31)
// ---------------------------------------------------------------------------

/**
 * One of three ways a run can reach the workbench, chosen before anything is
 * rendered.
 *
 * The completed page used to mount `DecisionBrief` (which renders
 * `run-view-v1.view.brief`, including `learning_summary`) next to
 * `ReaderSurface`, and the two measured 96% overlapping text. That pair is the
 * duplication T26 removes, and the reason the decision cannot be "keep both
 * and let the reader choose".
 *
 * So the routing is explicit: a run is read either as a *catalyst case* (one
 * summary, the seven-row first screen) or as a *legacy record* (three layers,
 * no priority) or it is *live*. Nothing else mounts a summary.
 */
export type CatalystRouteKind = "catalyst" | "legacy" | "live" | "empty";

export interface CatalystRoute {
  kind: CatalystRouteKind;
  /**
   * For a legacy record, which of the three layers the page is showing. Kept
   * here rather than in component state so the summary-container count is a
   * property of the route, not of whichever tab happens to be open.
   */
  layer: LegacyLayerId | null;
}

export interface CatalystRouteInput {
  profile?: ResearchProfile;
  runId: string | null;
  /** True once the run has a terminal projection on the classic path. */
  classicTerminal: boolean;
  /**
   * The catalyst read state, or null when the read produced no body.
   *
   * Null is not a verdict: it is also what an unfinished or failed read looks
   * like, and neither may change which contract produced the run.
   */
  readState: CatalystReadState | null;
  loading: boolean;
}

/**
 * Route by contract, not by which text happens to be present.
 *
 * `unsupported` is the discriminator that matters: the server says outright
 * that this run has no catalyst artifact, which is what stops the page from
 * reaching for a legacy summary and presenting it as a research conclusion.
 */
export function catalystRoute(input: CatalystRouteInput): CatalystRoute {
  if (input.runId === null) return { kind: "empty", layer: null };
  const state = input.readState;
  if (state === null) {
    // A null state is not a verdict. It also means "not read yet" and "the read
    // failed", and a read that never classifies an old run would otherwise
    // leave it unreadable forever. The terminal projection is what separates
    // the two cases: a completed classic run is a legacy record whatever the
    // catalyst read says, while a run that is live or still loading has
    // nothing to show and belongs to the progress surface.
    if (input.classicTerminal && input.profile !== "catalyst_v1") return { kind: "legacy", layer: "summary" };
    return { kind: "live", layer: null };
  }
  // Order matters here, and the order is not arbitrary. A `catalyst_v1` run
  // also has a terminal *classic* projection — that is how the run-view
  // endpoint reports completion for both profiles — so testing `classicTerminal`
  // first would send every catalyst run to the legacy reader and the new
  // first screen would never render.
  if (state.state === "ready") return { kind: "catalyst", layer: null };
  // `unsupported` is the discriminator that matters for the legacy route: the
  // server says outright that this run has no catalyst artifact, which is what
  // stops the page from reaching for a classic summary and presenting it as a
  // research conclusion.
  if (state.state === "unsupported") return { kind: "legacy", layer: "summary" };
  if (input.classicTerminal && input.profile !== "catalyst_v1") return { kind: "legacy", layer: "summary" };
  // `unavailable` on a non-terminal run: queued, running, or not yet
  // committed. The progress surface owns this; no summary, no priority.
  return { kind: "live", layer: null };
}

/**
 * A legacy record read in layers (design 4.4 / T31).
 *
 * The layers exist because an old run has a different amount of information at
 * each level, and collapsing them is what produced the 8,399-character first
 * screen. `summary` is the old conclusion, `detail` the full report, `process`
 * the role outputs and the audit entry point.
 */
export interface LegacyLayerView {
  id: LegacyLayerId;
  label: string;
  hint: string;
  /** The old rating, if the record had one. Never a research priority. */
  rating: string | null;
  /** Always null. Present so a caller cannot "find" a priority by accident. */
  priority: null;
  /** Whether this layer has anything to show, or is an honest empty state. */
  hasContent: boolean;
}

export function legacyLayerView(
  id: LegacyLayerId,
  source: LegacyPrioritySource & { has_report?: boolean; has_process?: boolean },
): LegacyLayerView {
  const copy = LEGACY_LAYER_COPY[id];
  return {
    id,
    label: copy.label,
    hint: copy.hint,
    ...legacyPriorityView(source),
    hasContent:
      id === "summary"
        ? true
        : id === "detail"
          ? source.has_report !== false
          : source.has_process !== false,
  };
}
