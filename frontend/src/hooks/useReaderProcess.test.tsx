import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentKey, ReaderAgentDTO, ReaderProcessDTO } from "../api/contracts";
import { getReaderAgent, getReaderProcess } from "../api/client";
import { useReaderAgent, useReaderProcess } from "./useReaderProcess";
vi.mock("../api/client", () => ({getReaderAgent:vi.fn(),getReaderProcess:vi.fn()}));
const unknown = {value:null,completeness:"not_recorded",basis:"not_recorded"} as const;
function process(run="run-a", seq=10, availability="pending_publication" as "pending_publication" | "available"): ReaderProcessDTO {
 return {schema_version:1,run_id:run,source_sequence:seq,profile:"evidence_v1",workflow_version:"evidence-production-v5",availability:"partial",reason_code:null,question_origin:"user",primary_selection:"not_recorded",counts:{main_budget:unknown,repair_budget:unknown,sdk_main:unknown,sdk_repair:unknown,sdk_total:unknown,data_capability:unknown,data_http:unknown},claim_origins:[],source_failures:[],roles:[{role_key:"operating_quality",actor_id:"native.operating_quality",label:"经营研究",purpose:"核对经营",origin:"model",status:"completed",output_availability:availability,reason_code:null,output_count:null,output_sequence:availability==="available" ? 9:null,main_budget:unknown,sdk_main:unknown,sdk_repair:unknown}]};
}
function output(run:string, role:AgentKey, seq:number):ReaderAgentDTO {return {schema_version:1,run_id:run,source_sequence:seq,role_key:role,availability:"available",reason_code:null,origin:"model",input_description:"冻结事实",proposal:{hypotheses:[],unknowns:[]},relations:[],claim_ids:[],input_fact_ids:[],challenge_ids:[],code_sections:[]};}
function deferred<T>() {let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve};}

describe("bounded saved Reader reads",()=>{
 beforeEach(()=>{vi.clearAllMocks();Object.defineProperty(document,"hidden",{configurable:true,value:false});});
 afterEach(()=>{vi.useRealTimers();});
 it("rejects a slow response from the prior run",async()=>{
  const old=deferred<ReaderProcessDTO>();vi.mocked(getReaderProcess).mockReturnValueOnce(old.promise).mockResolvedValue(process("run-b"));
  const {result,rerender}=renderHook(({run})=>useReaderProcess(run,10,"completed","closed","done"),{initialProps:{run:"run-a"}});
  rerender({run:"run-b"});await waitFor(()=>expect(result.current.response?.run_id).toBe("run-b"));
  await act(async()=>old.resolve(process("run-a")));expect(result.current.response?.run_id).toBe("run-b");
 });
 it("coalesces checkpoint updates and stops after terminal catch-up",async()=>{
  vi.useFakeTimers();vi.mocked(getReaderProcess).mockResolvedValueOnce(process("run-a",1)).mockResolvedValueOnce(process("run-a",9));
  const {result,rerender}=renderHook(({seq,status})=>useReaderProcess("run-a",seq,status,"live","same"),{initialProps:{seq:1,status:"running"}});
  await act(async()=>{});rerender({seq:9,status:"running"});await act(async()=>{await vi.advanceTimersByTimeAsync(1500);});expect(getReaderProcess).toHaveBeenCalledTimes(1);
  await act(async()=>{await vi.advanceTimersByTimeAsync(500);});expect(result.current.response?.source_sequence).toBe(9);
  rerender({seq:9,status:"completed"});await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});expect(getReaderProcess).toHaveBeenCalledTimes(2);
 });
 it("bounds failures and offers manual retry",async()=>{
  vi.useFakeTimers();vi.mocked(getReaderProcess).mockRejectedValue(new Error("offline"));
  const {result}=renderHook(()=>useReaderProcess("run-a",10,"completed","closed","done"));
  await act(async()=>{await vi.advanceTimersByTimeAsync(30000);});expect(getReaderProcess).toHaveBeenCalledTimes(3);expect(result.current.error).toBe(true);
  vi.mocked(getReaderProcess).mockResolvedValue(process("run-a"));act(()=>result.current.retry());await act(async()=>{});expect(result.current.response?.run_id).toBe("run-a");
 });
 it("only refreshes the selected output when publication qualification changes",async()=>{
  vi.mocked(getReaderAgent).mockImplementation(async(run,role,seq)=>output(run,role,seq));
  const {result,rerender}=renderHook(({p})=>useReaderAgent("run-a","operating_quality",p),{initialProps:{p:process("run-a",1)}});
  await waitFor(()=>expect(getReaderAgent).toHaveBeenCalledTimes(1));rerender({p:process("run-a",5)});expect(getReaderAgent).toHaveBeenCalledTimes(1);
  rerender({p:process("run-a",10,"available")});await waitFor(()=>expect(result.current.response?.source_sequence).toBe(10));expect(getReaderAgent).toHaveBeenCalledTimes(2);
 });
 it("a stale role response cannot replace the active role",async()=>{
  const old=deferred<ReaderAgentDTO>();vi.mocked(getReaderAgent).mockReturnValueOnce(old.promise).mockResolvedValue(output("run-a","challenge",10));
  const {result,rerender}=renderHook(({role})=>useReaderAgent("run-a",role,process()),{initialProps:{role:"operating_quality" as AgentKey}});
  rerender({role:"challenge"});await waitFor(()=>expect(result.current.response?.role_key).toBe("challenge"));
  await act(async()=>old.resolve(output("run-a","operating_quality",10)));expect(result.current.response?.role_key).toBe("challenge");
 });
});
