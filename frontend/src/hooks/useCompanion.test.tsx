import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanionDTO, CompanionSelectionDTO } from "../api/contracts";
import { getCompanion } from "../api/client";
import { useCompanion } from "./useCompanion";

vi.mock("../api/client", () => ({ getCompanion: vi.fn() }));

const mockedGetCompanion = vi.mocked(getCompanion);
const claimSelection: CompanionSelectionDTO = { kind: "claim", id: "claim-margin" };
const roleSelection: CompanionSelectionDTO = { kind: "role", id: "fundamentals" };

function companion(
  runId: string,
  selection: CompanionSelectionDTO,
  summary = "伴读摘要",
): CompanionDTO {
  return {
    schema_version: 1,
    run_id: runId,
    selection,
    summary,
    actual_coverage: ["来源：年报"],
    conclusion_impact: "支持当前研究结论",
    next_validation: "下一期复核",
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe("useCompanion", () => {
  beforeEach(() => {
    mockedGetCompanion.mockReset();
  });

  it("does not prefetch and reuses only a successful cached DTO", async () => {
    mockedGetCompanion.mockResolvedValue(companion("run_one", claimSelection));
    const { result, rerender } = renderHook(
      ({ selection }) => useCompanion("run_one", selection),
      { initialProps: { selection: null as CompanionSelectionDTO | null } },
    );

    expect(mockedGetCompanion).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);

    rerender({ selection: claimSelection });
    await waitFor(() => expect(result.current.companion?.summary).toBe("伴读摘要"));
    expect(mockedGetCompanion).toHaveBeenCalledTimes(1);

    rerender({ selection: null });
    rerender({ selection: claimSelection });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.companion?.selection).toEqual(claimSelection);
    expect(mockedGetCompanion).toHaveBeenCalledTimes(1);
  });

  it("aborts stale work and never lets an old response replace the new selection", async () => {
    const first = deferred<CompanionDTO>();
    const second = deferred<CompanionDTO>();
    mockedGetCompanion
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(
      ({ selection }) => useCompanion("run_one", selection),
      { initialProps: { selection: claimSelection as CompanionSelectionDTO | null } },
    );

    await waitFor(() => expect(mockedGetCompanion).toHaveBeenCalledTimes(1));
    const firstSignal = mockedGetCompanion.mock.calls[0]?.[2];
    rerender({ selection: roleSelection });
    await waitFor(() => expect(mockedGetCompanion).toHaveBeenCalledTimes(2));
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => {
      first.resolve(companion("run_one", claimSelection, "过时摘要"));
      second.resolve(companion("run_one", roleSelection, "最新摘要"));
    });
    await waitFor(() => expect(result.current.companion?.summary).toBe("最新摘要"));
    expect(result.current.error).toBeNull();
  });

  it("aborts on close and clears successful cache when the run changes", async () => {
    const pending = deferred<CompanionDTO>();
    mockedGetCompanion
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(companion("run_two", claimSelection, "第二个运行"));
    const { result, rerender } = renderHook(
      ({ runId, selection }) => useCompanion(runId, selection),
      {
        initialProps: {
          runId: "run_one",
          selection: claimSelection as CompanionSelectionDTO | null,
        },
      },
    );

    await waitFor(() => expect(mockedGetCompanion).toHaveBeenCalledTimes(1));
    const firstSignal = mockedGetCompanion.mock.calls[0]?.[2];
    rerender({ runId: "run_one", selection: null });
    expect(firstSignal?.aborted).toBe(true);
    expect(result.current.error).toBeNull();

    rerender({ runId: "run_two", selection: claimSelection });
    await waitFor(() => expect(result.current.companion?.summary).toBe("第二个运行"));
    expect(mockedGetCompanion).toHaveBeenCalledTimes(2);
  });

  it("does not cache failures and retries the current key with a fresh request", async () => {
    mockedGetCompanion
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce(companion("run_one", claimSelection, "重试成功"));
    const { result } = renderHook(() => useCompanion("run_one", claimSelection));

    await waitFor(() => expect(result.current.error?.message).toBe("temporary failure"));
    expect(mockedGetCompanion).toHaveBeenCalledTimes(1);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.companion?.summary).toBe("重试成功"));
    expect(mockedGetCompanion).toHaveBeenCalledTimes(2);
    expect(mockedGetCompanion.mock.calls[0]?.[2]).not.toBe(
      mockedGetCompanion.mock.calls[1]?.[2],
    );
  });
});
