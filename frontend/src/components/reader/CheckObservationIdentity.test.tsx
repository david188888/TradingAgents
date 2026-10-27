import { render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReportExplanationDTO, ResearchRecordV1DTO } from "../../api/contracts";
import saved from "../../test/fixtures/unified-research-v7.json";
import { NativeReader } from "./NativeReader";

const indicator = (label: string, value: string) => ({label, value, definition:"核对具体问题。", interpretation:"", caution:"", scope:"", professional:value, raw_value:null, raw_unit:null});
const data: ReportExplanationDTO = {schema_version:1, run_id:saved.run_id, base_record_sha256:"a".repeat(64), state:"not_generated", reason_code:null, eligible:false, model:null, generated_at:null, unavailable_targets:{}, entries:{}, indicators:{
  "check:operating_disclosures:observation:0":indicator("总销量", "20,467 百万立方米"),
  "check:operating_disclosures:observation:1":indicator("接卸量", "56.48 万吨"),
  "check:operating_disclosures:operating_measure_current":indicator("旧的歧义项", "56.48 万吨"),
}};
vi.mock("../../hooks/useReportExplanation", () => ({useReportExplanation:()=>({response:data,error:false,submitting:false,retry:vi.fn(),reload:vi.fn()})}));
vi.mock("../../hooks/useReaderProcess", () => ({useReaderAgent:()=>({response:null,error:false,retry:vi.fn()}),useReaderFocus:()=>({response:null,error:false,retry:vi.fn()})}));

it("shows each saved operating observation rather than a colliding legacy indicator", () => {
  vi.stubGlobal("scrollTo",vi.fn());
  const old = saved as ResearchRecordV1DTO;
  const check = old.evidence_checks!.checks[0];
  const record: ResearchRecordV1DTO = {...old, evidence_checks:{...old.evidence_checks!, checks:[{...check, check_id:"operating_disclosures", question:"运营核对", observations:[
    {key:"operating_measure_current",label:"总销量",value:"20467",unit:"百万立方米",method:"原表",evidence_ids:[]},
    {key:"operating_measure_current",label:"接卸量",value:"56.48",unit:"万吨",method:"原表",evidence_ids:[]},
  ]}]}};
  render(<NativeReader runId={record.run_id} record={record} process={null} processError={false} retryProcess={vi.fn()}/>);
  const section = screen.getByText("运营核对").closest("article")!;
  expect(within(section).getByText("20,467 百万立方米", {selector:".qr-readable-value"})).toBeVisible();
  expect(within(section).getByText("56.48 万吨", {selector:".qr-readable-value"})).toBeVisible();
});
