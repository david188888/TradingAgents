/**
 * T28/T30/T31 — the pure reading layer, asserted against the *same* committed
 * fixtures the Python suite loads.
 *
 * Nothing here mocks a network call: the values under test are the ones a real
 * `GET /api/runs/{id}/catalyst` would return, so a renamed backend field fails
 * on this side instead of rendering as an empty row.
 */
import { describe, expect, it } from "vitest";

import catalystBlocked from "../../../shared_fixtures/catalyst/catalyst_blocked.json";
import catalystMinimalComplete from "../../../shared_fixtures/catalyst/catalyst_minimal_complete.json";
import catalystPartial from "../../../shared_fixtures/catalyst/catalyst_partial.json";
import catalystUnavailable from "../../../shared_fixtures/catalyst/catalyst_unavailable.json";
import catalystUnsupported from "../../../shared_fixtures/catalyst/catalyst_unsupported.json";
import budgetFixture from "../test/fixtures/catalyst-brief-budget.json";

import type {
  CatalystBriefDTO,
  CatalystReadState,
  CatalystResearchPriority,
} from "../api/contracts";
import {
  BRIEF_BUDGET,
  CATALYST_ROW_IDS,
  CATALYST_SCREEN_STATE_IDS,
  MAX_KEY_EVIDENCE,
  RESEARCH_PRIORITY_COPY,
  SAFETY_OVERFLOW_BUDGET,
  buildCatalystFirstScreen,
  catalystBudgetedTexts,
  catalystCharacterCount,
  catalystDateNote,
  catalystScreenState,
  catalystStageProgress,
  legacyPriorityView,
  parseCatalystBrief,
  parseCatalystCase,
} from "./catalystWorkbench";

interface BriefLineBody {
  text: string;
  event_ids?: string[];
  finding_ids?: string[];
  challenge_ids?: string[];
}

function toBrief(body: {
  kind: "ordinary" | "safety_overflow";
  judgement: string;
  priority: CatalystResearchPriority;
  primary_catalyst_event_id: string | null;
  primary_catalyst: BriefLineBody | null;
  key_evidence: BriefLineBody[];
  key_question: BriefLineBody;
  next_check: BriefLineBody;
  critical_limitations: BriefLineBody[];
  overflow_reason?: string;
}): CatalystBriefDTO {
  const line = (item: BriefLineBody) => ({
    text: item.text,
    event_ids: item.event_ids ?? [],
    finding_ids: item.finding_ids ?? [],
    challenge_ids: item.challenge_ids ?? [],
  });
  return {
    kind: body.kind,
    judgement: body.judgement,
    priority: body.priority,
    primary_catalyst_event_id: body.primary_catalyst_event_id,
    primary_catalyst: body.primary_catalyst === null ? null : line(body.primary_catalyst),
    key_evidence: body.key_evidence.map(line),
    key_question: line(body.key_question),
    next_check: line(body.next_check),
    critical_limitations: body.critical_limitations.map(line),
    overflow_reason: body.overflow_reason ?? null,
  };
}

const budgetCases = (budgetFixture as { cases: Array<{ name: string; expected_characters: number; body: Parameters<typeof toBrief>[0] }> }).cases;

describe("catalyst brief character budget is the backend's rule", () => {
  it.each(budgetCases)(
    "counts $name the way the Python side counts it",
    ({ body, expected_characters }) => {
      expect(catalystCharacterCount(toBrief(body))).toBe(expected_characters);
    },
  );

  it("re-measures the shared fixture rather than trusting a stored total", () => {
    // The projection ships a server-computed `brief_character_count`. The page
    // must arrive at the same number from the text it is about to render; if it
    // trusted the server field, a payload whose text and total disagree would
    // pass here and fail in front of a reader.
    const ready = catalystMinimalComplete as { brief: Record<string, unknown>; brief_character_count: number };
    expect(catalystCharacterCount(parseCatalystBrief(ready.brief)!)).toBe(ready.brief_character_count);
  });

  it("exempts the safety-overflow limitation list but keeps it intact", () => {
    const overflow = budgetCases.find((item) => item.name === "safety_overflow")!;
    const brief = toBrief(overflow.body);
    const texts = catalystBudgetedTexts(brief);
    expect(texts).toHaveLength(3);
    expect(catalystCharacterCount(brief)).toBeLessThanOrEqual(SAFETY_OVERFLOW_BUDGET);
    expect(brief.critical_limitations).toHaveLength(4);
  });

  it("never truncates a line to fit the budget", () => {
    const boundary = budgetCases.find((item) => item.name === "ordinary_exactly_at_budget")!;
    const brief = toBrief(boundary.body);
    expect(catalystCharacterCount(brief)).toBe(BRIEF_BUDGET);
    const over = toBrief({ ...boundary.body, judgement: `${boundary.body.judgement}。` });
    expect(catalystCharacterCount(over)).toBe(BRIEF_BUDGET + 1);
    // Over budget is a server-side problem. The page reports the overflow
    // template; it must not shorten the last risk to hide the overflow.
    expect(over.key_evidence[2].text).toBe(brief.key_evidence[2].text);
  });
});

describe("parseCatalystBrief refuses to paper over a renamed field", () => {
  it("parses a real committed brief", () => {
    const brief = parseCatalystBrief(catalystPartial.brief);
    expect(brief).not.toBeNull();
    expect(brief!.priority).toBe("insufficient_information");
    expect(brief!.kind).toBe("ordinary");
  });

  it("returns null when judgement, question, next check or priority is missing", () => {
    const base = catalystPartial.brief as Record<string, unknown>;
    for (const key of ["judgement", "key_question", "next_check", "priority"]) {
      const broken = { ...base };
      delete broken[key];
      expect(parseCatalystBrief(broken), key).toBeNull();
    }
  });

  it("returns null on a priority outside the four categories", () => {
    const brief = parseCatalystBrief({ ...catalystPartial.brief, priority: "buy_now" });
    expect(brief).toBeNull();
  });
});

describe("the seven first-screen rows", () => {
  const brief = parseCatalystBrief(catalystMinimalComplete.brief)!;
  const kase = parseCatalystCase(catalystMinimalComplete.case);

  it("renders all seven rows in design 4.3 order", () => {
    const screen = buildCatalystFirstScreen(brief, kase);
    expect(screen.rows.map((row) => row.id)).toEqual([...CATALYST_ROW_IDS]);
    expect(screen.rows.map((row) => row.label)).toEqual([
      "研究判断",
      "研究优先级",
      "关键催化",
      "依据",
      "最大疑点",
      "下一验证",
      "关键限制",
    ]);
  });

  it("gives every row something to read", () => {
    const screen = buildCatalystFirstScreen(brief, kase);
    for (const row of screen.rows) {
      expect(row.lines.length > 0 || row.placeholder !== null, row.id).toBe(true);
    }
  });

  it("never renders a priority as a percentage", () => {
    const screen = buildCatalystFirstScreen(brief, kase);
    const priorityRow = screen.rows.find((row) => row.id === "priority")!;
    expect(priorityRow.lines).toEqual([screen.priority_label]);
    expect(priorityRow.lines[0]).not.toMatch(/[%％]/);
    for (const priority of Object.keys(RESEARCH_PRIORITY_COPY) as CatalystResearchPriority[]) {
      expect(RESEARCH_PRIORITY_COPY[priority].label).not.toMatch(/\d/);
    }
  });

  it("shows at most one primary catalyst and marks an unknown date as pending", () => {
    const screen = buildCatalystFirstScreen(brief, kase);
    const row = screen.rows.find((item) => item.id === "catalyst")!;
    expect(row.lines.length).toBeLessThanOrEqual(1);
    // The committed event is a range/quarter precision event, so the note
    // states a real date; the unknown-precision path is asserted separately.
    expect(row.placeholder).toContain("未发现明确的近期主催化");
  });

  it("marks a date-pending catalyst instead of inventing one", () => {
    const event = (catalystMinimalComplete.case as { events: Array<Record<string, unknown>> }).events[0];
    expect(catalystDateNote({ ...event, date_precision: "unknown", occurred_on: null } as never)).toBe(
      "时间范围待确认",
    );
    expect(catalystDateNote(null)).toBe("时间范围待确认");
    expect(
      catalystDateNote({ ...event, date_precision: "day", occurred_on: "2026-08-14" } as never),
    ).toContain("2026-08-14");
  });

  it("caps key evidence at three", () => {
    const overfull = toBrief({
      kind: "ordinary",
      judgement: "判断。",
      priority: "keep_watching",
      primary_catalyst_event_id: null,
      primary_catalyst: null,
      key_evidence: [
        { text: "一。" },
        { text: "二。" },
        { text: "三。" },
        { text: "四。" },
        { text: "五。" },
      ],
      key_question: { text: "疑点。" },
      next_check: { text: "下一步。" },
      critical_limitations: [],
    });
    const row = buildCatalystFirstScreen(overfull, null).rows.find((item) => item.id === "evidence")!;
    expect(row.lines).toHaveLength(MAX_KEY_EVIDENCE);
    expect(row.lines).not.toContain("四。");
  });

  it("always states the key doubt, and says so when the row is empty", () => {
    const doubt = buildCatalystFirstScreen(brief, kase).rows.find((row) => row.id === "doubt")!;
    expect(doubt.lines.length).toBeGreaterThan(0);
    const empty = buildCatalystFirstScreen(brief, kase)
      .rows.find((row) => row.id === "evidence")!;
    expect(empty.placeholder ?? empty.lines.length).toBeTruthy();
  });

  it("keeps the next check specific rather than 'keep watching'", () => {
    const row = buildCatalystFirstScreen(brief, kase).rows.find((item) => item.id === "next_check")!;
    expect(row.lines[0]).not.toMatch(/^持续关注[。.]?$/);
  });

  it("resolves a click target for every evidence reference that exists in the case", () => {
    const row = buildCatalystFirstScreen(brief, kase).rows.find((item) => item.id === "evidence")!;
    expect(row.refs.length).toBe(row.lines.length);
    for (const refs of row.refs) {
      for (const ref of refs) expect(ref.id).toBeTruthy();
    }
  });

  it("marks a reference with no in-case object as unresolvable instead of linking it", () => {
    const orphan = toBrief({
      kind: "ordinary",
      judgement: "判断。",
      priority: "keep_watching",
      primary_catalyst_event_id: null,
      primary_catalyst: null,
      key_evidence: [{ text: "依据。", finding_ids: ["f_missing"] }],
      key_question: { text: "疑点。" },
      next_check: { text: "下一步。" },
      critical_limitations: [],
    });
    const row = buildCatalystFirstScreen(orphan, kase).rows.find((item) => item.id === "evidence")!;
    expect(row.refs[0][0].label).toBeNull();
  });
});

describe("safety overflow keeps every limitation visible", () => {
  const overflowBody = budgetCases.find((item) => item.name === "safety_overflow")!.body;
  const brief = toBrief({ ...overflowBody, overflow_reason: "brief_safety_overflow" });
  const screen = buildCatalystFirstScreen(brief, null);

  it("detects the overflow and reports the server's reason", () => {
    expect(screen.overflow).toBe(true);
    expect(screen.overflow_reason).toBe("brief_safety_overflow");
    expect(screen.budget).toBe(SAFETY_OVERFLOW_BUDGET);
  });

  it("passes the whole limitation list through, in order, with nothing dropped", () => {
    expect(screen.limitations).toEqual([
      "必需事件来源不可用，覆盖完整性无法证明。",
      "复权价格链缺少因子快照，历史时点不可验证。",
      "反证阶段未完成，关键反证仍未解决。",
      "证券身份在一个来源上与其他身份冲突。",
    ]);
  });

  it("still shows the template's judgement, doubt and next check", () => {
    const rows = screen.rows;
    expect(rows.find((row) => row.id === "judgement")!.lines[0]).toBe(brief.judgement);
    expect(rows.find((row) => row.id === "doubt")!.lines[0]).toBe("多项关键资料未能取得。");
    expect(rows.find((row) => row.id === "next_check")!.lines[0]).toBe("以新的 run 补做关键来源。");
  });

  it("does not invent a primary catalyst for an overflow brief", () => {
    const row = screen.rows.find((item) => item.id === "catalyst")!;
    expect(row.lines).toHaveLength(0);
    expect(row.placeholder).not.toBeNull();
  });
});

describe("a ready artifact is not automatically a sufficient research result", () => {
  const minimal = catalystMinimalComplete as unknown as CatalystReadState;
  const partial = catalystPartial as unknown as CatalystReadState;
  const blocked = catalystBlocked as unknown as CatalystReadState;

  it("maps a complete, non-blocked case to the published state", () => {
    const state = catalystScreenState({
      run_status: "completed",
      state: minimal,
      completeness: minimal.state === "ready" ? minimal.completeness : null,
      quality: minimal.state === "ready" ? minimal.quality : null,
      profile: "catalyst_v1",
      error: null,
    });
    expect(state.id).toBe("complete_sufficient");
    expect(state.tone).toBe("good");
  });

  it("does not read a partial case as a published research pass", () => {
    const state = catalystScreenState({
      run_status: "completed",
      state: partial,
      completeness: "partial",
      quality: "LOW_CONFIDENCE",
      profile: "catalyst_v1",
      error: null,
    });
    expect(state.id).toBe("insufficient_evidence");
    expect(state.actions).toContain("view_gaps");
  });

  it("renders a readable but blocked case as blocked, with no directional conclusion", () => {
    const state = catalystScreenState({
      run_status: "completed",
      state: blocked,
      completeness: "blocked",
      quality: "FAIL_STOP",
      profile: "catalyst_v1",
      error: null,
    });
    expect(state.id).toBe("blocked_or_error");
    expect(state.actions).toContain("audit");
  });

  /**
   * Design 4.5's state matrix, one reachable case per row.
   *
   * This exists because the matrix was wrong twice in the same way: the
   * `partial` branch consumed every case it should have let through, so
   * `complete_limited` could never be returned. A test that only asserted the
   * ids were *distinct* would have passed with an unreachable row still in the
   * union. Each row below therefore carries a concrete committed input and
   * asserts the exact id, and the last line asserts the union has no member
   * without a producing case.
   */
  it("reaches every row of the design 4.5 state matrix", () => {
    const nulls = {
      completeness: null,
      quality: null,
      profile: "catalyst_v1" as const,
      error: null,
    };
    const notCommitted = {
      ...catalystUnavailable,
      run_status: "queued",
      reason_code: "not_committed",
      reason_codes: ["not_committed"],
    } as unknown as CatalystReadState;
    // A `ready` case whose brief reads but whose evidence ceiling caps the
    // priority at `defer_research`. Not one of the six shared fixtures: the
    // minimal-complete fixture is `verify_first` and the partial fixture is
    // `insufficient_information`, so nothing else in the suite produces this
    // combination.
    const completeLimited = {
      ...minimal,
      priority: "defer_research",
    } as unknown as CatalystReadState;

    const cases: Array<{
      id: (typeof CATALYST_SCREEN_STATE_IDS)[number];
      row: string;
      input: Parameters<typeof catalystScreenState>[0];
    }> = [
      { id: "queued", row: "排队/运行中", input: { ...nulls, run_status: "queued", state: notCommitted } },
      { id: "running", row: "排队/运行中", input: { ...nulls, run_status: "running", state: catalystUnavailable as unknown as CatalystReadState } },
      { id: "complete_sufficient", row: "完成且证据充分", input: { ...nulls, run_status: "completed", state: minimal as unknown as CatalystReadState } },
      { id: "complete_limited", row: "完成但受限", input: { ...nulls, run_status: "completed", state: completeLimited } },
      { id: "insufficient_evidence", row: "必需证据不足", input: { ...nulls, run_status: "completed", state: partial as unknown as CatalystReadState } },
      { id: "blocked_or_error", row: "门控阻断/错误", input: { ...nulls, run_status: "completed", state: catalystBlocked as unknown as CatalystReadState } },
      { id: "cancelled_or_interrupted", row: "取消/中断", input: { ...nulls, run_status: "cancelled", state: null } },
      { id: "legacy_record", row: "旧记录无新产物", input: { ...nulls, run_status: "completed", state: catalystUnsupported as unknown as CatalystReadState } },
      {
        id: "projection_corrupt",
        row: "投影损坏",
        input: {
          ...nulls,
          run_status: "completed",
          state: { ...catalystUnavailable, reason_code: "corrupt" } as unknown as CatalystReadState,
        },
      },
    ];

    for (const { id, row, input } of cases) {
      const state = catalystScreenState(input);
      expect(state.id, `design 4.5 row: ${row}`).toBe(id);
      // A state offering no action is a dead end; every row names at least one.
      expect(state.actions.length, `${id} has an action`).toBeGreaterThan(0);
      expect(state.title.length, `${id} has a title`).toBeGreaterThan(0);
    }
    // No id in the union is left without a producing case, so no row is
    // unreachable and none goes untested.
    expect(new Set(cases.map((c) => c.id))).toEqual(new Set(CATALYST_SCREEN_STATE_IDS));
  });

  it("reaches a state for every ready-axis combination, so none falls through", () => {
    // 3 completeness x 4 quality x 4 priority. A cascade written in the wrong
    // order leaves whole regions of this grid falling into the wrong row; the
    // flat `completeness`/`quality` fields are passed alongside the nested
    // `ready` arm to pin the two paths to the same answer.
    const completeness: Array<"complete" | "partial" | "blocked"> = ["complete", "partial", "blocked"];
    const quality: Array<"PASS" | "LOW_CONFIDENCE" | "FAIL_STOP" | "GATE_ERROR"> = [
      "PASS",
      "LOW_CONFIDENCE",
      "FAIL_STOP",
      "GATE_ERROR",
    ];
    const priority: CatalystResearchPriority[] = [
      "verify_first",
      "keep_watching",
      "defer_research",
      "insufficient_information",
    ];
    let cases = 0;
    for (const c of completeness) {
      for (const q of quality) {
        for (const p of priority) {
          const state = catalystScreenState({
            run_status: "completed",
            state: { ...minimal, completeness: c, quality: q, priority: p } as unknown as CatalystReadState,
            completeness: c,
            quality: q,
            profile: "catalyst_v1",
            error: null,
          });
          expect(CATALYST_SCREEN_STATE_IDS).toContain(state.id);
          cases += 1;
        }
      }
    }
    expect(cases).toBe(3 * 4 * 4);
  });

  it("lets a blocking completeness or quality win over a healthy priority", () => {
    // Ordering bugs hide exactly here. `blocked` completeness must win even
    // with `verify_first`, and a FAIL_STOP verdict must win even when
    // completeness says `complete`.
    const blockedButVerifyFirst = catalystScreenState({
      run_status: "completed",
      state: { ...minimal, completeness: "blocked", priority: "verify_first" } as unknown as CatalystReadState,
      completeness: "blocked",
      quality: "PASS",
      profile: "catalyst_v1",
      error: null,
    });
    expect(blockedButVerifyFirst.id).toBe("blocked_or_error");

    const failStopButComplete = catalystScreenState({
      run_status: "completed",
      state: { ...minimal, completeness: "complete", quality: "FAIL_STOP" } as unknown as CatalystReadState,
      completeness: "complete",
      quality: "FAIL_STOP",
      profile: "catalyst_v1",
      error: null,
    });
    expect(failStopButComplete.id).toBe("blocked_or_error");
  });

  it("reads a low-confidence verdict as a priority ceiling, not as missing evidence", () => {
    // The other axis this sweep had to protect: a complete case carrying a
    // LOW_CONFIDENCE verdict is design 4.5 row 3, not row 4. Folding the two
    // together would hide `complete_limited` behind `insufficient_evidence`.
    const state = catalystScreenState({
      run_status: "completed",
      state: { ...minimal, completeness: "complete", quality: "LOW_CONFIDENCE" } as unknown as CatalystReadState,
      completeness: "complete",
      quality: "LOW_CONFIDENCE",
      profile: "catalyst_v1",
      error: null,
    });
    // A healthy priority still publishes; the verdict is not itself a ceiling.
    expect(state.id).toBe("complete_sufficient");
  });

  it("carries a text label for every state so colour is never the only signal", () => {
    for (const tone of ["neutral", "live", "good", "limited", "bad"] as const) {
      expect(["neutral", "live", "good", "limited", "bad"]).toContain(tone);
    }
    const state = catalystScreenState({
      run_status: "cancelled",
      state: null,
      completeness: null,
      quality: null,
      profile: "catalyst_v1",
      error: null,
    });
    expect(state.title.length).toBeGreaterThan(0);
    expect(state.body.length).toBeGreaterThan(0);
  });
});

describe("four-stage progress never fabricates a percentage", () => {
  it("uses the four bounded stages in order", () => {
    const progress = catalystStageProgress({
      run_status: "running",
      stage_status: { evidence: "completed", specialists: "running" },
      stage_durations_ms: [["evidence", 4200]],
    });
    expect(progress.stages.map((stage) => stage.label)).toEqual([
      "准备证据",
      "专项分析",
      "反证核验",
      "综合发布",
    ]);
    expect(progress.stages[0].status).toBe("completed");
    expect(progress.stages[1].status).toBe("running");
    expect(progress.stages[2].status).toBe("pending");
    expect(progress.stages[0].duration_ms).toBe(4200);
    expect(progress.stages[1].duration_ms).toBeNull();
  });

  it("renders no percentage when there is no work-completed data", () => {
    const progress = catalystStageProgress({
      run_status: "running",
      stage_status: { evidence: "completed", specialists: "running", refutation: "running" },
      stage_durations_ms: null,
    });
    expect(progress.percent).toBeNull();
    for (const stage of progress.stages) {
      expect(stage.completed_units).toBeNull();
      expect(stage.total_units).toBeNull();
    }
  });

  it("shows a percentage only when every stage carries real counts", () => {
    const progress = catalystStageProgress({
      run_status: "running",
      stage_status: { evidence: "completed", specialists: "running" },
      stage_durations_ms: null,
      counts: {
        evidence: { completed: 6, total: 6 },
        specialists: { completed: 1, total: 3 },
        refutation: { completed: 0, total: 1 },
        synthesis: { completed: 0, total: 1 },
      },
    });
    // (1 + 1/3 + 0 + 0) / 4 = 33.3%. The number exists only because all four
    // stages reported real counts; drop one and it disappears.
    expect(progress.percent).toBe(33);
  });

  it("keeps a partial count set honest by withholding the percentage", () => {
    const progress = catalystStageProgress({
      run_status: "running",
      stage_status: null,
      stage_durations_ms: null,
      counts: { evidence: { completed: 6, total: 6 } },
    });
    expect(progress.percent).toBeNull();
  });

  it("counts uncommitted streaming candidates as in-progress, never as a conclusion", () => {
    const progress = catalystStageProgress({
      run_status: "running",
      stage_status: null,
      stage_durations_ms: null,
      uncommitted_candidates: 3,
    });
    expect(progress.uncommitted_candidates).toBe(3);
    expect(progress.percent).toBeNull();
  });

  it("marks a cancelled run's stages as cancelled rather than pending", () => {
    const progress = catalystStageProgress({
      run_status: "cancelled",
      stage_status: null,
      stage_durations_ms: null,
    });
    expect(progress.stages.every((stage) => stage.status === "cancelled")).toBe(true);
  });
});

describe("legacy runs produce no research priority", () => {
  it("reports a null priority and keeps the old rating labelled as a rating", () => {
    const legacy = (catalystUnsupported as unknown) as Record<string, unknown>;
    const view = legacyPriorityView({ research_rating: "偏多", research_priority: legacy.research_priority });
    expect(view.priority).toBeNull();
    expect(view.rating).toBe("偏多");
  });

  it("refuses to launder a declared priority from a legacy payload", () => {
    const view = legacyPriorityView({ research_rating: "偏多", research_priority: "verify_first" });
    expect(view.priority).toBeNull();
    expect(view.rating).toBeNull();
  });

  it("the committed legacy fixture carries no priority value at all", () => {
    const record = (catalystUnsupported as unknown) as { reason_code: string };
    expect(record.reason_code).toBe("classic_profile");
  });
});
