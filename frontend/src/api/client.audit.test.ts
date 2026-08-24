import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditDetailDTO, AuditSummaryDTO } from "./contracts";
import { getAuditDetail, getAuditSummary } from "./client";

const summary: AuditSummaryDTO = {
  schema_version: 1,
  run_id: "run_audit",
  source_sequence: 17,
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
    quick_think_llm: "gpt-4.1-mini",
    deep_think_llm: "gpt-4.1",
    data_quality: "healthy",
  },
  counts: {
    stages: 6,
    roles: 1,
    turns: 1,
    model_calls: 1,
    tool_calls: 1,
    artifacts: 1,
    prompts: 0,
    configs: 0,
    reports: 1,
  },
  sections: [
    { section_id: "overview", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "roles", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "capabilities", availability: "not_recorded", reason_code: "not_recorded", item_count: 0 },
    { section_id: "tools", availability: "ready", reason_code: null, item_count: 1 },
    { section_id: "artifacts", availability: "ready", reason_code: null, item_count: 1 },
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

const detail: AuditDetailDTO = {
  schema_version: 1,
  run_id: "run_audit",
  source_sequence: 17,
  selection: { kind: "role", id: "analyst.fundamentals /? 中文" },
  availability: "ready",
  reason_code: null,
  title: "Fundamentals Analyst",
  facts: [],
  related_selections: [],
  content: {
    mode: "none",
    media_type: null,
    byte_size: null,
    redaction_status: "clean",
    text: null,
    download_url: null,
  },
};

describe("Audit API client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("keeps summary and version-pinned detail on dedicated encoded routes", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(summary), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(detail), { status: 200 }));

    await expect(getAuditSummary("run_audit")).resolves.toEqual(summary);
    await expect(getAuditDetail(
      "run_audit",
      17,
      { kind: "role", id: "analyst.fundamentals /? 中文" },
    )).resolves.toEqual(detail);

    const summaryUrl = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    const detailUrl = new URL(String(fetchMock.mock.calls[1]?.[0]), "http://localhost");
    expect(summaryUrl.pathname).toBe("/api/runs/run_audit/audit");
    expect(detailUrl.pathname).toBe("/api/runs/run_audit/audit/detail");
    expect(detailUrl.searchParams.get("kind")).toBe("role");
    expect(detailUrl.searchParams.get("id")).toBe("analyst.fundamentals /? 中文");
    expect(detailUrl.searchParams.get("v")).toBe("17");
  });

  it("rejects unsafe run IDs and invalid source sequences before fetch", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(() => getAuditSummary("../other-run")).toThrow(RangeError);
    expect(() => getAuditDetail("run_audit", -1, { kind: "run", id: "run" })).toThrow(
      RangeError,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
