import { useEffect, useState } from "react";
import { ApiError, getResearchPackage } from "../api/client";
import type { ResearchPackageDTO } from "../api/contracts";

export interface UseResearchPackageResult {
  researchPackage: ResearchPackageDTO | null;
  loading: boolean;
  error: ApiError | Error | null;
}

/** Reads the immutable public package; a missing package is a normal legacy state. */
export function useResearchPackage(runId: string | null): UseResearchPackageResult {
  const [researchPackage, setResearchPackage] = useState<ResearchPackageDTO | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  useEffect(() => {
    if (runId === null) {
      setResearchPackage(null);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setResearchPackage(null);
    setLoading(true);
    setError(null);
    void getResearchPackage(runId, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setResearchPackage(next);
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

  return { researchPackage, loading, error };
}
