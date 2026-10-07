/**
 * F3 - Left sidebar controls for the TradingAgents workbench.
 *
 * Pure renderer of useConfig() selection state + useWorkbenchStore() run state.
 * Owns no selection state itself; every input dispatches back into the hook.
 * Visual classes reference the V2 workbench stylesheet (.eyebrow, .section-title,
 * .input-group, .grid-2, .analysts, .check, .key-status, .ok, .primary,
 * .primary.running) where they exist.
 */
import { useState } from "react";
import { BatchControls } from "./BatchControls";
import { requestCompletionNotificationPermission } from "../../hooks/useCompletionNotifications";
import { useConfig } from "../../hooks/useConfig";
import { useWorkbenchSelection, useWorkbenchStream } from "../../state/WorkbenchStore";
import { ApiError, createRun, cancelRun } from "../../api/client";

/** Backend preflight code when a global ticker cannot reach Yahoo Finance. */
const VPN_BLOCKED_CODE = "yfinance_unreachable";

export interface ControlsProps {
  /** Called after a new run is successfully created so the history list refreshes. */
  refreshHistory?: () => Promise<void>;
}

export function Controls({ refreshHistory }: ControlsProps = {}): JSX.Element {
  const cfg = useConfig();
  const stream = useWorkbenchStream();
  const { run_id, selectRun } = useWorkbenchSelection();
  const [apiError, setApiError] = useState<string | null>(null);
  const [vpnMessage, setVpnMessage] = useState<string | null>(null);
  const [starting, setStarting] = useState<boolean>(false);
  const [analysisMode, setAnalysisMode] = useState<"single" | "batch">("single");

  const runActive =
    stream.status === "live" ||
    stream.status === "replaying" ||
    stream.status === "loading";

  function handleStart(): void {
    const req = cfg.buildRequest();
    if (req === null) return;
    setApiError(null);
    setVpnMessage(null);
    setStarting(true);
    void requestCompletionNotificationPermission();
    createRun(req)
      .then((snap) => {
        selectRun(snap.run_id);
        refreshHistory?.();
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.code === VPN_BLOCKED_CODE) {
          // The backend blocked a global (yfinance) ticker because Yahoo is
          // unreachable — prompt the user to enable the VPN (modal, not inline).
          setVpnMessage(e.message);
        } else {
          setApiError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        setStarting(false);
      });
  }

  function handleCancel(): void {
    if (run_id === null) return;
    cancelRun(run_id)
      .then(() => refreshHistory?.())
      .catch((e: unknown) => {
        setApiError(e instanceof Error ? e.message : String(e));
      });
  }

  if (analysisMode === "batch") {
    return (
      <>
        <div className="analysis-mode-tabs" role="group" aria-label="分析模式">
          <button type="button" className="mode-tab" aria-pressed="false" onClick={() => setAnalysisMode("single")}>单公司</button>
          <button type="button" className="mode-tab active" aria-pressed="true">批量分析</button>
        </div>
        <BatchControls cfg={cfg} refreshHistory={refreshHistory} onSelectRun={selectRun} />
      </>
    );
  }

  const startDisabled =
    cfg.validationError !== null || runActive || starting || cfg.loading;

  return (
    <>
      <div className="analysis-mode-tabs" role="group" aria-label="分析模式">
        <button type="button" className="mode-tab active" aria-pressed="true">单公司</button>
        <button type="button" className="mode-tab" aria-pressed="false" onClick={() => setAnalysisMode("batch")}>批量分析</button>
      </div>
      <div className="controls">
        <div className="eyebrow">新建研究</div>
        <div className="section-title">
        <h2>分析输入</h2>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-ticker">股票代码</label>
        <input
          id="ctrl-ticker"
          type="text"
          value={cfg.ticker}
          onChange={(e) => cfg.setTicker(e.target.value)}
          placeholder="如 600803 / 002130"
        />
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-date">分析日期</label>
        <input
          id="ctrl-date"
          type="date"
          value={cfg.analysis_date}
          onChange={(e) => cfg.setAnalysisDate(e.target.value)}
        />
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-mode">研究模式</label>
        <select
          id="ctrl-mode"
          value={cfg.mode}
          onChange={(e) =>
            cfg.setMode(
              e.target.value === "holding_review" ? "holding_review" : e.target.value === "catalyst_research" ? "catalyst_research" : "company_research",
            )
          }
        >
          <option value="company_research">公司研究</option>
          <option value="catalyst_research">催化研究 · 未来 84 天</option>
          <option value="holding_review">持仓复盘</option>
        </select>
        <small>公司研究用于理解标的；持仓复盘只用于学习和复查已有或模拟持仓。</small>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-question">补充关注点（可选）</label>
        <textarea id="ctrl-question" value={cfg.research_question} onChange={e => cfg.setResearchQuestion(e.target.value)} maxLength={800} placeholder="独立研究完成后，补充回应你关心的角度" rows={3} />
        <small>独立基础分析完成后，再依据已有证据回应；不会参与基础分析或改写综合判断。</small>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-provider">LLM Provider</label>
        <select
          id="ctrl-provider"
          value={cfg.llm_provider}
          onChange={(e) => cfg.setLlmProvider(e.target.value)}
          disabled={cfg.loading}
        >
          {cfg.config?.providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.id}
              {p.configured ? " · 已配置" : " · 未配置"}
            </option>
          ))}
        </select>
        {cfg.selectedProvider !== null && (
          <div className="key-status">
            {cfg.selectedProvider.requires_api_key === false ? (
              <span className="ok">无需 API Key</span>
            ) : cfg.configured_keys[cfg.llm_provider] === true ? (
              <span className="ok">已配置</span>
            ) : (
              <span style={{ color: "var(--red)" }}>未配置</span>
            )}
          </div>
        )}
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-quick">专项与挑战模型</label>
        <select
          id="ctrl-quick"
          value={cfg.quick_model_selection}
          onChange={(e) => cfg.setQuickThinkLlm(e.target.value)}
          disabled={cfg.loading || cfg.quickOptions.length === 0}
        >
          {cfg.quickOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        {cfg.quick_model_selection === "custom" ? <>
          <label htmlFor="ctrl-quick-custom">专项与挑战模型 ID</label>
          <input id="ctrl-quick-custom" value={cfg.quick_custom_model_id} onChange={e => cfg.setQuickCustomModelId(e.target.value)} type="text" placeholder="填写 Provider 支持的实际模型 ID" />
        </> : null}
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-deep">综合模型</label>
        <select
          id="ctrl-deep"
          value={cfg.deep_model_selection}
          onChange={(e) => cfg.setDeepThinkLlm(e.target.value)}
          disabled={cfg.loading || cfg.deepOptions.length === 0}
        >
          {cfg.deepOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        {cfg.deep_model_selection === "custom" ? <>
          <label htmlFor="ctrl-deep-custom">综合模型 ID</label>
          <input id="ctrl-deep-custom" value={cfg.deep_custom_model_id} onChange={e => cfg.setDeepCustomModelId(e.target.value)} type="text" placeholder="填写 Provider 支持的实际模型 ID" />
        </> : null}
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-lang">输出语言</label>
        <select
          id="ctrl-lang"
          value={cfg.output_language}
          onChange={(e) => cfg.setOutputLanguage(e.target.value)}
          disabled={cfg.loading}
        >
          {cfg.config?.output_languages.map((lang) => (
            <option key={lang} value={lang}>
              {lang}
            </option>
          ))}
        </select>
      </div>

      {cfg.mode === "holding_review" && (
        <>
          <div className="input-group">
            <label htmlFor="ctrl-holding-quantity">
              持仓数量
              <input
                id="ctrl-holding-quantity"
                type="number"
                min="0.000001"
                step="any"
                value={cfg.holding_quantity}
                onChange={(e) => cfg.setHoldingQuantity(e.target.value)}
                placeholder="必填，如 100"
              />
            </label>
            <label htmlFor="ctrl-holding-cost">
              平均成本（每单位）
              <input
                id="ctrl-holding-cost"
                type="number"
                min="0.000001"
                step="any"
                value={cfg.holding_average_cost}
                onChange={(e) => cfg.setHoldingAverageCost(e.target.value)}
                placeholder="必填"
              />
            </label>
          </div>
          <div className="input-group grid-2">
            <label htmlFor="ctrl-holding-cash">
              现金（可选）
              <input
                id="ctrl-holding-cash"
                type="number"
                min="0"
                step="any"
                value={cfg.holding_cash}
                onChange={(e) => cfg.setHoldingCash(e.target.value)}
              />
            </label>
            <label htmlFor="ctrl-holding-nav">
              账户总资产（可选）
              <input
                id="ctrl-holding-nav"
                type="number"
                min="0.000001"
                step="any"
                value={cfg.holding_total_account_value}
                onChange={(e) => cfg.setHoldingTotalAccountValue(e.target.value)}
              />
            </label>
          </div>
          <div className="input-group grid-2">
            <label htmlFor="ctrl-holding-currency">
              金额币种（可选）
              <input
                id="ctrl-holding-currency"
                type="text"
                maxLength={3}
                value={cfg.holding_currency}
                onChange={(e) => cfg.setHoldingCurrency(e.target.value)}
                placeholder="如 CNY"
              />
            </label>
            <label htmlFor="ctrl-holding-as-of">
              持仓事实日期（可选）
              <input
                id="ctrl-holding-as-of"
                type="date"
                value={cfg.holding_facts_as_of}
                onChange={(e) => cfg.setHoldingFactsAsOf(e.target.value)}
              />
            </label>
          </div>
          <div className="input-group">
            <label htmlFor="ctrl-holding-thesis">原始持仓理由（可选）</label>
            <textarea
              id="ctrl-holding-thesis"
              value={cfg.holding_original_thesis}
              onChange={(e) => cfg.setHoldingOriginalThesis(e.target.value)}
              placeholder="用于复查当初的研究逻辑；留空则不推测。"
              rows={3}
            />
            <small>
              持仓事实以分析日期为准。仅用于学习和复盘，不构成交易指令，也不会连接券商或执行订单。
            </small>
          </div>
        </>
      )}

      {cfg.validationError !== null && (
        <div className="error-text" style={{ color: "var(--red)" }}>
          {cfg.validationError}
        </div>
      )}
      {apiError !== null && (
        <div className="error-text" style={{ color: "var(--red)" }}>
          {apiError}
        </div>
      )}

      <div className="actions">
        {runActive ? (
          <>
            <button type="button" className="primary running" disabled>
              分析进行中
            </button>
            <button type="button" className="cancel" onClick={handleCancel}>
              取消
            </button>
          </>
        ) : (
          <button
            type="button"
            className="primary"
            onClick={handleStart}
            disabled={startDisabled}
          >
            {starting ? "启动中…" : "开始分析"}
          </button>
        )}
      </div>

      {vpnMessage !== null && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setVpnMessage(null)}
        >
          <div
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="vpn-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="vpn-modal-title">需要开启 VPN</h3>
            <p>{vpnMessage}</p>
            <p className="modal-hint">
              美股 / 港股等海外标的通过 Yahoo Finance 获取数据。请开启 VPN
              后重试；A 股无需 VPN。
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="primary"
                onClick={() => setVpnMessage(null)}
              >
                知道了
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </>
  );
}
