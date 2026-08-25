import { useState } from "react";

export interface ResumableRunBarProps {
  /** Continues this interrupted run from its durable checkpoint (202). */
  onResume: () => Promise<void>;
}

/**
 * Inline banner for a terminal interrupted run: the durable checkpoint is
 * still on disk, so the same run can pick up where it stopped. Resuming
 * keeps the run_id; the workbench re-selects the run so the live stream
 * and projection refetch restart.
 */
export function ResumableRunBar({ onResume }: ResumableRunBarProps): JSX.Element {
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

  const handleResume = (): void => {
    setResuming(true);
    setResumeError(null);
    void onResume().catch((reason: unknown) => {
      setResumeError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => setResuming(false));
  };

  return (
    <section className="resumable-run-bar" data-ready="true">
      <div className="resumable-run-copy">
        <span className="eyebrow">运行已中断</span>
        <p>
          上次执行在中途停止。已完成的阶段保留在检查点中，恢复后将从断点继续，不会重复已消耗的分析步骤。
        </p>
        {resumeError ? <p className="entry-error">{resumeError}</p> : null}
      </div>
      <button
        type="button"
        className="brief-audit-command"
        disabled={resuming}
        onClick={handleResume}
      >
        {resuming ? "正在恢复…" : "恢复分析"}
      </button>
    </section>
  );
}
