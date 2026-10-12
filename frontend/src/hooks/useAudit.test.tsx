import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, getAuditDetail, getAuditSummary, getReaderProcess, getResearchRecord } from "../api/client";
import type { AuditDetailDTO, AuditSelectionDTO, AuditSummaryDTO, ReaderProcessDTO } from "../api/contracts";
import { useAuditDetail, useAuditResearch, useAuditSummary } from "./useAudit";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getAuditSummary: vi.fn(), getAuditDetail: vi.fn(), getReaderProcess: vi.fn(), getResearchRecord: vi.fn() };
});

const mockedSummary = vi.mocked(getAuditSummary);
const mockedDetail = vi.mocked(getAuditDetail);
const roleSelection: AuditSelectionDTO = { kind: "role", id: "analyst.fundamentals" };
const toolSelection: AuditSelectionDTO = { kind: "tool", id: "tool-1" };

function summary(sequence: number): AuditSummaryDTO {
  return {
    schema_version: 1,
    run_id: "run_one",
    source_sequence: sequence,
    availability: "ready",
    reason_code: null,
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
      quick_think_llm: "quick",
      deep_think_llm: "deep",
      data_quality: "healthy",
    },
    counts: { stages: 6, roles: 1, turns: 1, model_calls: 1, tool_calls: 1, artifacts: 0, prompts: 0, configs: 0, reports: 0 },
    sections: [
      { section_id: "overview", availability: "ready", reason_code: null, item_count: 1 },
      { section_id: "roles", availability: "ready", reason_code: null, item_count: 1 },
      { section_id: "capabilities", availability: "not_recorded", reason_code: "not_recorded", item_count: 0 },
      { section_id: "tools", availability: "ready", reason_code: null, item_count: 1 },
      { section_id: "artifacts", availability: "not_recorded", reason_code: "not_recorded", item_count: 0 },
      { section_id: "prompt_config", availability: "not_recorded", reason_code: "not_recorded", item_count: 0 },
    ],
    stage_navigation: [],
    roles: [],
    capabilities: [],
    tools: [],
    artifacts: [],
    prompts: [],
    configs: [],
  };
}

function detail(sequence: number, selection: AuditSelectionDTO): AuditDetailDTO {
  return {
    schema_version: 1,
    run_id: "run_one",
    source_sequence: sequence,
    selection,
    availability: "ready",
    reason_code: null,
    title: `${selection.kind} detail`,
    facts: [],
    related_selections: [],
    content: { mode: "none", media_type: null, byte_size: null, redaction_status: "clean", text: null, download_url: null },
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("Audit hooks", () => {
  beforeEach(() => {
    mockedSummary.mockReset();
    mockedDetail.mockReset();
  });

  it("does no work while closed and revalidates once on every open", async () => {
    mockedSummary.mockResolvedValueOnce(summary(10)).mockResolvedValueOnce(summary(11));
    const { result, rerender } = renderHook(
      ({ open }) => useAuditSummary("run_one", open),
      { initialProps: { open: false } },
    );
    expect(mockedSummary).not.toHaveBeenCalled();

    rerender({ open: true });
    await waitFor(() => expect(result.current.summary?.source_sequence).toBe(10));
    expect(mockedSummary).toHaveBeenCalledTimes(1);

    rerender({ open: false });
    expect(result.current.summary).toBeNull();
    rerender({ open: true });
    expect(result.current.summary?.source_sequence).toBe(10);
    await waitFor(() => expect(result.current.summary?.source_sequence).toBe(11));
    expect(mockedSummary).toHaveBeenCalledTimes(2);
  });

  it("aborts a closed summary request and retries failures with a fresh request", async () => {
    const pending = deferred<AuditSummaryDTO>();
    mockedSummary.mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(summary(12));
    const { result, rerender } = renderHook(
      ({ open }) => useAuditSummary("run_one", open),
      { initialProps: { open: true } },
    );
    await waitFor(() => expect(mockedSummary).toHaveBeenCalledTimes(1));
    const firstSignal = mockedSummary.mock.calls[0]?.[1];
    rerender({ open: false });
    expect(firstSignal?.aborted).toBe(true);

    rerender({ open: true });
    await waitFor(() => expect(result.current.error?.message).toBe("offline"));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.summary?.source_sequence).toBe(12));
    expect(mockedSummary).toHaveBeenCalledTimes(3);
  });

  it("fetches details only after selection and caches by source sequence", async () => {
    mockedDetail
      .mockResolvedValueOnce(detail(10, roleSelection))
      .mockResolvedValueOnce(detail(11, roleSelection));
    const onStale = vi.fn();
    const { result, rerender } = renderHook(
      ({ sequence, selection }) => useAuditDetail("run_one", sequence, selection, onStale),
      { initialProps: { sequence: 10, selection: null as AuditSelectionDTO | null } },
    );
    expect(mockedDetail).not.toHaveBeenCalled();

    rerender({ sequence: 10, selection: roleSelection });
    await waitFor(() => expect(result.current.detail?.source_sequence).toBe(10));
    rerender({ sequence: 10, selection: null });
    rerender({ sequence: 10, selection: roleSelection });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockedDetail).toHaveBeenCalledTimes(1);

    rerender({ sequence: 11, selection: roleSelection });
    await waitFor(() => expect(result.current.detail?.source_sequence).toBe(11));
    expect(mockedDetail).toHaveBeenCalledTimes(2);
  });

  it("aborts stale detail work and prevents old selection overwrite", async () => {
    const first = deferred<AuditDetailDTO>();
    const second = deferred<AuditDetailDTO>();
    mockedDetail.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ selection }) => useAuditDetail("run_one", 10, selection, vi.fn()),
      { initialProps: { selection: roleSelection as AuditSelectionDTO | null } },
    );
    await waitFor(() => expect(mockedDetail).toHaveBeenCalledTimes(1));
    const firstSignal = mockedDetail.mock.calls[0]?.[3];
    rerender({ selection: toolSelection });
    expect(firstSignal?.aborted).toBe(true);
    await act(async () => {
      first.resolve(detail(10, roleSelection));
      second.resolve(detail(10, toolSelection));
    });
    await waitFor(() => expect(result.current.detail?.selection).toEqual(toolSelection));
  });

  it("turns audit_summary_stale into a summary refresh instead of visible detail", async () => {
    const refreshSummary = vi.fn();
    mockedDetail.mockRejectedValue(new ApiError({
      code: "audit_summary_stale",
      message: "stale",
      status: 409,
    }));
    const { result } = renderHook(() => useAuditDetail(
      "run_one",
      10,
      roleSelection,
      refreshSummary,
    ));
    await waitFor(() => expect(refreshSummary).toHaveBeenCalledTimes(1));
    expect(result.current.detail).toBeNull();
    expect(result.current.error).toBeNull();
  });
});

const observed = {value:0, completeness:"complete", basis:"test"} as const;
const publicProcess = (run: string, sequence = 24): ReaderProcessDTO => ({
  schema_version:1, run_id:run, source_sequence:sequence, profile:"evidence_v1", workflow_version:"evidence-production-v7",
  availability:"partial", reason_code:"publication_pending", question_origin:"default", primary_selection:"not_recorded",
  counts:{main_budget:observed, repair_budget:observed, sdk_main:observed, sdk_repair:observed, sdk_total:observed, data_capability:observed, data_http:observed}, roles:[], claim_origins:[], source_failures:[],
});

describe("research audit reads", () => {
  beforeEach(() => { vi.mocked(getReaderProcess).mockReset(); vi.mocked(getResearchRecord).mockReset(); });
  it("does no research reads in technical mode, preserves partial failures, and rejects a different sequence", async () => {
    vi.mocked(getReaderProcess).mockResolvedValue(publicProcess("run_one"));
    vi.mocked(getResearchRecord).mockRejectedValue(new Error("PRIVATE"));
    const {result, rerender} = renderHook(({enabled, sequence}) => useAuditResearch("run_one", sequence, enabled), {initialProps:{enabled:false, sequence:24}});
    expect(getReaderProcess).not.toHaveBeenCalled();
    rerender({enabled:true, sequence:24});
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.process?.run_id).toBe("run_one");
    expect(result.current.error).toBe(true);
    expect(result.current.record).toBeNull();
    rerender({enabled:true, sequence:25});
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.process).toBeNull();
  });
  it("ignores a late response after switching runs", async () => {
    const old = deferred<ReaderProcessDTO>();
    vi.mocked(getReaderProcess).mockReturnValueOnce(old.promise).mockResolvedValue(publicProcess("run_two"));
    vi.mocked(getResearchRecord).mockImplementation(async run => ({state:"unavailable",schema_version:1,run_id:run,reason_code:"not_published"}));
    const {result, rerender} = renderHook(({run}) => useAuditResearch(run, 24, true), {initialProps:{run:"run_one"}});
    rerender({run:"run_two"});
    await waitFor(() => expect(result.current.process?.run_id).toBe("run_two"));
    await act(async () => old.resolve(publicProcess("run_one")));
    expect(result.current.process?.run_id).toBe("run_two");
    expect(result.current.record?.run_id).toBe("run_two");
  });
});
