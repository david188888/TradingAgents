/** Web creation state. Native scheduling and roles are code-owned. */
import { useEffect, useState } from "react";
import type { ConfigResponseDTO, HoldingInputDTO, ResearchMode, RunCreateRequestDTO } from "../api/contracts";
import { getConfig } from "../api/client";

export type UseConfigResult = ReturnType<typeof useConfig>;

function todayIso(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function useConfig() {
  const [config, setConfig] = useState<ConfigResponseDTO | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [ticker, setTicker] = useState("");
  const [analysis_date, setAnalysisDate] = useState(todayIso);
  const [mode, setMode] = useState<ResearchMode>("company_research");
  const [research_question, setResearchQuestion] = useState("");
  const [llm_provider, setLlmProviderState] = useState("");
  const [quick_model_selection, setQuickThinkLlm] = useState("");
  const [deep_model_selection, setDeepThinkLlm] = useState("");
  const [quick_custom_model_id, setQuickCustomModelId] = useState("");
  const [deep_custom_model_id, setDeepCustomModelId] = useState("");
  const [output_language, setOutputLanguage] = useState("Chinese");
  const [holding_quantity, setHoldingQuantity] = useState("");
  const [holding_average_cost, setHoldingAverageCost] = useState("");
  const [holding_cash, setHoldingCash] = useState("");
  const [holding_total_account_value, setHoldingTotalAccountValue] = useState("");
  const [holding_currency, setHoldingCurrency] = useState("");
  const [holding_facts_as_of, setHoldingFactsAsOf] = useState("");
  const [holding_original_thesis, setHoldingOriginalThesis] = useState("");

  useEffect(() => {
    let cancelled = false;
    getConfig().then(c => {
      if (cancelled) return;
      setConfig(c);
      const provider = c.providers.find(p => p.id === c.defaults.llm_provider) ?? c.providers[0];
      setLlmProviderState(provider?.id ?? "");
      const quick = c.defaults.quick_think_llm ?? provider?.models.quick[0]?.id ?? "";
      const deep = c.defaults.deep_think_llm ?? provider?.models.deep[0]?.id ?? "";
      setQuickThinkLlm(provider?.models.quick.some(m => m.id === quick) ? quick : provider?.custom_model_allowed ? "custom" : provider?.models.quick[0]?.id ?? "");
      setDeepThinkLlm(provider?.models.deep.some(m => m.id === deep) ? deep : provider?.custom_model_allowed ? "custom" : provider?.models.deep[0]?.id ?? "");
      setQuickCustomModelId(quick === "custom" || provider?.models.quick.some(m => m.id === quick) ? "" : quick);
      setDeepCustomModelId(deep === "custom" || provider?.models.deep.some(m => m.id === deep) ? "" : deep);
      setOutputLanguage(c.defaults.output_language);
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e : new Error(String(e))); });
    return () => { cancelled = true; };
  }, []);

  function setLlmProvider(id: string): void {
    setLlmProviderState(id);
    const provider = config?.providers.find(p => p.id === id);
    setQuickThinkLlm(provider?.models.quick[0]?.id ?? (provider?.custom_model_allowed ? "custom" : ""));
    setDeepThinkLlm(provider?.models.deep[0]?.id ?? (provider?.custom_model_allowed ? "custom" : ""));
    setQuickCustomModelId("");
    setDeepCustomModelId("");
  }
  const selectedProvider = config?.providers.find(p => p.id === llm_provider) ?? null;
  const quickOptions = selectedProvider?.models.quick.length ? selectedProvider.models.quick : selectedProvider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  const deepOptions = selectedProvider?.models.deep.length ? selectedProvider.models.deep : selectedProvider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  const quick_think_llm = quick_model_selection === "custom" ? quick_custom_model_id.trim() : quick_model_selection;
  const deep_think_llm = deep_model_selection === "custom" ? deep_custom_model_id.trim() : deep_model_selection;
  const configured_keys = config?.configured_keys ?? {};
  const support = config?.research_profiles?.evidence_v1;
  const commonError = error ? "无法读取服务配置" : config === null ? "正在读取服务配置"
    : support?.supported !== true ? support?.reason ?? "此服务不支持新建证据研究"
    : !analysis_date || analysis_date > todayIso() ? "请选择有效的分析日期"
    : Array.from(research_question.trim()).length > 400 ? "研究问题最多 400 个字符"
    : !selectedProvider ? "请选择 LLM Provider"
    : selectedProvider.requires_api_key && configured_keys[llm_provider] !== true ? "所选 Provider 未配置 API Key"
    : !quick_think_llm || !deep_think_llm || quick_think_llm === "custom" || deep_think_llm === "custom" ? "请选择研究模型；自定义模型需填写实际 ID" : null;
  let holdingError: string | null = null;
  if (mode === "holding_review") {
    const quantity = Number(holding_quantity), cost = Number(holding_average_cost);
    if (!Number.isFinite(quantity) || quantity <= 0) holdingError = "持仓数量必须是大于 0 的数字";
    else if (!Number.isFinite(cost) || cost <= 0) holdingError = "平均成本必须是大于 0 的数字";
    else if (holding_cash !== "" && (!Number.isFinite(Number(holding_cash)) || Number(holding_cash) < 0)) holdingError = "现金必须是非负数字";
    else if (holding_total_account_value !== "" && (!Number.isFinite(Number(holding_total_account_value)) || Number(holding_total_account_value) <= 0)) holdingError = "账户总资产必须是大于 0 的数字";
    else if (holding_currency !== "" && !/^[A-Za-z]{3}$/.test(holding_currency)) holdingError = "币种请使用三个英文字母，例如 CNY";
    else if (holding_facts_as_of !== "" && holding_facts_as_of !== analysis_date) holdingError = "持仓事实日期必须与分析日期一致";
    else if (Array.from(holding_original_thesis.trim()).length > 4000) holdingError = "原持仓论点最多 4000 个字符";
  }
  const validationError = commonError ?? (!ticker.trim() ? "请输入股票代码" : holdingError);
  function nativeRequest(value: string, scope: ResearchMode): RunCreateRequestDTO | null {
    if (commonError !== null || !value.trim() || (scope === "holding_review" && holdingError !== null)) return null;
    const holding: HoldingInputDTO | undefined = scope === "holding_review" ? {
      ticker: value.trim(), quantity: Number(holding_quantity), average_cost: Number(holding_average_cost),
      ...(holding_cash !== "" ? { cash: Number(holding_cash) } : {}),
      ...(holding_total_account_value !== "" ? { total_account_value: Number(holding_total_account_value) } : {}),
      ...(holding_currency !== "" ? { currency: holding_currency.toUpperCase() } : {}),
      facts_as_of: holding_facts_as_of || analysis_date,
      ...(holding_original_thesis.trim() ? { original_thesis: holding_original_thesis.trim() } : {}),
    } : undefined;
    return { ticker: value.trim(), analysis_date, research_profile: "evidence_v1", mode: scope,
      research_question: research_question.trim() || null,
      selected_analysts: ["market", "social", "news", "fundamentals"], research_depth: 1, horizon: "medium",
      llm_provider, quick_think_llm, deep_think_llm, output_language, checkpoint_enabled: false, asset_type: null,
      ...(holding ? { holding } : {}),
    };
  }
  return { config, error, loading: config === null && error === null, ticker, setTicker, analysis_date, setAnalysisDate,
    mode, setMode, research_question, setResearchQuestion, llm_provider, setLlmProvider, quick_think_llm, setQuickThinkLlm,
    deep_think_llm, setDeepThinkLlm, output_language, setOutputLanguage,
    quick_model_selection, deep_model_selection, quick_custom_model_id, setQuickCustomModelId, deep_custom_model_id, setDeepCustomModelId,
    selectedProvider, quickOptions, deepOptions, configured_keys, validationError, batchValidationError: commonError,
    holding_quantity, setHoldingQuantity, holding_average_cost, setHoldingAverageCost, holding_cash, setHoldingCash,
    holding_total_account_value, setHoldingTotalAccountValue, holding_currency, setHoldingCurrency,
    holding_facts_as_of, setHoldingFactsAsOf, holding_original_thesis, setHoldingOriginalThesis,
    buildRequest: () => nativeRequest(ticker, mode),
    buildRequestForTicker: (value: string) => nativeRequest(value, "company_research"),
  };
}
