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
  custom: boolean;
  depth?: 1 | 3 | 5;
  horizon?: "short" | "medium" | "long";
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
  const [rows, setRows] = useState<CompanyRow[]>([{ id: 1, input: "", custom: false }]);
  const [concurrency, setConcurrency] = useState<1 | 2 | 3>(3);
  const [batch, setBatch] = useState<BatchSnapshotDTO | null>(null);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const previousBatchStatus = useRef<string | null>(null);

  const sharedRequest = cfg.buildRequestForTicker("AAPL");
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
          ...(row.custom && row.depth !== undefined ? { research_depth: row.depth } : {}),
          ...(row.custom && row.horizon !== undefined ? { horizon: row.horizon } : {}),
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
              <label className="check batch-custom-check"><input type="checkbox" checked={row.custom} onChange={(event) => updateRow(row.id, { custom: event.target.checked, depth: cfg.research_depth, horizon: cfg.horizon })} /> 单独配置</label>
              {row.custom ? <div className="batch-item-config"><select value={String(row.depth ?? cfg.research_depth)} onChange={(event) => updateRow(row.id, { depth: Number(event.target.value) as 1 | 3 | 5 })}><option value="1">深度 1</option><option value="3">深度 3</option><option value="5">深度 5</option></select><select value={row.horizon ?? cfg.horizon} onChange={(event) => updateRow(row.id, { horizon: event.target.value as "short" | "medium" | "long" })}><option value="short">短期</option><option value="medium">中期</option><option value="long">长期</option></select></div> : null}
            </div>
          ))}
        </div>
        <button type="button" className="secondary" disabled={!canAdd} onClick={() => setRows((current) => [...current, { id: Math.max(...current.map((row) => row.id), 0) + 1, input: "", custom: false }])}>＋ 添加公司（{rows.length}/{MAX_ITEMS}）</button>
      </div>
      <div className="input-group"><label htmlFor="batch-date">分析日期</label><input id="batch-date" type="date" value={cfg.analysis_date} onChange={(event) => cfg.setAnalysisDate(event.target.value)} /></div>
      <div className="input-group"><label htmlFor="batch-depth">公共研究深度</label><select id="batch-depth" value={String(cfg.research_depth)} onChange={(event) => cfg.setResearchDepth(Number(event.target.value) as 1 | 3 | 5)}><option value="1">1 轮</option><option value="3">3 轮</option><option value="5">5 轮</option></select></div>
      <div className="input-group"><label htmlFor="batch-horizon">公共研究周期</label><select id="batch-horizon" value={cfg.horizon} onChange={(event) => cfg.setHorizon(event.target.value as "short" | "medium" | "long")}><option value="short">短期</option><option value="medium">中期</option><option value="long">长期</option></select></div>
      {cfg.validationError ? <div className="error-text">{cfg.validationError === "请输入股票代码" ? "请在上方填写公司列表" : cfg.validationError}</div> : null}
      {error ? <div className="error-text">{error}</div> : null}
      <div className="actions"><button type="button" className="secondary" onClick={handleValidate} disabled={checking || hasEmptyRow || activeRows.length === 0}>{checking ? "校验中…" : checked ? "重新校验" : "校验批次"}</button><button type="button" className="primary" onClick={handleStart} disabled={!canStart}>{starting ? "启动中…" : "开始批量分析"}</button></div>
      {checked ? <p className="batch-ready">已校验 {resolvedInputs.length} 家，公司配置将在启动后冻结。</p> : null}
    </div>
  );
}
