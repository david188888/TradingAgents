import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentKey, ReaderProcessDTO, ReaderRoleDTO } from "../../api/contracts";
import { AGENT_LABELS } from "../../domain/readerExplanation";
import { ResearchFlow } from "./ResearchFlow";
import { createInitialState } from "../../state/runReducer";

const count = {value:0,completeness:"complete",basis:"sdk_dispatch_authorization"} as const;
function role(key: AgentKey, status="completed", availability: ReaderRoleDTO["output_availability"]="pending_publication"): ReaderRoleDTO {
  return {role_key:key,actor_id:`native.${key}`,label:AGENT_LABELS[key],origin:key === "code_checks" || key === "evidence" ? "code":"model",
    purpose:"给定事实范围",status,output_availability:availability,reason_code:availability === "pending_publication" ? "publication_pending":null,
    output_count:null,output_sequence:null,main_budget:count,sdk_main:count,sdk_repair:count};
}
function process(version="evidence-production-v7"): ReaderProcessDTO {
  return {schema_version:1,run_id:"flow-run",source_sequence:202,profile:"evidence_v1",workflow_version:version,
    availability:"partial",reason_code:"publication_pending",question_origin:"default",primary_selection:"not_recorded",
    counts:{main_budget:count,repair_budget:count,sdk_main:count,sdk_repair:count,sdk_total:count,data_capability:count,data_http:count},
    roles:[role("evidence"),role("operating_quality"),role("event_context"),role("market_context"),role("challenge","not_reached","not_recorded"),
      role("code_checks","not_applicable","not_recorded"),role("response_operating_quality","skipped","not_applicable"),
      role("response_event_context","skipped","not_applicable"),role("response_market_context","skipped","not_applicable"),role("synthesis","not_reached","not_recorded")],
    claim_origins:[],source_failures:[]};
}
function Harness({value=process(),status="failed"}:{value?:ReaderProcessDTO;status?:string}) {
  const [selected,setSelected] = useState<AgentKey|null>(null);
  return <ResearchFlow process={value} runStatus={status} selectedRole={selected} onSelect={setSelected} onClose={()=>setSelected(null)}>
    <h3>{selected ? AGENT_LABELS[selected]:""}</h3>
  </ResearchFlow>;
}

describe("truthful dependency flow",()=>{
  beforeEach(()=>{HTMLElement.prototype.scrollIntoView=vi.fn();});
  it("keeps execution completion separate from unpublished output and does not invent a failed node",()=>{
    const {container}=render(<Harness/>);
    const operating=within(screen.getByRole("group",{name:"独立专项分工"})).getByRole("heading",{name:"经营研究"}).closest("article")!;
    expect(operating).toHaveTextContent("已完成");
    expect(operating).toHaveTextContent("提议已保存 · 本次未发布");
    expect(operating).not.toHaveTextContent("3 条假设");
    expect(screen.getAllByText("后续未执行")).toHaveLength(2);
    expect(container.querySelector('[data-status="failed"]')).toBeNull();
    expect(container.querySelector('[data-active="true"]')).toBeNull();
    expect(screen.queryByText(/等待发布/)).toBeNull();
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
    fireEvent.click(within(detail).getByRole("button",{name:"收起角色回顾"}));
    expect(button).toHaveFocus();expect(button).toHaveAttribute("aria-expanded","false");
  });
  it("uses two code positions with shared selection and only one displayed count",()=>{
    const value=process();value.roles.find(r=>r.role_key==="code_checks")!.output_count=7;
    render(<Harness value={value}/>);
    fireEvent.click(screen.getByRole("button",{name:"查看基础研究发布环节与保存产物"}));
    expect(screen.getByRole("button",{name:"查看代码条件核查环节与保存产物"})).toHaveAttribute("aria-expanded","true");
    expect(screen.getAllByText(/7 项/)).toHaveLength(1);
    expect(screen.getByRole("region",{name:"所选环节详情"})).toHaveTextContent("代码核查与发布");
  });
  it("renders V6 focus only after baseline publication and leaves conditional replies out",()=>{
    const value=process("evidence-production-v6");value.roles=value.roles.filter(r=>!r.role_key.startsWith("response_"));value.roles.push(role("focus_response"));
    const {container}=render(<Harness value={value} status="completed"/>);
    const groups=Array.from(container.querySelectorAll(".rf-group"));
    expect(groups.at(-1)).toHaveAttribute("data-group","focus");
    expect(screen.queryByRole("group",{name:"被质疑专项回应"})).toBeNull();
  });
  it("preserves explicitly requested focus while process data is loading",()=>{
    const state=createInitialState();state.meta.focus_requested=true;
    render(<ResearchFlow process={null} workflowVersion="evidence-production-v7" state={state} runStatus="running"
      selectedRole={null} onSelect={vi.fn()} onClose={vi.fn()}/>);
    expect(screen.getByRole("group",{name:"基础研究保存后的补充"})).toHaveTextContent("关注点回应");
    expect(screen.queryByText(/条事实/)).toBeNull();
  });
  it("uses a compatibility list for unknown versions rather than inventing V7 dependencies",()=>{
    render(<Harness value={process("future-workflow")}/>);
    expect(screen.getByRole("status")).toHaveTextContent("暂不绘制依赖图");
    expect(screen.getByRole("group",{name:"已记录环节"})).toBeVisible();
    expect(screen.queryByRole("group",{name:"独立专项分工"})).toBeNull();
  });
  it("activates only running nodes and incoming connectors; cancellation stops motion",()=>{
    const value=process();value.roles.find(r=>r.role_key==="market_context")!.status="running";
    const {container,rerender}=render(<Harness value={value} status="running"/>);
    expect(container.querySelectorAll('.rf-node[data-active="true"]')).toHaveLength(1);
    expect(container.querySelector('.rf-node[data-active="true"]')).toHaveAttribute("data-role","market_context");
    expect(container.querySelectorAll('.rf-connector[data-active="true"]')).toHaveLength(1);
    rerender(<Harness value={value} status="cancel_requested"/>);
    expect(container.querySelector('[data-active="true"]')).toBeNull();
  });
});
