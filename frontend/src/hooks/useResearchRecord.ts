import { useEffect, useState } from "react";
import { getResearchRecord } from "../api/client";
import type { ResearchRecordResponseDTO } from "../api/contracts";

/** Reads committed records only; missing history never triggers backfill. */
export function useResearchRecord(runId: string | null): {
  response: ResearchRecordResponseDTO | null;
  loading: boolean;
  error: boolean;
} {
  const [response, setResponse] = useState<ResearchRecordResponseDTO | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setResponse(null);
    setLoading(runId !== null);
    setError(false);
    if (runId !== null) {
      void getResearchRecord(runId, controller.signal).then((next) => {
        if (!controller.signal.aborted) {
          if (next.run_id !== runId || (next.state === "ready" && next.record.run_id !== runId)) setError(true);
          else setResponse(next);
        }
      }).catch(() => {
        if (!controller.signal.aborted) setError(true);
      }).finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    }
    return () => controller.abort();
  }, [runId]);
  return { response: response?.run_id === runId ? response : null, loading, error };
}
