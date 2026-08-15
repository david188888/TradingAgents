import { useEffect, useRef } from "react";
import { ApiError } from "../../api/client";
import type { CompanionDTO, CompanionSelectionDTO } from "../../api/contracts";

export type CompanionPanelMode = "temporary" | "pinned" | "drawer";

export interface CompanionPanelProps {
  mode: CompanionPanelMode;
  selection: CompanionSelectionDTO;
  companion: CompanionDTO | null;
  loading: boolean;
  error: ApiError | Error | null;
  onClose: () => void;
  onPinToggle: () => void;
  onRetry: () => void;
}

const KIND_LABELS: Record<CompanionSelectionDTO["kind"], string> = {
  role: "分析视角",
  claim: "研究论点",
  evidence: "证据来源",
  risk: "失效风险",
};

const FOCUSABLE = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function CompanionPanel({
  mode,
  selection,
  companion,
  loading,
  error,
  onClose,
  onPinToggle,
  onRetry,
}: CompanionPanelProps): JSX.Element {
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (mode === "drawer") {
      closeRef.current?.focus({ preventScroll: true });
    }
  }, [mode]);

  const trapDrawerFocus = (event: React.KeyboardEvent<HTMLElement>): void => {
    if (mode !== "drawer" || event.key !== "Tab") return;
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

  const unavailable = error instanceof ApiError
    && error.status === 404
    && error.code === "companion_not_found";

  return (
    <aside
      ref={panelRef}
      className={`companion-panel companion-panel--${mode}`}
      data-mode={mode}
      role={mode === "drawer" ? "dialog" : "complementary"}
      aria-modal={mode === "drawer" ? true : undefined}
      aria-labelledby="companion-panel-title"
      aria-label="研究伴读"
      onKeyDown={trapDrawerFocus}
    >
      <header className="companion-panel-head">
        <div>
          <span className="eyebrow">Companion · {KIND_LABELS[selection.kind]}</span>
          <h3 id="companion-panel-title">研究伴读</h3>
        </div>
        <div className="companion-panel-actions">
          {mode !== "drawer" ? (
            <button
              type="button"
              className="companion-icon-button"
              aria-label={mode === "pinned" ? "取消固定" : "固定伴读栏"}
              aria-pressed={mode === "pinned"}
              onClick={onPinToggle}
            >
              <span aria-hidden="true">{mode === "pinned" ? "◇" : "◆"}</span>
            </button>
          ) : null}
          <button
            ref={closeRef}
            type="button"
            className="companion-icon-button"
            aria-label="关闭伴读栏"
            onClick={onClose}
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </header>

      <div className="companion-panel-body" aria-live="polite">
        {loading ? (
          <div className="companion-loading" aria-busy="true" aria-label="正在加载伴读内容">
            <span />
            <span />
            <span />
          </div>
        ) : error ? (
          <div className="companion-state companion-state--error">
            <strong>{unavailable ? "该伴读内容当前不可用" : "暂时无法读取伴读内容"}</strong>
            {!unavailable ? <p>暂时无法读取公开伴读内容，请稍后重试</p> : null}
            {!unavailable ? (
              <button type="button" className="companion-retry" onClick={onRetry}>
                重试
              </button>
            ) : null}
          </div>
        ) : companion ? (
          <div className="companion-content">
            <section className="companion-summary">
              <span className="companion-section-label">摘要</span>
              <p>{companion.summary}</p>
            </section>
            <section>
              <span className="companion-section-label">实际覆盖</span>
              <ul className="companion-coverage">
                {companion.actual_coverage.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
            </section>
            <section>
              <span className="companion-section-label">对结论的影响</span>
              <p>{companion.conclusion_impact}</p>
            </section>
            <section className="companion-next-step">
              <span className="companion-section-label">下一验证</span>
              <p>{companion.next_validation}</p>
            </section>
          </div>
        ) : (
          <div className="companion-state">
            <strong>暂无可展示的伴读内容</strong>
          </div>
        )}
      </div>
    </aside>
  );
}
