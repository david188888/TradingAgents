/**
 * T31 — a legacy run, read in layers.
 *
 * A run that predates `catalyst_v1` has no research priority and this component
 * does not produce one. It shows what the old record actually had: the old
 * rating, the old report, and the role process behind it. The rating is
 * labelled as a rating, in the old vocabulary, and `legacyLayerView` returns
 * `priority: null` by construction — there is no code path here that could map
 * it onto the four new categories.
 *
 * The three layers are progressive on purpose. The measured problem this
 * replaces was a first screen carrying 8,399 characters; an old record read all
 * at once is how that happened. `summary` is what the reader opens, and the
 * rest is one click away.
 */
import {
  LEGACY_LAYER_COPY,
  LEGACY_LAYER_IDS,
  type LegacyLayerId,
  legacyLayerView,
} from "../../domain/catalystWorkbench";

export interface LegacyReaderProps {
  /** The run's own ids, for the header. */
  runId: string;
  ticker: string;
  /** The old conclusion, if the record had one. Rendered as-is. */
  summaryText?: string | null;
  /** The old `research_rating`. A rating of the old flow, never a priority. */
  rating?: string | null;
  /** Whether the full report exists in this record. */
  hasReport?: boolean;
  /** Whether role outputs are recorded for this run. */
  hasProcess?: boolean;
  layer: LegacyLayerId;
  onLayerChange: (layer: LegacyLayerId) => void;
  onOpenAudit: () => void;
}

export function LegacyReader({
  runId,
  ticker,
  summaryText = null,
  rating = null,
  hasReport = true,
  hasProcess = true,
  layer,
  onLayerChange,
  onOpenAudit,
}: LegacyReaderProps): JSX.Element {
  const view = legacyLayerView(layer, {
    research_rating: rating,
    has_report: hasReport,
    has_process: hasProcess,
  });

  return (
    <section className="legacy-reader" data-run={runId} data-layer={view.id}>
      <header className="legacy-reader-head">
        <div>
          <span className="eyebrow">历史记录 · 旧版研究流程</span>
          <h2>{ticker}</h2>
        </div>
        {/*
          A version label, so the reader knows which contract produced the text
          in front of them. This is a legacy run: it has no research priority
          and none is derived from the old rating.
        */}
        <span className="legacy-version-tag">旧版记录</span>
      </header>

      <p className="legacy-no-priority">
        这次运行使用旧版研究流程，没有研究优先级。系统不会从旧文字反推优先级，也不会在后台重算。
      </p>

      <div className="legacy-layers" role="tablist" aria-label="历史记录分层">
        {LEGACY_LAYER_IDS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`legacy-tab-${id}`}
            aria-selected={view.id === id}
            aria-controls={`legacy-panel-${id}`}
            className={view.id === id ? "active" : undefined}
            onClick={() => onLayerChange(id)}
          >
            {LEGACY_LAYER_COPY[id].label}
          </button>
        ))}
      </div>

      <section
        className="legacy-layer-panel"
        role="tabpanel"
        id={`legacy-panel-${view.id}`}
        aria-labelledby={`legacy-tab-${view.id}`}
      >
        <p className="legacy-layer-hint">{view.hint}</p>

        {view.id === "summary" ? (
          <>
            {view.rating !== null ? (
              <div className="legacy-rating">
                <span>旧版倾向（评级）</span>
                <strong>{view.rating}</strong>
              </div>
            ) : null}
            <div className="legacy-summary-text">
              <h3>结论</h3>
              {summaryText !== null && summaryText !== "" ? (
                <p>{summaryText}</p>
              ) : (
                <p className="placeholder">这次运行没有可验证的公开结论摘要。</p>
              )}
            </div>
          </>
        ) : null}

        {view.id === "detail" ? (
          view.hasContent ? (
            <p className="legacy-detail-lead">
              完整报告按旧版阅读视图展示，不经过新的研究简报，也不重算优先级。
            </p>
          ) : (
            <p className="placeholder">这次运行没有可展示的完整报告。</p>
          )
        ) : null}

        {view.id === "process" ? (
          view.hasContent ? (
            <div className="legacy-process-actions">
              <p>角色产出与调用记录按旧版流程查看。</p>
              <button type="button" onClick={onOpenAudit}>
                打开审计中心
              </button>
            </div>
          ) : (
            <p className="placeholder">这次运行没有记录研究过程。</p>
          )
        ) : null}
      </section>
    </section>
  );
}
