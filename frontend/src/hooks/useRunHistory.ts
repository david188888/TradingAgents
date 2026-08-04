/**
 * F3 - Hook for loading the run history list from GET /api/runs.
 *
 * Fetches once on mount; exposes refresh() so the layout can re-fetch after a
 * run starts/ends (e.g. after createRun resolves or a terminal stream event
 * arrives). The backend returns runs newest-first; this hook preserves that
 * order without client-side sorting or dedup.
 */
import { useCallback, useEffect, useState } from "react";
import type { RunSummaryDTO } from "../api/contracts";
import { deleteRun, listRecentRuns } from "../api/client";

export interface UseRunHistoryResult {
  runs: RunSummaryDTO[];
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  removeRun: (run_id: string) => Promise<boolean>;
}

export function useRunHistory(): UseRunHistoryResult {
  const [runs, setRuns] = useState<RunSummaryDTO[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  const refresh = useCallback((): Promise<void> => {
    setLoading(true);
    setError(null);
    return listRecentRuns()
      .then((page) => {
        setRuns(
          page.items.map((item) => ({
            run_id: item.run_id,
            status: item.status,
            ticker: item.ticker,
            analysis_date: "",
            asset_type: "stock",
            created_at: item.created_at,
            updated_at: item.created_at,
            latest_sequence: item.latest_sequence,
            final_signal: item.final_signal,
            summary: undefined,
          })),
        );
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const removeRun = useCallback(async (run_id: string): Promise<boolean> => {
    try {
      await deleteRun(run_id);
      setRuns((current) => current.filter((run) => run.run_id !== run_id));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      return false;
    }
  }, []);

  return { runs, loading, error, refresh, removeRun };
}
