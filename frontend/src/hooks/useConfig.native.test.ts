import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ConfigResponseDTO } from "../api/contracts";
import { getConfig } from "../api/client";
import { useConfig } from "./useConfig";
vi.mock("../api/client", () => ({ getConfig: vi.fn() }));
const mockedGetConfig = vi.mocked(getConfig);
function configResponse(): ConfigResponseDTO {
  return {
    providers: [
      {
        id: "openai",
        configured: true,
        requires_api_key: true,
        custom_model_allowed: true,
        models: {
          quick: [{ id: "gpt-4o-mini", label: "gpt-4o-mini" }],
          deep: [{ id: "gpt-4o", label: "gpt-4o" }],
        },
      },
    ],
    configured_keys: { openai: true },
    analysts: [
      { id: "fundamentals" },
      { id: "technical" },
      { id: "sentiment" },
      { id: "news" },
    ],
    presets: [],
    depths: [1, 3, 5],
    output_languages: ["zh", "en"],
    checkpoint_available: true,
    wind: { enabled: false, configured: false, capabilities: [] },
    research_profiles: { evidence_v1: { supported: true, reason: null } },
    defaults: {
      llm_provider: "openai",
      quick_think_llm: "gpt-4o-mini",
      deep_think_llm: "gpt-4o",
      output_language: "zh",
      research_depth: 3,
      checkpoint_enabled: false,
    },
  };
}


beforeEach(() => vi.clearAllMocks());
async function mount(config = configResponse()) {
  mockedGetConfig.mockResolvedValue(config);
  const hook = renderHook(() => useConfig());
  await waitFor(() => expect(hook.result.current.config).not.toBeNull());
  act(() => hook.result.current.setTicker("600803"));
  return hook;
}
it("creates native company research with normalized scheduling regardless of legacy config defaults", async () => {
  const { result } = await mount();
  expect(result.current.buildRequest()).toMatchObject({ ticker: "600803", mode: "company_research", research_profile: "evidence_v1", research_depth: 1, horizon: "medium", selected_analysts: ["market", "social", "news", "fundamentals"], checkpoint_enabled: false });
});
it("keeps catalyst question and mode without carrying holding fields", async () => {
  const { result } = await mount();
  act(() => { result.current.setMode("catalyst_research"); result.current.setResearchQuestion("  兑现条件？  "); result.current.setHoldingQuantity("100"); });
  const request = result.current.buildRequest();
  expect(request).toMatchObject({ mode: "catalyst_research", research_question: "兑现条件？" });
  expect(request).not.toHaveProperty("holding");
});
it("validates user holdings, while batch company requests ignore single holding state", async () => {
  const { result } = await mount();
  act(() => result.current.setMode("holding_review"));
  expect(result.current.buildRequest()).toBeNull();
  expect(result.current.buildRequestForTicker("600803")).toMatchObject({mode: "company_research", research_profile: "evidence_v1"});
  act(() => { result.current.setHoldingQuantity("100"); result.current.setHoldingAverageCost("20"); result.current.setHoldingOriginalThesis("收入改善"); });
  expect(result.current.buildRequest()?.holding).toMatchObject({ quantity: 100, average_cost: 20, original_thesis: "收入改善" });
  act(() => result.current.setHoldingOriginalThesis("😀".repeat(4000)));
  expect(result.current.buildRequest()).not.toBeNull();
  act(() => result.current.setHoldingOriginalThesis("😀".repeat(4001)));
  expect(result.current.buildRequest()).toBeNull();
});
it("enforces 400 Unicode code points for the question", async () => {
  const { result } = await mount();
  act(() => result.current.setResearchQuestion("😀".repeat(400)));
  expect(result.current.buildRequest()).not.toBeNull();
  act(() => result.current.setResearchQuestion("😀".repeat(401)));
  expect(result.current.buildRequest()).toBeNull();
});
it("refuses disabled native creation for both single and batch", async () => {
  const config = configResponse(); config.research_profiles = { evidence_v1: { supported: false, reason: "已关闭新建" } };
  const { result } = await mount(config);
  expect(result.current.validationError).toBe("已关闭新建");
  expect(result.current.buildRequest()).toBeNull();
  expect(result.current.buildRequestForTicker("600803")).toBeNull();
});

it("preserves a configured custom model and refuses placeholder IDs", async () => {
  const config = configResponse();
  config.defaults.quick_think_llm = "local-research-model";
  const {result} = await mount(config);
  expect(result.current.quick_model_selection).toBe("custom");
  expect(result.current.buildRequest()?.quick_think_llm).toBe("local-research-model");
  act(() => {result.current.setDeepThinkLlm("custom"); result.current.setDeepCustomModelId("");});
  expect(result.current.buildRequest()).toBeNull();
  act(() => result.current.setDeepCustomModelId("  local-synthesis-model  "));
  expect(result.current.buildRequestForTicker("600803")?.deep_think_llm).toBe("local-synthesis-model");
});

it("can configure a provider without preset models and clears custom IDs on a provider change", async () => {
  const config = configResponse();
  config.providers.push({id:"ollama", configured:true, requires_api_key:false, custom_model_allowed:true, models:{quick:[],deep:[]}});
  const {result} = await mount(config);
  act(() => result.current.setLlmProvider("ollama"));
  expect(result.current.quickOptions.map(m => m.id)).toEqual(["custom"]);
  expect(result.current.buildRequest()).toBeNull();
  act(() => {result.current.setQuickCustomModelId("local:research"); result.current.setDeepCustomModelId("local:research");});
  expect(result.current.buildRequest()?.llm_provider).toBe("ollama");
  act(() => result.current.setLlmProvider("openai"));
  expect(result.current.quick_custom_model_id).toBe("");
  expect(result.current.buildRequest()?.quick_think_llm).toBe("gpt-4o-mini");
});
