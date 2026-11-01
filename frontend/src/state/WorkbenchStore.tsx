/** Current run selection and SSE state shared by terminal-independent Web controls. */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { useRunStream } from "../hooks/useRunStream";

export interface WorkbenchSelectionValue {
  run_id: string | null;
  selectRun(id: string | null): void;
  reconnectRun(id: string): void;
}
export type WorkbenchStreamValue = ReturnType<typeof useRunStream>;
export interface WorkbenchStoreValue extends WorkbenchSelectionValue { stream: WorkbenchStreamValue }
const Selection = createContext<WorkbenchSelectionValue | null>(null);
const Stream = createContext<WorkbenchStreamValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }): JSX.Element {
  const [run_id, setRunId] = useState<string | null>(null);
  const [reconnectKey, setReconnectKey] = useState(0);
  const selected = useRef(run_id);
  selected.current = run_id;
  const stream = useRunStream(run_id, reconnectKey);
  const selectRun = useCallback((id: string | null) => setRunId(id), []);
  const reconnectRun = useCallback((id: string) => {
    if (selected.current === id) setReconnectKey(key => key + 1);
  }, []);
  const selection = useMemo(() => ({run_id, selectRun, reconnectRun}), [run_id, selectRun, reconnectRun]);
  const value = useMemo(() => ({state: stream.state, status: stream.status, error: stream.error}), [stream.state, stream.status, stream.error]);
  return <Selection.Provider value={selection}><Stream.Provider value={value}>{children}</Stream.Provider></Selection.Provider>;
}
export function useWorkbenchSelection(): WorkbenchSelectionValue {
  const value = useContext(Selection);
  if (!value) throw new Error("WorkbenchProvider is required");
  return value;
}
export function useWorkbenchStream(): WorkbenchStreamValue {
  const value = useContext(Stream);
  if (!value) throw new Error("WorkbenchProvider is required");
  return value;
}
export function useWorkbenchStore(): WorkbenchStoreValue {
  return {...useWorkbenchSelection(), stream: useWorkbenchStream()};
}
