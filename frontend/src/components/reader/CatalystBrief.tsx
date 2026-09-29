/**
 * T28 — the first screen.
 *
 * This is the single main summary of a catalyst run. It renders exactly the
 * seven rows of design 4.3, in order, and it is the *only* place a completed
 * run's judgement is presented. The second summary that used to render
 * beside it (`reader-brief-v1.learning_summary` next to `run-view-v1.view.brief`,
 * measured at 96% overlap) is no longer mounted here — see
 * `CatalystFirstScreen.briefs.test.tsx`.
 *
 * The safety-overflow rule is the reason this component is written the way it
 * is. When the server could not fit every major counter-evidence into 420
 * characters it emits a ≤120-character template plus a full limitation list
 * that is *exempt* from the budget. That list is expanded by default, rendered
 * in full, and scrollable. It is never truncated, never collapsed, and never
 * replaced by a count. Design 4.3 says this rule outranks the length target.
 */
import {
  type CatalystBriefRow,
  type CatalystFirstScreen,
  type CatalystScreenState,
} from "../../domain/catalystWorkbench";

export interface CatalystBriefProps {
  runId: string;
  screen: CatalystFirstScreen;
  state: CatalystScreenState;
  /** The committed data cutoff, when the projection carries one. */
  asOf?: string | null;
  /** Open a reference in the evidence drawer. */
  onOpenEvidence(refId: string, title: string | null, trigger: HTMLElement): void;
}

const TONE_LABELS: Record<CatalystScreenState["tone"], string> = {
  neutral: "历史记录",
  live: "进行中",
  good: "已发布",
  limited: "受限",
  bad: "不可用",
};

const OVERFLOW_TITLE = "信息限制较多，暂不形成简短判断";

function formatAsOf(value: string | null): string {
  if (value === null) return "未记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().slice(0, 10);
}

function rowOf(screen: CatalystFirstScreen, id: CatalystBriefRow["id"]): CatalystBriefRow {
  const found = screen.rows.find((row) => row.id === id);
  if (found === undefined) throw new Error(`missing catalyst row: ${id}`);
  return found;
}

export function CatalystBrief({
  runId,
  screen,
  state,
  asOf = null,
  onOpenEvidence,
}: CatalystBriefProps): JSX.Element {
  const judgement = rowOf(screen, "judgement");
  const priority = rowOf(screen, "priority");
  const catalyst = rowOf(screen, "catalyst");
  const evidence = rowOf(screen, "evidence");
  const doubt = rowOf(screen, "doubt");
  const nextCheck = rowOf(screen, "next_check");

  const renderLine = (
    key: string,
    text: string,
    refs: CatalystBriefRow["refs"][number],
  ): JSX.Element => (
    <li key={key} className="catalyst-row-line">
      <span>{text}</span>
      {refs.length > 0 ? (
        <span className="catalyst-row-refs">
          {refs.map((ref) => (
            <button
              key={`${ref.kind}:${ref.id}`}
              type="button"
              className="catalyst-ref"
              disabled={ref.label === null}
              title={ref.label === null ? "该引用在本次运行内无法解析" : `查看${ref.kind === "event" ? "事件" : ref.kind === "challenge" ? "反证" : "依据"}：${ref.label}`}
              onClick={(event) => onOpenEvidence(ref.id, ref.label, event.currentTarget)}
            >
              来源
            </button>
          ))}
        </span>
      ) : null}
    </li>
  );

  return (
    <section className="catalyst-brief" data-run={runId} data-screen={state.id}>
      <header className="catalyst-brief-head">
        <div>
          <span className="eyebrow">研究简报</span>
          <h2>研究结论</h2>
        </div>
        <div className="catalyst-brief-status">
          <span className={`catalyst-state-pill tone-${state.tone}`}>{state.title}</span>
          <span className="catalyst-state-note">{TONE_LABELS[state.tone]}</span>
        </div>
      </header>

      {screen.overflow ? (
        <div className="catalyst-overflow-note" role="note">
          <strong>{OVERFLOW_TITLE}</strong>
          <p>
            本次有多个重大限制无法在简报的 {screen.budget} 字预算内忠实表达，因此不发布普通简报。
            原因：{screen.overflow_reason ?? "brief_safety_overflow"}。以下限制列表不受该预算限制，完整展示。
          </p>
        </div>
      ) : null}

      {/* Row 1 — one specific judgement, or an honest "not enough information". */}
      <section className="catalyst-row catalyst-row-judgement">
        <h3 className="catalyst-row-label">{judgement.label}</h3>
        <ul>{judgement.lines.map((line, index) => renderLine(`j-${index}`, line, judgement.refs[index] ?? []))}</ul>
      </section>

      {/* Row 2 — one of four categories. Never a percentage. */}
      <section className="catalyst-row catalyst-row-priority">
        <h3 className="catalyst-row-label">{priority.label}</h3>
        <ul>{priority.lines.map((line, index) => renderLine(`p-${index}`, line, priority.refs[index] ?? []))}</ul>
        <p className="catalyst-row-hint">{screen.priority_hint}</p>
      </section>

      {/* Row 3 — at most one primary catalyst, with a date or "pending". */}
      <section className="catalyst-row catalyst-row-catalyst">
        <h3 className="catalyst-row-label">{catalyst.label}</h3>
        {catalyst.lines.length > 0 ? (
          <ul>{catalyst.lines.map((line, index) => renderLine(`c-${index}`, line, catalyst.refs[index] ?? []))}</ul>
        ) : (
          <p className="catalyst-row-placeholder">{catalyst.placeholder}</p>
        )}
      </section>

      {/* Row 4 — at most three evidence lines, each traceable on click. */}
      <section className="catalyst-row catalyst-row-evidence">
        <h3 className="catalyst-row-label">{evidence.label}</h3>
        {evidence.lines.length > 0 ? (
          <ol className="catalyst-numbered">
            {evidence.lines.map((line, index) => renderLine(`e-${index}`, line, evidence.refs[index] ?? []))}
          </ol>
        ) : (
          <p className="catalyst-row-placeholder">{evidence.placeholder}</p>
        )}
      </section>

      {/* Row 5 — at least one doubt, never "no counter-evidence found". */}
      <section className="catalyst-row catalyst-row-doubt">
        <h3 className="catalyst-row-label">{doubt.label}</h3>
        <ul>{doubt.lines.map((line, index) => renderLine(`d-${index}`, line, doubt.refs[index] ?? []))}</ul>
      </section>

      {/* Row 6 — what to look at, what triggers it, why it changes the judgement. */}
      <section className="catalyst-row catalyst-row-next">
        <h3 className="catalyst-row-label">{nextCheck.label}</h3>
        <ul>{nextCheck.lines.map((line, index) => renderLine(`n-${index}`, line, nextCheck.refs[index] ?? []))}</ul>
      </section>

      {/*
        Row 7 — the limitations.
        Under overflow this list is the payload: expanded by default, whole,
        and scrollable. `scrollable` only caps the height; `overflow: auto` lets
        the reader reach every entry, and the list is never collapsed to a
        count. Under an ordinary brief the list is shorter and still fully
        visible — a limitation that changes priority is always visible.
      */}
      <section
        className="catalyst-row catalyst-row-limitations"
        data-overflow={screen.overflow ? "true" : "false"}
      >
        <h3 className="catalyst-row-label">{rowOf(screen, "limitations").label}</h3>
        {screen.limitations.length > 0 ? (
          <ul
            className={screen.overflow ? "catalyst-limitations-scroll" : undefined}
            tabIndex={screen.overflow ? 0 : undefined}
            role={screen.overflow ? "region" : undefined}
            aria-label={screen.overflow ? "影响判断的限制（完整列表）" : undefined}
          >
            {screen.limitations.map((text, index) =>
              renderLine(`l-${index}`, text, screen.limitation_refs[index] ?? []),
            )}
          </ul>
        ) : (
          <p className="catalyst-row-placeholder">{rowOf(screen, "limitations").placeholder}</p>
        )}
      </section>

      <footer className="catalyst-brief-foot">
        <span>
          首屏正文 {screen.character_count} / {screen.budget} 字
        </span>
        <span>数据截止 {formatAsOf(asOf)}</span>
      </footer>
    </section>
  );
}
