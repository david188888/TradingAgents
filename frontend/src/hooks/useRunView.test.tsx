import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getRunView } from "../api/client";
import type { RunViewEnvelopeDTO } from "../api/contracts";
import { runView } from "../test/runFixtures";
import { useRunView } from "./useRunView";
vi.mock("../api/client", () => ({ getRunView: vi.fn() }));
const get = vi.mocked(getRunView);

describe("useRunView run isolation", () => {
  beforeEach(() => { vi.useFakeTimers(); get.mockReset(); });
  afterEach(() => vi.useRealTimers());

  it("drops a delayed summary response after switching companies", async () => {
    let finish!: (next: RunViewEnvelopeDTO) => void;
    get.mockResolvedValueOnce(runView("summary_A", true));
    get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    get.mockResolvedValueOnce(runView("summary_B"));
    const { result, rerender } = renderHook(({ id }) => useRunView(id), { initialProps: { id: "summary_A" } });
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(3000));
    const signal = get.mock.calls[1][1];
    rerender({ id: "summary_B" });
    await act(async () => {});
    expect(result.current.view?.view.run.run_id).toBe("summary_B");
    await act(async () => finish(runView("summary_A")));
    expect(result.current.view?.view.run.run_id).toBe("summary_B");
    expect(signal?.aborted).toBe(true);
  });

  it("drops an initial read after switching runs even when the transport ignores abort", async () => {
    let finish!: (next: RunViewEnvelopeDTO) => void;
    get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    get.mockResolvedValueOnce(runView("initial_B"));
    const { result, rerender } = renderHook(({ id }) => useRunView(id), { initialProps: { id: "initial_A" } });
    rerender({ id: "initial_B" });
    await act(async () => {});
    await act(async () => finish(runView("initial_A")));
    expect(result.current.view?.view.run.run_id).toBe("initial_B");
  });
});
