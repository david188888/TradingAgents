import type { UseConfigResult } from "../../hooks/useConfig";
import { ChatGPTControls } from "./ChatGPTControls";

/** Shared single/batch model form; recovery state belongs to useChatGPT. */
export function ModelConfiguration({ cfg, prefix }: { cfg: UseConfigResult; prefix: string }) {
  const subscription = cfg.llm_provider === "chatgpt";
  const modelDisabled = cfg.loading || (subscription && (cfg.chatgpt.busy || !cfg.chatgpt.catalog));
  const placeholder = !subscription ? "暂无可选模型" : cfg.chatgpt.busy ? "正在加载模型…" : cfg.chatgpt.error ? "模型暂不可用，请先恢复连接"
    : !cfg.chatgpt.account?.plan_enabled ? "请先登录并授权" : "等待模型列表";
  const notice = subscription ? (!cfg.chatgpt.busy && cfg.chatgpt.catalog ? cfg.configurationError : null) : cfg.configurationError;
  return <section className="sidebar-section model-configuration" aria-labelledby={`${prefix}-model-heading`}>
    <div className="section-title"><h2 id={`${prefix}-model-heading`}>模型与账户</h2></div>
    <div className="input-group">
      <label htmlFor={`${prefix}-provider`}>LLM Provider</label>
      <select id={`${prefix}-provider`} value={cfg.llm_provider} onChange={e => cfg.setLlmProvider(e.target.value)} disabled={cfg.loading}>
        {cfg.config?.providers.map(p => <option key={p.id} value={p.id}>{p.id === "chatgpt" ? "ChatGPT 订阅" : `${p.id} · ${p.configured ? "已配置" : "未配置"}`}</option>)}
      </select>
      {!subscription && cfg.selectedProvider && <div className="key-status">
        {cfg.selectedProvider.requires_api_key === false ? <span className="ok">无需 API Key</span>
          : cfg.configured_keys[cfg.llm_provider] === true ? <span className="ok">已配置</span> : <span className="error-text">未配置</span>}
      </div>}
    </div>
    <div id={`${prefix}-configuration-message`}>
      {subscription && <ChatGPTControls auth={cfg.chatgpt} />}
      {notice && <p className="error-text" role="alert">{notice}</p>}
    </div>
    {([
      { key: "quick", label: "专项与挑战模型", value: cfg.quick_model_selection, options: cfg.quickOptions, set: cfg.setQuickThinkLlm, custom: cfg.quick_custom_model_id, setCustom: cfg.setQuickCustomModelId },
      { key: "deep", label: "综合模型", value: cfg.deep_model_selection, options: cfg.deepOptions, set: cfg.setDeepThinkLlm, custom: cfg.deep_custom_model_id, setCustom: cfg.setDeepCustomModelId },
    ] as const).map(field => <div className="input-group" key={field.key}>
      <label htmlFor={`${prefix}-${field.key}`}>{field.label}</label>
      <select id={`${prefix}-${field.key}`} value={subscription && !cfg.chatgpt.catalog ? "" : field.value}
        onChange={e => field.set(e.target.value)} disabled={modelDisabled || !field.options.length}>
        {subscription && !cfg.chatgpt.catalog ? <option value="">{placeholder}</option> : field.options.length
          ? field.options.map(m => <option key={m.id} value={m.id}>{m.label}</option>) : <option value="">暂无可选模型</option>}
      </select>
      {!subscription && field.value === "custom" && <>
        <label htmlFor={`${prefix}-${field.key}-custom`}>{field.label} ID</label>
        <input id={`${prefix}-${field.key}-custom`} type="text" value={field.custom} onChange={e => field.setCustom(e.target.value)} placeholder="填写 Provider 支持的实际模型 ID" />
      </>}
    </div>)}
    <div className="input-group">
      <label htmlFor={`${prefix}-lang`}>输出语言</label>
      <select id={`${prefix}-lang`} value={cfg.output_language} onChange={e => cfg.setOutputLanguage(e.target.value)} disabled={cfg.loading}>
        {cfg.config?.output_languages.map(lang => <option key={lang} value={lang}>{lang}</option>)}
      </select>
    </div>
  </section>;
}
