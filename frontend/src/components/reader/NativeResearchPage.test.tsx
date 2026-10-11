import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useReaderAgent, useReaderProcess } from "../../hooks/useReaderProcess";
import { NativeResearchPage } from "./NativeResearchPage";
import type { ReaderAgentDTO, ResearchRecordResponseDTO } from "../../api/contracts";

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
      fireEvent.click(within(detail).getByRole("button", { name: "收起角色回顾" }));
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
    const output: ReaderAgentDTO={schema_version:1,run_id:"run-a",source_sequence:5,role_key:"operating_quality",availability:"pending_publication",
      reason_code:"publication_pending",origin:"model",input_description:"合格财务事实",proposal:null,relations:[],claim_ids:[],input_fact_ids:[],challenge_ids:[],code_sections:[]};
    vi.mocked(useReaderAgent).mockReturnValue({response:output,error:false,retry:retryAgent});
    render(<NativeResearchPage runId="run-a" ticker="600418.SS" status="failed" state={null} loading={false} error={false}
      response={{state:"unavailable",schema_version:1,run_id:"run-a",reason_code:"not_published"}}
      onOpenAudit={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} onResume={vi.fn()} onNewResearch={vi.fn()}/>);
    expect(screen.getByText("本次未生成可读最终报告。")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:"查看经营研究环节与保存产物"}));
    const detail=screen.getByRole("region",{name:"所选环节详情"});
    expect(detail).toHaveTextContent("提议已保存 · 本次未发布");
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
});
