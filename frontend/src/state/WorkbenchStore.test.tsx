import type { ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getRun, getRunView } from "../api/client";
import { openRunStream } from "../api/eventSource";
import { runSnapshot, runView } from "../test/runFixtures";
import { WorkbenchProvider, useWorkbenchStore } from "./WorkbenchStore";
vi.mock("../api/client", () => ({ getRun: vi.fn(), getRunView: vi.fn() }));
vi.mock("../api/eventSource", () => ({ openRunStream: vi.fn(() => ({ close: vi.fn() })) }));
const wrapper = ({ children }: { children: ReactNode }) => <WorkbenchProvider>{children}</WorkbenchProvider>;

describe("WorkbenchProvider explicit reconnect", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.useFakeTimers();
    vi.mocked(getRun).mockImplementation(async id => runSnapshot(id, "interrupted"));
    vi.mocked(getRunView).mockImplementation(async id => runView(id));
  });
  afterEach(() => vi.useRealTimers());

  it("restarts a same-ID terminal stream and invalidates its cached view in one React batch", async () => {
    const { result } = renderHook(useWorkbenchStore, { wrapper });
    act(() => result.current.selectRun("resume_same"));
    await act(async () => {});
    await act(async () => {
      vi.mocked(openRunStream).mock.calls.at(-1)![2].onClose?.();
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(result.current.stream.status).toBe("closed");
    await act(async () => {});
    const updated = runView("resume_same");
    updated.terminal = false; updated.view.run.status = "running";
    vi.mocked(getRun).mockResolvedValue(runSnapshot("resume_same"));
    vi.mocked(getRunView).mockResolvedValue(updated);
    await act(async () => result.current.reconnectRun("resume_same"));
    expect(result.current.run_id).toBe("resume_same");
    expect(result.current.stream.status).toBe("replaying");
    expect(result.current.stream.state?.meta.status).toBe("running");
    expect(result.current.view.view?.view.run.status).toBe("running");
    expect(openRunStream).toHaveBeenCalledTimes(2);
  });

  it("ignores a resume completion for a run that is no longer selected", async () => {
    const { result } = renderHook(useWorkbenchStore, { wrapper });
    act(() => result.current.selectRun("resume_old"));
    await act(async () => {});
    act(() => result.current.selectRun("resume_new"));
    await act(async () => {});
    await act(async () => result.current.reconnectRun("resume_old"));
    expect(result.current.run_id).toBe("resume_new");
    expect(result.current.stream.state?.meta.run_id).toBe("resume_new");
    expect(openRunStream).toHaveBeenCalledTimes(2);
  });
});
