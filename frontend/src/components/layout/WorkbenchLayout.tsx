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
import { DecisionBrief } from "../reader/DecisionBrief";
import { ReaderSurface } from "../reader/ReaderSurface";
import { FailedRunView } from "../reader/FailedRunView";
import { RunDisclosure } from "./RunDisclosure";
import { DebateTimeline } from "../timeline/DebateTimeline";
import { StageDetail } from "../timeline/StageDetail";
import type { JourneyStageId } from "../../api/contracts";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { useRunHistory } from "../../hooks/useRunHistory";

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
  const [expandedStage, setExpandedStage] = useState<JourneyStageId | null>(null);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const inspectorWidthRef = useRef(DEFAULT_INSPECTOR_WIDTH);
  const resizeFrameRef = useRef<number | null>(null);
  const isResizingRef = useRef(false);
  const previousStatus = useRef<string | null>(null);
  const auditReturnFocusRef = useRef<HTMLElement | null>(null);
  const state = stream.state;

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
    }
    previousStatus.current = current;
  }, [history.refresh, state?.meta.status]);

  const openAudit: AuditOpenHandler = (context, trigger): void => {
    auditReturnFocusRef.current = trigger;
    setAuditContext(context);
    setAuditOpen(true);
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

  return (
    <div className="app">
      <header className="topbar">
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

      <div className={`layout${inspectorOpen ? " with-inspector" : ""}`} ref={layoutRef}>
        <aside className="sidebar">
          <Controls refreshHistory={history.refresh} />
          <RunHistory
            runs={history.runs}
            loading={history.loading}
            error={history.error}
            onDeleteRun={handleDeleteRun}
          />
        </aside>

        <main className="main">
          {run_id === null ? (
            <section className="reader-empty">
              <span className="eyebrow">研究工作台</span>
              <h2>选择一次运行</h2>
            </section>
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
               only once the projection is terminal. */
            <>
              <SwarmStatusCard state={state} streamStatus={stream.status} />
              <WorkflowMap onRoleSelected={handleRoleSelected} />
              <RunDisclosure state={state} />
            </>
          ) : view.view ? (
            view.view.view.run.status === "failed" ? (
              <FailedRunView envelope={view.view} onOpenAudit={openAudit} />
            ) : view.view.view.run.status === "completed" ? (
              <>
                <DecisionBrief envelope={view.view} onOpenAudit={openAudit} />
                <ReaderSurface runId={run_id} onOpenAudit={openAudit} />
                <DebateTimeline
                  journey={view.view.view.debate_journey}
                  selectedStage={expandedStage}
                  onStageToggle={toggleStage}
                />
                {expandedStage ? (
                  <StageDetail
                    stageId={expandedStage}
                    envelope={view.view}
                    runId={run_id}
                    onOpenAudit={openAudit}
                    onRoleSelected={handleRoleSelected}
                  />
                ) : null}
              </>
            ) : (
              /* Terminal but neither completed nor failed (cancelled /
                 interrupted historical run): the honest fallback. */
              <>
                <DecisionBrief envelope={view.view} onOpenAudit={openAudit} />
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
    </div>
  );
}
