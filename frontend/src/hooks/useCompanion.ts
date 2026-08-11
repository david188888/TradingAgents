import { useCallback, useEffect, useRef, useState } from "react";
import { getCompanion } from "../api/client";
import type { ApiError } from "../api/client";
import type { CompanionDTO, CompanionSelectionDTO } from "../api/contracts";

export interface UseCompanionResult {
  companion: CompanionDTO | null;
  loading: boolean;
  error: ApiError | Error | null;
  retry: () => void;
}

interface CompanionState {
  key: string | null;
  companion: CompanionDTO | null;
  loading: boolean;
  error: ApiError | Error | null;
}

const IDLE_STATE: CompanionState = {
  key: null,
  companion: null,
  loading: false,
  error: null,
};

function selectionKey(runId: string, selection: CompanionSelectionDTO): string {
  return `${runId}\u0000${selection.kind}\u0000${selection.id}`;
}

export function useCompanion(
  runId: string,
  selection: CompanionSelectionDTO | null,
): UseCompanionResult {
  const cacheRef = useRef(new Map<string, CompanionDTO>());
  const runRef = useRef(runId);
  const [retryVersion, setRetryVersion] = useState(0);
  const [state, setState] = useState<CompanionState>(IDLE_STATE);

  if (runRef.current !== runId) {
    runRef.current = runId;
    cacheRef.current.clear();
  }

  const key = selection === null ? null : selectionKey(runId, selection);

  useEffect(() => {
    if (selection === null || key === null) {
      setState(IDLE_STATE);
      return;
    }

    const cached = cacheRef.current.get(key);
    if (cached !== undefined) {
      setState({ key, companion: cached, loading: false, error: null });
      return;
    }

    const controller = new AbortController();
    setState({ key, companion: null, loading: true, error: null });
    void getCompanion(runId, selection, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        cacheRef.current.set(key, next);
        setState({ key, companion: next, loading: false, error: null });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        const error = reason instanceof Error ? reason : new Error(String(reason));
        setState({ key, companion: null, loading: false, error });
      });

    return () => controller.abort();
  }, [key, retryVersion, runId, selection]);

  const retry = useCallback(() => {
    if (key === null) return;
    cacheRef.current.delete(key);
    setRetryVersion((version) => version + 1);
  }, [key]);

  if (key === null) {
    return { companion: null, loading: false, error: null, retry };
  }
  if (state.key !== key) {
    return { companion: null, loading: true, error: null, retry };
  }
  return {
    companion: state.companion,
    loading: state.loading,
    error: state.error,
    retry,
  };
}
