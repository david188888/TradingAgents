/**
 * F2 - Thin React context providing per-run state isolation for the
 * TradingAgents workbench. Holds the currently selected run_id plus the live
 * stream handle and view projection, exposed as three independently
 * subscribed slices; F3 components consume via useWorkbenchStore (all) or
 * the fine-grained useWorkbenchSelection / useWorkbenchStream /
 * useWorkbenchRunView hooks.
 *
 * Slices are memoized field-by-field: useRunStream and useRunView return
 * fresh object literals on every render, so a combined context value would
 * invalidate every frame and re-render every consumer. Keying each slice's
 * useMemo on its primitive fields keeps the context reference stable until
 * that slice's own data actually changes.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useRunStream } from "../hooks/useRunStream";
import { useRunView } from "../hooks/useRunView";

export interface WorkbenchSelectionValue {
  run_id: string | null;
  selectRun: (id: string | null) => void;
}

/** Stream slice: reducer state + transport status, no projection. */
export type WorkbenchStreamValue = ReturnType<typeof useRunStream>;

/** View slice: server projection envelope + fetch bookkeeping, no stream. */
export type WorkbenchViewValue = ReturnType<typeof useRunView>;

export interface WorkbenchRunValue {
  stream: WorkbenchStreamValue;
  view: WorkbenchViewValue;
}

export interface WorkbenchStoreValue extends WorkbenchSelectionValue, WorkbenchRunValue {}

const WorkbenchSelectionContext = createContext<WorkbenchSelectionValue | null>(null);
const WorkbenchStreamContext = createContext<WorkbenchStreamValue | null>(null);
const WorkbenchViewContext = createContext<WorkbenchViewValue | null>(null);

export function WorkbenchProvider({
  children,
}: {
  children: ReactNode;
}): JSX.Element {
  const [run_id, setRunId] = useState<string | null>(null);
  const stream = useRunStream(run_id);
  const viewRefreshKey = useRef(0);
  const [refreshKey, setRefreshKey] = useState(0);

  // When the SSE stream reaches a terminal state (run.completed/run.failed
  // observed, or the history snapshot is already terminal), force the view
  // projection to refetch: the live run's in-flight partial view must give
  // way to the committed completed view.
  const previousStreamStatus = useRef<string | null>(null);
  useEffect(() => {
    const previous = previousStreamStatus.current;
    const current = stream.status;
    if (
      previous !== null &&
      previous !== "closed" &&
      current === "closed" &&
      run_id !== null
    ) {
      viewRefreshKey.current += 1;
      setRefreshKey(viewRefreshKey.current);
    }
    previousStreamStatus.current = current;
  }, [run_id, stream.status]);

  const view = useRunView(run_id, refreshKey);
  const selectRun = useCallback((id: string | null): void => {
    setRunId(id);
  }, []);
  const selectionValue = useMemo(() => ({ run_id, selectRun }), [run_id, selectRun]);
  const streamValue = useMemo(
    () => ({ state: stream.state, status: stream.status, error: stream.error }),
    [stream.state, stream.status, stream.error],
  );
  const viewValue = useMemo(
    () => ({ view: view.view, loading: view.loading, error: view.error }),
    [view.view, view.loading, view.error],
  );
  return (
    <WorkbenchSelectionContext.Provider value={selectionValue}>
      <WorkbenchStreamContext.Provider value={streamValue}>
        <WorkbenchViewContext.Provider value={viewValue}>
          {children}
        </WorkbenchViewContext.Provider>
      </WorkbenchStreamContext.Provider>
    </WorkbenchSelectionContext.Provider>
  );
}

export function useWorkbenchSelection(): WorkbenchSelectionValue {
  const ctx = useContext(WorkbenchSelectionContext);
  if (ctx === null) {
    throw new Error("useWorkbenchSelection must be used within a WorkbenchProvider");
  }
  return ctx;
}

export function useWorkbenchStream(): WorkbenchStreamValue {
  const ctx = useContext(WorkbenchStreamContext);
  if (ctx === null) {
    throw new Error("useWorkbenchStream must be used within a WorkbenchProvider");
  }
  return ctx;
}

export function useWorkbenchRunView(): WorkbenchViewValue {
  const ctx = useContext(WorkbenchViewContext);
  if (ctx === null) {
    throw new Error("useWorkbenchRunView must be used within a WorkbenchProvider");
  }
  return ctx;
}

export function useWorkbenchRun(): WorkbenchRunValue {
  // Explicitly nested: the aggregate shape keeps the `stream`/`view` keys
  // consumers destructure, unlike a spread which would flatten the slices.
  return { stream: useWorkbenchStream(), view: useWorkbenchRunView() };
}

export function useWorkbenchStore(): WorkbenchStoreValue {
  return { ...useWorkbenchSelection(), ...useWorkbenchRun() };
}
