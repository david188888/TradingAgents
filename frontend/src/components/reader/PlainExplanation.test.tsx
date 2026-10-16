import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReportExplanationDTO, ResearchRecordV1DTO } from "../../api/contracts";
import record from "../../test/fixtures/unified-research-v7.json";
import { CompanyBasics } from "./CompanyBasics";
import { ExplainedText, ExplanationContext, ExplanationStatus } from "./PlainExplanation";
import { ReaderEvidence } from "./ReaderEvidence";

const saved = record as ResearchRecordV1DTO;
const id = saved.claims[0].claim_id;
const data: ReportExplanationDTO = {
  schema_version: 1, run_id: saved.run_id, base_record_sha256: "a".repeat(64), state: "available", reason_code: null,
  eligible: true, model: "configured-model", generated_at: null, unavailable_targets: {},
  entries: { "assessment:judgement": { target: "assessment:judgement", explanation: "当前只能作有条件的判断。", uncertainty: "经营变化还需要后续资料确认。", references: [] } },
  indicators: { [`claim:${id}`]: { label: "归母净利润", value: "8 亿元", definition: "净利润中归属于母公司股东的部分。",
    interpretation: "", caution: "利润不等于现金流。", scope: "报告期 2025-12-31 · 合并口径", professional: saved.claims[0].statement, raw_value:"800000000", raw_unit:"CNY" } },
};

it("shows the same beginner explanation and exact professional source in report and rail", () => {
  const basics = { schema_version: "company-basics-v1" as const, company_name: "测试公司", introduction: [], fundamentals: [{label:"归母净利润",claim_id:id,report_period:"2025-12-31"}], quantitative: [], gaps: [] };
  render(<ExplanationContext.Provider value={data}>
    <CompanyBasics record={{...saved,company_basics:basics}} onInspect={vi.fn()}/>
    <aside aria-label="test rail"><ReaderEvidence record={saved} selected={{kind:"claim",id}} term={null} onTerm={vi.fn()}/></aside>
  </ExplanationContext.Provider>);
  const main = screen.getByRole("region",{name:"公司基础资料"});
  const rail = screen.getByRole("complementary",{name:"test rail"});
  for (const surface of [main,rail]) {
    expect(within(surface).getByText("8 亿元")).toBeVisible();
    expect(within(surface).getByText("利润不等于现金流。")).toBeVisible();
    expect(within(surface).getByText(saved.claims[0].statement)).not.toBeVisible();
    fireEvent.click(within(surface).getByText("专业表述与完整数值"));
    expect(within(surface).getByText(saved.claims[0].statement)).toBeVisible();
  }
});

it("keeps the professional narrative accessible beside its saved model explanation", () => {
  render(<ExplanationContext.Provider value={data}><ExplainedText target="assessment:judgement" text="专业判断：证据存在限制。"/></ExplanationContext.Provider>);
  expect(screen.getByText("当前只能作有条件的判断。")).toBeVisible();
  expect(screen.getByText("经营变化还需要后续资料确认。")).toBeVisible();
  fireEvent.click(screen.getByText("专业原文"));
  expect(screen.getByText("专业判断：证据存在限制。")).toBeVisible();
});

it("never offers generation for historical reports and retries only after explicit action", () => {
  const retry=vi.fn(), props={error:false,submitting:false,retry,reload:vi.fn()};
  const {rerender}=render(<ExplanationStatus {...props} value={{...data,state:"not_generated",eligible:false}}/>);
  expect(screen.queryByRole("button")).toBeNull();expect(retry).not.toHaveBeenCalled();
  rerender(<ExplanationStatus {...props} value={{...data,state:"failed"}}/>);
  expect(retry).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"生成或重试通俗解读"}));
  expect(retry).toHaveBeenCalledOnce();
});

it("keeps unavailable explanations explicit and preserves their original text", () => {
  render(<ExplanationContext.Provider value={{...data,entries:{},unavailable_targets:{unknown:"capacity_limited"}}}>
    <ExplainedText target="unknown" text="专业分析仍待进一步确认。"/>
  </ExplanationContext.Provider>);
  expect(screen.getByText("专业分析仍待进一步确认。")).toBeVisible();
  expect(screen.getByText("此段通俗解读暂缺，保留专业原文。")).toBeVisible();
});
