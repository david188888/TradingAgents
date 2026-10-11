import {act, renderHook, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {useConfig} from "./useConfig";
import {useChatGPT} from "./useChatGPT";
import {getConfig} from "../api/client";
import type {ConfigResponseDTO} from "../api/contracts";
vi.mock("../api/client", () => ({getConfig: vi.fn()}));
const a = "cg_" + "a".repeat(32), b = "cg_" + "b".repeat(32);
const account = (ref: string) => ({account_ref:ref, label:ref, signed_in:true, plan_enabled:true, usage_paused:false, revocation_unconfirmed:false});
let active = a;
let models = [{id:"future-z",label:"Future Z"},{id:"unknown-mini",label:"Unknown Mini"}];
let delayed: ((value: Response) => void) | null = null;
const response = (value: unknown) => new Response(JSON.stringify(value), {headers:{"content-type":"application/json"}});
beforeEach(() => {
 active = a; delayed = null; models = [{id:"future-z",label:"Future Z"},{id:"unknown-mini",label:"Unknown Mini"}];
 vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
  if (url.endsWith("/account")) active = JSON.parse(options!.body as string).account_ref;
  if (url.includes("/models")) return response({account_ref:active,models,fetched_at:Date.now()/1000});
  return response({accounts:[account(a),account(b)],active_account_ref:active,usage_url:"https://chatgpt.com/settings/usage"});
 }));
 vi.mocked(getConfig).mockResolvedValue({providers:[{id:"chatgpt",configured:false,requires_api_key:false,authentication:"oauth",custom_model_allowed:false,models:{quick:[],deep:[]}}],
 analysts:[],presets:[],depths:[1],output_languages:["Chinese"],checkpoint_available:false,wind:{enabled:false,configured:false,capabilities:[]}, configured_keys:{}, defaults:{llm_provider:"chatgpt",quick_think_llm:"",deep_think_llm:"",output_language:"Chinese",research_depth:1,checkpoint_enabled:false}, research_profiles:{evidence_v1:{supported:true,reason:null}}} satisfies ConfigResponseDTO);
});
afterEach(() => vi.unstubAllGlobals());
it("loads future model names in official order and freezes account into single and batch inputs", async () => {
 const {result} = renderHook(() => useConfig());
 await waitFor(() => expect(result.current.quick_think_llm).toBe("future-z"));
 act(() => {result.current.setTicker("600803"); result.current.setDeepThinkLlm("unknown-mini");});
 expect(result.current.quickOptions.map(m=>m.id)).toEqual(["future-z","unknown-mini"]);
 expect(result.current.buildRequest()).toMatchObject({chatgpt_account_ref:a,deep_think_llm:"unknown-mini"});
 expect(result.current.buildRequestForTicker("600519")).toMatchObject({chatgpt_account_ref:a});
 models = [{id:"future-z",label:"Future Z"}];
 await act(async () => result.current.chatgpt.refresh());
 expect(result.current.deep_think_llm).toBe("unknown-mini");
 expect(result.current.buildRequest()).toBeNull();
 expect(result.current.validationError).toContain("当前不可用");
});
it("ignores an old account model response after switching accounts", async () => {
 const {result} = renderHook(() => useChatGPT(true));
 await waitFor(() => expect(result.current.catalog?.account_ref).toBe(a));
 vi.mocked(fetch).mockImplementationOnce(() => new Promise<Response>(resolve => {delayed=resolve;}));
 let pending: Promise<void>;
 act(() => {pending=result.current.refresh();});
 await act(async () => result.current.select(b));
 await waitFor(() => expect(result.current.catalog?.account_ref).toBe(b));
 await act(async () => {delayed!(response({account_ref:a,models:[{id:"old",label:"Old"}],fetched_at:1})); await pending!;});
 expect(result.current.catalog?.account_ref).toBe(b);
 expect(result.current.catalog?.models[0].id).toBe("future-z");
});
it("does not fetch credentials or models while another provider is selected", () => {
 renderHook(() => useChatGPT(false));
 expect(fetch).not.toHaveBeenCalled();
});

it("does not treat an official slug named custom as the API-key placeholder", async () => {
 models = [{id:"custom",label:"Official Custom"}];
 const {result} = renderHook(() => useConfig());
 await waitFor(() => expect(result.current.quick_think_llm).toBe("custom"));
 act(() => result.current.setTicker("600803"));
 expect(result.current.buildRequest()).toMatchObject({quick_think_llm:"custom",deep_think_llm:"custom"});
});
