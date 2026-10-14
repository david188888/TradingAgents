/** Web creation state. Native scheduling and roles are code-owned. */
import { useEffect, useState } from "react";
import type { ConfigResponseDTO, RunCreateRequestDTO } from "../api/contracts";
import { getConfig } from "../api/client";
import { useChatGPT } from "./useChatGPT";

export type UseConfigResult = ReturnType<typeof useConfig>;

function todayIso(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function useConfig() {
  const [config, setConfig] = useState<ConfigResponseDTO | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [ticker, setTicker] = useState("");
  const [analysis_date, setAnalysisDate] = useState(todayIso);
  const [research_question, setResearchQuestion] = useState("");
  const [llm_provider, setLlmProviderState] = useState("");
  const [quick_model_selection, setQuickThinkLlm] = useState("");
  const [deep_model_selection, setDeepThinkLlm] = useState("");
  const [quick_custom_model_id, setQuickCustomModelId] = useState("");
  const [deep_custom_model_id, setDeepCustomModelId] = useState("");
  const chatgpt = useChatGPT(llm_provider === "chatgpt");
  useEffect(() => {
    if (llm_provider !== "chatgpt" || !chatgpt.catalog?.models.length) return;
    const first = chatgpt.catalog.models[0].id;
    setQuickThinkLlm(previous => previous || first);
    setDeepThinkLlm(previous => previous || first);
  }, [llm_provider, chatgpt.catalog]);
  const [output_language, setOutputLanguage] = useState("Chinese");

  useEffect(() => {
    let cancelled = false;
    getConfig().then(c => {
      if (cancelled) return;
      setConfig(c);
      const provider = c.providers.find(p => p.id === c.defaults.llm_provider) ?? c.providers[0];
      setLlmProviderState(provider?.id ?? "");
      const quick = c.defaults.quick_think_llm ?? provider?.models.quick[0]?.id ?? "";
      const deep = c.defaults.deep_think_llm ?? provider?.models.deep[0]?.id ?? "";
      setQuickThinkLlm(provider?.id === "chatgpt" ? quick : provider?.models.quick.some(m => m.id === quick) ? quick : provider?.custom_model_allowed ? "custom" : provider?.models.quick[0]?.id ?? "");
      setDeepThinkLlm(provider?.id === "chatgpt" ? deep : provider?.models.deep.some(m => m.id === deep) ? deep : provider?.custom_model_allowed ? "custom" : provider?.models.deep[0]?.id ?? "");
      setQuickCustomModelId(quick === "custom" || provider?.models.quick.some(m => m.id === quick) ? "" : quick);
      setDeepCustomModelId(deep === "custom" || provider?.models.deep.some(m => m.id === deep) ? "" : deep);
      setOutputLanguage(c.defaults.output_language);
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e : new Error(String(e))); });
    return () => { cancelled = true; };
  }, []);

  function setLlmProvider(id: string): void {
    if (id === llm_provider) return;
    setLlmProviderState(id);
    const provider = config?.providers.find(p => p.id === id);
    setQuickThinkLlm(provider?.models.quick[0]?.id ?? (provider?.custom_model_allowed ? "custom" : ""));
    setDeepThinkLlm(provider?.models.deep[0]?.id ?? (provider?.custom_model_allowed ? "custom" : ""));
    setQuickCustomModelId("");
    setDeepCustomModelId("");
  }
  const selectedProvider = config?.providers.find(p => p.id === llm_provider) ?? null;
  const subscriptionModels = chatgpt.catalog?.models ?? [];
  const withSelection = (selection: string) => selection && !subscriptionModels.some(m => m.id === selection)
    ? [...subscriptionModels, {id: selection, label: `${selection} · 当前不可用`}] : subscriptionModels;
  const quickOptions = llm_provider === "chatgpt" ? withSelection(quick_model_selection) : selectedProvider?.models.quick.length ? selectedProvider.models.quick : selectedProvider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  const deepOptions = llm_provider === "chatgpt" ? withSelection(deep_model_selection) : selectedProvider?.models.deep.length ? selectedProvider.models.deep : selectedProvider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  const quick_think_llm = llm_provider !== "chatgpt" && quick_model_selection === "custom" ? quick_custom_model_id.trim() : quick_model_selection;
  const deep_think_llm = llm_provider !== "chatgpt" && deep_model_selection === "custom" ? deep_custom_model_id.trim() : deep_model_selection;
  const configured_keys = config?.configured_keys ?? {};
  const support = config?.research_profiles?.evidence_v1;
  const configurationError = !selectedProvider ? "请选择 LLM Provider"
    : llm_provider === "chatgpt" && chatgpt.busy ? "正在读取账户或订阅模型列表"
    : llm_provider === "chatgpt" && chatgpt.error ? chatgpt.error
    : llm_provider === "chatgpt" && !chatgpt.account?.plan_enabled ? "请使用 ChatGPT 登录并授权订阅用量"
    : llm_provider === "chatgpt" && chatgpt.account?.usage_paused ? "订阅用量已暂停，请管理用量后主动重新尝试"
    : llm_provider === "chatgpt" && !chatgpt.catalog ? "正在读取订阅模型列表"
    : llm_provider === "chatgpt" && (!subscriptionModels.some(m => m.id === quick_think_llm) || !subscriptionModels.some(m => m.id === deep_think_llm)) ? "所选模型当前不可用，请刷新模型并重新选择"
    : selectedProvider.requires_api_key && configured_keys[llm_provider] !== true ? "所选 Provider 未配置 API Key"
    : !quick_think_llm || !deep_think_llm || (llm_provider !== "chatgpt" && (quick_think_llm === "custom" || deep_think_llm === "custom")) ? "请选择研究模型；自定义模型需填写实际 ID" : null;
  const commonError = error ? "无法读取服务配置" : config === null ? "正在读取服务配置"
    : support?.supported !== true ? support?.reason ?? "此服务不支持新建证据研究"
    : !analysis_date || analysis_date > todayIso() ? "请选择有效的分析日期"
    : Array.from(research_question.trim()).length > 400 ? "补充关注点最多 400 个字符"
    : configurationError;
  const validationError = commonError ?? (!ticker.trim() ? "请输入股票代码" : null);
  function nativeRequest(value: string): RunCreateRequestDTO | null {
    if (commonError !== null || !value.trim()) return null;
    return { ticker: value.trim(), analysis_date, research_profile: "evidence_v1", mode: "company_research",
      research_question: research_question.trim() || null,
      selected_analysts: ["market", "social", "news", "fundamentals"], research_depth: 1, horizon: "medium",
      llm_provider, quick_think_llm, deep_think_llm, output_language, checkpoint_enabled: false, asset_type: null,
      ...(llm_provider === "chatgpt" && chatgpt.account_ref ? {chatgpt_account_ref: chatgpt.account_ref} : {}),
    };
  }
  return { config, error, loading: config === null && error === null, ticker, setTicker, analysis_date, setAnalysisDate,
    research_question, setResearchQuestion, llm_provider, setLlmProvider, quick_think_llm, setQuickThinkLlm,
    deep_think_llm, setDeepThinkLlm, output_language, setOutputLanguage,
    quick_model_selection, deep_model_selection, quick_custom_model_id, setQuickCustomModelId, deep_custom_model_id, setDeepCustomModelId,
    selectedProvider, quickOptions, deepOptions, configured_keys, chatgpt, configurationError, validationError, batchValidationError: commonError,
    buildRequest: () => nativeRequest(ticker),
    buildRequestForTicker: (value: string) => nativeRequest(value),
  };
}
