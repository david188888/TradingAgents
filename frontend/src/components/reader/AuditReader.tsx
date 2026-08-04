import { useArtifact } from "../../hooks/useArtifact";
import { SafeMarkdown } from "../shared/SafeMarkdown";

export interface AuditReaderProps {
  runId: string;
  completeReportArtifactId: string | null;
  onClose(): void;
}

/** A bounded reader keeps raw audit exports out of the primary scroll surface. */
export function AuditReader({ runId, completeReportArtifactId, onClose }: AuditReaderProps): JSX.Element {
  const { content, loading, error } = useArtifact(runId, completeReportArtifactId);
  return (
    <section className="audit-reader" aria-label="审计阅读器">
      <header className="audit-reader-head">
        <div>
          <span className="eyebrow">审计原文</span>
          <h2>完整报告</h2>
        </div>
        <button type="button" className="icon-command" aria-label="关闭审计阅读器" title="关闭" onClick={onClose}>×</button>
      </header>
      <div className="audit-reader-scroll">
        {completeReportArtifactId === null ? <p className="placeholder">没有可读取的完整报告 artifact。</p> : null}
        {loading ? <p className="placeholder">正在加载完整审计报告…</p> : null}
        {error ? <p className="entry-error">报告读取失败：{error}</p> : null}
        {content ? <SafeMarkdown content={content} /> : null}
      </div>
    </section>
  );
}
