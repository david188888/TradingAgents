import { useEffect, useState } from "react";
import { getRunView } from "../api/client";
import type { RunViewEnvelopeDTO } from "../api/contracts";

const MAX_CACHED_VIEWS = 3;
const cache = new Map<string, RunViewEnvelopeDTO>();
const pending = new Map<string, Promise<RunViewEnvelopeDTO>>();

function cacheView(view: RunViewEnvelopeDTO): void {
  const key = `${view.view.run.run_id}:${view.schema_version}:${view.source_sequence}`;
  cache.delete(key);
  cache.set(key, view);
  while (cache.size > MAX_CACHED_VIEWS) {
    const oldest = cache.keys().next().value as string | undefined;
    if (oldest) cache.delete(oldest);
  }
}

function cachedFor(runId: string): RunViewEnvelopeDTO | null {
  for (const [key, view] of [...cache.entries()].reverse()) {
    if (key.startsWith(`${runId}:`)) return view;
  }
  return null;
}

export interface UseRunViewResult {
  view: RunViewEnvelopeDTO | null;
  loading: boolean;
  error: Error | null;
}

/**
 * Fetches the small server projection first. Switching runs aborts the old
 * request; a bounded LRU restores terminal views without rereading artifacts.
 */
export function useRunView(runId: string | null): UseRunViewResult {
  const [view, setView] = useState<RunViewEnvelopeDTO | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (runId === null) {
      setView(null);
      setLoading(false);
      setError(null);
      return;
    }
    const cached = cachedFor(runId);
    if (cached?.terminal) {
      setView(cached);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setView(null);
    setLoading(true);
    setError(null);
    const task = pending.get(runId) ?? getRunView(runId, controller.signal);
    pending.set(runId, task);
    void task
      .then((next) => {
        cacheView(next);
        if (!controller.signal.aborted) setView(next);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason : new Error(String(reason)));
        }
      })
      .finally(() => {
        if (pending.get(runId) === task) pending.delete(runId);
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId]);

  return { view, loading, error };
}
