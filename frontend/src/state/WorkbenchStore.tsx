/**
 * F2 - Thin React context providing per-run state isolation for the
 * TradingAgents workbench. Holds the currently selected run_id and the live
 * stream handle from useRunStream; F3 components consume via useWorkbenchStore.
 *
 * Minimal: no UI, no selectors, no memoization beyond a stable selectRun.
 * The context value is recreated when run_id or stream changes, which is the
 * desired re-render trigger.
 */
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRunStream } from "../hooks/useRunStream";
import { useRunView } from "../hooks/useRunView";

export interface WorkbenchSelectionValue {
  run_id: string | null;
  selectRun: (id: string | null) => void;
}

export interface WorkbenchRunValue {
  stream: ReturnType<typeof useRunStream>;
  view: ReturnType<typeof useRunView>;
}

export interface WorkbenchStoreValue extends WorkbenchSelectionValue, WorkbenchRunValue {}

const WorkbenchSelectionContext = createContext<WorkbenchSelectionValue | null>(null);
const WorkbenchRunContext = createContext<WorkbenchRunValue | null>(null);

export function WorkbenchProvider({
  children,
}: {
  children: ReactNode;
}): JSX.Element {
  const [run_id, setRunId] = useState<string | null>(null);
  const stream = useRunStream(run_id);
  const view = useRunView(run_id);
  const selectRun = useCallback((id: string | null): void => {
    setRunId(id);
  }, []);
  const selectionValue = useMemo(() => ({ run_id, selectRun }), [run_id, selectRun]);
  const runValue = useMemo(() => ({ stream, view }), [stream, view]);
  return (
    <WorkbenchSelectionContext.Provider value={selectionValue}>
      <WorkbenchRunContext.Provider value={runValue}>
        {children}
      </WorkbenchRunContext.Provider>
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

export function useWorkbenchRun(): WorkbenchRunValue {
  const ctx = useContext(WorkbenchRunContext);
  if (ctx === null) {
    throw new Error("useWorkbenchRun must be used within a WorkbenchProvider");
  }
  return ctx;
}

export function useWorkbenchStore(): WorkbenchStoreValue {
  return { ...useWorkbenchSelection(), ...useWorkbenchRun() };
}
