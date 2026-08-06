import { useEffect, useRef, useState } from "react";
import { getRunView } from "../api/client";
import type { RunViewEnvelopeDTO } from "../api/contracts";

const MAX_CACHED_VIEWS = 3;
const cache = new Map<string, RunViewEnvelopeDTO>();
const pending = new Map<string, Promise<RunViewEnvelopeDTO>>();

// Background debate-summary generation (quick LLM) typically lands within a
// few seconds. Poll at most twice after a completed run first loads without a
// ready summary; a permanently unavailable summary stops the polling.
const SUMMARY_REFRESH_DELAYS_MS = [3000, 7000] as const;

function cacheKey(view: RunViewEnvelopeDTO): string {
  return `${view.view.run.run_id}:${view.schema_version}:${view.source_sequence}`;
}

function cacheView(view: RunViewEnvelopeDTO): void {
  const key = cacheKey(view);
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

function summaryPending(view: RunViewEnvelopeDTO): boolean {
  return view.terminal && view.view.debate_summary.availability === "pending";
}

export interface UseRunViewResult {
  view: RunViewEnvelopeDTO | null;
  loading: boolean;
  error: Error | null;
}

/**
 * Fetches the small server projection first. Switching runs aborts the old
 * request; a bounded LRU restores terminal views without rereading artifacts.
 * For completed runs whose debate summary is still generating, a couple of
 * delayed refetches pick it up once the background LLM pass finishes.
 *
 * ``refreshKey`` forces a refetch that bypasses both the LRU and the pending
 * request dedupe. The workbench bumps it when an SSE stream terminalizes so a
 * live run transitions from the partial in-flight view to the committed
 * completed view the moment it finishes.
 */
export function useRunView(runId: string | null, refreshKey = 0): UseRunViewResult {
  const [view, setView] = useState<RunViewEnvelopeDTO | null>(null);
  const [loading, setLoading] = useState(runId !== null);
  const [error, setError] = useState<Error | null>(null);
  const refreshAttempt = useRef(0);

  useEffect(() => {
    refreshAttempt.current = 0;
  }, [runId]);

  useEffect(() => {
    if (runId === null) {
      setView(null);
      setLoading(false);
      setError(null);
      return;
    }
    if (refreshKey === 0) {
      const cached = cachedFor(runId);
      if (cached?.terminal) {
        setView(cached);
        setLoading(false);
        setError(null);
        if (!summaryPending(cached)) return;
      }
    }
    const controller = new AbortController();
    setView(null);
    setLoading(true);
    setError(null);
    const task =
      refreshKey === 0
        ? (pending.get(runId) ?? getRunView(runId, controller.signal))
        : getRunView(runId, controller.signal);
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
  }, [refreshKey, runId]);

  // Delayed refetch while the debate summary is still pending.
  useEffect(() => {
    if (!view || !summaryPending(view)) return;
    const attempt = refreshAttempt.current;
    if (attempt >= SUMMARY_REFRESH_DELAYS_MS.length) return;
    const delay = SUMMARY_REFRESH_DELAYS_MS[attempt];
    const timer = window.setTimeout(() => {
      refreshAttempt.current += 1;
      getRunView(view.view.run.run_id)
        .then((next) => {
          cacheView(next);
          setView(next);
        })
        .catch(() => {
          // Leave the pending state; the user can still read L3/full report.
        });
    }, delay);
    return () => window.clearTimeout(timer);
  }, [view]);

  return { view, loading, error };
}

