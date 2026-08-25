import { useState } from "react";
import type { RunViewEnvelopeDTO } from "../../api/contracts";
import { errorCategoryLabel } from "../../domain/errorCategory";
import type { AuditOpenHandler } from "./AuditCenter";

export interface FailedRunViewProps {
  envelope: RunViewEnvelopeDTO;
  onOpenAudit: AuditOpenHandler;
  /** Re-runs this failed analysis as a new run (POST /retry, 201). */
  onRetry: () => Promise<void>;
}

/**
 * Terminal failure surface: the run directory is intact and the event log is
 * browsable via the workflow map below, but no DecisionBrief exists. We show
 * the categorized failure reason instead of pretending a conclusion exists,
 * plus an inline retry that forks a fresh run from the same request.
 */
export function FailedRunView({ envelope, onOpenAudit, onRetry }: FailedRunViewProps): JSX.Element {
  const { run } = envelope.view;
  const category = run.error_category;
  const message = run.error_message;
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const handleRetry = (): void => {
    setRetrying(true);
    setRetryError(null);
    void onRetry().catch((reason: unknown) => {
      setRetryError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => setRetrying(false));
  };

  return (
    <section className="failed-run" data-ready="true">
      <header className="failed-run-head">
        <div>
          <span className="eyebrow">运行失败</span>
          <h2>{run.ticker}</h2>
        </div>
        <span className="brief-status status-failed">{errorCategoryLabel(category)}</span>
      </header>
      {message ? (
        <p className="failed-run-message">
          <code>{message}</code>
        </p>
      ) : (
        <p className="placeholder">该运行未留下错误详情，请查看服务端日志。</p>
      )}
      <p className="failed-run-hint">
        开始时间：{new Date(run.created_at).toLocaleString()}。完整事件记录保留在运行目录中，可通过工作流图回顾失败前的进度。
      </p>
      {retryError ? <p className="entry-error">{retryError}</p> : null}
      <div className="failed-run-actions">
        <button
          type="button"
          className="brief-audit-command"
          disabled={retrying}
          onClick={handleRetry}
        >
          {retrying ? "正在重试…" : "重试本次运行"}
        </button>
        <button
          type="button"
          className="brief-audit-command"
          onClick={(event) => onOpenAudit({ section: "overview" }, event.currentTarget)}
        >
          进入审计中心
        </button>
      </div>
    </section>
  );
}
