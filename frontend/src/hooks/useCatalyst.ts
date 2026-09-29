/**
 * T26/T29/T31 — the catalyst read hook.
 *
 * Two properties this hook exists to guarantee:
 *
 * * **Reading calls nothing.** It issues one plain GET of the committed
 *   projection. It never polls, never refetches on a timer, and never calls a
 *   model or data source, so opening a tab, expanding evidence or reconnecting
 *   SSE cannot spend a run's budget.
 * * **Evidence never crosses a run boundary.** The result is keyed by
 *   `run_id`; a state that arrives for the previous run after the user has
 *   switched is dropped rather than rendered. That is the failure design 4.6
 *   names, and it is the reason the state carries its own `runId` instead of
 *   living in a bare ref.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getCatalyst } from "../api/client";
import type { CatalystBriefDTO, CatalystReadState } from "../api/contracts";
import {
  parseCatalystBrief,
  parseCatalystCase,
  type CatalystCaseSlice,
  type CatalystFirstScreen,
  type CatalystStageId,
  type CatalystStageStatus,
  buildCatalystFirstScreen,
} from "../domain/catalystWorkbench";

export interface UseCatalystResult {
  /** The endpoint body, or null before the first successful read. */
  state: CatalystReadState | null;
  brief: CatalystBriefDTO | null;
  kase: CatalystCaseSlice | null;
  /** The seven first-screen rows, or null when there is no brief to render. */
  screen: CatalystFirstScreen | null;
  loading: boolean;
  error: Error | null;
  /** T30: per-stage status as the committed case reports it. */
  stageStatus: Partial<Record<CatalystStageId, CatalystStageStatus>> | null;
  /** T30: measured stage durations, passed through unparsed for the domain. */
  stageDurations: unknown;
  /**
   * T30: real completed/total counts, or null when the case carries none.
   * `null` is the value that makes the page show stage status instead of a
   * percentage, so it is never defaulted to zeros.
   */
  stageCounts: Partial<Record<CatalystStageId, { completed: number; total: number }>> | null;
  /** T30: streaming candidates the server has not committed. */
  uncommittedCandidates: number;
  /** Force a re-read of committed facts. Never recomputes anything. */
  refresh: () => void;
  /** The run the current values belong to, or null. */
  runId: string | null;
}
interface CatalystState {
  runId: string;
  state: CatalystReadState | null;
  brief: CatalystBriefDTO | null;
  kase: CatalystCaseSlice | null;
  stageStatus: Partial<Record<CatalystStageId, CatalystStageStatus>> | null;
  stageDurations: unknown;
  stageCounts: Partial<Record<CatalystStageId, { completed: number; total: number }>> | null;
  uncommittedCandidates: number;
  loading: boolean;
  error: Error | null;
}

const EMPTY: CatalystState = {
  runId: "",
  state: null,
  brief: null,
  kase: null,
  stageStatus: null,
  stageDurations: null,
  stageCounts: null,
  uncommittedCandidates: 0,
  loading: false,
  error: null,
};

const STAGE_IDS: readonly CatalystStageId[] = ["evidence", "specialists", "refutation", "synthesis"];

const STAGE_STATUSES: readonly CatalystStageStatus[] = [
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
  "interrupted",
];

/**
 * Read the stage fields off whatever shape the projection carries.
 *
 * These are read defensively because the case body is `Record<string, unknown>`
 * on the wire: a renamed field yields nulls (and therefore no percentage)
 * rather than a crash or, worse, a plausible-looking progress bar.
 */
function readStages(caseBody: unknown): Pick<
  CatalystState,
  "stageStatus" | "stageDurations" | "stageCounts" | "uncommittedCandidates"
> {
  if (typeof caseBody !== "object" || caseBody === null) {
    return { stageStatus: null, stageDurations: null, stageCounts: null, uncommittedCandidates: 0 };
  }
  const body = caseBody as Record<string, unknown>;

  const rawStatus = body.stages ?? body.stage_status;
  let stageStatus: Partial<Record<CatalystStageId, CatalystStageStatus>> | null = null;
  if (typeof rawStatus === "object" && rawStatus !== null && !Array.isArray(rawStatus)) {
    const entries = rawStatus as Record<string, unknown>;
    for (const id of STAGE_IDS) {
      const value = entries[id];
      if (typeof value !== "string") continue;
      if (!(STAGE_STATUSES as readonly string[]).includes(value)) continue;
      stageStatus ??= {};
      stageStatus[id] = value as CatalystStageStatus;
    }
  }

  const rawCounts = body.stage_counts ?? body.counts;
  let stageCounts: Partial<Record<CatalystStageId, { completed: number; total: number }>> | null = null;
  if (typeof rawCounts === "object" && rawCounts !== null && !Array.isArray(rawCounts)) {
    const entries = rawCounts as Record<string, unknown>;
    for (const id of STAGE_IDS) {
      const value = entries[id];
      if (typeof value !== "object" || value === null) continue;
      const { completed, total } = value as Record<string, unknown>;
      if (typeof completed !== "number" || typeof total !== "number") continue;
      // A total of zero cannot yield a ratio; recording it would make the
      // domain compute a percentage out of a division by nothing.
      if (!(total > 0)) continue;
      stageCounts ??= {};
      stageCounts[id] = { completed, total };
    }
  }

  const uncommitted = body.uncommitted_candidates ?? body.candidate_count;
  return {
    stageStatus,
    stageDurations: body.stage_durations_ms ?? null,
    stageCounts,
    uncommittedCandidates: typeof uncommitted === "number" && uncommitted > 0 ? Math.floor(uncommitted) : 0,
  };
}

export function useCatalyst(runId: string | null): UseCatalystResult {
  const [revision, setRevision] = useState(0);
  const [value, setValue] = useState<CatalystState>(EMPTY);
  const runRef = useRef<string | null>(runId);

  useEffect(() => {
    if (runRef.current !== runId) {
      runRef.current = runId;
      setValue(EMPTY);
    }
  }, [runId]);

  useEffect(() => {
    if (runId === null) {
      setValue(EMPTY);
      return;
    }
    const controller = new AbortController();
    setValue((current) => ({ ...current, runId, loading: true, error: null }));
    void getCatalyst(runId, controller.signal)
      .then((next) => {
        if (controller.signal.aborted || runRef.current !== runId) return;
        const brief =
          next.state === "ready" ? parseCatalystBrief(next.brief) : null;
        const kase = next.state === "ready" ? parseCatalystCase(next.case) : null;
        setValue({
          runId,
          state: next,
          brief,
          kase,
          ...readStages(next.state === "ready" ? next.case : null),
          loading: false,
          error: null,
        });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || runRef.current !== runId) return;
        setValue({
          runId,
          state: null,
          brief: null,
          kase: null,
          stageStatus: null,
          stageDurations: null,
          stageCounts: null,
          uncommittedCandidates: 0,
          loading: false,
          error: reason instanceof Error ? reason : new Error(String(reason)),
        });
      });
    return () => controller.abort();
  }, [revision, runId]);

  const refresh = useCallback((): void => setRevision((n) => n + 1), []);

  return {
    state: value.runId === (runId ?? "") ? value.state : null,
    brief: value.runId === (runId ?? "") ? value.brief : null,
    kase: value.runId === (runId ?? "") ? value.kase : null,
    stageStatus: value.runId === (runId ?? "") ? value.stageStatus : null,
    stageDurations: value.runId === (runId ?? "") ? value.stageDurations : null,
    stageCounts: value.runId === (runId ?? "") ? value.stageCounts : null,
    uncommittedCandidates: value.runId === (runId ?? "") ? value.uncommittedCandidates : 0,
    screen:
      value.runId === (runId ?? "") && value.brief !== null
        ? buildCatalystFirstScreen(value.brief, value.kase)
        : null,
    loading: value.runId === (runId ?? "") ? value.loading : runId !== null,
    error: value.runId === (runId ?? "") ? value.error : null,
    refresh,
    runId,
  };
}
