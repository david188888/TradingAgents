import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Controls } from "../controls/Controls";
import { RunHistory } from "../history/RunHistory";
import { Inspector } from "../inspector/Inspector";
import { SwarmStatusCard } from "../status/SwarmStatusCard";
import { WorkflowMap } from "../workflow/WorkflowMap";
import {
  AuditCenter,
  type AuditEntryContext,
  type AuditOpenHandler,
} from "../reader/AuditCenter";
import { ReaderSurface } from "../reader/ReaderSurface";
import { FailedRunView } from "../reader/FailedRunView";
import { ResumableRunBar } from "../reader/ResumableRunBar";
import { CatalystCasePage } from "../reader/CatalystCasePage";
import { CatalystProgress } from "../reader/CatalystProgress";
import { EvidenceDrawer } from "../reader/EvidenceDrawer";
import { ResearchRecordSection } from "../reader/ResearchRecordSection";
import { NativeResearchPage } from "../reader/NativeResearchPage";
import { restoreFocus } from "../shared/drawerFocus";
import { LegacyReader } from "../reader/LegacyReader";
import { RunDisclosure } from "./RunDisclosure";
import { DebateTimeline } from "../timeline/DebateTimeline";
import { StageDetail } from "../timeline/StageDetail";
import type { JourneyStageId } from "../../api/contracts";
import { cancelRun, resumeRun, retryRun } from "../../api/client";
import { notifyRun } from "../../hooks/useCompletionNotifications";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { useRunHistory } from "../../hooks/useRunHistory";
import { useCatalyst } from "../../hooks/useCatalyst";
import { useResearchRecord } from "../../hooks/useResearchRecord";
import {
  catalystRoute,
  catalystScreenState,
  catalystStageProgress,
  type LegacyLayerId,
} from "../../domain/catalystWorkbench";

const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "interrupted",
]);

const INSPECTOR_WIDTH_KEY = "tradingagents.inspector-width";
const DEFAULT_INSPECTOR_WIDTH = 340;
const MIN_INSPECTOR_WIDTH = 320;

function maximumInspectorWidth(): number {
  return Math.max(MIN_INSPECTOR_WIDTH, Math.min(640, Math.floor(window.innerWidth * 0.45)));
}

function clampInspectorWidth(width: number): number {
  return Math.min(maximumInspectorWidth(), Math.max(MIN_INSPECTOR_WIDTH, width));
}

/** The primary surface reads the compact view first; audit material is opt-in. */
export function WorkbenchLayout(): JSX.Element {
  const { run_id, stream, view, selectRun } = useWorkbenchStore();
  const history = useRunHistory();
  const [selectedTurn, setSelectedTurn] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditContext, setAuditContext] = useState<AuditEntryContext | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [expandedStage, setExpandedStage] = useState<JourneyStageId | null>(null);
  const topbarRef = useRef<HTMLElement | null>(null);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const inspectorWidthRef = useRef(DEFAULT_INSPECTOR_WIDTH);
  const resizeFrameRef = useRef<number | null>(null);
  const isResizingRef = useRef(false);
  const previousStatus = useRef<string | null>(null);
  const auditReturnFocusRef = useRef<HTMLElement | null>(null);
  /**
   * T29: the control that opened the evidence drawer. Kept separately from the
   * audit trigger because the two overlays are mutually exclusive and each has
   * to return focus to its own trigger.
   */
  const catalystReturnFocusRef = useRef<HTMLElement | null>(null);
  const [legacyLayer, setLegacyLayer] = useState<LegacyLayerId>("summary");
  const [openRef, setOpenRef] = useState<{ id: string; title: string | null } | null>(null);
  const state = stream.state;
  const selectedViewRun = view.view?.view.run.run_id === run_id ? view.view.view.run : null;
  const selectedState = state?.meta.run_id === run_id ? state : null;
  const selectedProfile = selectedViewRun?.research_profile ?? selectedState?.meta.research_profile;
  const isNative = selectedProfile === "evidence_v1";

  /**
   * T26. The catalyst projection is read once per selected run, alongside the
   * classic view rather than instead of it: a classic run still needs its view,
   * and the read is a plain GET of committed facts (no LLM, no data source), so
   * mounting it costs nothing.
   */
  const catalyst = useCatalyst(isNative ? null : run_id, JSON.stringify([state?.meta.catalyst_stages, state?.meta.status]));
  const recordRunId = selectedViewRun?.status === "completed" || (isNative && selectedState?.meta.status === "completed") ? run_id : null;
  const researchRecord = useResearchRecord(recordRunId);

  /**
   * Which contract produced this page. The completed page used to mount
   * `DecisionBrief` (rendering `view.brief` + `learning_summary`) directly above
   * `ReaderSurface`, and the two measured 96% overlapping. Routing by contract
   * means exactly one of them is mounted, which is the only way the duplication
   * goes away: the projection fields cannot be deleted, because
   * `executive_summary` is null in 15/15 real runs and carries no content.
   */
  const route = catalystRoute({
    runId: run_id,
    classicTerminal: view.view?.terminal === true,
    readState: catalyst.state,
    profile: state?.meta.research_profile,
    loading: view.loading || catalyst.loading,
  });

  const screenState = catalystScreenState({
    run_status: state?.meta.status ?? view.view?.view.run.status ?? "created",
    state: catalyst.state,
    completeness: null,
    quality: null,
    profile: route.kind === "catalyst" ? "catalyst_v1" : null,
    error: catalyst.error,
  });

  const stageProgress = catalystStageProgress({
    run_status: state?.meta.status ?? "created",
    stage_status: catalyst.stageStatus,
    stage_durations_ms: catalyst.stageDurations,
    counts: catalyst.stageCounts,
    uncommitted_candidates: catalyst.uncommittedCandidates,
  });

  const openEvidence = (refId: string, title: string | null, trigger: HTMLElement): void => {
    catalystReturnFocusRef.current = trigger;
    setOpenRef({ id: refId, title });
  };

  const closeEvidence = (): void => {
    setOpenRef(null);
    const trigger = catalystReturnFocusRef.current;
    catalystReturnFocusRef.current = null;
    restoreFocus(trigger);
  };

  const handleCancelRun = async (): Promise<void> => {
    if (run_id === null) return;
    await cancelRun(run_id);
    await history.refresh();
  };

  useEffect(() => {
    setOpenRef(null);
    catalystReturnFocusRef.current = null;
    setLegacyLayer("summary");
  }, [run_id]);

  useEffect(() => {
    const stored = Number(window.localStorage.getItem(INSPECTOR_WIDTH_KEY));
    const width = Number.isFinite(stored) ? clampInspectorWidth(stored) : DEFAULT_INSPECTOR_WIDTH;
    inspectorWidthRef.current = width;
    layoutRef.current?.style.setProperty("--inspector-width", `${width}px`);
  }, []);

  const setInspectorWidth = (width: number, persist: boolean): void => {
    const clamped = clampInspectorWidth(width);
    inspectorWidthRef.current = clamped;
    layoutRef.current?.style.setProperty("--inspector-width", `${clamped}px`);
    if (persist) window.localStorage.setItem(INSPECTOR_WIDTH_KEY, String(clamped));
  };

  const handleResizePointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    isResizingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handleResizePointerMove = (event: PointerEvent<HTMLDivElement>): void => {
    // Only resize while the pointer button is held down — a plain hover or
    // pointer sweep over the divider must not change the inspector width.
    if (!isResizingRef.current) return;
    const width = window.innerWidth - event.clientX;
    if (resizeFrameRef.current !== null) cancelAnimationFrame(resizeFrameRef.current);
    resizeFrameRef.current = requestAnimationFrame(() => setInspectorWidth(width, false));
  };

  const handleResizePointerUp = (event: PointerEvent<HTMLDivElement>): void => {
    if (!isResizingRef.current) return;
    isResizingRef.current = false;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (resizeFrameRef.current !== null) cancelAnimationFrame(resizeFrameRef.current);
    resizeFrameRef.current = null;
    setInspectorWidth(window.innerWidth - event.clientX, true);
  };

  const handleResizePointerCancel = (event: PointerEvent<HTMLDivElement>): void => {
    isResizingRef.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (resizeFrameRef.current !== null) cancelAnimationFrame(resizeFrameRef.current);
    resizeFrameRef.current = null;
  };

  const handleResizeKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key === "ArrowLeft") setInspectorWidth(inspectorWidthRef.current + 16, true);
    else if (event.key === "ArrowRight") setInspectorWidth(inspectorWidthRef.current - 16, true);
    else if (event.key === "Home") setInspectorWidth(MIN_INSPECTOR_WIDTH, true);
    else if (event.key === "End") setInspectorWidth(maximumInspectorWidth(), true);
    else return;
    event.preventDefault();
  };

  useEffect(() => () => {
    if (resizeFrameRef.current !== null) cancelAnimationFrame(resizeFrameRef.current);
  }, []);

  useEffect(() => {
    const targets = [topbarRef.current, layoutRef.current].filter(
      (item): item is HTMLElement => item !== null,
    ) as Array<HTMLElement & { inert: boolean }>;
    for (const target of targets) target.inert = auditOpen;
    return () => {
      for (const target of targets) target.inert = false;
    };
  }, [auditOpen]);

  useEffect(() => {
    setAuditOpen(false);
    setAuditContext(null);
    auditReturnFocusRef.current = null;
    setInspectorOpen(false);
    setSelectedTurn(null);
    setExpandedStage(null);
  }, [run_id]);

  const toggleStage = (stage: JourneyStageId): void => {
    setExpandedStage((current) => (current === stage ? null : stage));
  };

  useEffect(() => {
    const current = state?.meta.status ?? null;
    const wasLive = previousStatus.current !== null && !TERMINAL_RUN_STATUSES.has(previousStatus.current);
    if (current && wasLive && TERMINAL_RUN_STATUSES.has(current)) {
      void history.refresh();
      if (state?.meta.run_id && state.meta.ticker) {
        notifyRun(
          {
            run_id: state.meta.run_id,
            status: current as "completed" | "failed" | "cancelled" | "interrupted",
            ticker: state.meta.ticker,
            error_message: state.meta.error_message,
          },
          () => selectRun(state.meta.run_id),
        );
      }
    }
    previousStatus.current = current;
  }, [history.refresh, state?.meta.status]);

  const openAudit: AuditOpenHandler = (context, trigger): void => {
    auditReturnFocusRef.current = trigger;
    setAuditContext(context);
    setAuditOpen(true);
  };

  const openAuditFromActiveControl = (): void => {
    const active = document.activeElement;
    openAudit(
      { section: "overview" },
      active instanceof HTMLElement ? active : document.body,
    );
  };

  const handleRoleSelected = (actorId: string): void => {
    if (view.view?.terminal) {
      const active = document.activeElement;
      openAudit(
        { section: "roles", itemId: actorId },
        active instanceof HTMLElement ? active : document.body,
      );
      return;
    }
    const turnId = state?.roles[actorId]?.latest_turn_id;
    if (turnId) {
      setSelectedTurn(turnId);
      setInspectorOpen(true);
    }
  };

  const handleDeleteRun = async (targetRunId: string): Promise<void> => {
    const removed = await history.removeRun(targetRunId);
    if (removed && run_id === targetRunId) {
      selectRun(null);
    }
  };

  const handleClearHistory = async (): Promise<void> => {
    setClearingHistory(true);
    try {
      const result = await history.clearAll();
      // clearAll() already refreshed the list. If every visible run was removed
      // (no active run survived), drop the current reader selection.
      if (result !== null && !result.skipped_active && run_id !== null) {
        selectRun(null);
      }
    } finally {
      setClearingHistory(false);
    }
  };

  const handleRetryRun = async (): Promise<void> => {
    if (run_id === null) return;
    if (!isNative) { selectRun(null); return; }
    const retried = await retryRun(run_id);
    await history.refresh();
    selectRun(retried.run_id);
  };

  const handleResumeRun = async (): Promise<void> => {
    if (run_id === null) return;
    await resumeRun(run_id);
    await history.refresh();
    // The run keeps its id but leaves the terminal set; re-select it so the
    // live stream reconnects and the stale terminal projection is refetched.
    selectRun(null);
    selectRun(run_id);
  };

  return (
    <div className="app">
      <header
        ref={topbarRef}
        className="topbar"
        aria-hidden={auditOpen ? true : undefined}
      >
        <div className="brand">
          <span className="brand-mark">TA</span>
          TradingAgents <span className="brand-sub">Research Console</span>
        </div>
        <div className="top-meta">
          <span className="local-pill">● localhost</span>
          <span>仅用于研究，不构成投资建议</span>
          {run_id !== null && state && !view.view?.terminal ? (
            <button type="button" className="audit-toggle" onClick={() => setInspectorOpen((open) => !open)}>
              {inspectorOpen ? "收起实时审计栏" : "实时审计栏"}
            </button>
          ) : null}
        </div>
      </header>

      <div
        className={`layout${inspectorOpen ? " with-inspector" : ""}`}
        ref={layoutRef}
        aria-hidden={auditOpen ? true : undefined}
      >
        <aside className="sidebar">
          <Controls refreshHistory={history.refresh} />
          <RunHistory
            runs={history.runs}
            loading={history.loading}
            error={history.error}
            onDeleteRun={handleDeleteRun}
            onClearHistory={handleClearHistory}
            clearing={clearingHistory}
          />
        </aside>

        <main className="main">
          {run_id === null ? (
            <section className="reader-empty">
              <span className="eyebrow">研究工作台</span>
              <h2>选择一次运行</h2>
            </section>
          ) : isNative ? (
            <NativeResearchPage
              runId={run_id}
              ticker={selectedViewRun?.ticker ?? selectedState?.meta.ticker ?? ""}
              status={selectedViewRun?.status ?? selectedState?.meta.status ?? "created"}
              state={selectedState}
              {...researchRecord}
              onOpenAudit={openAuditFromActiveControl}
              onCancel={() => void handleCancelRun()}
              onRetry={() => void handleRetryRun()}
              onResume={() => void handleResumeRun()}
              onNewResearch={() => selectRun(null)}
            />
          ) : view.loading && !state ? (
            <section className="reader-skeleton" aria-busy="true">
              <span className="eyebrow">正在读取研究投影</span>
              <div /><div /><div />
            </section>
          ) : view.error && !state ? (
            <section className="reader-empty">
              <h2>无法读取运行视图</h2>
              <p className="entry-error">{view.error.message}</p>
            </section>
          ) : state && !(view.view?.terminal) ? (
            /* Live run (or a terminal run still replaying events): the swarm
               view is the monitoring surface; the reader surface takes over
               only once the projection is terminal. T30 also shows the four
               bounded stages here, so a catalyst run in flight never shows a
               final research priority. */
            <>
              {state.meta.research_profile !== "catalyst_v1" && <SwarmStatusCard state={state} streamStatus={stream.status} />}
              {state.meta.research_profile === "catalyst_v1" &&
              <CatalystProgress
                progress={stageProgress}
                state={screenState}
                onCancel={() => void handleCancelRun()}
                onRetry={handleRetryRun}
                onResume={handleResumeRun}
                onViewProcess={() => setLegacyLayer("process")}
                onNewRun={() => selectRun(null)}
                onOpenAudit={openAuditFromActiveControl}
              />}
              {state.meta.research_profile !== "catalyst_v1" && <>
                <WorkflowMap onRoleSelected={handleRoleSelected} />
                <RunDisclosure state={state} />
              </>}
            </>
          ) : view.view ? (
            view.view.view.run.status === "failed" ? (
              <FailedRunView envelope={view.view} onOpenAudit={openAudit} onRetry={handleRetryRun} onNewResearch={() => selectRun(null)} />
            ) : route.kind === "catalyst" && catalyst.screen !== null ? (
              /*
                T26 — the single main summary.
                `DecisionBrief` and `ReaderSurface` are NOT mounted here. They
                render `view.brief` and `learning_summary`, which overlap 96% and
                are the duplication this restructure removes. Both remain
                reachable: `ReaderSurface` is the 依据与事件 tab's content, and
                `DecisionBrief`'s old summary is the legacy route's 概要 layer.
                Neither is a second copy of the same text on one screen.
              */
              <CatalystCasePage
                runId={run_id}
                screen={catalyst.screen}
                state={screenState}
                asOf={catalyst.kase?.as_of ?? null}
                onOpenEvidence={openEvidence}
                onOpenAudit={openAuditFromActiveControl}
                onNewResearch={() => selectRun(null)}
                recordPanel={<ResearchRecordSection runId={run_id} {...researchRecord} />}
                detailPane={
                  view.view ? <ReaderSurface runId={run_id} onOpenAudit={openAudit} /> : null
                }
                processPane={
                  <>
                    {view.view ? (
                      <DebateTimeline
                        journey={view.view.view.debate_journey}
                        selectedStage={expandedStage}
                        onStageToggle={toggleStage}
                      />
                    ) : null}
                    {expandedStage && view.view ? (
                      <StageDetail
                        stageId={expandedStage}
                        envelope={view.view}
                        runId={run_id}
                        onOpenAudit={openAudit}
                        onRoleSelected={handleRoleSelected}
                      />
                    ) : null}
                  </>
                }
              />
            ) : route.kind === "legacy" ? (
              /*
                T31 — a legacy run, read in layers and with no research priority.
                `legacyLayerView` returns `priority: null` by construction, so
                the old `research_rating` is shown as a rating and never mapped
                onto the four new categories.
              */
              <><LegacyReader
                runId={run_id}
                ticker={view.view.view.run.ticker}
                /*
                  `brief` is typed as required, but a run that produced no
                  readable brief still has a terminal projection — and this page
                  must not white-screen on it. An absent brief is an honest
                  "no summary" state, not an error.
                */
                summaryText={view.view.view.brief?.value?.executive_summary?.text ?? null}
                rating={view.view.view.brief?.value?.research_rating ?? null}
                layer={legacyLayer}
                onLayerChange={setLegacyLayer}
                onOpenAudit={openAuditFromActiveControl}
              /><ResearchRecordSection runId={run_id} {...researchRecord} /></>
            ) : (
              /* Terminal but neither completed nor failed (cancelled /
                 interrupted historical run): the honest fallback. */
              <>
                {view.view.view.run.status === "interrupted" ? (
                  <ResumableRunBar onResume={handleResumeRun} />
                ) : null}
                {/*
                  A completed classic run that the catalyst read has not
                  classified yet. This is the honest holding state, not a second
                  summary: it says the page is still deciding which contract
                  produced this run, and it renders no brief text of its own.
                */}
                <CatalystProgress
                  progress={stageProgress}
                  state={screenState}
                  onRetry={handleRetryRun}
                  onResume={handleResumeRun}
                  onCancel={() => void handleCancelRun()}
                  onViewProcess={() => setLegacyLayer("process")}
                  onNewRun={() => selectRun(null)}
                  onOpenAudit={openAuditFromActiveControl}
                />
              </>
            )
          ) : null}
        </main>

        {inspectorOpen ? <div
          className="inspector-resizer"
          role="separator"
          aria-label="调整审计侧栏宽度"
          aria-orientation="vertical"
          aria-valuemin={MIN_INSPECTOR_WIDTH}
          aria-valuemax={maximumInspectorWidth()}
          aria-valuenow={inspectorWidthRef.current}
          tabIndex={0}
          onDoubleClick={() => setInspectorWidth(DEFAULT_INSPECTOR_WIDTH, true)}
          onKeyDown={handleResizeKeyDown}
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={handleResizePointerUp}
          onPointerCancel={handleResizePointerCancel}
        /> : null}
        {inspectorOpen ? <button className="inspector-backdrop" aria-label="关闭审计侧栏" onClick={() => setInspectorOpen(false)} /> : null}
        {inspectorOpen ? <aside className="inspector inspector-open">
          <div className="inspector-mobile-head">
            <span>审计依据</span>
            <button className="icon-command" aria-label="关闭审计侧栏" onClick={() => setInspectorOpen(false)}>×</button>
          </div>
          <Inspector selectedTurnId={selectedTurn} />
        </aside> : null}
      </div>
      {run_id !== null ? (
        <AuditCenter
          key={run_id}
          runId={run_id}
          open={auditOpen}
          context={auditContext}
          returnFocus={auditReturnFocusRef.current}
          onClose={() => setAuditOpen(false)}
        />
      ) : null}
      {!isNative && run_id !== null && catalyst.kase !== null ? (
        <EvidenceDrawer
          runId={run_id}
          evidence={catalyst.kase.evidence}
          events={catalyst.kase.events}
          sourceRecord={researchRecord.response?.state === "ready" ? researchRecord.response.record : undefined}
          openId={openRef?.id ?? null}
          title={openRef?.title ?? null}
          background={[topbarRef.current, layoutRef.current]}
          onClose={closeEvidence}
        />
      ) : null}
    </div>
  );
}
