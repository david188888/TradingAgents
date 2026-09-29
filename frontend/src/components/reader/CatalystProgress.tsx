/**
 * T30 — the four bounded stages, and the state a run is in.
 *
 * The percentage is the point of this component. A progress bar that cannot be
 * measured must not display a number: a fabricated "90%" tells a reader the
 * run is nearly done when the server has committed nothing of the sort. So
 * `percent` is `null` unless all four stages reported real completed/total
 * counts (`catalystStageProgress`), and this component renders stage *status*
 * in that case — a reader can always say which stage they are in, and only
 * sees a number when the number means something.
 *
 * Uncommitted streaming candidates are shown as still in progress, never folded
 * into a conclusion: a candidate the server has not committed is not a result.
 */
import type {
  CatalystScreenState,
  CatalystStageProgress,
} from "../../domain/catalystWorkbench";

export interface CatalystProgressProps {
  progress: CatalystStageProgress;
  state: CatalystScreenState;
  /** Wired to the layout's existing cancel/retry/resume handlers. */
  onCancel?: () => void;
  onRetry?: () => void;
  onResume?: () => void;
  onViewProcess?: () => void;
  onNewRun?: () => void;
  onOpenAudit?: () => void;
}

const ACTION_LABELS: Record<CatalystScreenState["actions"][number], string> = {
  view_process: "查看研究过程",
  view_gaps: "查看关键缺口",
  view_sources: "查看来源状态",
  retry: "重试",
  resume: "恢复运行",
  audit: "打开审计中心",
  new_run: "发起新研究",
  retry_read: "重新读取",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "等待中",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
};

export function CatalystProgress({
  progress,
  state,
  onCancel,
  onRetry,
  onResume,
  onViewProcess,
  onNewRun,
  onOpenAudit,
}: CatalystProgressProps): JSX.Element {
  const handlers: Partial<Record<CatalystScreenState["actions"][number], (() => void) | undefined>> = {
    view_process: onViewProcess,
    view_gaps: onViewSourcesFallback(onViewProcess),
    view_sources: onViewSourcesFallback(onViewProcess),
    retry: onRetry,
    resume: onResume,
    audit: onOpenAudit,
    new_run: onNewRun,
    retry_read: onRetry,
  };

  return (
    <section className="catalyst-progress" data-state={state.id} aria-live="polite">
      <header className="catalyst-progress-head">
        <div>
          <span className="eyebrow">研究进度</span>
          <h2>{state.title}</h2>
        </div>
        {/*
          The number is rendered only when it is measured. `percent === null`
          means at least one stage did not report real completed/total counts,
          and in that case the page shows stage status instead of a guess.
        */}
        {progress.percent === null ? (
          <span className="catalyst-progress-unmeasured" data-testid="catalyst-progress-no-percent">
            暂无进度百分比
          </span>
        ) : (
          <span className="catalyst-progress-percent" data-testid="catalyst-progress-percent">
            {progress.percent}%
          </span>
        )}
      </header>

      <p className="catalyst-progress-body">{state.body}</p>

      <ol className="catalyst-stages">
        {progress.stages.map((stage) => (
          <li key={stage.id} className="catalyst-stage" data-status={stage.status}>
            <span className="catalyst-stage-name">{stage.label}</span>
            <span className="catalyst-stage-status">
              {STATUS_LABELS[stage.status] ?? stage.status}
            </span>
            {stage.duration_ms !== null ? (
              <span className="catalyst-stage-duration">{(stage.duration_ms / 1000).toFixed(1)} 秒</span>
            ) : null}
          </li>
        ))}
      </ol>

      {progress.uncommitted_candidates > 0 ? (
        <p className="catalyst-candidates" data-testid="catalyst-uncommitted-candidates">
          还有 {progress.uncommitted_candidates} 条未提交的候选结论。候选不是结论：本次运行尚未提交它们，不计入判断。
        </p>
      ) : null}

      <div className="catalyst-progress-actions">
        {state.actions.map((action) => {
          const handler = handlers[action];
          if (handler === undefined && action !== "view_gaps" && action !== "view_sources") return null;
          return (
            <button
              key={action}
              type="button"
              className={action === "new_run" || action === "resume" ? "primary" : undefined}
              disabled={handler === undefined}
              onClick={handler}
            >
              {ACTION_LABELS[action]}
            </button>
          );
        })}
        {/*
          Cancel is available while the run is still in flight — queued or
          running — which is what design 4.5's "取消" action means. It is also
          rendered for a cancelled/interrupted run, because the run-view
          endpoint's own cancel is idempotent and the layout re-reads the run
          afterwards; hiding it there would strand a user whose cancel has not
          yet been reflected in the projection. A terminal failure or a
          blocked result has no cancel: nothing is running to stop.
        */}
        {state.id === "queued" || state.id === "running" || state.id === "cancelled_or_interrupted" ? (
          <button type="button" onClick={onCancel} disabled={onCancel === undefined}>
            取消
          </button>
        ) : null}
      </div>
    </section>
  );
}

/**
 * `view_gaps` and `view_sources` have no separate handler here; both are
 * "look at the evidence" and route to the evidence tab, which the layout owns.
 * Returning `onViewProcess` keeps the button enabled and honest rather than
 * disabling an action the state matrix promises.
 */
function onViewSourcesFallback(onViewProcess: (() => void) | undefined): (() => void) | undefined {
  return onViewProcess;
}
