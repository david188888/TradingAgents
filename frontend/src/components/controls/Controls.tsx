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
import { useConfig } from "../../hooks/useConfig";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { ApiError, createRun, cancelRun } from "../../api/client";
import type { ResearchDepth } from "../../api/contracts";

const DEPTH_OPTIONS: ResearchDepth[] = [1, 3, 5];
/** Backend preflight code when a global ticker cannot reach Yahoo Finance. */
const VPN_BLOCKED_CODE = "yfinance_unreachable";

export interface ControlsProps {
  /** Called after a new run is successfully created so the history list refreshes. */
  refreshHistory?: () => Promise<void>;
}

export function Controls({ refreshHistory }: ControlsProps = {}): JSX.Element {
  const cfg = useConfig();
  const store = useWorkbenchStore();
  const [apiError, setApiError] = useState<string | null>(null);
  const [vpnMessage, setVpnMessage] = useState<string | null>(null);
  const [starting, setStarting] = useState<boolean>(false);

  const runActive =
    store.stream.status === "live" ||
    store.stream.status === "replaying" ||
    store.stream.status === "loading";

  function handleStart(): void {
    const req = cfg.buildRequest();
    if (req === null) return;
    setApiError(null);
    setVpnMessage(null);
    setStarting(true);
    createRun(req)
      .then((snap) => {
        store.selectRun(snap.run_id);
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
    if (store.run_id === null) return;
    cancelRun(store.run_id)
      .then(() => refreshHistory?.())
      .catch((e: unknown) => {
        setApiError(e instanceof Error ? e.message : String(e));
      });
  }

  const startDisabled =
    cfg.validationError !== null || runActive || starting || cfg.loading;

  return (
    <div className="controls">
      <div className="eyebrow">New analysis</div>
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
          placeholder="如 600519 / AAPL"
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
              e.target.value === "holding_review" ? "holding_review" : "company_research",
            )
          }
        >
          <option value="company_research">公司研究</option>
          <option value="holding_review">持仓复盘</option>
        </select>
        <small>公司研究用于理解标的；持仓复盘只用于学习和复查已有或模拟持仓。</small>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-horizon">研究周期</label>
        <select
          id="ctrl-horizon"
          value={cfg.horizon}
          onChange={(e) => {
            const value = e.target.value;
            if (value === "short" || value === "medium" || value === "long") {
              cfg.setHorizon(value);
            }
          }}
        >
          <option value="short">短期</option>
          <option value="medium">中期</option>
          <option value="long">长期</option>
        </select>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-depth">研究深度</label>
        <select
          id="ctrl-depth"
          value={String(cfg.research_depth)}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (v === 1 || v === 3 || v === 5) cfg.setResearchDepth(v);
          }}
        >
          {DEPTH_OPTIONS.map((d) => (
            <option key={d} value={String(d)}>
              {d} 轮
            </option>
          ))}
        </select>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-preset">研究预设</label>
        <select
          id="ctrl-preset"
          value={cfg.selected_preset ?? "custom"}
          onChange={(e) => cfg.setAnalystPreset(e.target.value)}
          disabled={cfg.loading}
        >
          {cfg.selected_preset === null && <option value="custom">自定义组合</option>}
          {cfg.config?.presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.label}
            </option>
          ))}
        </select>
        <small>预设只调整分析师启停与顺序，后续研究和风控链路始终执行。</small>
      </div>

      <div className="input-group">
        <label>分析师</label>
        <div className="analysts grid-2">
          {cfg.config?.analysts.map((a) => (
            <label
              key={a.id}
              className="check"
              htmlFor={`ctrl-analyst-${a.id}`}
            >
              <input
                id={`ctrl-analyst-${a.id}`}
                type="checkbox"
                checked={cfg.selected_analysts.includes(a.id)}
                onChange={() => cfg.toggleAnalyst(a.id)}
              />
              {a.id}
            </label>
          ))}
        </div>
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
        <label htmlFor="ctrl-quick">快速思考模型</label>
        <select
          id="ctrl-quick"
          value={cfg.quick_think_llm}
          onChange={(e) => cfg.setQuickThinkLlm(e.target.value)}
          disabled={cfg.loading || cfg.quickOptions.length === 0}
        >
          {cfg.quickOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div className="input-group">
        <label htmlFor="ctrl-deep">深度思考模型</label>
        <select
          id="ctrl-deep"
          value={cfg.deep_think_llm}
          onChange={(e) => cfg.setDeepThinkLlm(e.target.value)}
          disabled={cfg.loading || cfg.deepOptions.length === 0}
        >
          {cfg.deepOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
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

      <div className="input-group">
        <label className="check" htmlFor="ctrl-checkpoint">
          <input
            id="ctrl-checkpoint"
            type="checkbox"
            checked={cfg.checkpoint_enabled}
            onChange={(e) => cfg.setCheckpointEnabled(e.target.checked)}
            disabled={!cfg.config?.checkpoint_available}
          />
          启用 Checkpoint 续跑
        </label>
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
  );
}
