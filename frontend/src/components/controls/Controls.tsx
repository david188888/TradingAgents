import { ModelConfiguration } from "./ModelConfiguration";
/** V9 research controls; selection and run state live in their existing hooks. */
import { useState } from "react";
import { BatchControls } from "./BatchControls";
import { requestCompletionNotificationPermission } from "../../hooks/useCompletionNotifications";
import { useConfig } from "../../hooks/useConfig";
import { useWorkbenchSelection, useWorkbenchStream } from "../../state/WorkbenchStore";
import { createRun, cancelRun } from "../../api/client";

export interface ControlsProps {
  /** Called after a new run is successfully created so the history list refreshes. */
  refreshHistory?: () => Promise<void>;
}

export function Controls({ refreshHistory }: ControlsProps = {}): JSX.Element {
  const cfg = useConfig();
  const stream = useWorkbenchStream();
  const { run_id, selectRun } = useWorkbenchSelection();
  const [apiError, setApiError] = useState<string | null>(null);
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
    setStarting(true);
    void requestCompletionNotificationPermission();
    createRun(req)
      .then((snap) => {
        selectRun(snap.run_id);
        refreshHistory?.();
      })
      .catch((e: unknown) => {
        setApiError(e instanceof Error ? e.message : String(e));
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
        <section className="sidebar-section research-input" aria-labelledby="ctrl-input-heading">
          <div className="section-title"><h2 id="ctrl-input-heading">研究输入</h2></div>

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

          <p className="qr-meta">使用当前可得资料，研究经营、估值、事件与市场风险；报告保留资料的实际时间。</p>

          <div className="input-group">
            <label htmlFor="ctrl-question">补充关注点（可选）</label>
            <textarea id="ctrl-question" value={cfg.research_question} onChange={e => cfg.setResearchQuestion(e.target.value)} maxLength={800} placeholder="独立研究完成后，补充回应你关心的角度" rows={2} />
            <small>基础研究完成后补充回应，不改写综合判断。</small>
          </div>

        </section>
      <ModelConfiguration cfg={cfg} prefix="ctrl" />

      {cfg.validationError !== null && cfg.validationError !== cfg.configurationError && (
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
            aria-describedby={cfg.configurationError ? "ctrl-configuration-message" : undefined}
          >
            {starting ? "启动中…" : "开始分析"}
          </button>
        )}
      </div>

      </div>
    </>
  );
}
