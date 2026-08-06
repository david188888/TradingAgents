import type { RunViewEnvelopeDTO } from "../../api/contracts";
import { errorCategoryLabel } from "../../domain/errorCategory";

export interface FailedRunViewProps {
  envelope: RunViewEnvelopeDTO;
}

/**
 * Terminal failure surface: the run directory is intact and the event log is
 * browsable via the workflow map below, but no DecisionBrief exists. We show
 * the categorized failure reason instead of pretending a conclusion exists.
 */
export function FailedRunView({ envelope }: FailedRunViewProps): JSX.Element {
  const { run } = envelope.view;
  const category = run.error_category;
  const message = run.error_message;

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
    </section>
  );
}
