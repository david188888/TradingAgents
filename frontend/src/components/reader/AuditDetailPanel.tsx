import { useEffect, useRef } from "react";
import { ApiError } from "../../api/client";
import type { AuditDetailDTO } from "../../api/contracts";
import { SafeMarkdown } from "../shared/SafeMarkdown";

export interface AuditDetailPanelProps {
  narrow: boolean;
  detail: AuditDetailDTO | null;
  loading: boolean;
  error: ApiError | Error | null;
  onBack(): void;
  onRetry(): void;
}

const FOCUSABLE = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function formatBytes(value: number | null): string | null {
  if (value === null) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function unavailableLabel(reason: AuditDetailDTO["reason_code"]): string {
  return {
    not_recorded: "该运行没有记录此项详情",
    content_sensitive: "该内容因敏感度限制不可展示",
    detail_not_available: "该详情当前不可用",
    unsupported_artifact: "该类型仅支持下载",
    content_too_large: "内容过大，请使用下载入口",
  }[reason ?? "detail_not_available"];
}

export function AuditDetailPanel({
  narrow,
  detail,
  loading,
  error,
  onBack,
  onRetry,
}: AuditDetailPanelProps): JSX.Element {
  const panelRef = useRef<HTMLElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (narrow) backRef.current?.focus({ preventScroll: true });
  }, [narrow]);

  const trapFocus = (event: React.KeyboardEvent<HTMLElement>): void => {
    if (!narrow || event.key !== "Tab") return;
    const focusable = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  };

  const notFound = error instanceof ApiError
    && error.status === 404
    && error.code === "audit_item_not_found";
  const size = formatBytes(detail?.content.byte_size ?? null);

  return (
    <aside
      ref={panelRef}
      className={`audit-detail-panel${narrow ? " audit-detail-panel--overlay" : ""}`}
      role={narrow ? "dialog" : "region"}
      aria-modal={narrow ? true : undefined}
      aria-label="审计详情"
      onKeyDown={trapFocus}
    >
      <header className="audit-detail-head">
        <div>
          <span className="eyebrow">Single record · 按需读取</span>
          <h3>{detail?.title ?? "审计详情"}</h3>
        </div>
        <button
          ref={backRef}
          type="button"
          className="audit-detail-back"
          aria-label="返回审计列表"
          onClick={onBack}
        >
          <span aria-hidden="true">←</span> 返回
        </button>
      </header>

      <div className="audit-detail-scroll" aria-live="polite">
        {loading ? (
          <div className="audit-detail-loading" aria-busy="true" aria-label="正在读取审计详情">
            <span /><span /><span /><span />
          </div>
        ) : error ? (
          <div className="audit-detail-state audit-detail-state--error">
            <span className="audit-detail-state-mark" aria-hidden="true">!</span>
            <h4>{notFound ? "该审计项当前不可用" : "暂时无法读取审计详情"}</h4>
            <p>Reader 与其他审计摘要保持不变。</p>
            {!notFound ? (
              <button type="button" onClick={onRetry}>重试当前详情</button>
            ) : null}
          </div>
        ) : detail ? (
          <>
            <div className="audit-detail-meta">
              <span>{detail.selection.kind}</span>
              <span>seq {detail.source_sequence}</span>
              {size ? <span>{size}</span> : null}
              <span>{detail.content.redaction_status}</span>
            </div>

            {detail.availability === "unavailable" ? (
              <div className="audit-detail-state">
                <span className="audit-detail-state-mark" aria-hidden="true">—</span>
                <h4>{unavailableLabel(detail.reason_code)}</h4>
                <p>系统不会回退到任意 raw artifact。</p>
              </div>
            ) : null}

            {detail.facts.length ? (
              <dl className="audit-fact-grid">
                {detail.facts.map((fact) => (
                  <div key={fact.label}>
                    <dt>{fact.label}</dt>
                    <dd>{fact.value === null ? "未记录" : String(fact.value)}</dd>
                  </div>
                ))}
              </dl>
            ) : null}

            {detail.content.mode === "inline" && detail.content.text !== null ? (
              <section className="audit-inline-content">
                <span className="audit-section-kicker">已脱敏内容</span>
                <SafeMarkdown
                  content={detail.content.text}
                  mode={detail.content.media_type === "application/json" ? "data" : "prose"}
                />
              </section>
            ) : null}

            {detail.content.mode === "download" && detail.content.download_url !== null ? (
              <section className="audit-download-card">
                <span aria-hidden="true">⇩</span>
                <div>
                  <h4>{unavailableLabel(detail.reason_code)}</h4>
                  <p>{detail.content.media_type ?? "未知媒体类型"}{size ? ` · ${size}` : ""}</p>
                </div>
                <a href={detail.content.download_url} download>下载原始文件</a>
              </section>
            ) : null}
          </>
        ) : (
          <div className="audit-detail-state">
            <span className="audit-detail-state-mark" aria-hidden="true">↗</span>
            <h4>选择一项摘要查看详情</h4>
            <p>只有明确选择后才会读取单项内容。</p>
          </div>
        )}
      </div>
    </aside>
  );
}
