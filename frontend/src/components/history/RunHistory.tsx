/**
 * F3 - Run history sidebar list.
 *
 * Renders runs from GET /api/runs grouped by outcome: active runs first
 * (created/running/cancel_requested), then completed runs, then the most
 * recent 3 failed runs, then cancelled/interrupted runs. Failed runs stay
 * on disk and remain clickable; only the rendered count is capped. Each item
 * shows the ticker, a colored status badge, and either the final signal or
 * the failure category in the sub line.
 */
import type { CSSProperties } from "react";
import type { RunStatusLiteral, RunSummaryDTO } from "../../api/contracts";
import { errorCategoryLabel } from "../../domain/errorCategory";
import { useWorkbenchSelection } from "../../state/WorkbenchStore";

interface StatusBadge {
  /** Extra class for completed (green) -> "ok"; empty for others. */
  className: string;
  /** CSS color token applied via inline style. */
  color: string;
  /** Chinese status label. */
  label: string;
  /** Whether to prefix a pulsing dot (running only). */
  dot: boolean;
}

const STATUS_BADGES: Record<RunStatusLiteral, StatusBadge> = {
  completed: { className: "ok", color: "var(--green)", label: "已完成", dot: false },
  failed: { className: "fail", color: "var(--red)", label: "失败", dot: false },
  cancelled: { className: "", color: "var(--muted)", label: "已取消", dot: false },
  interrupted: { className: "", color: "var(--gold)", label: "已中断", dot: false },
  queued: { className: "", color: "var(--muted)", label: "排队中", dot: false },
  running: { className: "", color: "var(--gold)", label: "运行中", dot: true },
  cancel_requested: { className: "", color: "var(--gold)", label: "取消中", dot: false },
  created: { className: "", color: "var(--muted)", label: "已创建", dot: false },
};

const ACTIVE_STATUSES = new Set<RunStatusLiteral>(["created", "queued", "running", "cancel_requested"]);
const FAILED_GROUP_LIMIT = 3;

export interface RunHistoryProps {
  runs: RunSummaryDTO[];
  loading: boolean;
  error: Error | null;
  /** Called after the user confirms deletion of a run. */
  onDeleteRun: (run_id: string) => void;
  /** Called after the user confirms clearing the whole history. */
  onClearHistory: () => void;
  /** True while a bulk clear is in flight so the button can be disabled. */
  clearing?: boolean;
}

export function RunHistory({
  runs,
  loading,
  error,
  onDeleteRun,
  onClearHistory,
  clearing = false,
}: RunHistoryProps): JSX.Element {
  const { run_id, selectRun } = useWorkbenchSelection();

  const handleDelete = (run: RunSummaryDTO): void => {
    if (window.confirm(`确定删除 ${run.ticker} 的运行记录吗？此操作不可恢复。`)) {
      onDeleteRun(run.run_id);
    }
  };

  const handleClear = (): void => {
    if (
      window.confirm(
        "确定清空全部历史记录吗？此操作不可恢复。运行中的分析会被保留。",
      )
    ) {
      onClearHistory();
    }
  };

  const active: RunSummaryDTO[] = [];
  const completed: RunSummaryDTO[] = [];
  const failed: RunSummaryDTO[] = [];
  const terminated: RunSummaryDTO[] = [];
  for (const run of runs) {
    if (ACTIVE_STATUSES.has(run.status)) active.push(run);
    else if (run.status === "completed") completed.push(run);
    else if (run.status === "failed") failed.push(run);
    else terminated.push(run);
  }

  const renderItem = (run: RunSummaryDTO): JSX.Element => {
    const badge = STATUS_BADGES[run.status];
    const badgeStyle: CSSProperties = { color: badge.color };
    const isActive = run.run_id === run_id;
    const itemClassName = `history-item${isActive ? " active" : ""}${
      run.status === "failed" ? " history-item-failed" : ""
    }`;
    const badgeClassName = `status-badge${badge.className ? ` ${badge.className}` : ""}`;
    const sub =
      run.status === "failed"
        ? errorCategoryLabel(run.error_category)
        : run.final_signal
          ? run.final_signal
          : null;
    return (
      <li
        key={run.run_id}
        className={itemClassName}
        onClick={() => selectRun(run.run_id)}
      >
        <div className="history-top">
          <strong>{run.ticker}</strong>
          <div className="history-actions">
            <span className={badgeClassName} style={badgeStyle}>
              {badge.dot ? `● ${badge.label}` : badge.label}
            </span>
            <button
              className="history-delete"
              aria-label={`删除 ${run.ticker} 的运行记录`}
              onClick={(e) => {
                e.stopPropagation();
                handleDelete(run);
              }}
            >
              ×
            </button>
          </div>
        </div>
        <div className="history-sub">
          <span>{new Date(run.created_at).toLocaleString()}</span>
          {sub ? <span> · {sub}</span> : null}
        </div>
      </li>
    );
  };

  const groups: Array<{ title: string; items: RunSummaryDTO[]; capped?: boolean }> = [];
  if (active.length) groups.push({ title: "进行中", items: active });
  if (completed.length) groups.push({ title: "已完成", items: completed });
  if (failed.length) {
    groups.push({
      title: `失败（最近 ${Math.min(failed.length, FAILED_GROUP_LIMIT)} 个）`,
      items: failed.slice(0, FAILED_GROUP_LIMIT),
      capped: failed.length > FAILED_GROUP_LIMIT,
    });
  }
  if (terminated.length) groups.push({ title: "已终止", items: terminated });

  return (
    <section className="history">
      <div className="section-title">
        <h2>最近运行</h2>
        {runs.length > 0 ? (
          <button
            type="button"
            className="history-clear"
            onClick={handleClear}
            disabled={clearing}
          >
            {clearing ? "清空中…" : "清空历史"}
          </button>
        ) : null}
      </div>
      {error ? (
        <p className="placeholder">加载失败：{error.message}</p>
      ) : loading && runs.length === 0 ? (
        <p className="placeholder">加载中…</p>
      ) : runs.length === 0 ? (
        <p className="placeholder">暂无运行记录</p>
      ) : (
        groups.map((group) => (
          <div className="history-group" key={group.title}>
            <div className="history-group-title">{group.title}</div>
            <ul>{group.items.map(renderItem)}</ul>
            {group.capped ? (
              <p className="history-group-note">更早的失败记录已折叠，文件仍保留</p>
            ) : null}
          </div>
        ))
      )}
    </section>
  );
}
