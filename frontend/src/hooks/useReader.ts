import { useEffect, useState } from "react";
import { getReader } from "../api/client";
import { ApiError } from "../api/client";
import type { ReaderResponseDTO } from "../api/contracts";

export interface UseReaderResult {
  reader: ReaderResponseDTO | null;
  loading: boolean;
  error: ApiError | Error | null;
}

/**
 * Fetches the read-only, terminal Reader projection for a run. The reader is a
 * final-state projection (no background regeneration / polling), so a simple
 * abort-on-switch fetch is enough — no cache is needed. A null ``runId``
 * clears the result; switching runs aborts the in-flight request.
 */
export function useReader(runId: string | null): UseReaderResult {
  const [reader, setReader] = useState<ReaderResponseDTO | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  useEffect(() => {
    if (runId === null) {
      setReader(null);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setReader(null);
    setLoading(true);
    setError(null);
    void getReader(runId, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setReader(next);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason : new Error(String(reason)));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId]);

  return { reader, loading, error };
}
