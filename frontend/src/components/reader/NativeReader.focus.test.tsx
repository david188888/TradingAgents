import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import savedRecord from "../../../../shared_fixtures/research-record.json";
import type { ReaderFocusDTO, ReaderProcessDTO, ResearchRecordV1DTO } from "../../api/contracts";
import { useReaderFocus } from "../../hooks/useReaderProcess";
import { NativeReader } from "./NativeReader";

vi.mock("../../hooks/useReaderProcess",()=>({useReaderAgent:()=>({response:null,error:false,retry:vi.fn()}),useReaderFocus:vi.fn()}));
const raw = savedRecord.record;
const record: ResearchRecordV1DTO = {...raw, assessment:{schema_version:"research-assessment-v1", input_snapshot_id:raw.snapshots[0].snapshot_id,
 research_question:"独立研究范围",judgement:"经营质量与风险需综合判断",dimensions:[],key_claim_ids:[],primary_challenge_id:null,
 next_check:"补充经营兑现",challenge_assessments:[],completeness:"partial",quality:"LOW_CONFIDENCE",forward_window_calendar_days:null,limitations:[]}} as ResearchRecordV1DTO;
const unknown = {value:null,completeness:"not_recorded",basis:"not_recorded"} as const;
const base: ReaderProcessDTO = {schema_version:1,run_id:record.run_id,source_sequence:10,profile:"evidence_v1",workflow_version:"evidence-production-v6",availability:"ready",reason_code:null,question_origin:"default",primary_selection:"not_recorded",counts:{main_budget:unknown,repair_budget:unknown,sdk_main:unknown,sdk_repair:unknown,sdk_total:unknown,data_capability:unknown,data_http:unknown},roles:[],claim_origins:[],source_failures:[]};
const process: ReaderProcessDTO = {...base,roles:[{role_key:"focus_response",actor_id:"native.focus_response",label:"关注点回应",origin:"model",purpose:"补充回应",status:"completed",output_availability:"available",reason_code:null,output_count:1,output_sequence:9,main_budget:unknown,sdk_main:unknown,sdk_repair:unknown}]};
const response: ReaderFocusDTO = {schema_version:1,run_id:record.run_id,source_sequence:10,workflow_version:"evidence-production-v6",state:"ready",focus:"AI 业务关系",reason_code:null,response:{schema_version:"research-focus-response-v1",run_id:record.run_id,ticker:record.ticker,mode:record.mode,analysis_date:record.analysis_date,input_snapshot_id:raw.snapshots[0].snapshot_id,base_record_sha256:"a".repeat(64),focus:"AI 业务关系",status:"available",reason_code:null,proposal:{answer:"现有保存证据只能部分回应",answerability:"partial",claim_ids:[record.claims[0].claim_id],evidence_ids:[],limitations:["缺少细分业务披露"],suggested_next_check:null}}};
function show(p=process){return render(<NativeReader runId={record.run_id} record={record} process={p} processError={false} retryProcess={vi.fn()}/>);}

describe("independent baseline precedes optional supplement",()=>{
 beforeEach(()=>{vi.stubGlobal("scrollTo",vi.fn());vi.mocked(useReaderFocus).mockReturnValue({response,error:false,retry:vi.fn()});});
 it("keeps supplement last, identifies citations and leaves baseline judgement visible",()=>{
  const {container}=show();
  expect(screen.getByRole("heading",{name:"综合判断"})).toBeVisible();
  expect(screen.getByText(record.assessment!.judgement)).toBeVisible();
  expect(Array.from(container.querySelectorAll(".qr-report-section")).at(-1)).toHaveAttribute("id","qr-focus");
  fireEvent.click(screen.getByRole("button",{name:"引用事实或推断 1 →"}));
  expect(screen.getByRole("complementary",{name:"相关依据"})).toHaveTextContent(record.claims[0].statement.split(":")[0]);
 });
 it("shows typed optional failure while retaining baseline judgement",()=>{
  vi.mocked(useReaderFocus).mockReturnValue({response:{...response,response:null,state:"unavailable",reason_code:"publication_failed"},error:false,retry:vi.fn()});show();
  expect(screen.getByText(/补充回应未能发布/)).toBeVisible();expect(screen.getByText(record.assessment!.judgement)).toBeVisible();
 });
 it("has no supplement or role when no focus was requested",()=>{show(base);expect(screen.queryByRole("region",{name:"补充关注点回应"})).toBeNull();fireEvent.click(screen.getByRole("button",{name:"Agent 产物"}));expect(screen.queryByRole("button",{name:"关注点回应"})).toBeNull();});
 it("preserves legacy question semantics and six roles",()=>{
  show({...base,workflow_version:"evidence-production-v5",question_origin:"user"});expect(screen.getByText("你的研究问题")).toBeVisible();expect(screen.getByRole("heading",{name:"当前回答"})).toBeVisible();expect(screen.getByText(/历史运行：研究问题参与/)).toBeVisible();expect(screen.queryByRole("region",{name:"补充关注点回应"})).toBeNull();
 });
});
