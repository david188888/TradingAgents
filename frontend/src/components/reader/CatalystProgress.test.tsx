/**
 * T30 — four-stage progress, and the state a run is actually in.
 *
 * Two things are load-bearing here.
 *
 * The first is the percentage. A progress bar that cannot be measured must not
 * display a number: a fabricated "90%" tells a reader the run is nearly done
 * when the server has committed nothing of the sort. These tests drive
 * `catalystStageProgress` through the component so the assertion covers both
 * the domain's decision to withhold the number and the component's decision
 * not to invent one.
 *
 * The second is the terminal state matrix. Design section 4.5 names eight, and
 * each has to render something true. A state with no rendering case is a state
 * that renders a blank box.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  CATALYST_SCREEN_STATE_IDS,
  catalystScreenState,
  catalystStageProgress,
  type CatalystScreenInput,
  type CatalystScreenStateId,
} from "../../domain/catalystWorkbench";
import {
  CATALYST_CASE_SCHEMA_NUMBER,
  CATALYST_CASE_SCHEMA_VERSION,
  CATALYST_ENDPOINT_VERSION,
  type CatalystCompleteness,
  type CatalystReadState,
  type CatalystResearchPriority,
  type CatalystResearchQuality,
} from "../../api/contracts";
import { CatalystProgress } from "./CatalystProgress";

const STAGE_IDS = ["evidence", "specialists", "refutation", "synthesis"] as const;

const ALL_COUNTS = Object.fromEntries(STAGE_IDS.map((id) => [id, { completed: 1, total: 2 }]));

/** The percentage must not appear anywhere, not merely in one slot. */
function expectNoPercent(container: HTMLElement): void {
  expect(screen.queryByTestId("catalyst-progress-percent")).toBeNull();
  expect(container.textContent ?? "").not.toMatch(/\d+\s*%/);
}

const RUN_ID = "run_progress";
const TICKER = "600519";

/**
 * Fully-typed wire fixtures.
 *
 * These are built through the DTOs rather than as bare object literals on
 * purpose: a partial literal would typecheck under `as never` and would stop
 * being a statement about the wire at all. `brief` and `case` are empty
 * because `catalystScreenState` reads only the state axes — completeness,
 * quality and priority — and this file is about which state the page shows.
 */
function ready(
  completeness: CatalystCompleteness,
  quality: CatalystResearchQuality,
  priority: CatalystResearchPriority,
): CatalystReadState {
  return {
    state: "ready",
    schema_version: CATALYST_ENDPOINT_VERSION,
    case_schema_version: CATALYST_CASE_SCHEMA_VERSION,
    case_schema_number: CATALYST_CASE_SCHEMA_NUMBER,
    run_id: RUN_ID,
    ticker: TICKER,
    run_status: "completed",
    completeness,
    quality,
    priority,
    research_question: null,
    brief: {},
    limitations: [],
    brief_character_count: 0,
    case: {},
  };
}

function unavailable(reason_code: "run_running" | "not_committed" | "missing" | "corrupt"): CatalystReadState {
  return {
    state: "unavailable",
    schema_version: CATALYST_ENDPOINT_VERSION,
    run_id: RUN_ID,
    ticker: TICKER,
    run_status: "running",
    reason_code,
    reason_codes: [reason_code],
  };
}

function unsupported(): CatalystReadState {
  return {
    state: "unsupported",
    schema_version: CATALYST_ENDPOINT_VERSION,
    run_id: RUN_ID,
    ticker: TICKER,
    reason_code: "classic_profile",
  };
}

function input(over: Partial<CatalystScreenInput>): CatalystScreenInput {
  return { run_status: "created", state: null, completeness: null, quality: null, profile: null, error: null, ...over };
}

const inputs: Record<CatalystScreenStateId, CatalystScreenInput> = {
  queued: input({ run_status: "created", state: unavailable("not_committed") }),
  running: input({ run_status: "running", state: unavailable("run_running") }),
  complete_sufficient: input({
    run_status: "completed",
    profile: "catalyst_v1",
    state: ready("complete", "PASS", "verify_first"),
  }),
  // Complete, and the brief reads — but a blocking reason forbids
  // `verify_first`, so the priority is capped below it. `LOW_CONFIDENCE` is
  // not that signal: the priority ceiling is carried by the category, and
  // `keep_watching` is a legitimate published answer in its own right.
  complete_limited: input({
    run_status: "completed",
    profile: "catalyst_v1",
    state: ready("complete", "PASS", "defer_research"),
  }),
  insufficient_evidence: input({
    run_status: "completed",
    profile: "catalyst_v1",
    state: ready("partial", "LOW_CONFIDENCE", "insufficient_information"),
  }),
  blocked_or_error: input({
    run_status: "completed",
    profile: "catalyst_v1",
    state: ready("blocked", "GATE_ERROR", "insufficient_information"),
  }),
  cancelled_or_interrupted: input({ run_status: "cancelled" }),
  legacy_record: input({ run_status: "completed", state: unsupported() }),
  // A read that failed outright: the same row as a corrupt body, and the one
  // state a caller reaches with no server state at all.
  projection_corrupt: input({ run_status: "completed", error: new Error("bad body") }),
};

describe("T30 — a percentage appears only when work-completed data exists", () => {
  it("renders no percentage when the case reports no counts", () => {
    const { container } = render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "running",
          stage_status: { evidence: "completed", specialists: "running" },
          stage_durations_ms: null,
          counts: null,
        })}
        state={catalystScreenState(input({ run_status: "running" }))}
      />,
    );
    expectNoPercent(container);
    // Stage status is still fully readable, so the reader is not left with
    // nothing at all in place of the number.
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("进行中")).toBeInTheDocument();
  });

  it("renders no percentage when only some stages reported counts", () => {
    const { container } = render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "running",
          stage_status: null,
          stage_durations_ms: null,
          // Three of four. Averaging over the stages that happen to have data
          // would produce a number that is not the run's progress.
          counts: { evidence: { completed: 1, total: 2 } } as never,
        })}
        state={catalystScreenState(input({ run_status: "running" }))}
      />,
    );
    expectNoPercent(container);
  });

  it("renders the measured percentage when all four stages report counts", () => {
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "running",
          stage_status: null,
          stage_durations_ms: null,
          counts: ALL_COUNTS,
        })}
        state={catalystScreenState(input({ run_status: "running" }))}
      />,
    );
    // 1/2 completed on each of four stages is 50%.
    expect(screen.getByTestId("catalyst-progress-percent")).toHaveTextContent("50%");
    expect(screen.queryByTestId("catalyst-progress-no-percent")).toBeNull();
  });

  it("names the four bounded stages in order", () => {
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "running",
          stage_status: null,
          stage_durations_ms: null,
          counts: null,
        })}
        state={catalystScreenState(input({ run_status: "running" }))}
      />,
    );
    const names = Array.from(document.querySelectorAll(".catalyst-stage-name")).map(
      (el) => el.textContent,
    );
    expect(names).toEqual(["准备证据", "专项分析", "反证核验", "综合发布"]);
  });
});

describe("T30 — uncommitted candidates are never a conclusion", () => {
  it("shows them as still in progress, alongside the stage they belong to", () => {
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "running",
          stage_status: { evidence: "running" },
          stage_durations_ms: null,
          counts: null,
          uncommitted_candidates: 3,
        })}
        state={catalystScreenState(input({ run_status: "running" }))}
      />,
    );
    const note = screen.getByTestId("catalyst-uncommitted-candidates");
    expect(note).toHaveTextContent("3");
    expect(note).toHaveTextContent("候选不是结论");
    expect(note).toHaveTextContent("不计入判断");
  });

  it("shows no candidate note when there are none", () => {
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "running",
          stage_status: null,
          stage_durations_ms: null,
          counts: null,
          uncommitted_candidates: 0,
        })}
        state={catalystScreenState(input({ run_status: "running" }))}
      />,
    );
    expect(screen.queryByTestId("catalyst-uncommitted-candidates")).toBeNull();
  });
});

describe("T30 — every state in the design 4.5 matrix renders", () => {
  /*
    The state ids are exported and iterated below, so a row added to the matrix
    fails here until it has a rendering case. A state asserted only in a domain
    test can pass while the page renders a blank box for it.
  */
  it.each(CATALYST_SCREEN_STATE_IDS)("renders %s with a title, a body and its actions", (id) => {
    const input = inputs[id];
    const state = catalystScreenState(input);
    expect(state.id).toBe(id);

    const { container } = render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: input.run_status,
          stage_status: null,
          stage_durations_ms: null,
          counts: null,
        })}
        state={state}
        onRetry={vi.fn()}
        onResume={vi.fn()}
        onCancel={vi.fn()}
        onNewRun={vi.fn()}
        onOpenAudit={vi.fn()}
        onViewProcess={vi.fn()}
      />,
    );
    // Not a blank box: a heading, an explanation, and all four stages.
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(state.title);
    expect(state.body.length).toBeGreaterThan(0);
    expect(container.textContent).toContain(state.body);
    expect(document.querySelectorAll(".catalyst-stage")).toHaveLength(4);
    expect(container.querySelector(".catalyst-progress")).toHaveAttribute("data-state", id);
  });
});

describe("T30 — cancel, retry and resume keep their handlers", () => {
  /*
    The three are driven from different rows of the matrix, because that is
    where each is offered: `blocked_or_error` offers retry, `cancelled_or_
    interrupted` offers resume and cancel. Testing all three on one row would
    pass even if the matrix stopped offering one of them.
  */
  it("offers retry on a blocked run and calls through", () => {
    const onRetry = vi.fn();
    const onAudit = vi.fn();
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "completed",
          stage_status: null,
          stage_durations_ms: null,
          counts: null,
        })}
        state={catalystScreenState(inputs.blocked_or_error)}
        onRetry={onRetry}
        onOpenAudit={onAudit}
      />,
    );
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledOnce();
    // And the audit entry point the matrix promises for this row.
    fireEvent.click(screen.getByRole("button", { name: "打开审计中心" }));
    expect(onAudit).toHaveBeenCalledOnce();
  });

  it("offers resume and cancel on a cancelled run and calls through", () => {
    const onResume = vi.fn();
    const onCancel = vi.fn();
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "cancelled",
          stage_status: null,
          stage_durations_ms: null,
          counts: null,
        })}
        state={catalystScreenState(inputs.cancelled_or_interrupted)}
        onResume={onResume}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "恢复运行" }));
    expect(onResume).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledOnce();
    // Design 4.5: a cancelled run is explicitly not a complete result.
    expect(screen.getByText(/这不是一次完整结果/)).toBeInTheDocument();
  });

  it("offers cancel while a run is queued", () => {
    const onCancel = vi.fn();
    render(
      <CatalystProgress
        progress={catalystStageProgress({
          run_status: "created",
          stage_status: null,
          stage_durations_ms: null,
          counts: null,
        })}
        state={catalystScreenState(inputs.queued)}
        onCancel={onCancel}
      />,
    );
    expect(screen.getByRole("button", { name: "取消" })).toBeEnabled();
  });
});
