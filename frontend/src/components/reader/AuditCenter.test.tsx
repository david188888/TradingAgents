import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditDetailDTO, AuditSummaryDTO } from "../../api/contracts";
import { useAuditDetail, useAuditSummary } from "../../hooks/useAudit";
import { AuditCenter } from "./AuditCenter";

vi.mock("../../hooks/useAudit", () => ({
  useAuditSummary: vi.fn(),
  useAuditDetail: vi.fn(),
}));

const mockedSummary = vi.mocked(useAuditSummary);
const mockedDetail = vi.mocked(useAuditDetail);
const refresh = vi.fn();
const retry = vi.fn();
let narrow = false;
const mediaListeners = new Set<(event: MediaQueryListEvent) => void>();

const summary: AuditSummaryDTO = {
  schema_version: 1,
  run_id: "run_audit_ui",
  source_sequence: 24,
  availability: "partial",
  reason_code: "terminal_data_incomplete",
  run: {
    item_id: "run",
    status: "completed",
    ticker: "000338.SZ",
    mode: "company_research",
    horizon: "medium",
    created_at: "2026-08-11T00:00:00Z",
    completed_at: "2026-08-11T00:01:00Z",
    duration_ms: 60000,
    llm_provider: "openai",
    quick_think_llm: "gpt-4.1-mini",
    deep_think_llm: "gpt-4.1",
    data_quality: "limited",
  },
  counts: { stages: 6, roles: 1, turns: 1, model_calls: 1, tool_calls: 1, artifacts: 1, prompts: 1, configs: 1, reports: 1 },
  sections: [
    { section_id: "overview", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "roles", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "capabilities", availability: "not_recorded", reason_code: "not_recorded", item_count: 0 },
    { section_id: "tools", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "artifacts", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "prompt_config", availability: "ready", reason_code: null, item_count: 2 },
  ],
  stage_navigation: [
    {
      stage_id: "research",
      label: "研究辩论",
      status: "completed",
      availability: "ready",
      reason_code: null,
      related_selections: [{ kind: "role", id: "analyst.fundamentals" }],
    },
  ],
  roles: [
    { item_id: "analyst.fundamentals", actor_id: "analyst.fundamentals", label: "Fundamentals Analyst", status: "completed", turn_count: 1, model_call_count: 1, duration_ms: 900 },
  ],
  capabilities: [],
  tools: [
    { item_id: "tool-1", tool_name: "get_market_data", status: "committed", execution_count: 1, cache_status: "not_recorded", failure_code: null },
  ],
  artifacts: [
    { item_id: "report-1", label: "Report Final", artifact_kind: "report-final", media_type: "text/markdown", byte_size: 128, producer_stage: "portfolio", content_exposure: "safe_inline", is_report: true },
  ],
  prompts: [
    { item_id: "prompt-1", label: "Prompt snapshot", actor_id: "analyst.fundamentals", model_call_id: "model-1", redaction_status: "redacted", byte_size: 80 },
  ],
  configs: [
    { item_id: "config-1", label: "Effective config", actor_id: "analyst.fundamentals", model_call_id: null, redaction_status: "redacted", byte_size: 90 },
  ],
};

const detail: AuditDetailDTO = {
  schema_version: 1,
  run_id: summary.run_id,
  source_sequence: summary.source_sequence,
  selection: { kind: "role", id: "analyst.fundamentals" },
  availability: "ready",
  reason_code: null,
  title: "Fundamentals Analyst",
  facts: [{ label: "状态", value: "completed" }],
  related_selections: [],
  content: { mode: "none", media_type: null, byte_size: null, redaction_status: "clean", text: null, download_url: null },
};

function setNarrow(next: boolean): void {
  narrow = next;
  const event = { matches: next, media: "(max-width: 1399px)" } as MediaQueryListEvent;
  for (const listener of mediaListeners) listener(event);
}

describe("AuditCenter", () => {
  beforeEach(() => {
    narrow = false;
    mediaListeners.clear();
    refresh.mockReset();
    retry.mockReset();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: narrow,
        media: query,
        onchange: null,
        addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => mediaListeners.add(listener),
        removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => mediaListeners.delete(listener),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    mockedSummary.mockReturnValue({ summary, loading: false, refreshing: false, error: null, refresh });
    mockedDetail.mockReturnValue({ detail, loading: false, error: null, retry });
  });

  it("stays absent while closed and opens a six-section modal without preselecting detail", async () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    const { rerender } = render(
      <AuditCenter runId={summary.run_id} open={false} context={null} returnFocus={trigger} onClose={vi.fn()} />,
    );
    expect(screen.queryByRole("dialog", { name: "审计中心" })).toBeNull();
    expect(mockedSummary).toHaveBeenLastCalledWith(summary.run_id, false);

    rerender(
      <AuditCenter runId={summary.run_id} open context={null} returnFocus={trigger} onClose={vi.fn()} />,
    );
    expect(await screen.findByRole("dialog", { name: "审计中心" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /概览|角色|能力|工具|产物|Prompt 与配置/ })).toHaveLength(6);
    expect(mockedDetail).toHaveBeenLastCalledWith(summary.run_id, summary.source_sequence, null, refresh);
    await waitFor(() => expect(screen.getByRole("button", { name: "关闭审计中心" })).toHaveFocus());
    trigger.remove();
  });

  it("uses entry context only as a highlight, then applies layered Escape and focus return", async () => {
    const close = vi.fn();
    const returnFocus = document.createElement("button");
    document.body.append(returnFocus);
    render(
      <AuditCenter
        runId={summary.run_id}
        open
        context={{ section: "roles", itemId: "analyst.fundamentals" }}
        returnFocus={returnFocus}
        onClose={close}
      />,
    );
    const role = screen.getByRole("button", { name: /Fundamentals Analyst/ });
    expect(role).toHaveAttribute("data-highlighted", "true");
    expect(mockedDetail).toHaveBeenLastCalledWith(summary.run_id, summary.source_sequence, null, refresh);

    fireEvent.click(role);
    expect(mockedDetail).toHaveBeenLastCalledWith(
      summary.run_id,
      summary.source_sequence,
      { kind: "role", id: "analyst.fundamentals" },
      refresh,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).not.toHaveBeenCalled();
    await waitFor(() => expect(role).toHaveFocus());
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledTimes(1);
    expect(returnFocus).toHaveFocus();
    returnFocus.remove();
  });

  it("turns detail into an inner modal overlay below 1400px and restores its trigger", async () => {
    act(() => setNarrow(true));
    render(
      <AuditCenter runId={summary.run_id} open context={{ section: "roles" }} returnFocus={null} onClose={vi.fn()} />,
    );
    const role = screen.getByRole("button", { name: /Fundamentals Analyst/ });
    fireEvent.click(role);
    const overlay = screen.getByRole("dialog", { name: "审计详情" });
    expect(overlay).toHaveAttribute("aria-modal", "true");
    expect(screen.getByTestId("audit-browser")).toHaveAttribute("aria-hidden", "true");
    await waitFor(() => expect(screen.getByRole("button", { name: "返回审计列表" })).toHaveFocus());
    fireEvent.click(screen.getByRole("button", { name: "返回审计列表" }));
    expect(screen.queryByRole("dialog", { name: "审计详情" })).toBeNull();
    await waitFor(() => expect(role).toHaveFocus());
  });

  it("renders safe unavailable and retry states without raw fallback", () => {
    mockedSummary.mockReturnValue({
      summary: { ...summary, availability: "unavailable", reason_code: "projection_failed" },
      loading: false,
      refreshing: false,
      error: new Error("private backend failure"),
      refresh,
    });
    render(
      <AuditCenter runId={summary.run_id} open context={null} returnFocus={null} onClose={vi.fn()} />,
    );
    expect(screen.getByText("审计摘要当前不可用")).toBeInTheDocument();
    expect(screen.queryByText("private backend failure")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重新读取审计摘要" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
