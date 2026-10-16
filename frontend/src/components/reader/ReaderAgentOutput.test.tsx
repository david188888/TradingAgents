import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../../test/fixtures/unified-research-v7.json";
import type { AgentKey, ReaderAgentDTO, ResearchRecordV1DTO } from "../../api/contracts";
import { ReaderAgentOutput } from "./ReaderAgentOutput";
import { claimText } from "./ResearchRecordSection";

const saved = fixture as ResearchRecordV1DTO;
const record: ResearchRecordV1DTO = { ...saved, assessment: null, dialogue: null };
const facts = record.claims.filter(c => c.kind === "fact");
function output(role: AgentKey = "evidence"): ReaderAgentDTO {
  return {schema_version:1,run_id:record.run_id,source_sequence:144,role_key:role,availability:"stage_available",
    reason_code:"stage_qualified",origin:role === "evidence" ? "code":"model",input_description:"通用输入范围说明",
    stage_record:record,proposal:role === "evidence" ? null : {hypotheses:[{statement:"阶段经营假设",
      supporting_fact_ids:[facts[0].claim_id],conditions:[{condition_role:"invalidation",text:"后续经营发生变化",check:null}],alternative_explanation:"可能存在其他原因"}],unknowns:["仍待核查"]},
    claim_ids:role === "evidence" ? facts.map(f=>f.claim_id):["stage-hypothesis"],input_fact_ids:[facts[0].claim_id],
    relations:[],challenge_ids:[],code_sections:role === "evidence" ? ["facts","sources","checks"]:[]};
}
function show(value: ReaderAgentDTO, role: AgentKey = value.role_key) {
  return render(<ReaderAgentOutput role={role} process={null} output={value} error={false} record={null} runStatus="running"
    entity={null} onRole={vi.fn()} onInspect={vi.fn()} onLocate={vi.fn()} onRetry={vi.fn()}/>);
}

describe("independently readable saved stage outputs",()=>{
  beforeEach(()=>{HTMLElement.prototype.scrollIntoView=vi.fn();});
  it("shows actual frozen facts and sources before publication and keeps general instructions folded",()=>{
    show(output());
    expect(screen.getByRole("heading",{name:"已冻结的证据与检查"})).toBeVisible();
    expect(screen.getByText(claimText(facts[0].statement),{selector:"summary"})).toBeVisible();
    expect(screen.getByText("通用输入范围说明")).not.toBeVisible();
    expect(screen.queryByText(/当前没有可展示/)).toBeNull();
    expect(screen.queryByText(/记录完整性/)).toBeNull();
    fireEvent.click(screen.getByText(claimText(facts[0].statement),{selector:"summary"}));
    const source=record.evidence.find(s=>facts[0].evidence_ids.includes(s.evidence_id))!;
    expect(screen.getAllByText(source.source_name).some(el=>el.closest("details")?.open)).toBe(true);
    fireEvent.change(screen.getByRole("searchbox",{name:"查找事实或来源"}),{target:{value:"没有这个关键词"}});
    expect(screen.getByText("没有匹配的保存事实。")).toBeVisible();
  });
  it("labels a proposal as provisional and makes its fact link work without a final record",()=>{
    show(output("operating_quality"));
    expect(screen.getByRole("status")).toHaveTextContent("尚非最终研究结论");
    expect(screen.getByRole("heading",{name:"阶段经营假设"})).toBeVisible();
    expect(screen.queryByText(/未进入记录|未列为首页重点|最终报告仍可/)).toBeNull();
    const link=screen.getByRole("button",{name:`${claimText(facts[0].statement)} →`});
    fireEvent.click(link);
    const pane=screen.getByRole("region",{name:"阶段依据详情"});
    expect(pane).toHaveFocus();
    expect(within(pane).getByText(claimText(facts[0].statement),{selector:"p"})).toBeVisible();
    fireEvent.click(within(pane).getByRole("button",{name:"收起依据"}));
    expect(link).toHaveFocus();
  });
  it("separates a saved-output validation failure from an empty final report",()=>{
    show({...output(),availability:"unavailable",reason_code:"stage_binding_unavailable",stage_record:null});
    expect(screen.getByRole("status")).toHaveTextContent("未通过本环节校验");
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByText(/没有可展示的合格产物正文/)).toBeNull();
  });
});
