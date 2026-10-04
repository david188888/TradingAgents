import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getResearchRecord } from "../api/client";
import type { ResearchRecordResponseDTO } from "../api/contracts";
import { useResearchRecord } from "./useResearchRecord";

vi.mock("../api/client", () => ({ getResearchRecord: vi.fn() }));
const get = vi.mocked(getResearchRecord);
const missing = (run_id: string): ResearchRecordResponseDTO => ({ state: "unavailable", schema_version: 1, run_id, reason_code: "not_published" });

describe("useResearchRecord", () => {
  beforeEach(() => get.mockReset());
  it("reads once and does not backfill missing historical records", async () => {
    get.mockResolvedValue(missing("one"));
    const { result, rerender } = renderHook(() => useResearchRecord("one"));
    await waitFor(() => expect(result.current.response).toEqual(missing("one")));
    rerender();
    expect(get).toHaveBeenCalledTimes(1);
  });
  it("aborts a previous read and drops its late response", async () => {
    let late!: (value: ResearchRecordResponseDTO) => void;
    get.mockImplementationOnce(() => new Promise((resolve) => { late = resolve; }));
    get.mockResolvedValueOnce(missing("two"));
    const { result, rerender } = renderHook(({ id }) => useResearchRecord(id), { initialProps: { id: "one" } });
    const signal = get.mock.calls[0][1]!;
    rerender({ id: "two" });
    await waitFor(() => expect(result.current.response?.run_id).toBe("two"));
    await act(async () => late(missing("one")));
    expect(signal.aborted).toBe(true);
    expect(result.current.response?.run_id).toBe("two");
  });
  it("rejects a response for a different run", async () => {
    get.mockResolvedValue(missing("other"));
    const { result } = renderHook(() => useResearchRecord("one"));
    await waitFor(() => expect(result.current.error).toBe(true));
    expect(result.current.response).toBeNull();
  });
  it("issues no request while inactive", () => {
    renderHook(() => useResearchRecord(null));
    expect(get).not.toHaveBeenCalled();
  });
});
