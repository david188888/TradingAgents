import { useCallback, useEffect, useState } from "react";
import { readArtifactText } from "../api/client";

export interface UseArtifactResult {
  content: string | null;
  loading: boolean;
  error: string | null;
  reload(): void;
}

const MAX_CACHED_ARTIFACTS = 24;
const cache = new Map<string, string>();

function cacheValue(key: string, value: string): void {
  cache.delete(key);
  cache.set(key, value);
  while (cache.size > MAX_CACHED_ARTIFACTS) {
    const oldest = cache.keys().next().value as string | undefined;
    if (oldest) cache.delete(oldest);
  }
}

function cacheKey(runId: string, artifactId: string): string {
  return `${runId}:${artifactId}`;
}

/** Lazy, bounded artifact reader. Cleanup aborts the actual HTTP request. */
export function useArtifact(
  runId: string | null,
  artifactId: string | null,
): UseArtifactResult {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(runId !== null && artifactId !== null);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const reload = useCallback((): void => {
    if (runId !== null && artifactId !== null) cache.delete(cacheKey(runId, artifactId));
    setReloadToken((value) => value + 1);
  }, [artifactId, runId]);

  useEffect(() => {
    if (runId === null || artifactId === null) {
      setContent(null);
      setLoading(false);
      setError(null);
      return;
    }
    const key = cacheKey(runId, artifactId);
    const cached = cache.get(key);
    if (cached !== undefined) {
      cache.delete(key);
      cache.set(key, cached);
      setContent(cached);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setContent(null);
    void readArtifactText(runId, artifactId, controller.signal)
      .then((text) => {
        cacheValue(key, text);
        if (!controller.signal.aborted) {
          setContent(text);
          setLoading(false);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [artifactId, reloadToken, runId]);

  return { content, loading, error, reload };
}
