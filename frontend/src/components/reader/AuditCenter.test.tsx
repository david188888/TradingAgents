import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditDetailDTO, AuditSummaryDTO, ReaderProcessDTO, ResearchRecordV1DTO } from "../../api/contracts";
import { useAuditDetail, useAuditResearch, useAuditSummary } from "../../hooks/useAudit";
import { AuditCenter } from "./AuditCenter";

vi.mock("../../hooks/useAudit", () => ({
  useAuditSummary: vi.fn(),
  useAuditDetail: vi.fn(),
  useAuditResearch: vi.fn(),
}));

const mockedSummary = vi.mocked(useAuditSummary);
const mockedDetail = vi.mocked(useAuditDetail);
const mockedResearch = vi.mocked(useAuditResearch);
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
    mockedResearch.mockReturnValue({ process: null, record: {state:"unavailable", schema_version:1, run_id:summary.run_id, reason_code:"not_published"}, loading:false, error:false, retry });
  });

  it("opens research checks first and keeps technical sections behind an explicit entry", async () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    const { rerender } = render(
      <AuditCenter runId={summary.run_id} open={false} context={null} returnFocus={trigger} onClose={vi.fn()} />,
    );
    expect(screen.queryByRole("dialog", { name: "审计中心" })).toBeNull();
    expect(mockedSummary).toHaveBeenLastCalledWith(summary.run_id, false);

    rerender(
      <AuditCenter runId={summary.run_id} open context={{section:"overview"}} returnFocus={trigger} onClose={vi.fn()} />,
    );
    expect(await screen.findByRole("dialog", { name: "审计中心" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Prompt 与配置/ })).toBeNull();
    expect(screen.getByText("已保存报告，当前研究正文未能核验")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /技术排查/ }));
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
    const role = screen.getByRole("button", { name: /基本面分析师/ });
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
    const role = screen.getByRole("button", { name: /基本面分析师/ });
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

  it("keeps native authorization lower bounds and missing counts distinct from zero", () => {
    const complete = (value: number) => ({ value, completeness: "complete" as const, basis: "budget_dispatch_authorization" });
    const missing = { value: null, completeness: "not_recorded" as const, basis: "sdk_dispatch_authorization" };
    const lower = { value: 5, completeness: "known_lower_bound" as const, basis: "sdk_dispatch_authorization" };
    mockedSummary.mockReturnValue({ summary: { ...summary, counts: { ...summary.counts, turns: null, model_calls: 5, native_counts: {
      main_budget: complete(5), repair_budget: complete(0), sdk_main: lower, sdk_repair: missing, sdk_total: lower,
      data_capability: complete(17), data_http: complete(35),
    }}}, loading: false, refreshing: false, error: null, refresh });
    render(<AuditCenter runId={summary.run_id} open context={null} returnFocus={null} onClose={vi.fn()} />);
    expect(screen.queryByText(/预算授权/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /技术排查/ }));
    expect(screen.getByText(/结构化修复预算授权：0/)).toBeInTheDocument();
    expect(screen.getByText(/SDK 主发出授权：至少 5.*修复：未记录/)).toBeInTheDocument();
    expect(screen.getByText(/SDK 合计：至少 5/)).toBeInTheDocument();
    expect(screen.getByText("未记录")).toBeInTheDocument();
  });

  it("explains unpublished failed roles without presenting technical counts or waiting for publication", () => {
    const count = {value:0,completeness:"complete",basis:"test"} as const;
    const process: ReaderProcessDTO = {schema_version:1,run_id:summary.run_id,source_sequence:24,profile:"evidence_v1",workflow_version:"evidence-production-v7",availability:"partial",reason_code:"publication_pending",question_origin:"default",primary_selection:"not_recorded",counts:{main_budget:count,repair_budget:count,sdk_main:count,sdk_repair:count,sdk_total:count,data_capability:count,data_http:count},claim_origins:[],source_failures:[],roles:[
      {role_key:"operating_quality",actor_id:"native.operating_quality",label:"经营研究",origin:"model",purpose:"经营研究",status:"failed",output_availability:"not_recorded",reason_code:"publication_pending",output_count:null,output_sequence:null,main_budget:count,sdk_main:count,sdk_repair:count},
      {role_key:"event_context",actor_id:"native.event_context",label:"事件研究",origin:"model",purpose:"事件研究",status:"completed",output_availability:"pending_publication",reason_code:"publication_pending",output_count:null,output_sequence:null,main_budget:count,sdk_main:count,sdk_repair:count},
    ],model_failures:[{stage:"operating_quality",category:"schema_validation",upstream_status:null,upstream_code:null,request_id:null,safe_message:"研究输出未通过格式与字段校验。",action:"retry_later"}]};
    mockedSummary.mockReturnValue({summary:{...summary,run:{...summary.run,status:"failed"},counts:{...summary.counts,reports:0,artifacts:205}},loading:false,refreshing:false,error:null,refresh});
    mockedResearch.mockReturnValue({process,record:{state:"unavailable",schema_version:1,run_id:summary.run_id,reason_code:"not_published"},loading:false,error:false,retry});
    render(<AuditCenter runId={summary.run_id} open context={{section:"overview"}} returnFocus={null} onClose={vi.fn()} />);
    expect(screen.getByText("本次未发布研究报告")).toBeInTheDocument();
    expect(screen.getByText("研究输出未通过格式与字段校验。")).toBeInTheDocument();
    expect(screen.getByText("提议已保存 · 本次未发布")).toBeInTheDocument();
    expect(screen.queryByText(/SDK|预算授权|等待发布|205/)).toBeNull();
  });

  it("keeps a published partial report's limitations visible", () => {
    const record: ResearchRecordV1DTO = {schema_version:"research-record-v1",run_id:summary.run_id,ticker:"000338.SZ",mode:"company_research",analysis_date:"2026-08-11",construction:"native",source_case_contract:null,source_case_sha256:null,snapshots:[],evidence:[],claims:[{claim_id:"unknown-1",kind:"unknown",statement:"应收账款回款仍待核查。",evidence_ids:[],supporting_fact_ids:[],limitations:[]}],hypotheses:[],challenges:[],verifications:[],metrics:[],limitations:["经营研究缺少合格输出。"],assessment:{schema_version:"research-assessment-v1",input_snapshot_id:"test",research_question:"test",judgement:"test",dimensions:[],key_claim_ids:[],primary_challenge_id:null,next_check:"test",challenge_assessments:[],completeness:"partial",quality:"LOW_CONFIDENCE",forward_window_calendar_days:null,limitations:[]}};
    mockedResearch.mockReturnValue({process:null,record:{state:"ready",schema_version:1,run_id:summary.run_id,record},loading:false,error:false,retry});
    render(<AuditCenter runId={summary.run_id} open context={null} returnFocus={null} onClose={vi.fn()} />);
    expect(screen.getByText("已发布研究报告")).toBeInTheDocument();
    expect(screen.getByText(/报告存在证据或研究环节限制/)).toBeInTheDocument();
    expect(screen.getByText("经营研究缺少合格输出。")).toBeInTheDocument();
    expect(screen.getByText("应收账款回款仍待核查。")).toBeInTheDocument();
  });

  it("does not turn an unreadable record into a missing publication", () => {
    mockedSummary.mockReturnValue({summary:{...summary,counts:{...summary.counts,reports:0}},loading:false,refreshing:false,error:null,refresh});
    mockedResearch.mockReturnValue({process:null,record:{state:"unavailable",schema_version:1,run_id:summary.run_id,reason_code:"corrupt"},loading:false,error:false,retry});
    render(<AuditCenter runId={summary.run_id} open context={null} returnFocus={null} onClose={vi.fn()} />);
    expect(screen.getByText("研究记录未通过读取核验")).toBeInTheDocument();
    expect(screen.queryByText("本次未发布研究报告")).toBeNull();
  });
});
