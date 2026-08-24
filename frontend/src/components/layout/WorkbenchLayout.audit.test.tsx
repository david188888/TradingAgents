import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRunHistory } from "../../hooks/useRunHistory";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import type { AuditEntryContext, AuditOpenHandler } from "../reader/AuditCenter";
import { WorkbenchLayout } from "./WorkbenchLayout";

vi.mock("../../hooks/useRunHistory", () => ({ useRunHistory: vi.fn() }));
vi.mock("../../state/WorkbenchStore", () => ({ useWorkbenchStore: vi.fn() }));
vi.mock("../controls/Controls", () => ({ Controls: () => null }));
vi.mock("../history/RunHistory", () => ({ RunHistory: () => null }));
vi.mock("../inspector/Inspector", () => ({ Inspector: () => null }));
vi.mock("../status/SwarmStatusCard", () => ({ SwarmStatusCard: () => null }));
vi.mock("../workflow/WorkflowMap", () => ({ WorkflowMap: () => null }));
vi.mock("./RunDisclosure", () => ({ RunDisclosure: () => null }));
vi.mock("../timeline/DebateTimeline", () => ({ DebateTimeline: () => null }));
vi.mock("../timeline/StageDetail", () => ({ StageDetail: () => null }));
vi.mock("../reader/ReaderSurface", () => ({ ReaderSurface: () => null }));
vi.mock("../reader/FailedRunView", () => ({ FailedRunView: () => null }));
vi.mock("../reader/DecisionBrief", () => ({
  DecisionBrief: ({ onOpenAudit }: { onOpenAudit: AuditOpenHandler }) => (
    <button
      type="button"
      onClick={(event) => onOpenAudit({ section: "overview" }, event.currentTarget)}
    >
      打开终态审计
    </button>
  ),
}));
vi.mock("../reader/AuditCenter", () => ({
  AuditCenter: ({
    open,
    context,
    onClose,
  }: {
    open: boolean;
    context: AuditEntryContext | null;
    onClose(): void;
  }) => open ? (
    <div data-testid="workbench-audit-center" data-context={JSON.stringify(context)}>
      <button type="button" onClick={onClose}>关闭集成审计</button>
    </div>
  ) : null,
}));

const mockedStore = vi.mocked(useWorkbenchStore);
const mockedHistory = vi.mocked(useRunHistory);

describe("WorkbenchLayout audit center integration", () => {
  beforeEach(() => {
    mockedHistory.mockReturnValue({
      runs: [],
      loading: false,
      error: null,
      refresh: vi.fn().mockResolvedValue(undefined),
      removeRun: vi.fn().mockResolvedValue(true),
      clearAll: vi.fn().mockResolvedValue({ removed: 0, skipped_active: false }),
    });
    mockedStore.mockReturnValue({
      run_id: "run_terminal",
      selectRun: vi.fn(),
      stream: {
        state: null,
        status: "closed",
        error: null,
        reconnect: vi.fn(),
      },
      view: {
        view: {
          terminal: true,
          view: {
            run: { status: "completed" },
            debate_journey: {},
          },
        },
        loading: false,
        error: null,
      },
    } as unknown as ReturnType<typeof useWorkbenchStore>);
  });

  it("routes a terminal entry into the mounted center with explicit context", () => {
    render(<WorkbenchLayout />);
    expect(screen.queryByTestId("workbench-audit-center")).toBeNull();
    expect(screen.queryByRole("button", { name: "实时审计栏" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "打开终态审计" }));
    expect(screen.getByTestId("workbench-audit-center")).toHaveAttribute(
      "data-context",
      JSON.stringify({ section: "overview" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "关闭集成审计" }));
    expect(screen.queryByTestId("workbench-audit-center")).toBeNull();
  });

  it("does not expose the live inspector before a run is selected", () => {
    mockedStore.mockReturnValue({
      run_id: null,
      selectRun: vi.fn(),
      stream: {
        state: { meta: { status: "created" } },
        status: "idle",
        error: null,
        reconnect: vi.fn(),
      },
      view: { view: null, loading: false, error: null },
    } as unknown as ReturnType<typeof useWorkbenchStore>);

    render(<WorkbenchLayout />);
    expect(screen.queryByRole("button", { name: "实时审计栏" })).toBeNull();
    expect(screen.getByRole("heading", { name: "选择一次运行" })).toBeInTheDocument();
  });
});
