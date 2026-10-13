import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ResearchRecordV1DTO } from "../../api/contracts";
import saved from "../../test/fixtures/unified-research-v7.json";
import { CompanyBasics } from "./CompanyBasics";
import { InvestmentJudgement, ResearchDialogue } from "./InvestmentJudgement";
import { NativeReader } from "./NativeReader";

vi.mock("../../hooks/useReaderProcess",()=>({useReaderAgent:()=>({response:null,error:false,retry:vi.fn()}),useReaderFocus:()=>({response:null,error:false,retry:vi.fn()})}));
const old=saved as ResearchRecordV1DTO;
const record:ResearchRecordV1DTO={...old,company_basics:{schema_version:'company-basics-v1',company_name:'离线测试公司',introduction:[],fundamentals:[{label:'归母净利润',claim_id:old.claims[0].claim_id,report_period:'2025-12-31'}],quantitative:[],gaps:['主营业务明确字段未取得。']},assessment:old.assessment?.schema_version==='research-assessment-v3' ? {...old.assessment,investment_stance:null,report_status:'specialist_summary',judgement:'基础报告与专项汇总已交付；综合阶段未完成。'} : old.assessment};

it('keeps basic data and local gaps inspectable despite absent introduction',()=>{
 const inspect=vi.fn();render(<CompanyBasics record={record} onInspect={inspect}/>);
 expect(screen.getByRole('heading',{name:'公司基础资料 · 离线测试公司'})).toBeVisible();
 expect(screen.getByText('2025-12-31 报告期 · 归母净利润 8 亿元（合并口径）')).toBeVisible();
 const button=screen.getByRole('button',{name:'核对保存来源 →'});fireEvent.click(button);
 expect(inspect).toHaveBeenCalledWith({kind:'claim',id:old.claims[0].claim_id},button);
 fireEvent.click(screen.getByText('基础资料的具体缺口'));
 expect(screen.getByText('主营业务明确字段未取得。')).toBeVisible();
});

it('shows no invented rating or model adjudication when synthesis is absent',()=>{
 render(<><InvestmentJudgement record={record} onInspect={vi.fn()}/><ResearchDialogue record={record} onInspect={vi.fn()}/></>);
 expect(screen.getByRole('heading',{name:'已有分析 · 暂未形成总体评级'})).toBeVisible();
 expect(screen.queryByRole('heading',{name:/投资吸引力 · 中性|投资吸引力 · 证据不足/})).toBeNull();
 expect(screen.getByRole('heading',{name:'保留的专项回应状态 · 撤回'})).toBeVisible();
 expect(screen.queryByRole('heading',{name:/综合裁决/})).toBeNull();
});

it('delivers the Reader with basics and an explicit unfinished synthesis state',()=>{
 vi.stubGlobal('scrollTo',vi.fn());
 render(<NativeReader runId={record.run_id} record={record} process={null} processError={false} retryProcess={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'公司报告 · 暂未形成总体评级'})).toBeVisible();
 expect(screen.getByRole('region',{name:'公司基础资料'})).toBeVisible();
 expect(screen.getByText(/报告已交付 · 综合阶段未完成/)).toBeVisible();
 expect(screen.queryByRole('button',{name:'来自研究综合 · 回顾产物 →'})).toBeNull();
});
