import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AuditArtifactSummaryDTO,
  AuditSelectionDTO,
  AuditSummaryDTO,
} from "../../api/contracts";
import { useAuditDetail, useAuditSummary } from "../../hooks/useAudit";
import { AuditDetailPanel } from "./AuditDetailPanel";

export type AuditSectionId =
  | "overview"
  | "roles"
  | "capabilities"
  | "tools"
  | "artifacts"
  | "prompt_config";

export interface AuditEntryContext {
  section: AuditSectionId;
  itemId?: string;
  stageId?: string;
}

export type AuditOpenHandler = (
  context: AuditEntryContext,
  trigger: HTMLElement,
) => void;

export interface AuditCenterProps {
  runId: string;
  open: boolean;
  context: AuditEntryContext | null;
  returnFocus: HTMLElement | null;
  onClose(): void;
}

const SECTION_LABELS: Record<AuditSectionId, string> = {
  overview: "概览",
  roles: "角色",
  capabilities: "能力",
  tools: "工具",
  artifacts: "产物",
  prompt_config: "Prompt 与配置",
};

const FOCUSABLE = [
  "button:not([disabled])",
  "a[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function useNarrowAudit(): boolean {
  const [narrow, setNarrow] = useState(() => (
    typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 1399px)").matches
      : false
  ));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 1399px)");
    const change = (event: MediaQueryListEvent): void => setNarrow(event.matches);
    setNarrow(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  return narrow;
}

function statusLabel(value: string): string {
  return {
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
    running: "执行中",
    not_started: "未开始",
    not_reached: "未执行",
    unknown: "未记录",
    ready: "可用",
    partial: "部分可用",
    legacy: "历史运行",
    unavailable: "不可用",
    not_recorded: "未记录",
    degraded: "已降级",
    committed: "已提交",
  }[value] ?? value;
}

function restoreFocus(target: HTMLElement | null): void {
  if (target?.isConnected) {
    target.focus({ preventScroll: true });
    return;
  }
  const fallback = document.querySelector<HTMLElement>(".reader-surface h2, main");
  if (fallback !== null) {
    if (!fallback.hasAttribute("tabindex")) fallback.setAttribute("tabindex", "-1");
    fallback.focus({ preventScroll: true });
  }
}

export function AuditCenter({
  runId,
  open,
  context,
  returnFocus,
  onClose,
}: AuditCenterProps): JSX.Element | null {
  const [section, setSection] = useState<AuditSectionId>(context?.section ?? "overview");
  const [selection, setSelection] = useState<AuditSelectionDTO | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const browserRef = useRef<HTMLDivElement>(null);
  const detailTriggerRef = useRef<HTMLElement | null>(null);
  const narrow = useNarrowAudit();
  const summaryState = useAuditSummary(runId, open);
  const sourceSequence = summaryState.summary?.source_sequence ?? null;
  const detailState = useAuditDetail(
    runId,
    sourceSequence,
    selection,
    summaryState.refresh,
  );

  useEffect(() => {
    if (!open) return;
    setSection(context?.section ?? "overview");
    setSelection(null);
    detailTriggerRef.current = null;
    window.setTimeout(() => {
      if (detailTriggerRef.current === null) {
        closeRef.current?.focus({ preventScroll: true });
      }
    }, 0);
  }, [context, open, runId]);

  useEffect(() => {
    const browser = browserRef.current as (HTMLDivElement & { inert: boolean }) | null;
    if (browser !== null) browser.inert = narrow && selection !== null;
  }, [narrow, selection]);

  const closeDetail = useCallback((): void => {
    setSelection(null);
    const trigger = detailTriggerRef.current;
    window.setTimeout(() => trigger?.isConnected && trigger.focus({ preventScroll: true }), 0);
  }, []);

  const closeCenter = useCallback((): void => {
    setSelection(null);
    onClose();
    restoreFocus(returnFocus);
  }, [onClose, returnFocus]);

  useEffect(() => {
    if (!open) return;
    const onEscape = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      if (selection !== null) closeDetail();
      else closeCenter();
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [closeCenter, closeDetail, open, selection]);

  const trapOuterFocus = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== "Tab" || (narrow && selection !== null)) return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
    ).filter((item) => !item.closest('[aria-hidden="true"]'));
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

  const selectDetail = (next: AuditSelectionDTO, trigger: HTMLElement): void => {
    detailTriggerRef.current = trigger;
    setSelection(next);
  };

  if (!open) return null;

  const summary = summaryState.summary;
  const unavailable = summary?.availability === "unavailable";

  return (
    <div className="audit-center-backdrop">
      <div
        ref={dialogRef}
        className="audit-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-center-title"
        aria-label="审计中心"
        onKeyDown={trapOuterFocus}
      >
        <header className="audit-center-head">
          <div className="audit-center-identity">
            <span className="audit-center-seal" aria-hidden="true">AC</span>
            <div>
              <span className="eyebrow">Audit Center · Terminal record</span>
              <h2 id="audit-center-title">审计中心</h2>
            </div>
          </div>
          <div className="audit-center-runline">
            <strong>{summary?.run.ticker ?? "读取中"}</strong>
            <span>{summary ? statusLabel(summary.run.status) : "等待摘要"}</span>
            <span>{summary ? `seq ${summary.source_sequence}` : "—"}</span>
            {summaryState.refreshing ? <span className="audit-refreshing">正在校验…</span> : null}
          </div>
          <div className="audit-center-actions">
            <button type="button" onClick={summaryState.refresh} disabled={summaryState.loading}>
              刷新摘要
            </button>
            <button
              ref={closeRef}
              type="button"
              className="audit-center-close"
              aria-label="关闭审计中心"
              onClick={closeCenter}
            >
              ×
            </button>
          </div>
        </header>

        <div
          ref={browserRef}
          data-testid="audit-browser"
          className="audit-center-browser"
          aria-hidden={narrow && selection !== null ? true : undefined}
        >
          <nav className="audit-center-nav" aria-label="审计分区">
            <span className="audit-nav-label">Index / 目录</span>
            {(Object.keys(SECTION_LABELS) as AuditSectionId[]).map((id, index) => {
              const count = summary?.sections.find((item) => item.section_id === id)?.item_count;
              return (
                <button
                  type="button"
                  key={id}
                  className={section === id ? "active" : ""}
                  aria-current={section === id ? "page" : undefined}
                  onClick={() => {
                    setSection(id);
                    setSelection(null);
                  }}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  {SECTION_LABELS[id]}
                  <em>{count ?? "—"}</em>
                </button>
              );
            })}
            <div className="audit-nav-foot">
              <span>只读 · 本机</span>
              <span>Raw 按需加载</span>
            </div>
          </nav>

          <main className="audit-center-summary">
            <header className="audit-summary-head">
              <div>
                <span className="eyebrow">Section {SECTION_LABELS[section]}</span>
                <h3>{SECTION_LABELS[section]}</h3>
              </div>
              {summary ? (
                <span className={`audit-availability audit-availability--${summary.availability}`}>
                  {statusLabel(summary.availability)}
                </span>
              ) : null}
            </header>

            {summaryState.loading ? <AuditSummarySkeleton /> : null}
            {unavailable || (summaryState.error !== null && summary === null) ? (
              <div className="audit-summary-state">
                <span aria-hidden="true">!</span>
                <h4>审计摘要当前不可用</h4>
                <p>研究正文保持不变；系统不会自动读取 raw 内容。</p>
                <button type="button" onClick={summaryState.refresh}>重新读取审计摘要</button>
              </div>
            ) : null}
            {summary !== null && !unavailable ? (
              <AuditSection
                section={section}
                summary={summary}
                context={context}
                onSelect={selectDetail}
              />
            ) : null}
          </main>
        </div>

        {selection !== null ? (
          <AuditDetailPanel
            narrow={narrow}
            detail={detailState.detail}
            loading={detailState.loading}
            error={detailState.error}
            onBack={closeDetail}
            onRetry={detailState.retry}
          />
        ) : (
          <aside className="audit-detail-empty" aria-label="审计详情">
            <span aria-hidden="true">↗</span>
            <h3>选择一项记录</h3>
            <p>摘要不会自动读取 Prompt、配置值或 artifact 内容。</p>
          </aside>
        )}
      </div>
    </div>
  );
}

function AuditSummarySkeleton(): JSX.Element {
  return (
    <div className="audit-summary-skeleton" aria-busy="true" aria-label="正在读取审计摘要">
      <span /><span /><span /><span />
    </div>
  );
}

function AuditSection({
  section,
  summary,
  context,
  onSelect,
}: {
  section: AuditSectionId;
  summary: AuditSummaryDTO;
  context: AuditEntryContext | null;
  onSelect(selection: AuditSelectionDTO, trigger: HTMLElement): void;
}): JSX.Element {
  if (section === "overview") {
    return (
      <div className="audit-overview">
        <button
          type="button"
          className="audit-run-card"
          onClick={(event) => onSelect({ kind: "run", id: "run" }, event.currentTarget)}
        >
          <span className="audit-card-index">RUN / {summary.run.status.toUpperCase()}</span>
          <strong>{summary.run.ticker}</strong>
          <span>{summary.run.mode ?? "legacy"} · {summary.run.horizon ?? "未记录周期"}</span>
        </button>
        <div className="audit-count-grid">
          <Count label="角色" value={summary.counts.roles} />
          <Count label="轮次" value={summary.counts.turns} />
          <Count label="工具" value={summary.counts.tool_calls} />
          <Count label="产物" value={summary.counts.artifacts} />
        </div>
        <section className="audit-stage-ledger">
          <h4>阶段导航</h4>
          {summary.stage_navigation.map((stage, index) => (
            <article
              key={stage.stage_id}
              data-highlighted={context?.stageId === stage.stage_id ? "true" : undefined}
            >
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div><strong>{stage.label}</strong><small>{statusLabel(stage.availability)}</small></div>
              <em>{statusLabel(stage.status)}</em>
            </article>
          ))}
        </section>
      </div>
    );
  }
  if (section === "roles") {
    return <AuditList empty="没有记录角色执行事实。">{summary.roles.map((item) => (
      <AuditItemButton
        key={item.item_id}
        title={item.label}
        meta={`${statusLabel(item.status)} · ${item.turn_count} 轮 · ${item.model_call_count} 次模型调用`}
        highlighted={context?.itemId === item.item_id}
        onClick={(event) => onSelect({ kind: "role", id: item.item_id }, event.currentTarget)}
      />
    ))}</AuditList>;
  }
  if (section === "capabilities") {
    return <AuditList empty="此运行没有记录能力降级。">{summary.capabilities.map((item) => (
      <AuditItemButton
        key={item.item_id}
        title={item.label}
        meta={`${statusLabel(item.status)} · ${item.reason_codes.join("、") || "无原因分类"}`}
        highlighted={context?.itemId === item.item_id}
        onClick={(event) => onSelect({ kind: "capability", id: item.item_id }, event.currentTarget)}
      />
    ))}</AuditList>;
  }
  if (section === "tools") {
    return <AuditList empty="此运行没有记录工具调用。">{summary.tools.map((item) => (
      <AuditItemButton
        key={item.item_id}
        title={item.tool_name}
        meta={`${statusLabel(item.status)} · ${item.execution_count} 次执行 · ${item.cache_status}`}
        highlighted={context?.itemId === item.item_id}
        onClick={(event) => onSelect({ kind: "tool", id: item.item_id }, event.currentTarget)}
      />
    ))}</AuditList>;
  }
  if (section === "artifacts") {
    return <AuditList empty="此运行没有持久化产物。">{summary.artifacts.map((item) => (
      <ArtifactButton key={item.item_id} item={item} onSelect={onSelect} highlighted={context?.itemId === item.item_id} />
    ))}</AuditList>;
  }
  return (
    <div className="audit-prompt-config">
      <AuditSubsection title="Prompt snapshots" count={summary.prompts.length}>
        {summary.prompts.map((item) => (
          <AuditItemButton
            key={item.item_id}
            title={item.label}
            meta={`${item.actor_id ?? "未知角色"} · ${item.redaction_status}`}
            highlighted={context?.itemId === item.item_id}
            onClick={(event) => onSelect({ kind: "prompt", id: item.item_id }, event.currentTarget)}
          />
        ))}
      </AuditSubsection>
      <AuditSubsection title="Effective config" count={summary.configs.length}>
        {summary.configs.map((item) => (
          <AuditItemButton
            key={item.item_id}
            title={item.label}
            meta={`${item.actor_id ?? "运行级"} · ${item.redaction_status}`}
            highlighted={context?.itemId === item.item_id}
            onClick={(event) => onSelect({ kind: "config", id: item.item_id }, event.currentTarget)}
          />
        ))}
      </AuditSubsection>
    </div>
  );
}

function Count({ label, value }: { label: string; value: number }): JSX.Element {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}

function AuditList({ children, empty }: { children: React.ReactNode; empty: string }): JSX.Element {
  const items = useMemo(() => Array.isArray(children) ? children : [children], [children]);
  return <div className="audit-item-list">{items.length && items[0] ? items : <p className="placeholder">{empty}</p>}</div>;
}

function AuditItemButton({
  title,
  meta,
  highlighted,
  onClick,
}: {
  title: string;
  meta: string;
  highlighted: boolean;
  onClick: React.MouseEventHandler<HTMLButtonElement>;
}): JSX.Element {
  return (
    <button
      type="button"
      className="audit-item-button"
      data-highlighted={highlighted ? "true" : undefined}
      onClick={onClick}
    >
      <span className="audit-item-rule" aria-hidden="true" />
      <span><strong>{title}</strong><small>{meta}</small></span>
      <em aria-hidden="true">→</em>
    </button>
  );
}

function ArtifactButton({
  item,
  onSelect,
  highlighted,
}: {
  item: AuditArtifactSummaryDTO;
  onSelect(selection: AuditSelectionDTO, trigger: HTMLElement): void;
  highlighted: boolean;
}): JSX.Element {
  return (
    <AuditItemButton
      title={item.is_report ? `已发布报告 · ${item.label}` : item.label}
      meta={`${item.media_type} · ${item.byte_size} B · ${item.content_exposure}`}
      highlighted={highlighted}
      onClick={(event) => onSelect(
        { kind: item.is_report ? "report" : "artifact", id: item.item_id },
        event.currentTarget,
      )}
    />
  );
}

function AuditSubsection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <section>
      <header><h4>{title}</h4><span>{count}</span></header>
      {count ? children : <p className="placeholder">历史运行未记录。</p>}
    </section>
  );
}
