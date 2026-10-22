import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ResearchRecordV1DTO } from "../../api/contracts";
import saved from "../../test/fixtures/unified-research-v7.json";
import { ChallengeCheckSummary } from "./ChallengeChecks";
import { selectionContent } from "./ReaderEvidence";

function record(): ResearchRecordV1DTO {
  const base = structuredClone(saved) as ResearchRecordV1DTO;
  const challenge = base.challenges[0];
  return { ...base, challenge_check_policy: "hypothesis-directed-checks-v1", challenges: [{ ...challenge,
    test: {verifiability: "computable_now", supporting_fact_ids: [], required_inputs: [], required_operation: "value",
      reason_code: null, observation_date: null, check: null} }],
    challenge_outcomes: [{challenge_id:challenge.challenge_id, state:"completed", reason:null,
      task_id:"t.synthetic",plan_sha256:"a".repeat(64),inputs:[]}],
    verifications: [{verification_id:"v.synthetic",challenge_id:challenge.challenge_id,input_snapshot_id:base.snapshots[0].snapshot_id,
      output_snapshot_id:"v1.synthetic",method:"calculation",status:"supports",evidence_ids:[],executed_at:"2026-10-21T00:00:00Z",
      result:"只回答指定命题",scope:"challenge_predicate_only",condition_text:"保存的费用是否增加",predicate_met:true,
      value:"1.2500",result_reason:"predicate_evaluated"}] };
}

describe("challenge check delivery", () => {
  it("shows exact proposition outcome without upgrading it to economic proof", () => {
    const value = record();
    render(<ChallengeCheckSummary record={value} challengeId={value.challenges[0].challenge_id}/>);
    expect(screen.getByText("核查分类：当前可计算")).toBeVisible();
    expect(screen.getByText("任务去向：已实际执行")).toBeVisible();
    expect(screen.getByText("独立核查命题：保存的费用是否增加")).toBeVisible();
    expect(screen.getByText(/命题结果：满足/)).toBeVisible();
    expect(screen.getByText(/1.2500/)).toBeVisible();
    expect(screen.getByText(/不证明整条经济假设，也不自动消除风险/)).toBeVisible();
    expect(screen.queryByText("风险已消除")).not.toBeInTheDocument();
  });

  it.each(["budget_refused", "cancelled", "unknown"] as const)("does not fabricate an execution for %s", (state) => {
    const value = record(); value.verifications = []; value.challenge_outcomes![0].state = state;
    render(<ChallengeCheckSummary record={value} challengeId={value.challenges[0].challenge_id}/>);
    expect(screen.queryByText(/命题结果：满足/)).not.toBeInTheDocument();
    expect(screen.queryByText("任务去向：已实际执行")).not.toBeInTheDocument();
    expect(screen.getByText(/任务去向：/)).toBeVisible();
  });

  it("keeps missing information distinct from code-confirmed absence", () => {
    const value = record(); value.verifications = [];
    value.challenges[0].test = {verifiability:"needs_source",check:null,supporting_fact_ids:[],required_operation:"value",
      reason_code:null,observation_date:null,required_inputs:[{kind:"source",description:"管理层费用说明"}]};
    value.challenge_outcomes = [{challenge_id:value.challenges[0].challenge_id,state:"not_generated",reason:"needs_source",
      task_id:null,plan_sha256:null,inputs:[{input_index:0,availability:"availability_unknown",reason:"model_proposed_requirement",evidence_ids:[]}]}];
    render(<ChallengeCheckSummary record={value} challengeId={value.challenges[0].challenge_id}/>);
    expect(screen.getByText(/模型提出的资料需求，代码未确认可用性/)).toBeVisible();
    expect(screen.getByText("任务去向：未生成任务")).toBeVisible();
  });

  it("shows historical classification as unknown", () => {
    const value = structuredClone(saved) as ResearchRecordV1DTO;
    render(<ChallengeCheckSummary record={value} challengeId={value.challenges[0].challenge_id}/>);
    expect(screen.getByText("核查分类：未知（历史记录未保存）")).toBeVisible();
    expect(screen.queryByText("任务去向：未生成任务")).not.toBeInTheDocument();
  });

  it("related evidence includes challenge-only facts without changing the target inference", () => {
    const value = record(); const original = value.claims.filter(c => c.kind === "inference").map(c => structuredClone(c));
    const extra = {claim_id:"f.challenge-only",kind:"fact" as const,statement:"新增费用观察",evidence_ids:[value.evidence[0].evidence_id],supporting_fact_ids:[],limitations:[]};
    value.claims.push(extra); value.challenges[0].test!.supporting_fact_ids = [extra.claim_id];
    const related = selectionContent(value,{kind:"challenge",id:value.challenges[0].challenge_id});
    expect(related.facts).toContainEqual(extra);
    expect(value.claims.filter(c => c.kind === "inference")).toEqual(original);
  });
});
