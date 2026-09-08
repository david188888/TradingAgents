import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BatchControls } from "./BatchControls";
import type { ConfigResponseDTO } from "../../api/contracts";
import type { UseConfigResult } from "../../hooks/useConfig";

// --- Mocks (hoisted so vi.mock factories can reference them) -------------

const mockClient = vi.hoisted(() => ({
  listBatches: vi.fn(),
  validateBatch: vi.fn(),
  createBatch: vi.fn(),
  getBatch: vi.fn(),
  cancelBatch: vi.fn(),
  deleteBatch: vi.fn(),
  setSchedulerConcurrency: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  ...mockClient,
  ApiError: class ApiError extends Error {
    code: string;
    status: number;
    fields: string[];
    constructor(params: { code: string; message: string; status: number }) {
      super(params.message);
      this.name = "ApiError";
      this.code = params.code;
      this.status = params.status;
      this.fields = [];
    }
  },
}));

vi.mock("../../hooks/useCompletionNotifications", () => ({
  notifyBatch: vi.fn(),
  requestCompletionNotificationPermission: vi.fn(),
}));

// --- Fixtures ------------------------------------------------------------

function makeConfig(): ConfigResponseDTO {
  return {
    providers: [
      {
        id: "deepseek",
        configured: true,
        requires_api_key: true,
        models: {
          quick: [{ label: "DeepSeek Chat", id: "deepseek-chat" }],
          deep: [{ label: "DeepSeek Reasoner", id: "deepseek-reasoner" }],
        },
        custom_model_allowed: false,
      },
      {
        id: "openai",
        configured: false,
        requires_api_key: true,
        models: {
          quick: [{ label: "GPT-4o", id: "gpt-4o" }],
          deep: [{ label: "GPT-4o", id: "gpt-4o" }],
        },
        custom_model_allowed: false,
      },
    ],
    configured_keys: { deepseek: true, openai: false },
    analysts: [
      { id: "market" },
      { id: "social" },
      { id: "news" },
      { id: "fundamentals" },
    ],
    presets: [],
    depths: [1, 3, 5],
    output_languages: ["English", "Chinese"],
    checkpoint_available: false,
    defaults: {
      llm_provider: "deepseek",
      quick_think_llm: "deepseek-chat",
      deep_think_llm: "deepseek-reasoner",
      output_language: "Chinese",
      research_depth: 1,
      checkpoint_enabled: false,
    },
    wind: { enabled: false, configured: false, capabilities: [] },
  };
}

function makeCfg(overrides: Partial<UseConfigResult> = {}): UseConfigResult {
  const config = makeConfig();
  return {
    loading: false,
    error: null,
    config,
    ticker: "",
    setTicker: vi.fn(),
    analysis_date: "2026-09-08",
    setAnalysisDate: vi.fn(),
    selected_analysts: ["market", "news"],
    setSelectedAnalysts: vi.fn(),
    toggleAnalyst: vi.fn(),
    selected_preset: null,
    setAnalystPreset: vi.fn(),
    research_depth: 1,
    setResearchDepth: vi.fn(),
    llm_provider: "deepseek",
    setLlmProvider: vi.fn(),
    quick_think_llm: "deepseek-chat",
    setQuickThinkLlm: vi.fn(),
    deep_think_llm: "deepseek-reasoner",
    setDeepThinkLlm: vi.fn(),
    output_language: "Chinese",
    setOutputLanguage: vi.fn(),
    checkpoint_enabled: false,
    setCheckpointEnabled: vi.fn(),
    mode: "company_research",
    setMode: vi.fn(),
    horizon: "medium",
    setHorizon: vi.fn(),
    holding_quantity: "",
    setHoldingQuantity: vi.fn(),
    holding_average_cost: "",
    setHoldingAverageCost: vi.fn(),
    holding_cash: "",
    setHoldingCash: vi.fn(),
    holding_total_account_value: "",
    setHoldingTotalAccountValue: vi.fn(),
    holding_currency: "",
    setHoldingCurrency: vi.fn(),
    holding_facts_as_of: "",
    setHoldingFactsAsOf: vi.fn(),
    holding_original_thesis: "",
    setHoldingOriginalThesis: vi.fn(),
    selectedProvider: config.providers[0],
    quickOptions: config.providers[0].models.quick,
    deepOptions: config.providers[0].models.deep,
    configured_keys: config.configured_keys,
    validationError: null,
    buildRequest: vi.fn(() => null),
    buildRequestForTicker: vi.fn(() => null),
    ...overrides,
  } as unknown as UseConfigResult;
}

// --- Tests ---------------------------------------------------------------

describe("BatchControls shared model selection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listBatches.mockResolvedValue([]);
  });

  it("renders LLM Provider and quick/deep model selects wired to shared cfg", () => {
    const cfg = makeCfg();
    render(<BatchControls cfg={cfg} onSelectRun={vi.fn()} />);

    const provider = screen.getByLabelText("LLM Provider") as HTMLSelectElement;
    const quick = screen.getByLabelText("快速思考模型") as HTMLSelectElement;
    const deep = screen.getByLabelText("深度思考模型") as HTMLSelectElement;

    expect(provider).toHaveValue("deepseek");
    expect(quick).toHaveValue("deepseek-chat");
    expect(deep).toHaveValue("deepseek-reasoner");

    // Provider options carry the configured flag, same as single-company mode.
    const providerOptions = Array.from(provider.options).map((o) => o.textContent);
    expect(providerOptions).toEqual(["deepseek · 已配置", "openai · 未配置"]);

    // Key status mirrors the selected provider's configured state.
    expect(screen.getByText("已配置")).toBeInTheDocument();
  });

  it("propagates provider/model changes to the shared cfg setters", () => {
    const cfg = makeCfg();
    render(<BatchControls cfg={cfg} onSelectRun={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("快速思考模型"), {
      target: { value: "deepseek-chat" },
    });
    expect(cfg.setQuickThinkLlm).toHaveBeenCalledWith("deepseek-chat");

    fireEvent.change(screen.getByLabelText("深度思考模型"), {
      target: { value: "deepseek-reasoner" },
    });
    expect(cfg.setDeepThinkLlm).toHaveBeenCalledWith("deepseek-reasoner");

    fireEvent.change(screen.getByLabelText("LLM Provider"), {
      target: { value: "openai" },
    });
    expect(cfg.setLlmProvider).toHaveBeenCalledWith("openai");
  });

  it("flags an unconfigured provider in the key status block", () => {
    const cfg = makeCfg({
      llm_provider: "openai",
      selectedProvider: makeConfig().providers[1],
      quickOptions: [{ label: "GPT-4o", id: "gpt-4o" }],
      deepOptions: [{ label: "GPT-4o", id: "gpt-4o" }],
      quick_think_llm: "gpt-4o",
      deep_think_llm: "gpt-4o",
    });
    render(<BatchControls cfg={cfg} onSelectRun={vi.fn()} />);

    expect(screen.getByText("未配置")).toBeInTheDocument();
  });
});
