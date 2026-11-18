import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentKey, ReaderProcessDTO, ReaderRoleDTO } from "../../api/contracts";
import { AGENT_LABELS } from "../../domain/readerExplanation";
import { ResearchFlow } from "./ResearchFlow";
import { createInitialState } from "../../state/runReducer";

const count = {value:0,completeness:"complete",basis:"sdk_dispatch_authorization"} as const;
function role(key: AgentKey, status="completed", availability: ReaderRoleDTO["output_availability"]="insight_stage_available"): ReaderRoleDTO {
  return {role_key:key,actor_id:`native.${key}`,label:AGENT_LABELS[key],origin:key === "code_checks" || key === "evidence" ? "code":"model",
    purpose:"给定事实范围",status,output_availability:availability,reason_code:null,
    output_count:null,output_sequence:null,main_budget:count,sdk_main:count,sdk_repair:count};
}
function process(version="evidence-production-v9"): ReaderProcessDTO {
  return {schema_version:1,run_id:"flow-run",source_sequence:202,profile:"evidence_v1",workflow_version:version,
    availability:"partial",reason_code:"publication_pending",question_origin:"default",primary_selection:"not_recorded",
    counts:{main_budget:count,repair_budget:count,sdk_main:count,sdk_repair:count,sdk_total:count,data_capability:count,data_http:count},
    roles:[role("evidence"),role("operating_quality"),role("event_context"),role("market_context"),role("challenge","not_reached","not_recorded"),
      role("code_checks","not_applicable","not_recorded"),role("response_operating_quality","skipped","not_applicable"),
      role("response_event_context","skipped","not_applicable"),role("response_market_context","skipped","not_applicable"),role("synthesis","not_reached","not_recorded")],
    source_failures:[]};
}
function Harness({value=process(),status="failed",variant="running"}:{value?:ReaderProcessDTO;status?:string;variant?:"running"|"summary"}) {
  const [selected,setSelected] = useState<AgentKey|null>(null);
  return <ResearchFlow process={value} runStatus={status} selectedRole={selected} onSelect={setSelected} onClose={()=>setSelected(null)} variant={variant}>
    <h3>{selected ? AGENT_LABELS[selected]:""}</h3>
  </ResearchFlow>;
}

describe("truthful dependency flow",()=>{
  beforeEach(()=>{HTMLElement.prototype.scrollIntoView=vi.fn();});
  it("shows qualified stage counts without presenting code checks as final publication",()=>{
    const value=process();
    for (const item of value.roles) if (item.role_key === "evidence" || item.role_key === "code_checks") {
      item.output_availability="insight_stage_available";item.reason_code=null;
    }
    value.roles[0].output_count=132;
    const {container}=render(<Harness value={value} status="running"/>);
    expect(screen.getByText(/132 项/)).toBeVisible();
    const publication=container.querySelector('[data-stage="publication"]')!;
    expect(publication).toHaveTextContent("等待发布");
    expect(publication).not.toHaveTextContent("已发布，可回顾");
  });
  it("keeps execution completion separate from unpublished output and does not invent a failed node",()=>{
    const {container}=render(<Harness/>);
    const operating=within(screen.getByRole("group",{name:"独立专项分工"})).getByRole("button",{name:"查看经营研究环节与保存产物"});
    expect(operating).toHaveAttribute("data-status","completed");
    expect(operating).toHaveTextContent("已完成");
    expect(screen.queryByText("3 条假设")).toBeNull();
    expect(container.querySelector('[data-stage="challenge"]')).toHaveAttribute("data-status","pending");
    expect(container.querySelector('[data-stage="synthesis"]')).toHaveAttribute("data-status","pending");
    expect(container.querySelector('[data-status="failed"]')).toBeNull();
    expect(container.querySelector('[data-active="true"]')).toBeNull();
    expect(screen.queryByText(/等待发布总体判断/)).toBeNull();
  });
  it("locates again on repeat click and closes to the original trigger",()=>{
    render(<Harness/>);
    const button=screen.getByRole("button",{name:"查看经营研究环节与保存产物"});
    fireEvent.click(button);
    const detail=screen.getByRole("region",{name:"所选环节详情"});
    expect(detail).toHaveFocus();
    expect(button).toHaveAttribute("aria-controls",detail.id);
    expect(button).toHaveAttribute("aria-expanded","true");
    button.focus();fireEvent.click(button);expect(detail).toHaveFocus();
    fireEvent.click(within(detail).getByRole("button",{name:"收起环节详情"}));
    expect(button).toHaveFocus();expect(button).toHaveAttribute("aria-expanded","false");
  });
  it("collapses the same stage rail into a completed-run summary",()=>{
    render(<Harness status="completed" variant="summary"/>);
    expect(screen.getByText(/研究过程 .* 个阶段已完成/)).toBeVisible();
    expect(screen.getByText("查看阶段与保存产物")).toBeVisible();
    expect(screen.queryByRole("heading",{name:"研究进度"})).toBeNull();
  });
  it("preserves explicitly requested focus while process data is loading",()=>{
    const state=createInitialState();state.meta.focus_requested=true;
    render(<ResearchFlow process={null} workflowVersion="evidence-production-v9" state={state} runStatus="running"
      selectedRole={null} onSelect={vi.fn()} onClose={vi.fn()}/>);
    expect(screen.getByRole("group",{name:"基础研究保存后的补充"})).toHaveTextContent("关注点回应");
    expect(screen.queryByText(/条事实/)).toBeNull();
  });
  it("uses a compatibility list for unknown versions rather than inventing dependencies",()=>{
    render(<Harness value={process("future-workflow")}/>);
    expect(screen.getByRole("status")).toHaveTextContent("暂不绘制依赖图");
    expect(screen.getByRole("group",{name:"已记录环节"})).toBeVisible();
    expect(screen.queryByRole("group",{name:"独立专项分工"})).toBeNull();
  });
  it("activates only the running specialist and stops motion on cancellation",()=>{
    const value=process();value.roles.find(role=>role.role_key==="market_context")!.status="running";
    const {container,rerender}=render(<Harness value={value} status="running"/>);
    expect(container.querySelectorAll('.rf-subroles [data-active="true"]')).toHaveLength(1);
    expect(container.querySelector('.rf-subroles [data-active="true"]')).toHaveAttribute("data-role","market_context");
    expect(container.querySelector('[data-stage="specialists"]')).toHaveAttribute("data-status","running");
    rerender(<Harness value={value} status="cancel_requested"/>);
    expect(container.querySelector('[data-active="true"]')).toBeNull();
  });
});
