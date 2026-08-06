/**
 * F3 - RunHistory component tests.
 *
 * RunHistory is now a pure renderer receiving runs/loading/error as props
 * (the fetch lives in WorkbenchLayout via useRunHistory). Verifies: render
 * of a 3-run fixture (completed/failed/running), click -> selectRun wiring,
 * empty-list placeholder, loading placeholder, and error display.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { RunSummaryDTO } from "../../api/contracts";

const mockStore = vi.hoisted(() => ({
  useWorkbenchSelection: vi.fn(),
}));

vi.mock("../../state/WorkbenchStore", () => ({
  useWorkbenchSelection: mockStore.useWorkbenchSelection,
}));

import { RunHistory } from "./RunHistory";

const FIXTURES: RunSummaryDTO[] = [
  {
    run_id: "run-1",
    status: "completed",
    ticker: "600519.SS",
    analysis_date: "2026-07-18",
    asset_type: "stock",
    created_at: "2026-07-18T10:00:00Z",
    updated_at: "2026-07-18T10:30:00Z",
    latest_sequence: 42,
    final_signal: "Buy",
    summary: "Bullish",
  },
  {
    run_id: "run-2",
    status: "failed",
    ticker: "000001.SZ",
    analysis_date: "2026-07-18",
    asset_type: "stock",
    created_at: "2026-07-18T09:00:00Z",
    updated_at: "2026-07-18T09:15:00Z",
    latest_sequence: 10,
    final_signal: null,
    summary: null,
    error_category: "provider_timeout",
  },
  {
    run_id: "run-3",
    status: "running",
    ticker: "AAPL",
    analysis_date: "2026-07-19",
    asset_type: "stock",
    created_at: "2026-07-19T08:00:00Z",
    updated_at: "2026-07-19T08:05:00Z",
    latest_sequence: 5,
    final_signal: null,
    summary: null,
  },
];

function makeStore(
  overrides: Partial<{
    run_id: string | null;
    selectRun: ReturnType<typeof vi.fn>;
  }> = {},
) {
  return {
    run_id: null as string | null,
    selectRun: vi.fn(),
    stream: {
      state: null,
      status: "idle" as const,
      error: null,
    },
    ...overrides,
  };
}

describe("RunHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStore.useWorkbenchSelection.mockReturnValue(makeStore());
  });

  it("renders runs from props (newest-first as provided)", () => {
    render(<RunHistory runs={FIXTURES} loading={false} error={null} onDeleteRun={vi.fn()} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);

    expect(screen.getByText("600519.SS")).toBeInTheDocument();
    expect(screen.getByText("000001.SZ")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    expect(screen.getByText("已完成", { selector: ".history-group-title" })).toBeInTheDocument();
    expect(screen.getByText(/失败（最近/)).toBeInTheDocument();
    expect(screen.getByText("进行中", { selector: ".history-group-title" })).toBeInTheDocument();
    // The running item still carries the pulsing status badge.
    expect(screen.getByText(/● 运行中/)).toBeInTheDocument();
  });

  it("groups runs into active / completed / failed sections", () => {
    render(<RunHistory runs={FIXTURES} loading={false} error={null} onDeleteRun={vi.fn()} />);

    expect(screen.getByText("进行中", { selector: ".history-group-title" })).toBeInTheDocument();
    expect(screen.getByText("已完成", { selector: ".history-group-title" })).toBeInTheDocument();
    expect(screen.getByText(/失败（最近/)).toBeInTheDocument();

    // Failed item shows the mapped error category instead of a final signal.
    expect(screen.getByText(/供应商超时/)).toBeInTheDocument();
    // All three fixtures still rendered.
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("renders only the 3 most recent failed runs", () => {
    const manyFailed: RunSummaryDTO[] = Array.from({ length: 5 }, (_, index) => ({
      run_id: `fail-${index}`,
      status: "failed",
      ticker: `F${index}`,
      analysis_date: "2026-07-18",
      asset_type: "stock",
      // index 0 is newest; order is preserved as supplied
      created_at: `2026-07-18T0${5 - index}:00:00Z`,
      updated_at: `2026-07-18T0${5 - index}:00:00Z`,
      latest_sequence: 1,
      final_signal: null,
      summary: null,
      error_category: "unexpected_internal_failure",
    }));

    render(<RunHistory runs={manyFailed} loading={false} error={null} onDeleteRun={vi.fn()} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    // Items preserve supplied order (newest first per backend contract).
    expect(screen.getByText("F0")).toBeInTheDocument();
    expect(screen.queryByText("F3")).not.toBeInTheDocument();
    expect(screen.getByText(/更早的失败记录已折叠/)).toBeInTheDocument();
  });

  it("calls selectRun with the run_id when an item is clicked", () => {
    const selectRun = vi.fn();
    mockStore.useWorkbenchSelection.mockReturnValue(makeStore({ selectRun }));

    render(<RunHistory runs={FIXTURES} loading={false} error={null} onDeleteRun={vi.fn()} />);

    // Click the completed-run item (identified by ticker), since active runs
    // are grouped first and list order is no longer the fixture order.
    fireEvent.click(screen.getByText("600519.SS").closest("li")!);
    expect(selectRun).toHaveBeenCalledWith("run-1");
  });

  it("renders the placeholder when there are no runs", () => {
    render(<RunHistory runs={[]} loading={false} error={null} onDeleteRun={vi.fn()} />);
    expect(screen.getByText("暂无运行记录")).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("renders the loading placeholder while loading with no runs yet", () => {
    render(<RunHistory runs={[]} loading={true} error={null} onDeleteRun={vi.fn()} />);
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });

  it("renders the error message when fetch failed", () => {
    render(
      <RunHistory
        runs={[]}
        loading={false}
        error={new Error("network down")}
        onDeleteRun={vi.fn()}
      />,
    );
    expect(screen.getByText(/加载失败/)).toBeInTheDocument();
    expect(screen.getByText(/network down/)).toBeInTheDocument();
  });

  it("calls onDeleteRun after confirming a delete button", () => {
    const onDeleteRun = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <RunHistory runs={FIXTURES} loading={false} error={null} onDeleteRun={onDeleteRun} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除 600519.SS 的运行记录" }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDeleteRun).toHaveBeenCalledWith("run-1");
    confirmSpy.mockRestore();
  });

  it("does not call onDeleteRun when deletion is cancelled", () => {
    const onDeleteRun = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <RunHistory runs={FIXTURES} loading={false} error={null} onDeleteRun={onDeleteRun} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除 600519.SS 的运行记录" }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDeleteRun).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
