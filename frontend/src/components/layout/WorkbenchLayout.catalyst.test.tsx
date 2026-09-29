/**
 * T26 — the completed page has exactly one main summary.
 *
 * This is the test the restructure exists to pass. Before it, the completed
 * page mounted `DecisionBrief` (which renders `run-view-v1.view.brief` and its
 * `learning_summary`) directly above `ReaderSurface`, and the two carried the
 * same sentences twice — 96% overlap, measured against real runs, with a
 * first-screen p50 of 8,399 characters against a 420 budget.
 *
 * The duplication could not be removed by deleting a projection field:
 * `executive_summary` is null in 15/15 real runs, so those fields carry no
 * content to delete. The only fix is to stop mounting two live containers, and
 * that is what these tests assert — not a diff, but a rendered count.
 */
import { render, screen, fireEvent, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import catalystMinimalComplete from "../../../../shared_fixtures/catalyst/catalyst_minimal_complete.json";
import catalystUnsupported from "../../../../shared_fixtures/catalyst/catalyst_unsupported.json";
import type { CatalystReadState } from "../../api/contracts";
import { useCatalyst } from "../../hooks/useCatalyst";
import { useRunHistory } from "../../hooks/useRunHistory";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { WorkbenchLayout } from "./WorkbenchLayout";

const mockStoreModule = vi.hoisted(() => ({ useWorkbenchStore: vi.fn() }));
const mockCatalystModule = vi.hoisted(() => ({ useCatalyst: vi.fn() }));

vi.mock("../../hooks/useRunHistory", () => ({ useRunHistory: vi.fn() }));
vi.mock("../../hooks/useCatalyst", () => ({ useCatalyst: mockCatalystModule.useCatalyst }));
vi.mock("../../state/WorkbenchStore", () => ({
  useWorkbenchStore: mockStoreModule.useWorkbenchStore,
  useWorkbenchStream: () => mockStoreModule.useWorkbenchStore().stream,
  useWorkbenchSelection: () => mockStoreModule.useWorkbenchStore(),
  useWorkbenchRunView: () => mockStoreModule.useWorkbenchStore().view,
}));
// The heavy classic surfaces are stubbed so the count below is about the
// *layout's* mount decisions, not about what ReaderSurface happens to render.
vi.mock("../controls/Controls", () => ({ Controls: () => null }));
vi.mock("../history/RunHistory", () => ({ RunHistory: () => null }));
vi.mock("../inspector/Inspector", () => ({ Inspector: () => null }));
vi.mock("../status/SwarmStatusCard", () => ({ SwarmStatusCard: () => null }));
vi.mock("../workflow/WorkflowMap", () => ({ WorkflowMap: () => null }));
vi.mock("./RunDisclosure", () => ({ RunDisclosure: () => null }));
vi.mock("../timeline/StageDetail", () => ({ StageDetail: () => null }));
vi.mock("../reader/FailedRunView", () => ({ FailedRunView: () => null }));

const mockedStore = vi.mocked(useWorkbenchStore);
const mockedHistory = vi.mocked(useRunHistory);
const mockedCatalyst = vi.mocked(useCatalyst);

const RUN_ID = "run_catalyst";

/**
 * The stub for `ReaderSurface` and `DecisionBrief`.
 *
 * `DecisionBrief` is stubbed rather than deleted from the import graph so this
 * test can assert it is *not mounted*. The stub carries the class name the
 * layout would have given the real one, which is what the "no
 * `learning_summary` container beside the brief" assertion looks for.
 */
vi.mock("../reader/ReaderSurface", () => ({
  ReaderSurface: () => <div className="reader-surface" data-testid="reader-surface" />,
}));
vi.mock("../reader/DecisionBrief", () => ({
  DecisionBrief: () => <div className="decision-brief" data-testid="decision-brief" />,
}));

function classicTerminalView(ticker = "600519"): unknown {
  return {
    view: {
      terminal: true,
      view: {
        run: { run_id: RUN_ID, ticker, status: "completed", mode: "company_research" },
        brief: {
          availability: { state: "ready" },
          reason_code: null,
          value: {
            // The duplication source, verbatim from the real projection: the
            // same inference sentence the reader brief also carries.
            learning_summary: {
              inferences: ["预告已披露且日期明确，值得在下一次定期报告时优先核查收入兑现。"],
              facts: [],
              invalidation_conditions: ["分产品毛利率数据源不可用。"],
              catalysts: ["核对中报分产品毛利率。"],
            },
            executive_summary: null,
            research_rating: "偏积极",
          },
        },
        debate_journey: { stages: [] },
      },
    },
    loading: false,
    error: null,
  };
}

function readyCatalyst(): unknown {
  return {
    state: catalystMinimalComplete as unknown as CatalystReadState,
    brief: catalystMinimalComplete.brief,
    kase: {
      as_of: (catalystMinimalComplete as unknown as { as_of: string }).as_of,
      evidence: [],
      events: [],
    },
    screen: {
      brief: {},
      priority: "verify_first",
      priority_label: "优先核查",
      priority_hint: "h",
      overflow: false,
      overflow_reason: null,
      character_count: 122,
      budget: 420,
      rows: ["judgement", "priority", "catalyst", "evidence", "doubt", "next_check", "limitations"].map(
        (id) => ({ id, label: id, lines: [`${id} 行`], refs: [], placeholder: "—" }),
      ),
      limitations: ["分产品毛利率数据源不可用。"],
      limitation_refs: [[]],
    },
    stageStatus: null,
    stageDurations: null,
    stageCounts: null,
    uncommittedCandidates: 0,
    loading: false,
    error: null,
    refresh: vi.fn(),
    runId: RUN_ID,
  };
}

function installStore(overrides: Record<string, unknown> = {}): void {
  mockedStore.mockReturnValue({
    run_id: RUN_ID,
    selectRun: vi.fn(),
    stream: { state: null, status: "closed", error: null, reconnect: vi.fn() },
    view: classicTerminalView(),
    ...overrides,
  } as unknown as ReturnType<typeof useWorkbenchStore>);
}

describe("T26 — the completed page mounts one main summary", () => {
  beforeEach(() => {
    mockedHistory.mockReturnValue({
      runs: [],
      loading: false,
      error: null,
      refresh: vi.fn().mockResolvedValue(undefined),
      removeRun: vi.fn().mockResolvedValue(true),
      clearAll: vi.fn().mockResolvedValue({ removed: 0, skipped_active: false }),
    });
    installStore();
    mockedCatalyst.mockReturnValue(readyCatalyst() as unknown as ReturnType<typeof useCatalyst>);
  });

  it("mounts exactly one main summary container for a completed catalyst run", () => {
    const { container } = render(<WorkbenchLayout />);
    const summaries = container.querySelectorAll("[data-main-summary]");
    expect(summaries).toHaveLength(1);
    expect(summaries[0].getAttribute("data-main-summary")).toBe("catalyst_brief");
  });

  it("no longer mounts DecisionBrief beside the reader surface", () => {
    /*
      The de-duplication evidence. Both containers were live on the completed
      page and overlapped 96%; now the classic `DecisionBrief` — the container
      that rendered `view.brief` and `learning_summary` — is not mounted at all
      on the catalyst route.
    */
    const { container } = render(<WorkbenchLayout />);
    expect(screen.queryByTestId("decision-brief")).toBeNull();
    expect(container.querySelector(".decision-brief")).toBeNull();
    // And the text that used to be rendered twice is rendered once.
    expect(container.textContent).not.toContain("预告已披露且日期明确，值得在下一次定期报告时优先核查收入兑现。");
  });

  it("keeps the classic surfaces reachable rather than deleting them", () => {
    // De-duplication must not mean removing capability. ReaderSurface is the
    // 依据与事件 tab's content, mounted on demand.
    render(<WorkbenchLayout />);
    expect(screen.queryByTestId("reader-surface")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "依据与事件" }));
    expect(screen.getByTestId("reader-surface")).toBeInTheDocument();
    // And the summary count is still one while the detail is open.
    expect(document.querySelectorAll("[data-main-summary]")).toHaveLength(1);
  });

  it("offers the three tabs and defaults to the brief", () => {
    render(<WorkbenchLayout />);
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["研究简报", "依据与事件", "研究过程"]);
    expect(screen.getByRole("tab", { name: "研究简报" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps the 更多研究 entry point reachable", () => {
    render(<WorkbenchLayout />);
    expect(screen.getByRole("button", { name: "更多研究" })).toBeInTheDocument();
    // The audit entry point stays reachable too.
    expect(screen.getByRole("button", { name: "打开审计中心" })).toBeInTheDocument();
  });
});

describe("T31 — a legacy run is read in layers and gets no priority", () => {
  beforeEach(() => {
    mockedHistory.mockReturnValue({
      runs: [],
      loading: false,
      error: null,
      refresh: vi.fn().mockResolvedValue(undefined),
      removeRun: vi.fn().mockResolvedValue(true),
      clearAll: vi.fn().mockResolvedValue({ removed: 0, skipped_active: false }),
    });
    installStore();
    mockedCatalyst.mockReturnValue({
      ...(readyCatalyst() as object),
      state: catalystUnsupported as unknown as CatalystReadState,
      screen: null,
      kase: null,
    } as unknown as ReturnType<typeof useCatalyst>);
  });

  it("routes a legacy run to the three-layer reader", () => {
    const { container } = render(<WorkbenchLayout />);
    const layers = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(layers).toEqual(["概要", "详情", "研究过程"]);
    // Still exactly one summary container, and it is the legacy one.
    expect(container.querySelectorAll("[data-main-summary]")).toHaveLength(0);
    expect(container.querySelectorAll(".legacy-reader")).toHaveLength(1);
  });

  it("produces no research priority and says so", () => {
    const { container } = render(<WorkbenchLayout />);
    // The old rating is shown as a rating, in the old vocabulary.
    expect(screen.getByText("偏积极")).toBeInTheDocument();
    // None of the four new categories appears.
    for (const label of ["优先核查", "持续观察", "暂缓研究", "信息不足"]) {
      expect(container.textContent).not.toContain(label);
    }
    expect(container.textContent).toContain("没有研究优先级");
  });

  it("keeps the audit entry point reachable from the process layer", () => {
    render(<WorkbenchLayout />);
    fireEvent.click(screen.getByRole("tab", { name: "研究过程" }));
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByRole("button", { name: "打开审计中心" })).toBeInTheDocument();
  });

  it("does not mount the catalyst brief on a legacy run", () => {
    render(<WorkbenchLayout />);
    expect(document.querySelector(".catalyst-brief")).toBeNull();
    expect(screen.queryByTestId("reader-surface")).toBeNull();
  });
});
