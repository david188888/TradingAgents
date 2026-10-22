import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ResearchAssessmentV3DTO, ResearchRecordV1DTO } from "../../api/contracts";
import saved from "../../test/fixtures/unified-research-v7.json";
import { InvestmentJudgement, ResearchDialogue } from "./InvestmentJudgement";
import { NativeReader } from "./NativeReader";

vi.mock("../../hooks/useReaderProcess",()=>({useReaderAgent:()=>({response:null,error:false,retry:vi.fn()}),useReaderFocus:()=>({response:null,error:false,retry:vi.fn()})}));
const original = saved as ResearchRecordV1DTO;
const base = original.assessment as ResearchAssessmentV3DTO;
const sectionIds = [...base.dimensions.map(d=>`dimension:${d.dimension}`), ...original.challenges.map(c=>`adjudication:${c.challenge_id}`), 'overall', 'conditions'];

function partial(): ResearchRecordV1DTO {
  const unavailable = new Set(['overall', ...original.challenges.map(c=>`adjudication:${c.challenge_id}`)]);
  return {...original, assessment:{...base, investment_stance:null, report_status:'analysis_unrated',
    judgement:'综合未完成；已保留通过校验的分段，暂未形成总体评级。',
    supporting_arguments:[], opposing_arguments:[], completeness:'partial', quality:'LOW_CONFIDENCE',
    adjudications:base.adjudications.map(a=>({...a,rationale:'本条综合裁决未完成；保留原挑战、代码核查与专项回应。'})),
    synthesis_sections:{policy:'synthesis-sections-v1',sections:sectionIds.map(id=>({section_id:id,
      status:unavailable.has(id)?'unavailable':'accepted',phase:unavailable.has(id)?null:'main',
      reason_code:unavailable.has(id)?'missing_section':null}))}}};
}

it('lists incomplete sections while retaining validated dimensions and replies',()=>{
  const record=partial();
  render(<><InvestmentJudgement record={record} onInspect={vi.fn()}/><ResearchDialogue record={record} onInspect={vi.fn()}/></>);
  expect(screen.getByRole('heading',{name:'已有分析 · 暂未形成总体评级'})).toBeVisible();
  expect(screen.getByRole('complementary',{name:'未完成的综合分段'})).toHaveTextContent('总体判断 · 未完成');
  expect(screen.getByRole('heading',{name:'综合裁决 · 未完成'})).toBeVisible();
  expect(screen.getByText(base.dimensions[0].judgement)).toBeVisible();
  expect(screen.getByText(original.dialogue!.responses[0].rationale)).toBeVisible();
});

it('labels the Reader as unfinished synthesis without attributing host text to the model',()=>{
  vi.stubGlobal('scrollTo',vi.fn());
  const record=partial();
  render(<NativeReader runId={record.run_id} record={record} process={null} processError={false} retryProcess={vi.fn()}/>);
  expect(screen.getByRole('heading',{name:'公司报告 · 暂未形成总体评级'})).toBeVisible();
  expect(screen.getByText(/报告已交付 · 综合未完成/)).toBeVisible();
  expect(screen.queryByText(/报告已交付 · 综合分析已形成/)).toBeNull();
  expect(screen.queryByRole('button',{name:'来自研究综合 · 回顾产物 →'})).toBeNull();
});
