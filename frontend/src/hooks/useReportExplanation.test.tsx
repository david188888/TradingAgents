import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getReportExplanation, retryReportExplanation } from "../api/client";
import type { ReportExplanationDTO } from "../api/contracts";
import { useReportExplanation } from "./useReportExplanation";

vi.mock("../api/client",()=>({getReportExplanation:vi.fn(),retryReportExplanation:vi.fn()}));
const view=(run_id:string,state:ReportExplanationDTO["state"]="available"):ReportExplanationDTO=>({
  schema_version:1,run_id,state,base_record_sha256:null,reason_code:null,eligible:true,
  indicators:{},entries:{},unavailable_targets:{},model:"configured",generated_at:null,
});
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();vi.clearAllMocks();});

it("does not show a previous run's late explanation or POST during reading",async()=>{
  let resolveOld!:(value:ReportExplanationDTO)=>void;
  vi.mocked(getReportExplanation).mockImplementation(run=>run==="old" ? new Promise(resolve=>{resolveOld=resolve;}) : Promise.resolve(view(run)));
  const {result,rerender}=renderHook(({run})=>useReportExplanation(run),{initialProps:{run:"old"}});
  rerender({run:"new"});
  await waitFor(()=>expect(result.current.response?.run_id).toBe("new"));
  await act(async()=>resolveOld(view("old")));
  expect(result.current.response?.run_id).toBe("new");
  expect(retryReportExplanation).not.toHaveBeenCalled();
});

it("requires an explicit action to retry a failed explanation",async()=>{
  vi.mocked(getReportExplanation).mockResolvedValueOnce(view("run","failed")).mockResolvedValue(view("run"));
  vi.mocked(retryReportExplanation).mockResolvedValue(view("run","generating"));
  const {result}=renderHook(()=>useReportExplanation("run"));
  await waitFor(()=>expect(result.current.response?.state).toBe("failed"));
  expect(retryReportExplanation).not.toHaveBeenCalled();
  await act(async()=>{await result.current.retry();});
  await waitFor(()=>expect(result.current.response?.state).toBe("available"));
  expect(retryReportExplanation).toHaveBeenCalledOnce();
  expect(retryReportExplanation).toHaveBeenCalledWith("run");
});

it("pauses hidden reads and stops polling when the saved explanation arrives",async()=>{
  vi.useFakeTimers();
  const hidden=vi.spyOn(document,"hidden","get").mockReturnValue(true);
  vi.mocked(getReportExplanation).mockResolvedValueOnce(view("run","generating")).mockResolvedValue(view("run"));
  const {result}=renderHook(()=>useReportExplanation("run"));
  expect(getReportExplanation).not.toHaveBeenCalled();
  hidden.mockReturnValue(false);
  await act(async()=>{document.dispatchEvent(new Event("visibilitychange"));});
  expect(result.current.response?.state).toBe("generating");
  await act(async()=>{await vi.advanceTimersByTimeAsync(2000);});
  expect(result.current.response?.state).toBe("available");
  await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});
  expect(getReportExplanation).toHaveBeenCalledTimes(2);
  expect(retryReportExplanation).not.toHaveBeenCalled();
});
