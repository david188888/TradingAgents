/** Web creation state. Native scheduling and roles are code-owned. */
import { useEffect, useState } from "react";
import type { ConfigResponseDTO, ModelOptionDTO, RunCreateRequestDTO, StageModelDTO, StageModelKey } from "../api/contracts";
import { getConfig } from "../api/client";
import { useChatGPT } from "./useChatGPT";

export type UseConfigResult = ReturnType<typeof useConfig>;

/** Web stage overrides; an unset row inherits the two-tier models above. */
export const STAGE_ROWS: readonly { key: StageModelKey; label: string }[] = [
  { key: "operating_quality", label: "经营" },
  { key: "event_context", label: "事件" },
  { key: "market_context", label: "市场" },
  { key: "challenge", label: "质疑" },
  { key: "synthesis", label: "综合" },
];

export interface StageSelection { provider: string; model: string; custom: string; effort: string }

export function useConfig() {
  const [config, setConfig] = useState<ConfigResponseDTO | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [ticker, setTicker] = useState("");
  const [research_question, setResearchQuestion] = useState("");
  const [llm_provider, setLlmProviderState] = useState("");
  const [quick_model_selection, setQuickThinkLlm] = useState("");
  const [deep_model_selection, setDeepThinkLlm] = useState("");
  const [quick_custom_model_id, setQuickCustomModelId] = useState("");
  const [deep_custom_model_id, setDeepCustomModelId] = useState("");
  const [stageSelections, setStageSelections] = useState<Partial<Record<StageModelKey, StageSelection>>>({});
  const usesSubscription = llm_provider === "chatgpt" || Object.values(stageSelections).some(s => s?.provider === "chatgpt");
  const chatgpt = useChatGPT(usesSubscription);
  useEffect(() => {
    if (!chatgpt.catalog?.models.length) return;
    const first = chatgpt.catalog.models[0].id;
    if (llm_provider === "chatgpt") {
      setQuickThinkLlm(previous => previous || first);
      setDeepThinkLlm(previous => previous || first);
    }
    setStageSelections(previous => Object.fromEntries(Object.entries(previous).map(([key, s]) =>
      [key, s?.provider === "chatgpt" && !s.model ? { ...s, model: first } : s])));
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
  function stageModelOptions(providerId: string): ModelOptionDTO[] {
    if (providerId === "chatgpt") return subscriptionModels;
    const provider = config?.providers.find(p => p.id === providerId);
    const listed = [...provider?.models.quick ?? [], ...provider?.models.deep ?? []]
      .filter((m, i, all) => all.findIndex(o => o.id === m.id) === i);
    return listed.length ? listed : provider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  }
  function updateStage(key: StageModelKey, change: Partial<StageSelection>): void {
    setStageSelections(previous => {
      const current = previous[key];
      if (change.provider === "") return Object.fromEntries(Object.entries(previous).filter(([k]) => k !== key));
      if (change.provider !== undefined && change.provider !== current?.provider)
        return { ...previous, [key]: { provider: change.provider, model: stageModelOptions(change.provider)[0]?.id ?? "", custom: "", effort: "" } };
      return current ? { ...previous, [key]: { ...current, ...change } } : previous;
    });
  }
  const stage_models: Partial<Record<StageModelKey, StageModelDTO>> = Object.fromEntries(STAGE_ROWS.flatMap(({ key }) => {
    const s = stageSelections[key];
    if (!s) return [];
    const model = s.provider !== "chatgpt" && s.model === "custom" ? s.custom.trim() : s.model;
    return [[key, { provider: s.provider, model, ...(s.effort ? { effort: s.effort } : {}) }]];
  }));
  const withSelection = (selection: string) => selection && !subscriptionModels.some(m => m.id === selection)
    ? [...subscriptionModels, {id: selection, label: `${selection} · 当前不可用`}] : subscriptionModels;
  const quickOptions = llm_provider === "chatgpt" ? withSelection(quick_model_selection) : selectedProvider?.models.quick.length ? selectedProvider.models.quick : selectedProvider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  const deepOptions = llm_provider === "chatgpt" ? withSelection(deep_model_selection) : selectedProvider?.models.deep.length ? selectedProvider.models.deep : selectedProvider?.custom_model_allowed ? [{ id: "custom", label: "自定义模型 ID" }] : [];
  const quick_think_llm = llm_provider !== "chatgpt" && quick_model_selection === "custom" ? quick_custom_model_id.trim() : quick_model_selection;
  const deep_think_llm = llm_provider !== "chatgpt" && deep_model_selection === "custom" ? deep_custom_model_id.trim() : deep_model_selection;
  const configured_keys = config?.configured_keys ?? {};
  const support = config?.research_profiles?.evidence_v1;
  const stageError = STAGE_ROWS.map(({ key, label }) => {
    const s = stage_models[key];
    if (!s) return null;
    if (s.provider === "chatgpt") return subscriptionModels.some(m => m.id === s.model) ? null : `分阶段模型「${label}」所选订阅模型不可用`;
    const provider = config?.providers.find(p => p.id === s.provider);
    if (provider?.requires_api_key && configured_keys[s.provider] !== true) return `分阶段模型「${label}」的 Provider 未配置 API Key`;
    return !s.model || s.model === "custom" ? `请为分阶段模型「${label}」选择模型；自定义模型需填写实际 ID` : null;
  }).find(Boolean) ?? null;
  const configurationError = !selectedProvider ? "请选择 LLM Provider"
    : usesSubscription && chatgpt.busy ? "正在读取账户或订阅模型列表"
    : usesSubscription && chatgpt.error ? chatgpt.error
    : usesSubscription && !chatgpt.account?.plan_enabled ? "请使用 ChatGPT 登录并授权订阅用量"
    : usesSubscription && chatgpt.account?.usage_paused ? "订阅用量已暂停，请管理用量后主动重新尝试"
    : usesSubscription && !chatgpt.catalog ? "正在读取订阅模型列表"
    : llm_provider === "chatgpt" && (!subscriptionModels.some(m => m.id === quick_think_llm) || !subscriptionModels.some(m => m.id === deep_think_llm)) ? "所选模型当前不可用，请刷新模型并重新选择"
    : selectedProvider.requires_api_key && configured_keys[llm_provider] !== true ? "所选 Provider 未配置 API Key"
    : !quick_think_llm || !deep_think_llm || (llm_provider !== "chatgpt" && (quick_think_llm === "custom" || deep_think_llm === "custom")) ? "请选择研究模型；自定义模型需填写实际 ID"
    : stageError;
  const commonError = error ? "无法读取服务配置" : config === null ? "正在读取服务配置"
    : support?.supported !== true ? support?.reason ?? "此服务不支持新建证据研究"
    : Array.from(research_question.trim()).length > 400 ? "补充关注点最多 400 个字符"
    : configurationError;
  const validationError = commonError ?? (!ticker.trim() ? "请输入股票代码" : null);
  function nativeRequest(value: string): RunCreateRequestDTO | null {
    if (commonError !== null || !value.trim()) return null;
    return { ticker: value.trim(), research_profile: "evidence_v1",
      research_question: research_question.trim() || null,
      llm_provider, quick_think_llm, deep_think_llm, output_language,
      ...(Object.keys(stage_models).length ? { stage_models } : {}),
      ...(usesSubscription && chatgpt.account_ref ? {chatgpt_account_ref: chatgpt.account_ref} : {}),
    };
  }
  return { config, error, loading: config === null && error === null, ticker, setTicker,
    research_question, setResearchQuestion, llm_provider, setLlmProvider, quick_think_llm, setQuickThinkLlm,
    deep_think_llm, setDeepThinkLlm, output_language, setOutputLanguage,
    quick_model_selection, deep_model_selection, quick_custom_model_id, setQuickCustomModelId, deep_custom_model_id, setDeepCustomModelId,
    selectedProvider, quickOptions, deepOptions, configured_keys, chatgpt, configurationError, validationError, batchValidationError: commonError,
    usesSubscription, stageSelections, updateStage, stageModelOptions,
    stageEfforts: (providerId: string) => config?.stage_model_efforts?.[providerId] ?? [],
    buildRequest: () => nativeRequest(ticker),
    buildRequestForTicker: (value: string) => nativeRequest(value),
  };
}
