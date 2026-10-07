import { useEffect, useMemo, useRef, useState } from "react";
import type { BatchSnapshotDTO, RunCreateRequestDTO } from "../../api/contracts";
import {
  ApiError,
  cancelBatch,
  createBatch,
  getBatch,
  listBatches,
  setSchedulerConcurrency,
  validateBatch,
} from "../../api/client";
import type { UseConfigResult } from "../../hooks/useConfig";
import {
  notifyBatch,
  requestCompletionNotificationPermission,
} from "../../hooks/useCompletionNotifications";

const MAX_ITEMS = 8;
const TERMINAL_BATCH_STATUSES = new Set(["completed", "partial", "failed", "cancelled"]);

type CompanyRow = {
  id: number;
  input: string;
  resolved?: { company_name: string; ticker: string; market: string };
};

export interface BatchControlsProps {
  cfg: UseConfigResult;
  refreshHistory?: () => Promise<void>;
  onSelectRun: (run_id: string) => void;
}

function configFromRequest(request: RunCreateRequestDTO): Omit<RunCreateRequestDTO, "ticker" | "mode" | "holding" | "portfolio"> {
  const { ticker: _ticker, mode: _mode, holding: _holding, portfolio: _portfolio, ...config } = request;
  return config;
}

export function BatchControls({ cfg, refreshHistory, onSelectRun }: BatchControlsProps): JSX.Element {
  const [rows, setRows] = useState<CompanyRow[]>([{ id: 1, input: "" }]);
  const [concurrency, setConcurrency] = useState<1 | 2 | 3>(3);
  const [batch, setBatch] = useState<BatchSnapshotDTO | null>(null);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const previousBatchStatus = useRef<string | null>(null);

  const sharedRequest = cfg.buildRequestForTicker("600803");
  const activeRows = rows.filter((row) => row.input.trim() !== "");
  const canAdd = rows.length < MAX_ITEMS;
  const hasEmptyRow = rows.some((row) => row.input.trim() === "");
  const canStart = checked && batch === null && sharedRequest !== null && !hasEmptyRow && !checking && !starting;

  useEffect(() => {
    void listBatches()
      .then((batches) => {
        const active = batches.find((candidate) => !TERMINAL_BATCH_STATUSES.has(candidate.status));
        if (active !== undefined) setBatch(active);
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (batch !== null && previousBatchStatus.current !== null && previousBatchStatus.current !== batch.status) {
      notifyBatch(batch);
    }
    previousBatchStatus.current = batch?.status ?? null;
  }, [batch]);
  useEffect(() => {
    if (batch === null || TERMINAL_BATCH_STATUSES.has(batch.status)) return;
    // Background tabs do not need 1.2s polling: pause while hidden and
    // refresh once immediately on return so status stays current.
    const fetchBatch = (): void => {
      void getBatch(batch.batch_id)
        .then(setBatch)
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
    };
    let timer: number | null = null;
    const handleVisibility = (): void => {
      if (document.visibilityState === "visible") {
        fetchBatch();
        if (timer === null) timer = window.setInterval(fetchBatch, 1200);
      } else if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
    if (document.visibilityState === "visible") {
      timer = window.setInterval(fetchBatch, 1200);
    }
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      if (timer !== null) window.clearInterval(timer);
    };
  }, [batch]);

  const resolvedInputs = useMemo(
    () => rows.map((row) => row.resolved?.ticker ?? row.input.trim().toUpperCase()).filter(Boolean),
    [rows],
  );

  const updateRow = (id: number, patch: Partial<CompanyRow>): void => {
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...patch, resolved: patch.input !== undefined ? undefined : row.resolved } : row)));
    setChecked(false);
  };

  const handleValidate = (): void => {
    if (activeRows.length === 0 || hasEmptyRow) {
      setError("请填写所有公司后再校验批次");
      return;
    }
    setChecking(true);
    setError(null);
    validateBatch(activeRows.map((row) => row.input.trim()))
      .then((result) => {
        setRows((current) => {
          let index = 0;
          return current.map((row) => {
            if (!row.input.trim()) return row;
            const resolved = result.items[index++];
            return { ...row, resolved };
          });
        });
        setChecked(true);
      })
      .catch((reason: unknown) => {
        setChecked(false);
        setError(reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => setChecking(false));
  };

  const handleStart = (): void => {
    if (!canStart || sharedRequest === null) return;
    setStarting(true);
    void requestCompletionNotificationPermission();
    const baseConfig = configFromRequest(sharedRequest);
    createBatch({
      concurrency,
      entries: activeRows.map((row) => ({
        input: row.input.trim(),
        config: {
          ...baseConfig,
        },
      })),
    })
      .then((created) => {
        setBatch(created);
        void refreshHistory?.();
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setStarting(false));
  };

  const handleCancelBatch = (): void => {
    if (batch === null) return;
    void cancelBatch(batch.batch_id)
      .then(setBatch)
      .then(() => refreshHistory?.())
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  };

  const handleConcurrency = (value: 1 | 2 | 3): void => {
    setConcurrency(value);
    void setSchedulerConcurrency(value).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  };

  if (batch !== null) {
    return (
      <div className="controls batch-controls">
        <div className="eyebrow">Batch queue</div>
        <div className="section-title"><h2>批量分析</h2></div>
        <div className="batch-summary">
          <strong>{batch.completed_count}/{batch.items.length} 已完成</strong>
          <span>{batch.running_count} 运行中 · {batch.queued_count} 排队中 · {batch.failed_count} 失败 · {batch.cancelled_count} 取消</span>
        </div>
        <ol className="batch-list">
          {batch.items.map((item) => (
            <li key={item.run_id} className={`batch-item batch-item-${item.status}`}>
              <button type="button" className="batch-item-main" onClick={() => onSelectRun(item.run_id)}>
                <span className="batch-item-order">{item.ordinal + 1}</span>
                <span className="batch-item-copy"><strong>{item.company_name || item.input}</strong><small>{item.ticker} · {item.status}</small></span>
              </button>
              {item.error_message ? <small className="error-text">{item.error_message}</small> : null}
            </li>
          ))}
        </ol>
        {!TERMINAL_BATCH_STATUSES.has(batch.status) ? <button type="button" className="cancel" onClick={handleCancelBatch}>取消批次</button> : null}
        <button type="button" className="secondary" onClick={() => setBatch(null)}>新建批量分析</button>
      </div>
    );
  }

  return (
    <div className="controls batch-controls">
      <div className="eyebrow">Batch analysis</div>
      <div className="section-title"><h2>批量分析</h2></div>
      <div className="input-group">
        <label htmlFor="batch-concurrency">同时运行</label>
        <select id="batch-concurrency" value={String(concurrency)} onChange={(event) => handleConcurrency(Number(event.target.value) as 1 | 2 | 3)}>
          <option value="1">1 家</option><option value="2">2 家</option><option value="3">3 家</option>
        </select>
      </div>
      <div className="input-group">
        <label>公司列表</label>
        <div className="batch-input-list">
          {rows.map((row) => (
            <div className="batch-input-row" key={row.id}>
              <input value={row.input} placeholder="代码或公司名称" onChange={(event) => updateRow(row.id, { input: event.target.value })} />
              <button type="button" className="icon-button" aria-label={`移除第 ${row.id} 家公司`} onClick={() => { setRows((current) => current.filter((candidate) => candidate.id !== row.id)); setChecked(false); }}>×</button>
              {row.resolved ? <small className="batch-resolved">{row.resolved.company_name} · {row.resolved.ticker} · {row.resolved.market}</small> : null}
            </div>
          ))}
        </div>
        <button type="button" className="secondary" disabled={!canAdd} onClick={() => setRows((current) => [...current, { id: Math.max(...current.map((row) => row.id), 0) + 1, input: "" }])}>＋ 添加公司（{rows.length}/{MAX_ITEMS}）</button>
      </div>
      <div className="input-group"><label htmlFor="batch-date">分析日期</label><input id="batch-date" type="date" value={cfg.analysis_date} onChange={(event) => cfg.setAnalysisDate(event.target.value)} /></div>
      <div className="input-group">
        <label htmlFor="batch-question">补充关注点（可选）</label>
        <textarea id="batch-question" value={cfg.research_question} onChange={event => cfg.setResearchQuestion(event.target.value)} maxLength={800} rows={3} placeholder="独立研究完成后，补充回应你关心的角度" />
        <small>每家公司先完成独立基础分析，再依据已有证据回应同一关注点；不会改写综合判断。</small>
      </div>
      <div className="input-group">
        <label htmlFor="batch-provider">LLM Provider</label>
        <select
          id="batch-provider"
          value={cfg.llm_provider}
          onChange={(event) => cfg.setLlmProvider(event.target.value)}
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
        <label htmlFor="batch-quick">专项与挑战模型</label>
        <select
          id="batch-quick"
          value={cfg.quick_model_selection}
          onChange={(event) => cfg.setQuickThinkLlm(event.target.value)}
          disabled={cfg.loading || cfg.quickOptions.length === 0}
        >
          {cfg.quickOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        {cfg.quick_model_selection === "custom" ? <>
          <label htmlFor="batch-quick-custom">专项与挑战模型 ID</label>
          <input id="batch-quick-custom" value={cfg.quick_custom_model_id} onChange={event => cfg.setQuickCustomModelId(event.target.value)} type="text" placeholder="填写 Provider 支持的实际模型 ID" />
        </> : null}
      </div>
      <div className="input-group">
        <label htmlFor="batch-deep">综合模型</label>
        <select
          id="batch-deep"
          value={cfg.deep_model_selection}
          onChange={(event) => cfg.setDeepThinkLlm(event.target.value)}
          disabled={cfg.loading || cfg.deepOptions.length === 0}
        >
          {cfg.deepOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        {cfg.deep_model_selection === "custom" ? <>
          <label htmlFor="batch-deep-custom">综合模型 ID</label>
          <input id="batch-deep-custom" value={cfg.deep_custom_model_id} onChange={event => cfg.setDeepCustomModelId(event.target.value)} type="text" placeholder="填写 Provider 支持的实际模型 ID" />
        </> : null}
      </div>
      {cfg.batchValidationError ? <div className="error-text">{cfg.batchValidationError}</div> : null}
      {error ? <div className="error-text">{error}</div> : null}
      <div className="actions"><button type="button" className="secondary" onClick={handleValidate} disabled={checking || hasEmptyRow || activeRows.length === 0}>{checking ? "校验中…" : checked ? "重新校验" : "校验批次"}</button><button type="button" className="primary" onClick={handleStart} disabled={!canStart}>{starting ? "启动中…" : "开始批量分析"}</button></div>
      {checked ? <p className="batch-ready">已校验 {resolvedInputs.length} 家，公司配置将在启动后冻结。</p> : null}
    </div>
  );
}
