import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useReaderAgent, useReaderProcess } from "../../hooks/useReaderProcess";
import { NativeResearchPage } from "./NativeResearchPage";

vi.mock("../../hooks/useReaderProcess", () => ({ useReaderAgent: vi.fn(), useReaderProcess: vi.fn() }));
const retryProcess = vi.fn(), retryAgent = vi.fn();
const scrollIntoView = vi.fn();
function show() {
  return render(<NativeResearchPage runId="run-a" ticker="600803" status="running" state={null}
    response={null} loading={false} error={false} onOpenAudit={vi.fn()} onCancel={vi.fn()}
    onRetry={vi.fn()} onResume={vi.fn()} onNewResearch={vi.fn()} />);
}

describe("in-progress role review navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    vi.mocked(useReaderProcess).mockReturnValue({ response: null, error: false, retry: retryProcess });
    vi.mocked(useReaderAgent).mockReturnValue({ response: null, error: false, retry: retryAgent });
  });

  it("reveals the selected review, returns focus and reopens the same role", () => {
    show();
    const entries = screen.getAllByRole("button", { name: "查看本环节与保存产物 →" });
    for (const entry of [entries[0], entries[3], entries.at(-1)!]) {
      fireEvent.click(entry);
      const detail = screen.getByRole("region", { name: "所选环节详情" });
      expect(detail).toHaveFocus();
      expect(scrollIntoView).toHaveBeenCalled();
      expect(entry).toHaveAttribute("aria-expanded", "true");
      expect(entry).toHaveAttribute("aria-controls", detail.id);
      const calls = scrollIntoView.mock.calls.length;
      fireEvent.click(entry);
      expect(scrollIntoView.mock.calls.length).toBeGreaterThan(calls);
      fireEvent.click(within(detail).getByRole("button", { name: "收起角色回顾" }));
      expect(entry).toHaveFocus();
      expect(entry).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("region", { name: "所选环节详情" })).toBeNull();
    }
  });

  it("shows process read failure inside the selected review and retries it", () => {
    vi.mocked(useReaderProcess).mockReturnValue({ response: null, error: true, retry: retryProcess });
    show();
    fireEvent.click(screen.getAllByRole("button", { name: "查看本环节与保存产物 →" })[0]);
    const detail = screen.getByRole("region", { name: "所选环节详情" });
    expect(within(detail).getByRole("status")).toHaveTextContent("产物暂时无法读取");
    fireEvent.click(within(detail).getByRole("button", { name: "重试读取" }));
    expect(retryProcess).toHaveBeenCalledOnce();
    expect(retryAgent).toHaveBeenCalledOnce();
  });
});
