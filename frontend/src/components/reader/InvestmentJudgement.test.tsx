import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ResearchRecordV1DTO } from "../../api/contracts";
import saved from "../../test/fixtures/unified-research-v7.json";
import { rolesForProfile } from "../../state/model";
import { InvestmentJudgement, ResearchDialogue } from "./InvestmentJudgement";
const record=saved as ResearchRecordV1DTO;
it("shows saved reasons and original falsifiers with an evidence inspection action",()=>{
 const inspect=vi.fn();render(<InvestmentJudgement record={record} onInspect={inspect}/>);
 expect(screen.getByRole("heading",{name:"哪些条件会改变判断"})).toBeVisible();
 expect(screen.getByRole("heading",{name:/事件影响与兑现/})).toBeVisible();
 const buttons=screen.getAllByRole("button");fireEvent.click(buttons[0]);
 expect(inspect).toHaveBeenCalledWith({kind:"claim",id:record.assessment?.schema_version === "research-assessment-v3" ? record.assessment.opposing_arguments[0].claim_ids[0] : ""},buttons[0]);
});
it("keeps a withdrawn original traceable, distinguishes the reply from actual checks and shows its adjudication",()=>{
 render(<ResearchDialogue record={record} onInspect={vi.fn()}/>);
 expect(screen.getByRole("heading",{name:"专项回应 · 撤回"})).toBeVisible();
 expect(screen.getByRole("heading",{name:"综合裁决 · 撤回"})).toBeVisible();
 expect(screen.getByText(/已退出结论的有效支撑/)).toBeVisible();
 expect(screen.getByRole("heading",{name:"实际代码核查"})).toBeVisible();
});
it("adds reply roles only to V7, before synthesis, without changing the historical registry",()=>{
 const old=rolesForProfile("evidence_v1","evidence-production-v6");
 expect(old.some(r=>r.node_id.startsWith("response_"))).toBe(false);
 const next=rolesForProfile("evidence_v1","evidence-production-v7").map(r=>r.node_id);
 expect(next.slice(-4)).toEqual(["response_operating_quality","response_event_context","response_market_context","synthesis"]);
});
