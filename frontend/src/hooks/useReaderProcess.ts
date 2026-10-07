import { useEffect, useRef, useState } from "react";
import { getReaderAgent, getReaderFocus, getReaderProcess } from "../api/client";
import type { AgentKey, ReaderAgentDTO, ReaderFocusDTO, ReaderProcessDTO } from "../api/contracts";
import type { RunStreamStatus } from "./useRunStream";

const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);

/** One bounded process read stream; never starts research or prefetches outputs. */
export function useReaderProcess(runId: string, sequence: number, status: string, streamStatus: RunStreamStatus, roleVersion: string) {
  const [response, setResponse] = useState<ReaderProcessDTO | null>(null);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const current = useRef({ sequence, status, streamStatus, roleVersion });
  current.current = { sequence, status, streamStatus, roleVersion };
  useEffect(() => {
    let stopped = false, busy = false, accepted = -1, lastRead = 0, failures = 0, lastRoles = "", lastTerminal = false;
    let controller: AbortController | null = null;
    setResponse(null); setError(false);
    const read = async (initial = false) => {
      if (stopped || busy || (!initial && document.hidden) || failures >= 3) return;
      busy = true; controller = new AbortController(); lastRead = Date.now();
      const target = current.current;
      lastRoles = target.roleVersion; lastTerminal = terminal.has(target.status);
      try {
        const next = await getReaderProcess(runId, controller.signal);
        if (!stopped) {
          if (next.run_id !== runId) throw new Error("Reader identity mismatch");
          if (next.source_sequence >= accepted) { accepted = next.source_sequence; setResponse(next); }
          failures = 0; setError(false);
        }
      } catch { if (!stopped) { failures++; setError(true); } }
      finally { busy = false; }
    };
    const tick = () => {
      const target = current.current, ended = terminal.has(target.status), elapsed = Date.now() - lastRead;
      if (ended && accepted >= target.sequence && accepted >= 0 && !failures) return;
      const roleChanged = target.roleVersion !== lastRoles;
      const terminalChanged = ended && !lastTerminal;
      const eventChanged = target.sequence > accepted && elapsed >= 2000;
      const fallback = target.streamStatus !== "live" && elapsed >= 5000;
      if (accepted < 0 || roleChanged || terminalChanged || eventChanged || fallback) void read();
    };
    void read(true);
    const timer = window.setInterval(tick, 500);
    const visible = () => { if (!document.hidden) { lastRead = 0; void read(); } };
    document.addEventListener("visibilitychange", visible);
    return () => { stopped = true; controller?.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [runId, retryKey]);
  return { response: response?.run_id === runId ? response : null, error, retry: () => setRetryKey(k => k + 1) };
}

/** Supplemental output shares the process boundary; late responses cannot cross runs. */
export function useReaderFocus(runId: string, process: ReaderProcessDTO | null) {
  const [response, setResponse] = useState<ReaderFocusDTO | null>(null);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const sequence = process?.source_sequence;
  const version = process?.workflow_version;
  useEffect(() => {
    const controller = new AbortController();
    setResponse(null); setError(false);
    if (sequence === undefined || version !== "evidence-production-v6") return () => controller.abort();
    void getReaderFocus(runId, sequence, controller.signal).then(next => {
      if (controller.signal.aborted) return;
      if (next.run_id !== runId || next.source_sequence !== sequence || next.workflow_version !== version) throw new Error("Reader focus identity mismatch");
      setResponse(next);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [runId, sequence, version, retryKey]);
  return { response: response?.run_id === runId && response.source_sequence === sequence ? response : null, error, retry: () => setRetryKey(k => k + 1) };
}

/** Role/generation/boundary guards protect against slow responses and run switches. */
export function useReaderAgent(runId: string, role: AgentKey | null, process: ReaderProcessDTO | null) {
  const [response, setResponse] = useState<ReaderAgentDTO | null>(null);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const selected = process?.roles.find(item => item.role_key === role);
  const boundary = useRef(process?.source_sequence ?? 0);
  boundary.current = process?.source_sequence ?? 0;
  useEffect(() => {
    const controller = new AbortController();
    setResponse(null); setError(false);
    if (!role || !process) return () => controller.abort();
    const sequence = boundary.current;
    void getReaderAgent(runId, role, sequence, controller.signal).then(next => {
      if (controller.signal.aborted) return;
      if (next.run_id !== runId || next.role_key !== role || next.source_sequence !== sequence) throw new Error("Reader output identity mismatch");
      setResponse(next);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
    // A mere checkpoint count change does not fetch the output again.
  }, [runId, role, selected?.output_availability, selected?.output_sequence, retryKey, process?.profile]);
  return { response: response?.run_id === runId && response.role_key === role ? response : null, error, retry: () => setRetryKey(k => k + 1) };
}
