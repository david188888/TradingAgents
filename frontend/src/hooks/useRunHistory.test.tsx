import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RecentRunsPageDTO } from "../api/contracts";
import { useRunHistory } from "./useRunHistory";
function page(id: string, next_cursor: string | null = null): RecentRunsPageDTO {
  return { schema_version: 1, items: [{ run_id: id, ticker: id, status: "completed", created_at: "2026-10-25T00:00:00Z",
    completed_at: null, latest_sequence: 1, final_signal: null, error_category: null, duration_ms: null, data_quality_level: "unknown" }], next_cursor };
}
function response(value: RecentRunsPageDTO) { return new Response(JSON.stringify(value), { status: 200 }); }
afterEach(() => vi.restoreAllMocks());

describe("useRunHistory cursor navigation", () => {
  it("loads the API cursor, appends older runs once and reaches the final page", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(page("newer", "cursor+/=")))
      .mockResolvedValueOnce(response(page("older")));
    const { result } = renderHook(useRunHistory);
    await waitFor(() => expect(result.current.runs.map(run => run.run_id)).toEqual(["newer"]));
    expect(result.current.hasMore).toBe(true);
    await act(async () => Promise.all([result.current.loadMore(), result.current.loadMore()]));
    expect(result.current.runs.map(run => run.run_id)).toEqual(["newer", "older"]);
    expect(result.current.hasMore).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(2);
    const url = new URL(String(fetch.mock.calls[1][0]), "http://localhost");
    expect(url.searchParams.get("view")).toBe("recent");
    expect(url.searchParams.get("cursor")).toBe("cursor+/=");
  });

  it("does not append an old page after history has been refreshed", async () => {
    let finish!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(page("before", "old_cursor")))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response(page("after", "new_cursor")));
    const { result } = renderHook(useRunHistory);
    await waitFor(() => expect(result.current.loading).toBe(false));
    let older!: Promise<void>;
    act(() => { older = result.current.loadMore(); });
    await act(async () => result.current.refresh());
    await act(async () => { finish(response(page("stale"))); await older; });
    expect(result.current.runs.map(run => run.run_id)).toEqual(["after"]);
    expect(result.current.hasMore).toBe(true);
  });

  it("does not replace a newer refresh with a delayed initial page", async () => {
    let finish!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response(page("current")));
    const { result } = renderHook(useRunHistory);
    await act(async () => result.current.refresh());
    await act(async () => finish(response(page("stale_initial", "old"))));
    expect(result.current.runs.map(run => run.run_id)).toEqual(["current"]);
    expect(result.current.hasMore).toBe(false);
  });

  it("keeps loaded history and allows retrying a failed next-page request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(page("kept", "retry")))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(response(page("recovered")));
    const { result } = renderHook(useRunHistory);
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => result.current.loadMore());
    expect(result.current.runs.map(run => run.run_id)).toEqual(["kept"]);
    expect(result.current.error?.message).toBe("offline");
    expect(result.current.hasMore).toBe(true);
    await act(async () => result.current.loadMore());
    expect(result.current.runs.map(run => run.run_id)).toEqual(["kept", "recovered"]);
    expect(result.current.error).toBeNull();
  });
  it("does not resurrect a deleted run from an in-flight older page", async () => {
    let finish!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response(page("removed", "older_cursor")))
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(response(page("older_after_delete")));
    const { result } = renderHook(useRunHistory);
    await waitFor(() => expect(result.current.loading).toBe(false));
    let older!: Promise<void>;
    act(() => { older = result.current.loadMore(); });
    await act(async () => result.current.removeRun("removed"));
    await act(async () => { finish(response(page("removed"))); await older; });
    expect(result.current.runs).toEqual([]);
    expect(result.current.loadingMore).toBe(false);
    await act(async () => result.current.loadMore());
    expect(result.current.runs.map(run => run.run_id)).toEqual(["older_after_delete"]);
  });

});
