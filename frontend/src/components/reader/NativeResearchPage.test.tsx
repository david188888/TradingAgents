import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useReaderAgent, useReaderProcess } from "../../hooks/useReaderProcess";
import { NativeResearchPage } from "./NativeResearchPage";
import type { InsightReportDTO, ReaderAgentDTO, ResearchRecordResponseDTO } from "../../api/contracts";

vi.mock("../../hooks/useReaderProcess", () => ({ useReaderAgent: vi.fn(), useReaderProcess: vi.fn() }));
const retryProcess = vi.fn(), retryAgent = vi.fn();
const scrollIntoView = vi.fn();
const stageReport: InsightReportDTO = {
  schema_version:"insight-research-v1",construction:"native",run_id:"run-a",ticker:"600803",mode:"company_research",analysis_date:"2026-11-18",
  catalogs:{operating_quality:{snapshot_id:"snapshot-a",sources:[],evidence:[],numbers:[]}},insights:[{
    insight_id:"insight-running",role:"operating_quality",index:0,revision:1,snapshot_id:"snapshot-a",catalog_id:"operating_quality",status:"accepted",
    proposal:{claim:"运行中即可阅读已保存观点",reasoning:"保存后的结构化推理",limitations:"仍需后续核验",evidence_refs:[]},
    rendered:{claim:"运行中即可阅读已保存观点",reasoning:"保存后的结构化推理",limitations:"仍需后续核验"},fact_ids:[],source_ids:[],numeric_ids:[],issues:[]}],
  reviews:[],responses:[],synthesis:null,gaps:[],stages:{operating_quality:"completed"},focus_question:null,focus_insights:[],superseded_ids:[],search_requests:{},
};
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
    const entries = screen.getAllByRole("button", { name: /查看.*环节与保存产物/ });
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
      fireEvent.click(within(detail).getByRole("button", { name: "收起环节详情" }));
      expect(entry).toHaveFocus();
      expect(entry).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByRole("region", { name: "所选环节详情" })).toBeNull();
    }
  });

  it("shows process read failure inside the selected review and retries it", () => {
    vi.mocked(useReaderProcess).mockReturnValue({ response: null, error: true, retry: retryProcess });
    show();
    fireEvent.click(screen.getAllByRole("button", { name: /查看.*环节与保存产物/ })[0]);
    const detail = screen.getByRole("region", { name: "所选环节详情" });
    expect(within(detail).getByRole("status")).toHaveTextContent("产物暂时无法读取");
    fireEvent.click(within(detail).getByRole("button", { name: "重试读取" }));
    expect(retryProcess).toHaveBeenCalledOnce();
    expect(retryAgent).toHaveBeenCalledOnce();
  });

  it("does not claim a final report exists for a stopped unpublished run", () => {
    const output: ReaderAgentDTO={schema_version:1,run_id:"run-a",source_sequence:5,role_key:"operating_quality",availability:"insight_stage_available",
      reason_code:"publication_pending",origin:"model",input_description:"合格财务事实",insight_record:null};
    vi.mocked(useReaderAgent).mockReturnValue({response:output,error:false,retry:retryAgent});
    render(<NativeResearchPage runId="run-a" ticker="600418.SS" status="failed" state={null} loading={false} error={false}
      response={{state:"unavailable",schema_version:1,run_id:"run-a",reason_code:"not_published"}}
      onOpenAudit={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} onResume={vi.fn()} onNewResearch={vi.fn()}/>);
    expect(screen.getByText("本次未生成可读最终报告。")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:"查看经营研究环节与保存产物"}));
    const detail=screen.getByRole("region",{name:"所选环节详情"});
    expect(detail).toHaveTextContent("阶段观点已保存，尚未发布总体判断");
    expect(detail).not.toHaveTextContent("最终报告仍可");
    expect(detail).not.toHaveTextContent("等待发布");
  });

  it("distinguishes record loading and read failure from confirmed absence, and offers read retry", () => {
    const props={runId:"run-a",ticker:"600418.SS",status:"failed",state:null,response:null as ResearchRecordResponseDTO|null,
      onOpenAudit:vi.fn(),onCancel:vi.fn(),onRetry:vi.fn(),onResume:vi.fn(),onNewResearch:vi.fn(),retry:vi.fn()};
    const {rerender}=render(<NativeResearchPage {...props} loading error={false}/>);
    expect(screen.getByText(/正在核对保存记录/)).toBeVisible();
    expect(screen.queryByText("本次未生成可读最终报告。")).toBeNull();
    rerender(<NativeResearchPage {...props} loading={false} error/>);
    expect(screen.getByText(/尚不能确认报告是否已发布/)).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:"重试读取记录"}));expect(props.retry).toHaveBeenCalledOnce();
  });

  it("renders saved specialist Insights inline without presenting them as a final report", () => {
    vi.mocked(useReaderAgent).mockImplementation((_runId, role) => ({
      response: role === "operating_quality" ? {schema_version:1,run_id:"run-a",source_sequence:5,role_key:"operating_quality",availability:"insight_stage_available",
        reason_code:"publication_pending",origin:"model",input_description:"合格财务事实",insight_record:stageReport} : null,
      error:false,retry:retryAgent,
    }));
    show();
    const artifact = screen.getByRole("article",{name:"经营研究阶段产物"});
    expect(artifact).toHaveTextContent("运行中即可阅读已保存观点");
    expect(artifact).toHaveTextContent("仍需后续核验");
    expect(screen.queryByRole("article",{name:"Insight 研究报告"})).toBeNull();
  });
});
