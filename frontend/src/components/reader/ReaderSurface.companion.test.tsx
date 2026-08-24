import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type {
  CompanionDTO,
  CompanionSelectionDTO,
  LearningReaderV2DTO,
} from "../../api/contracts";
import { useCompanion } from "../../hooks/useCompanion";
import { useReader } from "../../hooks/useReader";
import { ReaderSurface } from "./ReaderSurface";

vi.mock("../../hooks/useReader", () => ({ useReader: vi.fn() }));
vi.mock("../../hooks/useCompanion", () => ({ useCompanion: vi.fn() }));

const mockedUseReader = vi.mocked(useReader);
const mockedUseCompanion = vi.mocked(useCompanion);
const retry = vi.fn();
let mediaMatches = true;
const mediaListeners = new Set<(event: MediaQueryListEvent) => void>();

const reader: LearningReaderV2DTO = {
  kind: "typed",
  schema_version: 2,
  run_id: "run_companion_ui",
  mode: "company_research",
  ticker: "000338.SZ",
  horizon: "medium",
  as_of: "2026-08-10T00:00:00Z",
  availability: "full",
  decision_eligibility: "limited",
  evidence_verdict: "PASS",
  research_tilt: "neutral",
  rating_confidence: 0.72,
  claims: [
    {
      claim_key: "claim-margin",
      claim_type: "fact",
      text: "利润率改善",
      evidence_ref_ids: ["ev-annual-report"],
      source_dates: ["2026-06-30"],
      supporting_claim_keys: [],
      coverage_ref_ids: [],
      confidence: 0.81,
      action_impact: { severity: "medium", direction: "positive", reason: "盈利改善" },
      lifecycle_status: "active",
    },
  ],
  scenarios: null,
  catalysts: [
    {
      item_id: "catalyst-results",
      text: "季度业绩发布",
      claim_keys: ["claim-margin"],
      trigger_kind: "date",
      trigger_value: "2026-10-30",
      due_at: null,
      status: "pending",
      evidence_ref_ids: [],
    },
  ],
  invalidation_conditions: [
    {
      item_id: "risk-margin",
      text: "毛利率跌破历史区间",
      claim_keys: ["claim-margin"],
      trigger_kind: "filing",
      trigger_value: "next-report",
      due_at: null,
      status: "pending",
      evidence_ref_ids: ["ev-annual-report"],
    },
  ],
  review_plan: null,
  analyst_cards: [
    {
      lens: "fundamentals",
      availability: "ready",
      summary: "基本面覆盖完整",
      confidence: 0.77,
      finding_claim_keys: ["claim-margin"],
      capability_statuses: [],
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
    {
      ref_id: "ev-annual-report",
      source_label: "2026 半年报",
      resolution_status: "available",
    },
  ],
  coverage_refs: [],
  omissions: [],
  thesis_diff: null,
  audit_entry: {
    route: "reader",
    artifact_count: 2,
    tool_call_count: 1,
    degradation_count: 0,
  },
};

function companion(selection: CompanionSelectionDTO): CompanionDTO {
  return {
    schema_version: 1,
    run_id: reader.run_id,
    selection,
    summary: `${selection.kind} 伴读摘要`,
    actual_coverage: ["来源：2026 半年报"],
    conclusion_impact: "支持当前研究结论",
    next_validation: "下一期复核",
  };
}

function setWide(next: boolean): void {
  mediaMatches = next;
  const event = { matches: next, media: "(min-width: 1400px)" } as MediaQueryListEvent;
  for (const listener of mediaListeners) listener(event);
}

describe("ReaderSurface companion", () => {
  beforeEach(() => {
    mediaMatches = true;
    mediaListeners.clear();
    retry.mockReset();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: mediaMatches,
        media: query,
        onchange: null,
        addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
          mediaListeners.add(listener);
        },
        removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
          mediaListeners.delete(listener);
        },
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    mockedUseReader.mockReturnValue({ reader, loading: false, error: null });
    mockedUseCompanion.mockImplementation((_runId, selection) => ({
      companion: selection === null ? null : companion(selection),
      loading: false,
      error: null,
      retry,
    }));
  });

  it("maps the four explicit public entry types and never turns catalysts into risks", () => {
    render(<ReaderSurface runId={reader.run_id} />);
    expect(mockedUseCompanion).toHaveBeenLastCalledWith(reader.run_id, null);

    fireEvent.click(screen.getByRole("button", { name: /查看论点伴读/ }));
    expect(mockedUseCompanion).toHaveBeenLastCalledWith(reader.run_id, {
      kind: "claim",
      id: "claim-margin",
    });

    fireEvent.click(screen.getByRole("button", { name: /查看证据伴读/ }));
    expect(mockedUseCompanion).toHaveBeenLastCalledWith(reader.run_id, {
      kind: "evidence",
      id: "ev-annual-report",
    });

    fireEvent.click(screen.getByRole("button", { name: /查看风险伴读/ }));
    expect(mockedUseCompanion).toHaveBeenLastCalledWith(reader.run_id, {
      kind: "risk",
      id: "risk-margin",
    });

    fireEvent.click(screen.getByRole("button", { name: /查看基本面视角伴读/ }));
    expect(mockedUseCompanion).toHaveBeenLastCalledWith(reader.run_id, {
      kind: "role",
      id: "fundamentals",
    });
    expect(screen.queryByRole("button", { name: /季度业绩发布.*伴读/ })).toBeNull();
  });

  it("moves through temporary, pinned, drawer, and back to temporary without losing focus rules", async () => {
    render(<ReaderSurface runId={reader.run_id} />);
    const trigger = screen.getByRole("button", { name: /查看论点伴读/ });
    trigger.focus();
    fireEvent.click(trigger);

    let panel = screen.getByRole("complementary", { name: "研究伴读" });
    expect(panel).toHaveAttribute("data-mode", "temporary");
    expect(trigger).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "固定伴读栏" }));
    panel = screen.getByRole("complementary", { name: "研究伴读" });
    expect(panel).toHaveAttribute("data-mode", "pinned");

    act(() => setWide(false));
    const drawer = await screen.findByRole("dialog", { name: "研究伴读" });
    expect(drawer).toHaveAttribute("data-mode", "drawer");
    expect(screen.queryByRole("button", { name: /固定伴读栏|取消固定/ })).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "关闭伴读栏" })).toHaveFocus());

    act(() => setWide(true));
    panel = await screen.findByRole("complementary", { name: "研究伴读" });
    expect(panel).toHaveAttribute("data-mode", "temporary");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "研究伴读" })).toBeNull();
    expect(trigger).toHaveFocus();
    expect(mockedUseCompanion).toHaveBeenLastCalledWith(reader.run_id, null);
  });

  it("shows safe typed 404 and retries ordinary errors", () => {
    mockedUseCompanion.mockImplementation((_runId, selection) => ({
      companion: null,
      loading: false,
      error: selection === null
        ? null
        : new ApiError({
            code: "companion_not_found",
            message: "private backend detail",
            status: 404,
          }),
      retry,
    }));
    const { rerender } = render(<ReaderSurface runId={reader.run_id} />);
    fireEvent.click(screen.getByRole("button", { name: /查看论点伴读/ }));
    expect(screen.getByText("该伴读内容当前不可用")).toBeInTheDocument();
    expect(screen.queryByText("private backend detail")).toBeNull();
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();

    mockedUseCompanion.mockImplementation((_runId, selection) => ({
      companion: null,
      loading: false,
      error: selection === null ? null : new Error("网络连接暂时不可用"),
      retry,
    }));
    rerender(<ReaderSurface runId={reader.run_id} />);
    expect(screen.getByText("暂时无法读取公开伴读内容，请稍后重试")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
