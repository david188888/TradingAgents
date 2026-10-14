import {act, renderHook, waitFor} from "@testing-library/react";
import {createElement, StrictMode} from "react";
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

it("recovers a transient catalog failure on cold entry without reselecting configuration", async () => {
 let modelCalls = 0;
 vi.mocked(fetch).mockImplementation(async (url) => {
  if (String(url).includes("/models")) {
   modelCalls++;
   if (modelCalls === 1) return new Response(JSON.stringify({detail:{code:"request_failed",message:"Temporary failure"}}),{status:503});
   return response({account_ref:a,models,fetched_at:1});
  }
  return response({accounts:[account(a)],active_account_ref:a,usage_url:"https://chatgpt.com/settings/usage"});
 });
 const {result} = renderHook(() => useConfig());
 await waitFor(() => expect(result.current.quick_think_llm).toBe("future-z"));
 expect(modelCalls).toBe(2);
 expect(result.current.chatgpt.error).toBeNull();
 act(() => result.current.setTicker("600803"));
 expect(result.current.buildRequest()).not.toBeNull();
});

it("reselecting the current provider preserves explicit model choices", async () => {
 const {result} = renderHook(() => useConfig());
 await waitFor(() => expect(result.current.quick_think_llm).toBe("future-z"));
 act(() => {result.current.setDeepThinkLlm("unknown-mini"); result.current.setLlmProvider("chatgpt");});
 expect(result.current.deep_think_llm).toBe("unknown-mini");
});

it("reloads models after same-account reauthentication even when permission flags do not change", async () => {
 vi.spyOn(window, "open").mockReturnValue(null);
 let loginBody: unknown;
 vi.mocked(fetch).mockImplementation(async (url, options) => {
  const path = String(url);
  if (path.endsWith("/login")) {
   loginBody = JSON.parse(options!.body as string);
   models = [{id:"reauthorized-model",label:"Reauthorized"}];
   return response({attempt_id:"test-login",authorization_url:"https://auth.openai.com/api/accounts/authorize?state=fixture"});
  }
  if (path.endsWith("/login/test-login")) return response({status:"complete",account_ref:a});
  if (path.includes("/models")) return response({account_ref:a,models,fetched_at:1});
  return response({accounts:[account(a)],active_account_ref:a,usage_url:"https://chatgpt.com/settings/usage"});
 });
 const {result} = renderHook(() => useChatGPT(true));
 await waitFor(() => expect(result.current.catalog?.models[0].id).toBe("future-z"));
 act(() => result.current.login(true));
 await waitFor(() => expect(result.current.catalog?.models[0].id).toBe("reauthorized-model"));
 expect(loginBody).toEqual({account_ref:a});
 expect(result.current.busy).toBe(false);
 vi.restoreAllMocks();
});

it("reconciles invalid credentials and exposes sign-in without retrying a rejected catalog", async () => {
 let enabled = true, modelCalls = 0;
 vi.mocked(fetch).mockImplementation(async url => {
  if (String(url).includes("/models")) {
   enabled = false; modelCalls++;
   return new Response(JSON.stringify({detail:{code:"invalid_grant",message:"请重新登录。",diagnostic:{action:"sign_in"}}}),{status:400});
  }
  return response({accounts:[{...account(a),plan_enabled:enabled,signed_in:enabled}],active_account_ref:a,usage_url:"https://chatgpt.com/settings/usage"});
 });
 const {result} = renderHook(() => useChatGPT(true));
 await waitFor(() => expect(result.current.failure?.action).toBe("sign_in"));
 await waitFor(() => expect(result.current.busy).toBe(false));
 expect(result.current.account?.plan_enabled).toBe(false);
 expect(result.current.catalog).toBeNull();
 expect(modelCalls).toBe(1);
});

it("never retries quota or capability failures even if the upstream status is 503", async () => {
 let modelCalls = 0;
 vi.mocked(fetch).mockImplementation(async url => {
  if (String(url).includes("/models")) {
   modelCalls++;
   return new Response(JSON.stringify({detail:{code:"subscription_sharing_usage_limit_exceeded",message:"用量受限",diagnostic:{action:"manage_usage"}}}),{status:503});
  }
  return response({accounts:[account(a)],active_account_ref:a,usage_url:"https://chatgpt.com/settings/usage"});
 });
 const {result} = renderHook(() => useChatGPT(true));
 await waitFor(() => expect(result.current.failure?.action).toBe("manage_usage"));
 await waitFor(() => expect(result.current.busy).toBe(false));
 expect(modelCalls).toBe(1);
});

it("restarts a cancelled same-account catalog request and ignores its late response", async () => {
 const {result} = renderHook(() => useChatGPT(true));
 await waitFor(() => expect(result.current.catalog).not.toBeNull());
 const original = vi.mocked(fetch).getMockImplementation()!;
 let completeOld: (value:Response) => void = () => {};
 vi.mocked(fetch).mockImplementation((url, options) => String(url).includes("/models")
  ? new Promise(resolve => {completeOld=resolve;}) : original(url, options));
 let pending: Promise<void>;
 act(() => {pending=result.current.refresh();});
 await waitFor(() => expect(result.current.busy).toBe(true));
 // Allow the asynchronous status read to reach the delayed model request.
 await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("refresh=true"),expect.anything()));
 vi.mocked(fetch).mockImplementation(original);
 models = [{id:"latest",label:"Latest"}];
 await act(async () => result.current.select(a));
 expect(result.current.catalog?.models[0].id).toBe("latest");
 await act(async () => {completeOld(response({account_ref:a,models:[{id:"old",label:"Old"}],fetched_at:1})); await pending!;});
 expect(result.current.catalog?.models[0].id).toBe("latest");
 expect(result.current.busy).toBe(false);
});

it("clears busy and ignores pending reads when disabled, then loads on return", async () => {
 const {result,rerender} = renderHook(({enabled}) => useChatGPT(enabled),{initialProps:{enabled:true}});
 await waitFor(() => expect(result.current.catalog).not.toBeNull());
 let complete: (value:Response) => void = () => {};
 vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => {complete=resolve;}));
 let pending: Promise<void>;
 act(() => {pending=result.current.refresh();});
 rerender({enabled:false});
 expect(result.current.busy).toBe(false);
 expect(result.current.catalog).toBeNull();
 await act(async () => {complete(response({accounts:[account(a)],active_account_ref:a})); await pending!;});
 expect(result.current.catalog).toBeNull();
 rerender({enabled:true});
 await waitFor(() => expect(result.current.catalog?.models[0].id).toBe("future-z"));
});

it("loads a cold catalog through StrictMode effect replay", async () => {
 const {result} = renderHook(() => useConfig(), {
  wrapper: ({children}) => createElement(StrictMode, null, children),
 });
 await waitFor(() => expect(result.current.chatgpt.catalog?.models[0].id).toBe("future-z"));
 await waitFor(() => expect(result.current.chatgpt.busy).toBe(false));
 expect(result.current.chatgpt.error).toBeNull();
});

it("keeps a fallback login URL and cancels explicitly without accepting a late completion", async () => {
 vi.spyOn(window,"open").mockReturnValue(null);
 const original = vi.mocked(fetch).getMockImplementation()!;
 let finishPoll: (value:Response) => void = () => {};
 vi.mocked(fetch).mockImplementation((url,options) => {
  const path=String(url);
  if (path.endsWith("/login")) return Promise.resolve(response({attempt_id:"pending-login",authorization_url:"https://auth.openai.com/api/accounts/authorize?state=fixture"}));
  if (path.endsWith("/login/pending-login")) return new Promise(resolve => {finishPoll=resolve;});
  return original(url,options);
 });
 const {result} = renderHook(() => useChatGPT(true));
 await waitFor(() => expect(result.current.catalog).not.toBeNull());
 act(() => result.current.login(true));
 await waitFor(() => expect(result.current.loginUrl).toContain("https://auth.openai.com/"));
 await act(async () => result.current.cancelLogin());
 await act(async () => finishPoll(response({status:"complete",first_sign_in:true})));
 expect(result.current.attempt).toBeNull();
 expect(result.current.loginUrl).toBeNull();
 expect(result.current.welcome).toBe(false);
 expect(fetch).toHaveBeenCalledWith("/api/chatgpt/login/pending-login/cancel", expect.objectContaining({method:"POST"}));
 vi.restoreAllMocks();
});

it("preserves configured subscription model IDs while the account catalog loads", async () => {
 const config=await vi.mocked(getConfig)();
 config.defaults.quick_think_llm="unknown-mini";
 config.defaults.deep_think_llm="removed-model";
 vi.mocked(getConfig).mockResolvedValue(config);
 const {result} = renderHook(() => useConfig());
 await waitFor(() => expect(result.current.chatgpt.catalog).not.toBeNull());
 expect(result.current.quick_think_llm).toBe("unknown-mini");
 expect(result.current.deep_think_llm).toBe("removed-model");
 expect(result.current.configurationError).toContain("当前不可用");
});

it("retries a typed backend transport timeout even through the HTTP 422 envelope", async () => {
 let calls=0;
 vi.mocked(fetch).mockImplementation(async url => {
  if (String(url).includes("/models")) {
   if (++calls===1) return new Response(JSON.stringify({detail:{code:"request_failed",message:"连接超时",diagnostic:{action:"retry_later",upstream_code:"transport_timeout",upstream_status:null}}}),{status:422});
   return response({account_ref:a,models,fetched_at:1});
  }
  return response({accounts:[account(a)],active_account_ref:a,usage_url:"https://chatgpt.com/settings/usage"});
 });
 const {result}=renderHook(()=>useChatGPT(true));
 await waitFor(()=>expect(result.current.catalog).not.toBeNull());
 expect(calls).toBe(2);
});

it.each(["subscription_sharing_unsupported_capability","chatpass_v2_scope_not_authorized","subscription_sharing_usage_limit_exceeded"])("does not retry a typed business failure from an older server: %s",async code=>{
 let calls=0;
 vi.mocked(fetch).mockImplementation(async url=>{
  if(String(url).includes("/models")){calls++;return new Response(JSON.stringify({detail:{code,message:"Needs user action"}}),{status:503});}
  return response({accounts:[account(a)],active_account_ref:a,usage_url:"https://chatgpt.com/settings/usage"});
 });
 const {result}=renderHook(()=>useChatGPT(true));
 await waitFor(()=>expect(result.current.busy).toBe(false));
 expect(result.current.failure?.transient).toBe(false);
 expect(calls).toBe(1);
});
