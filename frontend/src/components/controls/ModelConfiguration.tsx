import { STAGE_ROWS, type UseConfigResult } from "../../hooks/useConfig";
import { ChatGPTControls } from "./ChatGPTControls";

/** Shared single/batch model form; recovery state belongs to useChatGPT. */
export function ModelConfiguration({ cfg, prefix }: { cfg: UseConfigResult; prefix: string }) {
  const subscription = cfg.llm_provider === "chatgpt";
  const modelDisabled = cfg.loading || (subscription && (cfg.chatgpt.busy || !cfg.chatgpt.catalog));
  const placeholder = !subscription ? "暂无可选模型" : cfg.chatgpt.busy ? "正在加载模型…" : cfg.chatgpt.error ? "模型暂不可用，请先恢复连接"
    : !cfg.chatgpt.account?.plan_enabled ? "请先登录并授权" : "等待模型列表";
  const notice = cfg.usesSubscription ? (!cfg.chatgpt.busy && cfg.chatgpt.catalog ? cfg.configurationError : null) : cfg.configurationError;
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
      {cfg.usesSubscription && <ChatGPTControls auth={cfg.chatgpt} />}
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
    <details className="stage-models">
      <summary>分阶段模型（高级）</summary>
      <p className="stage-models-hint">未设置的阶段沿用上方模型；回应阶段自动跟随对应专项。</p>
      {STAGE_ROWS.map(({ key, label }) => {
        const s = cfg.stageSelections[key];
        const options = s ? cfg.stageModelOptions(s.provider) : [];
        const efforts = s ? cfg.stageEfforts(s.provider) : [];
        return <div className="input-group stage-model-row" key={key}>
          <label htmlFor={`${prefix}-stage-${key}`}>{label}</label>
          <select id={`${prefix}-stage-${key}`} value={s?.provider ?? ""} onChange={e => cfg.updateStage(key, { provider: e.target.value })} disabled={cfg.loading}>
            <option value="">继承</option>
            {cfg.config?.providers.map(p => <option key={p.id} value={p.id}>{p.id === "chatgpt" ? "ChatGPT 订阅" : p.id}</option>)}
          </select>
          {s && <select aria-label={`${label}模型`} value={s.model} onChange={e => cfg.updateStage(key, { model: e.target.value })} disabled={!options.length}>
            {options.length ? options.map(m => <option key={m.id} value={m.id}>{m.label}</option>) : <option value="">暂无可选模型</option>}
          </select>}
          {s && efforts.length > 0 && <select aria-label={`${label}推理强度`} value={s.effort} onChange={e => cfg.updateStage(key, { effort: e.target.value })}>
            <option value="">默认强度</option>
            {efforts.map(effort => <option key={effort} value={effort}>{effort}</option>)}
          </select>}
          {s && s.provider !== "chatgpt" && s.model === "custom" && <input aria-label={`${label}模型 ID`} type="text" value={s.custom}
            onChange={e => cfg.updateStage(key, { custom: e.target.value })} placeholder="填写 Provider 支持的实际模型 ID" />}
        </div>;
      })}
    </details>
    <div className="input-group">
      <label htmlFor={`${prefix}-lang`}>输出语言</label>
      <select id={`${prefix}-lang`} value={cfg.output_language} onChange={e => cfg.setOutputLanguage(e.target.value)} disabled={cfg.loading}>
        {cfg.config?.output_languages.map(lang => <option key={lang} value={lang}>{lang}</option>)}
      </select>
    </div>
  </section>;
}
