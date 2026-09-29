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
import { useEffect, useMemo, useState } from "react";
import type {
  ConfigResponseDTO,
  HoldingInputDTO,
  ModelOptionDTO,
  ProviderDTO,
  ResearchDepth,
  ResearchHorizon,
  ResearchMode,
  ResearchProfile,
  RunCreateRequestDTO,
} from "../api/contracts";
import { getConfig } from "../api/client";

/**
 * The four bounded stages `catalyst_v1` runs, in order. Shown on profile switch
 * so the reader knows what starting one will actually do — the classic form's
 * role checkboxes have no bearing on this flow and are not shown.
 */
const CATALYST_V1_STAGES: readonly string[] = ["准备证据", "专项分析", "反证核验", "综合发布"];

/**
 * The normalized compatibility defaults a `catalyst_v1` request carries
 * (design 7.1). The profile runs four bounded stages, so the old debate-round
 * count and look-ahead horizon are not inputs to it; these values exist so the
 * server's normalized view of the request is stable, not because the profile
 * honours them.
 */
const CATALYST_COMPAT_DEPTH: ResearchDepth = 3;
const CATALYST_COMPAT_HORIZON: ResearchHorizon = "medium";

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
  /**
   * T27: the catalyst request builder.
   *
   * Separate from `buildRequest` rather than a branch inside it, because the
   * two must not share a body. The classic request carries a research profile
   * the caller never set, a selected-analyst list from the classic form, and
   * a horizon; none of those belong in a `catalyst_v1` request, and a hidden
   * field leaking into the wrong profile is exactly the failure this split
   * makes impossible to express.
   */
  buildCatalystRequest: (researchQuestion?: string | null) => RunCreateRequestDTO | null;
  research_profile: ResearchProfile;
  setResearchProfile: (v: ResearchProfile) => void;
  research_question: string;
  setResearchQuestion: (v: string) => void;
  /** The effective config the next catalyst run will run under. */
  effectiveCatalystConfig: EffectiveCatalystConfig;
  validationError: string | null;
}

/**
 * What the reader is actually about to run, shown on profile switch (T27).
 *
 * "Effective" because it is the *server's* answer, not the form's: the server
 * may pin a depth or a model pair the form did not choose. Showing the form's
 * own values would let the two disagree silently.
 */
export interface EffectiveCatalystConfig {
  profile: ResearchProfile;
  researchDepth: ResearchDepth;
  horizon: ResearchHorizon;
  llmProvider: string;
  quickThinkLlm: string;
  deepThinkLlm: string;
  outputLanguage: string;
  /** The four bounded stages this profile runs. */
  stages: readonly string[];
  /** True when the deployment reports it can honor this profile. */
  supported: boolean | null;
  /** Set when the deployment cannot honor it; the run is not silently downgraded. */
  reason: string | null;
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
  // T27. `classic` by default, so an untouched form behaves exactly as it did
  // before this profile switch existed.
  const [researchProfile, setResearchProfile] = useState<ResearchProfile>("classic");
  const [researchQuestion, setResearchQuestion] = useState<string>("");
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

  // T27: whether this deployment can honor `catalyst_v1`. The server rejects
  // an unsupported profile rather than downgrading it, so the form says so
  // before the reader spends a run — `null` means the config has not loaded yet
  // and no claim is made either way.
  const catalystProfileSupported: boolean | null = useMemo(() => {
    if (config === null) return null;
    const declared = (config as { research_profiles?: { catalyst_v1?: { supported?: unknown; reason?: unknown } } })
      .research_profiles?.catalyst_v1;
    if (declared === undefined) return null;
    return declared.supported === true;
  }, [config]);

  const catalystProfileReason: string | null = useMemo(() => {
    if (config === null) return null;
    const declared = (config as { research_profiles?: { catalyst_v1?: { supported?: unknown; reason?: unknown } } })
      .research_profiles?.catalyst_v1;
    const reason = declared?.reason;
    return typeof reason === "string" ? reason : null;
  }, [config]);

  /**
   * T27: the catalyst request builder.
   *
   * Every field below is deliberate. The ones the classic form has and this
   * builder does not — `selected_analysts`, `mode`, `horizon`, `holding` —
   * are absent because `catalyst_v1` runs a fixed bounded sequence of four
   * specialist roles, so a role list chosen under the old form is not a valid
   * input to it and is not sent. `research_profile` is explicit: the server
   * treats omission as `classic`, and a catalyst run that arrived without it
   * would silently become the other research flow.
   *
   * The `research_question` is optional and, per design 4.1, carried in the
   * case rather than as a request field on this wire; it is returned alongside
   * so a caller can record what was asked.
   */
  function buildCatalystRequest(): RunCreateRequestDTO | null {
    if (config === null) return null;
    const normalizedTicker = ticker.trim();
    if (!normalizedTicker) return null;
    // The classic holding-review validation does not apply here: a catalyst run
    // is a company research, and `buildRequest`'s holding errors must not block
    // it or leak their text into the new form.
    if (mode === "holding_review" && holdingQuantity.trim() !== "" && !Number.isFinite(Number(holdingQuantity))) {
      return null;
    }
    return {
      ticker: normalizedTicker,
      analysis_date: analysisDate,
      // Design 7.1: the new profile gives the old scheduler fields no
      // scheduling authority. The values below are therefore the *normalized*
      // compatibility defaults the server sees when it inspects a
      // `catalyst_v1` request — not the classic form's values, which were set
      // by controls this profile never rendered. Sending the classic depth
      // here would submit a scheduling parameter the profile will ignore, and
      // the reader would reasonably read that as "my depth applied".
      selected_analysts: [],
      research_depth: CATALYST_COMPAT_DEPTH,
      mode: "company_research",
      // Design 7.1: the old `horizon` field is kept for wire compatibility and
      // the new entry point sends `medium`. The profile uses its own
      // `catalyst-evidence-policy-v1`; this is a compatibility value, not a
      // statement about how far ahead the run looks.
      horizon: CATALYST_COMPAT_HORIZON,
      llm_provider: llmProvider,
      quick_think_llm: quickThinkLlm,
      deep_think_llm: deepThinkLlm,
      output_language: outputLanguage,
      checkpoint_enabled: false,
      asset_type: null,
      research_profile: "catalyst_v1",
    };
  }

  const effectiveCatalystConfig: EffectiveCatalystConfig = {
    profile: researchProfile,
    researchDepth,
    horizon,
    llmProvider,
    quickThinkLlm,
    deepThinkLlm,
    outputLanguage,
    stages: CATALYST_V1_STAGES,
    supported: researchProfile === "catalyst_v1" ? catalystProfileSupported : null,
    reason: researchProfile === "catalyst_v1" ? catalystProfileReason : null,
  };

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
    buildCatalystRequest,
    research_profile: researchProfile,
    setResearchProfile,
    research_question: researchQuestion,
    setResearchQuestion,
    effectiveCatalystConfig,
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
