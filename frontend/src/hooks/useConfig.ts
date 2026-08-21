/**
 * F3 - Hook owning workbench config fetch + analyst input selection state.
 *
 * Owns every piece of selection state that feeds RunCreateRequestDTO and
 * guarantees the quick_think_llm / deep_think_llm pair is always valid for the
 * currently selected provider. When the provider changes, the hook auto-resets
 * quick/deep to that provider's first option (or leaves them in place when the
 * provider exposes no model options, in which case the derived validationError
 * flags the situation).
 *
 * The Controls component is a pure renderer of this hook's state.
 */
import { useEffect, useState } from "react";
import type {
  ConfigResponseDTO,
  HoldingInputDTO,
  ModelOptionDTO,
  ProviderDTO,
  ResearchDepth,
  ResearchHorizon,
  ResearchMode,
  RunCreateRequestDTO,
} from "../api/contracts";
import { getConfig } from "../api/client";

export interface UseConfigResult {
  loading: boolean;
  error: Error | null;
  config: ConfigResponseDTO | null;

  ticker: string;
  setTicker: (v: string) => void;
  analysis_date: string;
  setAnalysisDate: (v: string) => void;
  selected_analysts: string[];
  setSelectedAnalysts: (v: string[]) => void;
  toggleAnalyst: (id: string) => void;
  selected_preset: string | null;
  setAnalystPreset: (id: string) => void;
  research_depth: ResearchDepth;
  setResearchDepth: (v: ResearchDepth) => void;
  llm_provider: string;
  setLlmProvider: (v: string) => void;
  quick_think_llm: string;
  setQuickThinkLlm: (v: string) => void;
  deep_think_llm: string;
  setDeepThinkLlm: (v: string) => void;
  output_language: string;
  setOutputLanguage: (v: string) => void;
  checkpoint_enabled: boolean;
  setCheckpointEnabled: (v: boolean) => void;
  mode: ResearchMode;
  setMode: (v: ResearchMode) => void;
  horizon: ResearchHorizon;
  setHorizon: (v: ResearchHorizon) => void;
  holding_quantity: string;
  setHoldingQuantity: (v: string) => void;
  holding_average_cost: string;
  setHoldingAverageCost: (v: string) => void;
  holding_cash: string;
  setHoldingCash: (v: string) => void;
  holding_total_account_value: string;
  setHoldingTotalAccountValue: (v: string) => void;
  holding_currency: string;
  setHoldingCurrency: (v: string) => void;
  holding_facts_as_of: string;
  setHoldingFactsAsOf: (v: string) => void;
  holding_original_thesis: string;
  setHoldingOriginalThesis: (v: string) => void;

  selectedProvider: ProviderDTO | null;
  quickOptions: ModelOptionDTO[];
  deepOptions: ModelOptionDTO[];
  configured_keys: Record<string, boolean>;

  buildRequest: () => RunCreateRequestDTO | null;
  buildRequestForTicker: (ticker: string) => RunCreateRequestDTO | null;
  validationError: string | null;
}

const DEPTHS: ReadonlyArray<ResearchDepth> = [1, 3, 5];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function isResearchDepth(v: number): v is ResearchDepth {
  return (DEPTHS as ReadonlyArray<number>).includes(v);
}

export function useConfig(): UseConfigResult {
  const [config, setConfig] = useState<ConfigResponseDTO | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const [ticker, setTicker] = useState<string>("");
  const [analysisDate, setAnalysisDate] = useState<string>(todayIso);
  const [selectedAnalysts, setSelectedAnalystsState] = useState<string[]>([]);
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [researchDepth, setResearchDepth] = useState<ResearchDepth>(1);
  const [llmProvider, setLlmProviderState] = useState<string>("");
  const [quickThinkLlm, setQuickThinkLlm] = useState<string>("");
  const [deepThinkLlm, setDeepThinkLlm] = useState<string>("");
  const [outputLanguage, setOutputLanguage] = useState<string>("Chinese");
  const [checkpointEnabled, setCheckpointEnabled] = useState<boolean>(false);
  const [mode, setMode] = useState<ResearchMode>("company_research");
  const [horizon, setHorizon] = useState<ResearchHorizon>("medium");
  const [holdingQuantity, setHoldingQuantity] = useState<string>("");
  const [holdingAverageCost, setHoldingAverageCost] = useState<string>("");
  const [holdingCash, setHoldingCash] = useState<string>("");
  const [holdingTotalAccountValue, setHoldingTotalAccountValue] = useState<string>("");
  const [holdingCurrency, setHoldingCurrency] = useState<string>("");
  const [holdingFactsAsOf, setHoldingFactsAsOf] = useState<string>("");
  const [holdingOriginalThesis, setHoldingOriginalThesis] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    getConfig()
      .then((c: ConfigResponseDTO) => {
        if (cancelled) return;
        setConfig(c);
        setError(null);
        // Seed selection state from config.defaults.
        const providerId =
          c.defaults.llm_provider ?? c.providers[0]?.id ?? "";
        const provider =
          c.providers.find((p) => p.id === providerId) ?? null;
        setLlmProviderState(providerId);
        setQuickThinkLlm(
          c.defaults.quick_think_llm ?? provider?.models.quick[0]?.id ?? "",
        );
        setDeepThinkLlm(
          c.defaults.deep_think_llm ?? provider?.models.deep[0]?.id ?? "",
        );
        setOutputLanguage(c.defaults.output_language);
        setResearchDepth(
          isResearchDepth(c.defaults.research_depth)
            ? c.defaults.research_depth
            : 1,
        );
        setCheckpointEnabled(c.defaults.checkpoint_enabled);
        const defaultPreset =
          c.presets.find((preset) => preset.id === "full-research") ??
          c.presets[0];
        setSelectedPreset(defaultPreset?.id ?? null);
        setSelectedAnalystsState(
          defaultPreset?.analysts ?? c.analysts.map((analyst) => analyst.id),
        );
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function setLlmProvider(v: string): void {
    setLlmProviderState(v);
    const provider = config?.providers.find((p) => p.id === v) ?? null;
    if (provider === null) return;
    const firstQuick = provider.models.quick[0]?.id;
    const firstDeep = provider.models.deep[0]?.id;
    if (firstQuick !== undefined) setQuickThinkLlm(firstQuick);
    if (firstDeep !== undefined) setDeepThinkLlm(firstDeep);
    // When the new provider exposes no model options (custom-only) the stale
    // strings are left in place; the derived validationError below flags it.
  }

  function toggleAnalyst(id: string): void {
    setSelectedPreset(null);
    setSelectedAnalystsState((prev) =>
      prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id],
    );
  }

  function setSelectedAnalysts(value: string[]): void {
    setSelectedPreset(null);
    setSelectedAnalystsState(value);
  }

  function setAnalystPreset(id: string): void {
    const preset = config?.presets.find((candidate) => candidate.id === id);
    if (preset === undefined) return;
    setSelectedPreset(preset.id);
    setSelectedAnalystsState([...preset.analysts]);
  }

  const selectedProvider: ProviderDTO | null =
    config?.providers.find((p) => p.id === llmProvider) ?? null;
  const quickOptions: ModelOptionDTO[] = selectedProvider?.models.quick ?? [];
  const deepOptions: ModelOptionDTO[] = selectedProvider?.models.deep ?? [];
  const configured_keys: Record<string, boolean> =
    config?.configured_keys ?? {};

  // Derived validation: always reflects exactly why buildRequest would return
  // null. Computed each render (cheap) so it never diverges from buildRequest.
  let validationError: string | null = null;
  if (config !== null) {
    const trimmedTicker = ticker.trim();
    if (!trimmedTicker) {
      validationError = "请输入股票代码";
    } else if (selectedAnalysts.length === 0) {
      validationError = "至少选择一个分析师";
    } else {
      const provider = config.providers.find((p) => p.id === llmProvider);
      if (provider === undefined) {
        validationError = "请选择 LLM Provider";
      } else if (
        config.configured_keys[llmProvider] !== true &&
        provider.requires_api_key
      ) {
        validationError = "所选 Provider 未配置 API Key";
      } else if (quickOptions.length === 0) {
        validationError = "所选 Provider 未提供快速思考模型选项";
      } else if (deepOptions.length === 0) {
        validationError = "所选 Provider 未提供深度思考模型选项";
      } else if (!quickThinkLlm) {
        validationError = "请选择快速思考模型";
      } else if (!deepThinkLlm) {
        validationError = "请选择深度思考模型";
      } else if (mode === "holding_review") {
        const quantity = Number(holdingQuantity);
        const averageCost = Number(holdingAverageCost);
        if (!Number.isFinite(quantity) || quantity <= 0) {
          validationError = "持仓数量必须是大于 0 的数字";
        } else if (!Number.isFinite(averageCost) || averageCost <= 0) {
          validationError = "平均成本必须是大于 0 的数字";
        } else if (holdingCash !== "" && (!Number.isFinite(Number(holdingCash)) || Number(holdingCash) < 0)) {
          validationError = "现金必须是非负数字";
        } else if (
          holdingTotalAccountValue !== "" &&
          (!Number.isFinite(Number(holdingTotalAccountValue)) || Number(holdingTotalAccountValue) <= 0)
        ) {
          validationError = "账户总资产必须是大于 0 的数字";
        } else if (holdingCurrency !== "" && !/^[A-Za-z]{3}$/.test(holdingCurrency)) {
          validationError = "币种请使用三个英文字母，例如 CNY";
        } else if (holdingFactsAsOf !== "" && holdingFactsAsOf !== analysisDate) {
          validationError = "持仓事实日期必须与分析日期一致";
        }
      }
    }
  }

  function buildRequestForTicker(value: string): RunCreateRequestDTO | null {
    if (config === null || (validationError !== null && validationError !== "请输入股票代码")) return null;
    const normalizedTicker = value.trim();
    if (!normalizedTicker) return null;
    return {
      ticker: normalizedTicker,
      analysis_date: analysisDate,
      selected_analysts: [...selectedAnalysts],
      research_depth: researchDepth,
      mode: "company_research",
      horizon,
      llm_provider: llmProvider,
      quick_think_llm: quickThinkLlm,
      deep_think_llm: deepThinkLlm,
      output_language: outputLanguage,
      checkpoint_enabled: checkpointEnabled,
      asset_type: null,
    };
  }

  function buildRequest(): RunCreateRequestDTO | null {
    if (config === null || validationError !== null) return null;
    const orderedAnalysts = [...selectedAnalysts];
    const normalizedTicker = ticker.trim();
    const holding: HoldingInputDTO | undefined =
      mode === "holding_review"
        ? {
            ticker: normalizedTicker,
            quantity: Number(holdingQuantity),
            average_cost: Number(holdingAverageCost),
            ...(holdingCash !== "" ? { cash: Number(holdingCash) } : {}),
            ...(holdingTotalAccountValue !== ""
              ? { total_account_value: Number(holdingTotalAccountValue) }
              : {}),
            ...(holdingCurrency !== "" ? { currency: holdingCurrency.toUpperCase() } : {}),
            ...(holdingFactsAsOf !== "" ? { facts_as_of: holdingFactsAsOf } : {}),
            ...(holdingOriginalThesis.trim() !== ""
              ? { original_thesis: holdingOriginalThesis.trim() }
              : {}),
          }
        : undefined;
    return {
      ticker: normalizedTicker,
      analysis_date: analysisDate,
      selected_analysts: orderedAnalysts,
      research_depth: researchDepth,
      mode,
      horizon,
      llm_provider: llmProvider,
      quick_think_llm: quickThinkLlm,
      deep_think_llm: deepThinkLlm,
      output_language: outputLanguage,
      checkpoint_enabled: checkpointEnabled,
      asset_type: null,
      ...(holding !== undefined ? { holding } : {}),
    };
  }

  return {
    loading: config === null && error === null,
    error,
    config,
    ticker,
    setTicker,
    analysis_date: analysisDate,
    setAnalysisDate,
    selected_analysts: selectedAnalysts,
    setSelectedAnalysts,
    toggleAnalyst,
    selected_preset: selectedPreset,
    setAnalystPreset,
    research_depth: researchDepth,
    setResearchDepth,
    llm_provider: llmProvider,
    setLlmProvider,
    quick_think_llm: quickThinkLlm,
    setQuickThinkLlm,
    deep_think_llm: deepThinkLlm,
    setDeepThinkLlm,
    output_language: outputLanguage,
    setOutputLanguage,
    checkpoint_enabled: checkpointEnabled,
    setCheckpointEnabled,
    mode,
    setMode,
    horizon,
    setHorizon,
    holding_quantity: holdingQuantity,
    setHoldingQuantity,
    holding_average_cost: holdingAverageCost,
    setHoldingAverageCost,
    holding_cash: holdingCash,
    setHoldingCash,
    holding_total_account_value: holdingTotalAccountValue,
    setHoldingTotalAccountValue,
    holding_currency: holdingCurrency,
    setHoldingCurrency,
    holding_facts_as_of: holdingFactsAsOf,
    setHoldingFactsAsOf,
    holding_original_thesis: holdingOriginalThesis,
    setHoldingOriginalThesis,
    selectedProvider,
    quickOptions,
    deepOptions,
    configured_keys,
    buildRequest,
    buildRequestForTicker,
    validationError,
  };
}
