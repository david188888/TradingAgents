import { useEffect, useRef, useState } from "react";
import { getReportExplanation, retryReportExplanation } from "../api/client";
import type { ReportExplanationDTO } from "../api/contracts";

/** Reads only. Only the explicit retry command can dispatch model work. */
export function useReportExplanation(runId: string, sequence?: number) {
  const [response, setResponse] = useState<ReportExplanationDTO | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const current = useRef(runId);
  current.current = runId;
  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined, reads = 0, failures = 0, busy = false;
    setResponse(null); setError(false); setSubmitting(false);
    const read = async () => {
      if (controller.signal.aborted || document.hidden || busy) return;
      if (reads >= 65 || failures >= 3) { setError(true); return; }
      reads++; busy = true;
      try {
        const next = await getReportExplanation(runId, controller.signal);
        if (controller.signal.aborted) return;
        if (next.run_id !== runId) throw new Error("Explanation identity mismatch");
        setResponse(next); setError(false); failures = 0;
        if (next.state === "generating" || (next.eligible && next.state === "not_generated" && reads < 3)) timer = window.setTimeout(() => void read(), 2000);
      } catch {
        if (!controller.signal.aborted) { setError(true); failures++; timer = window.setTimeout(() => void read(), 2000); }
      } finally { busy = false; }
    };
    const visible = () => { if (!document.hidden) { window.clearTimeout(timer); void read(); } };
    void read(); document.addEventListener("visibilitychange", visible);
    return () => { controller.abort(); window.clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [runId, sequence, refresh]);
  const retry = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const next = await retryReportExplanation(runId);
      if (current.current === runId && next.run_id === runId) { setResponse(next); setRefresh(v => v + 1); }
    } catch { if (current.current === runId) setError(true); }
    finally { if (current.current === runId) setSubmitting(false); }
  };
  return { response: response?.run_id === runId ? response : null, error, submitting, retry, reload: () => setRefresh(v => v + 1) };
}
