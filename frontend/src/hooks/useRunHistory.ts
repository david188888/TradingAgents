/**
 * F3 - Hook for loading the run history list from GET /api/runs.
 *
 * Fetches once on mount; exposes refresh() so the layout can re-fetch after a
 * run starts/ends (e.g. after createRun resolves or a terminal stream event
 * arrives). The backend returns runs newest-first; this hook preserves that
 * order. Cursor pages append older records; refresh invalidates stale reads.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { DeleteAllRunsResultDTO, RecentRunsPageDTO, RunSummaryDTO } from "../api/contracts";
import { deleteAllRuns, deleteRun, listRecentRuns } from "../api/client";

export interface UseRunHistoryResult {
  runs: RunSummaryDTO[];
  loading: boolean;
  error: Error | null;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => Promise<void>;
  refresh: () => Promise<void>;
  removeRun: (run_id: string) => Promise<boolean>;
  /** Bulk-clear all persisted runs (the active run is kept by the server). */
  clearAll: () => Promise<DeleteAllRunsResultDTO | null>;
}

export function useRunHistory(): UseRunHistoryResult {
  const [runs, setRuns] = useState<RunSummaryDTO[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const cursorRef = useRef<string | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);

  const readPage = useCallback(async (cursor?: string): Promise<void> => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const currentGeneration = ++generation.current;
    const append = cursor !== undefined;
    setLoading(!append);
    setLoadingMore(append);
    setError(null);
    try {
      const page: RecentRunsPageDTO = await listRecentRuns(controller.signal, cursor);
      if (controller.signal.aborted || currentGeneration !== generation.current) return;
      const items: RunSummaryDTO[] = page.items.map((item) => ({
        run_id: item.run_id, status: item.status, ticker: item.ticker,
        analysis_date: "", asset_type: "stock", created_at: item.created_at,
        updated_at: item.created_at, latest_sequence: item.latest_sequence,
        final_signal: item.final_signal, error_category: item.error_category,
      }));
      setRuns((current) => {
        if (!append) return items;
        const known = new Set(current.map(run => run.run_id));
        return [...current, ...items.filter(item => !known.has(item.run_id))];
      });
      cursorRef.current = page.next_cursor;
      setNextCursor(page.next_cursor);
    } catch (err) {
      if (!controller.signal.aborted && currentGeneration === generation.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (currentGeneration === generation.current) {
        request.current = null;
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, []);

  const refresh = useCallback(() => readPage(), [readPage]);
  const loadMore = useCallback(async (): Promise<void> => {
    if (request.current !== null || cursorRef.current === null) return;
    await readPage(cursorRef.current);
  }, [readPage]);

  useEffect(() => {
    void refresh();
    return () => {
      generation.current += 1;
      request.current?.abort();
      request.current = null;
    };
  }, [refresh]);

  const removeRun = useCallback(async (run_id: string): Promise<boolean> => {
    try {
      await deleteRun(run_id);
      generation.current += 1;
      request.current?.abort();
      request.current = null;
      setLoading(false);
      setLoadingMore(false);
      setRuns((current) => current.filter((run) => run.run_id !== run_id));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      return false;
    }
  }, []);

  const clearAll = useCallback(async (): Promise<DeleteAllRunsResultDTO | null> => {
    try {
      const result = await deleteAllRuns();
      // The server keeps the active run; refresh to reflect exactly what remains.
      if (result.removed > 0 || result.skipped_active) {
        await refresh();
      }
      return result;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      return null;
    }
  }, [refresh]);

  return { runs, loading, error, hasMore: nextCursor !== null, loadingMore, loadMore, refresh, removeRun, clearAll };
}
