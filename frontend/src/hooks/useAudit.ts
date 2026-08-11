import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getAuditDetail, getAuditSummary } from "../api/client";
import type {
  AuditDetailDTO,
  AuditSelectionDTO,
  AuditSummaryDTO,
} from "../api/contracts";

type AuditError = ApiError | Error | null;

export interface UseAuditSummaryResult {
  summary: AuditSummaryDTO | null;
  loading: boolean;
  refreshing: boolean;
  error: AuditError;
  refresh: () => void;
}

interface SummaryState {
  runId: string;
  summary: AuditSummaryDTO | null;
  requesting: boolean;
  error: AuditError;
}

export function useAuditSummary(runId: string, open: boolean): UseAuditSummaryResult {
  const cacheRef = useRef(new Map<string, AuditSummaryDTO>());
  const runRef = useRef(runId);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [state, setState] = useState<SummaryState>({
    runId,
    summary: null,
    requesting: false,
    error: null,
  });

  if (runRef.current !== runId) {
    runRef.current = runId;
    cacheRef.current.clear();
  }

  useEffect(() => {
    if (!open) {
      setState({ runId, summary: null, requesting: false, error: null });
      return;
    }
    const cached = cacheRef.current.get(runId) ?? null;
    const controller = new AbortController();
    setState({ runId, summary: cached, requesting: true, error: null });
    void getAuditSummary(runId, controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        cacheRef.current.set(runId, next);
        setState({ runId, summary: next, requesting: false, error: null });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        const error = reason instanceof Error ? reason : new Error(String(reason));
        setState({ runId, summary: cached, requesting: false, error });
      });
    return () => controller.abort();
  }, [open, refreshVersion, runId]);

  const refresh = useCallback(() => {
    if (open) setRefreshVersion((version) => version + 1);
  }, [open]);

  if (!open || state.runId !== runId) {
    return { summary: null, loading: false, refreshing: false, error: null, refresh };
  }
  return {
    summary: state.summary,
    loading: state.requesting && state.summary === null,
    refreshing: state.requesting && state.summary !== null,
    error: state.error,
    refresh,
  };
}

export interface UseAuditDetailResult {
  detail: AuditDetailDTO | null;
  loading: boolean;
  error: AuditError;
  retry: () => void;
}

interface DetailState {
  key: string | null;
  detail: AuditDetailDTO | null;
  loading: boolean;
  error: AuditError;
}

const EMPTY_DETAIL: DetailState = {
  key: null,
  detail: null,
  loading: false,
  error: null,
};

function detailKey(
  runId: string,
  sourceSequence: number,
  selection: AuditSelectionDTO,
): string {
  return `${runId}\u0000${sourceSequence}\u0000${selection.kind}\u0000${selection.id}`;
}

export function useAuditDetail(
  runId: string,
  sourceSequence: number | null,
  selection: AuditSelectionDTO | null,
  onSummaryStale: () => void,
): UseAuditDetailResult {
  const cacheRef = useRef(new Map<string, AuditDetailDTO>());
  const scopeRef = useRef(`${runId}\u0000${sourceSequence ?? "none"}`);
  const staleHandlerRef = useRef(onSummaryStale);
  const [retryVersion, setRetryVersion] = useState(0);
  const [state, setState] = useState<DetailState>(EMPTY_DETAIL);
  staleHandlerRef.current = onSummaryStale;

  const scope = `${runId}\u0000${sourceSequence ?? "none"}`;
  if (scopeRef.current !== scope) {
    scopeRef.current = scope;
    cacheRef.current.clear();
  }
  const key = selection === null || sourceSequence === null
    ? null
    : detailKey(runId, sourceSequence, selection);

  useEffect(() => {
    if (selection === null || sourceSequence === null || key === null) {
      setState(EMPTY_DETAIL);
      return;
    }
    const cached = cacheRef.current.get(key);
    if (cached !== undefined) {
      setState({ key, detail: cached, loading: false, error: null });
      return;
    }
    const controller = new AbortController();
    setState({ key, detail: null, loading: true, error: null });
    void getAuditDetail(runId, sourceSequence, selection, controller.signal)
      .then((next) => {
        if (controller.signal.aborted || next.source_sequence !== sourceSequence) return;
        cacheRef.current.set(key, next);
        setState({ key, detail: next, loading: false, error: null });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        if (reason instanceof ApiError && reason.code === "audit_summary_stale") {
          setState({ key, detail: null, loading: false, error: null });
          staleHandlerRef.current();
          return;
        }
        const error = reason instanceof Error ? reason : new Error(String(reason));
        setState({ key, detail: null, loading: false, error });
      });
    return () => controller.abort();
  }, [key, retryVersion, runId, selection, sourceSequence]);

  const retry = useCallback(() => {
    if (key === null) return;
    cacheRef.current.delete(key);
    setRetryVersion((version) => version + 1);
  }, [key]);

  if (key === null) return { detail: null, loading: false, error: null, retry };
  if (state.key !== key) return { detail: null, loading: true, error: null, retry };
  return { detail: state.detail, loading: state.loading, error: state.error, retry };
}
