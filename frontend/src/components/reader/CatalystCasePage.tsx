/**
 * T26 — the completed catalyst page, in one column.
 *
 * This is the de-duplication. Before, the completed page mounted
 * `DecisionBrief` (which renders `run-view-v1.view.brief` and its
 * `learning_summary`) immediately above `ReaderSurface`, and the two carried
 * the same sentences twice — 96% overlap measured against real runs. The
 * duplication could not be removed by dropping a projection field, because
 * `executive_summary` is null in 15/15 real runs: the two live containers are
 * the problem, and the only fix is to stop mounting both.
 *
 * So exactly one main summary container is mounted here, and it is this one.
 * The classic-path components stay reachable through tabs and through the
 * legacy route, so nothing becomes unreachable — it just stops being
 * duplicated on the first screen.
 */
import { useState } from "react";
import type { RunViewEnvelopeDTO } from "../../api/contracts";
import {
  CATALYST_TAB_COPY,
  CATALYST_TAB_IDS,
  type CatalystFirstScreen,
  type CatalystScreenState,
  type CatalystTabId,
} from "../../domain/catalystWorkbench";
import { CatalystBrief } from "./CatalystBrief";

export interface CatalystCasePageProps {
  runId: string;
  screen: CatalystFirstScreen;
  state: CatalystScreenState;
  asOf: string | null;
  /** Open a reference in the evidence drawer. */
  onOpenEvidence(refId: string, title: string | null, trigger: HTMLElement): void;
  /** The classic reading surfaces, mounted on demand rather than stacked. */
  detailPane: JSX.Element | null;
  processPane: JSX.Element | null;
  onOpenAudit: () => void;
  /** 更多研究 — the entry point back into the form. */
  onNewResearch: () => void;
}

export function CatalystCasePage({
  runId,
  screen,
  state,
  asOf,
  onOpenEvidence,
  detailPane,
  processPane,
  onOpenAudit,
  onNewResearch,
}: CatalystCasePageProps): JSX.Element {
  const [tab, setTab] = useState<CatalystTabId>("brief");

  return (
    <section className="catalyst-page" data-run={runId}>
      {/*
        The single main summary. `data-main-summary` is the hook the layout test
        counts: exactly one of these may exist for a completed run.
      */}
      <div className="catalyst-main-summary" data-main-summary="catalyst_brief">
        <CatalystBrief
          runId={runId}
          screen={screen}
          state={state}
          asOf={asOf}
          onOpenEvidence={onOpenEvidence}
        />
      </div>

      <div className="catalyst-page-actions">
        <button type="button" className="primary" onClick={onNewResearch}>
          更多研究
        </button>
        <button type="button" onClick={onOpenAudit}>
          打开审计中心
        </button>
      </div>

      {/*
        Three tabs, not a stack. 依据与事件 and 研究过程 hold the classic
        surfaces; 研究简报 is the summary above, which stays visible so the
        reader never loses the conclusion while reading detail.
      */}
      <div className="catalyst-tabs" role="tablist" aria-label="研究视图">
        {CATALYST_TAB_IDS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`catalyst-tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`catalyst-panel-${id}`}
            className={tab === id ? "active" : undefined}
            onClick={() => setTab(id)}
          >
            {CATALYST_TAB_COPY[id]}
          </button>
        ))}
      </div>

      <div
        className="catalyst-tab-panel"
        role="tabpanel"
        id={`catalyst-panel-${tab}`}
        aria-labelledby={`catalyst-tab-${tab}`}
        data-tab={tab}
      >
        {tab === "evidence" ? detailPane : null}
        {tab === "process" ? processPane : null}
        {tab === "brief" ? (
          <p className="catalyst-tab-empty">
            研究简报在上方。依据与事件、研究过程按需查看，不重复展示同一段文字。
          </p>
        ) : null}
      </div>
    </section>
  );
}

/** Re-export so a caller can pass the classic surfaces without a deep import. */
export type { RunViewEnvelopeDTO };
