/**
 * Bug 1 回归测试：onClose 重连不应清空已重放的 turns。
 *
 * useRunStream 的 onClose 重连分支曾调用 dispatch({type:"snapshot"})，
 * 而 reducer 的 snapshot action 返回 createInitialState(snapshot) —— 只有
 * meta+roles 的骨架，导致查看历史 run 时 timeline 在 ~800ms 后突然消失。
 *
 * 修复：历史 terminal run 也只读重放一次事件流，保留事实层 turns/artifacts，
 * 不会重新运行分析；onClose 重连时不再 dispatch(snapshot)。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { PersistedEventDTO, RunSnapshotDTO } from "../api/contracts";

interface CapturedHandlers {
  onEvent: (e: PersistedEventDTO) => void;
  onClose: () => void;
  onError: (e: Error) => void;
}

// vi.mock factories are hoisted above imports, so shared state must live
// inside vi.hoisted to be referenceable from the factory closures.
const mocks = vi.hoisted(() => {
  const getRunMock = vi.fn();
  const closeMock = vi.fn();
  const state: { handlers: CapturedHandlers | null } = { handlers: null };
  return {
    getRunMock,
    closeMock,
    getHandlers: (): CapturedHandlers | null => state.handlers,
    setHandlers: (h: CapturedHandlers | null): void => {
      state.handlers = h;
    },
    resetHandlers: (): void => {
      state.handlers = null;
    },
  };
});

vi.mock("../api/client", () => ({ getRun: mocks.getRunMock }));

vi.mock("../api/eventSource", () => ({
  openRunStream: vi.fn(
    (_runId: string, _after: number, handlers: CapturedHandlers) => {
      mocks.setHandlers(handlers);
      return { close: mocks.closeMock };
    },
  ),
}));

import { useRunStream } from "./useRunStream";

function snap(
  run_id: string,
  status: string,
  latest_sequence: number,
): RunSnapshotDTO {
  return {
    run_id,
    status: status as RunSnapshotDTO["status"],
    ticker: "600519.SS",
    asset_type: "stock",
    analysis_date: "2026-07-21",
    selected_analysts: ["market"],
    max_debate_rounds: 1,
    max_risk_discuss_rounds: 1,
    output_language: "Chinese",
    llm_provider: "deepseek",
    quick_think_llm: "deepseek-chat",
    deep_think_llm: "deepseek-reasoner",
    configured_keys: {},
    created_at: "2026-07-21T12:00:00Z",
    updated_at: "2026-07-21T12:00:00Z",
    latest_sequence,
    artifacts: [],
    redaction_manifest: [],
    event_schema_version: 1,
    metadata: {},
  };
}

function ev(
  run_id: string,
  seq: number,
  type: string,
  payload: Record<string, unknown>,
): PersistedEventDTO {
  return {
    event_id: `${run_id}:${seq}`,
    run_id,
    sequence: seq,
    timestamp: `2026-07-21T12:00:${String(seq).padStart(2, "0")}Z`,
    type,
    payload,
    schema_version: 1,
  };
}

function runStarted(run_id: string, seq = 1): PersistedEventDTO {
  return ev(run_id, seq, "run.started", {
    run_status: "running",
    ticker: "600519.SS",
    asset_type: "stock",
    analysis_date: "2026-07-21",
    selected_analysts: ["market"],
    research_depth: 1,
    max_debate_rounds: 1,
    max_risk_discuss_rounds: 1,
    output_language: "Chinese",
    llm_provider: "deepseek",
    quick_think_llm: "deepseek-chat",
    deep_think_llm: "deepseek-reasoner",
    checkpoint_enabled: false,
  });
}

describe("useRunStream Bug 1: onClose reconnect preserves state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.getRunMock.mockReset();
    mocks.closeMock.mockReset();
    mocks.resetHandlers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("turns present before onClose survive the reconnect", async () => {
    mocks.getRunMock.mockResolvedValue(snap("run_bug1", "running", 0));
    const { result } = renderHook(() => useRunStream("run_bug1"));

    // 让 getRun promise resolve + streamFrom 注册 subscription
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.getHandlers()).not.toBeNull();;

    // 重放事件，填充 turns
    await act(async () => {
      mocks.getHandlers()!.onEvent(runStarted("run_bug1", 1));
      mocks.getHandlers()!.onEvent(
        ev("run_bug1", 2, "turn.started", {
          role_instance_id: "run_bug1:analyst.market",
          turn_id: "t1",
          graph_task_id: "gt1",
          graph_step: 1,
          turn_index: 1,
          turn_status: "started",
        }),
      );
      mocks.getHandlers()!.onEvent(
        ev("run_bug1", 3, "turn.output_ready", {
          role_instance_id: "run_bug1:analyst.market",
          turn_id: "t1",
          graph_task_id: "gt1",
          graph_step: 1,
          turn_index: 1,
          turn_status: "output_ready",
          artifact_id: "data:abc123",
        }),
      );
    });

    expect(Object.keys(result.current.state!.turns).length).toBe(1);

    // 模拟 stream 关闭。第二次 getRun 返回 completed（terminal）。
    mocks.getRunMock.mockResolvedValue(snap("run_bug1", "completed", 3));
    await act(async () => {
      mocks.getHandlers()!.onClose();
    });

    // 推进超过首档退避延迟（500ms）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });

    // Bug 1: onClose 重连曾 dispatch(snapshot) 清空 turns -> length 0
    // 修复后: turns 保留 -> length 1
    expect(Object.keys(result.current.state!.turns).length).toBe(1);
  });

  it("terminal history replays persisted facts once and closes", async () => {
    mocks.getRunMock.mockResolvedValue(snap("run_term", "completed", 3));
    const { result } = renderHook(() => useRunStream("run_term"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(mocks.getHandlers()).not.toBeNull();
    expect(result.current.status).toBe("replaying");

    await act(async () => {
      mocks.getHandlers()!.onEvent(ev("run_term", 3, "run.completed", { run_status: "completed" }));
      mocks.getHandlers()!.onClose();
      await vi.advanceTimersByTimeAsync(900);
    });

    expect(result.current.status).toBe("closed");
  });
});

describe("useRunStream symmetric error handling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.getRunMock.mockReset();
    mocks.closeMock.mockReset();
    mocks.resetHandlers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fails fast on a 4xx stream error without reconnecting", async () => {
    mocks.getRunMock.mockResolvedValue(snap("run_4xx", "running", 0));
    const { result } = renderHook(() => useRunStream("run_4xx"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.getHandlers()).not.toBeNull();

    // eventSource 把非 2xx 包成带 status 的 SseHttpError。
    await act(async () => {
      mocks.getHandlers()!.onError(
        Object.assign(new Error("SSE HTTP 404"), { name: "SseHttpError", status: 404 }),
      );
    });
    expect(result.current.status).toBe("error");

    // 推进远超全部退避窗口：不允许任何重连尝试。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(mocks.getRunMock).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("error");
  });

  it("recovers a transient stream error through the shared backoff path", async () => {
    mocks.getRunMock.mockResolvedValue(snap("run_5xx", "running", 0));
    const { result } = renderHook(() => useRunStream("run_5xx"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.getHandlers()).not.toBeNull();

    // 无 status 属性的传输层错误：不再直接终局，而是进入与 onClose
    // 相同的快照判定 + 指数退避路径。
    await act(async () => {
      mocks.getHandlers()!.onError(new Error("SSE stream error: socket hang up"));
    });
    expect(result.current.status).not.toBe("error");

    mocks.getRunMock.mockResolvedValue(snap("run_5xx", "completed", 0));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(mocks.getRunMock).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("closed");
  });
});

describe("useRunStream snapshot recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers(); mocks.getRunMock.mockReset(); mocks.closeMock.mockReset(); mocks.resetHandlers();
  });
  afterEach(() => vi.useRealTimers());

  it("continues backoff after a transient reconnect snapshot failure and recovers", async () => {
    mocks.getRunMock.mockResolvedValueOnce(snap("outage", "running", 0));
    mocks.getRunMock.mockRejectedValueOnce(new Error("temporary outage"));
    mocks.getRunMock.mockResolvedValueOnce(snap("outage", "completed", 0));
    const { result } = renderHook(() => useRunStream("outage"));
    await act(async () => {});
    await act(async () => { mocks.getHandlers()!.onClose(); await vi.advanceTimersByTimeAsync(500); });
    expect(result.current.status).not.toBe("error");
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(result.current.status).toBe("closed");
    expect(result.current.error).toBeNull();
  });

  it("stops after the bounded retry budget when snapshots stay unavailable", async () => {
    mocks.getRunMock.mockResolvedValueOnce(snap("exhausted", "running", 0));
    mocks.getRunMock.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useRunStream("exhausted"));
    await act(async () => {});
    await act(async () => { mocks.getHandlers()!.onClose(); await vi.advanceTimersByTimeAsync(200_000); });
    expect(result.current.status).toBe("error");
    expect(result.current.error?.message).toMatch(/too many times/);
    expect(mocks.getRunMock).toHaveBeenCalledTimes(21);
    await act(async () => vi.advanceTimersByTimeAsync(100_000));
    expect(mocks.getRunMock).toHaveBeenCalledTimes(21);
  });

  it("does not retry a permanent snapshot rejection", async () => {
    mocks.getRunMock.mockResolvedValueOnce(snap("deleted", "running", 0));
    mocks.getRunMock.mockRejectedValue(Object.assign(new Error("deleted"), { status: 404 }));
    const { result } = renderHook(() => useRunStream("deleted"));
    await act(async () => {});
    await act(async () => { mocks.getHandlers()!.onClose(); await vi.advanceTimersByTimeAsync(60_000); });
    expect(result.current.status).toBe("error");
    expect(result.current.error?.message).toBe("deleted");
    expect(mocks.getRunMock).toHaveBeenCalledTimes(2);
  });

  it("cancels the old run retry and ignores its late snapshot after switching", async () => {
    let finish!: (next: RunSnapshotDTO) => void;
    mocks.getRunMock.mockResolvedValueOnce(snap("old", "running", 0));
    mocks.getRunMock.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    mocks.getRunMock.mockResolvedValueOnce(snap("new", "running", 0));
    const { result, rerender } = renderHook(({ id }) => useRunStream(id), { initialProps: { id: "old" } });
    await act(async () => {});
    await act(async () => { mocks.getHandlers()!.onClose(); await vi.advanceTimersByTimeAsync(500); });
    rerender({ id: "new" });
    await act(async () => {});
    await act(async () => finish(snap("old", "completed", 0)));
    expect(result.current.state?.meta.run_id).toBe("new");
    expect(result.current.status).toBe("replaying");
  });
  it.each([408, 429])("retries a temporary HTTP %i snapshot rejection and reaches the terminal state", async (status) => {
    mocks.getRunMock.mockResolvedValueOnce(snap(`temporary_${status}`, "running", 0));
    mocks.getRunMock.mockRejectedValueOnce(Object.assign(new Error("temporary HTTP failure"), { status }));
    mocks.getRunMock.mockResolvedValueOnce(snap(`temporary_${status}`, "completed", 0));
    const { result } = renderHook(() => useRunStream(`temporary_${status}`));
    await act(async () => {});
    await act(async () => { mocks.getHandlers()!.onClose(); await vi.advanceTimersByTimeAsync(1500); });
    expect(result.current.status).toBe("closed");
    expect(result.current.error).toBeNull();
    expect(mocks.getRunMock).toHaveBeenCalledTimes(3);
  });

  it.each([408, 429])("recovers from a temporary HTTP %i stream rejection", async (status) => {
    mocks.getRunMock.mockResolvedValueOnce(snap(`stream_${status}`, "running", 0));
    mocks.getRunMock.mockResolvedValueOnce(snap(`stream_${status}`, "completed", 0));
    const { result } = renderHook(() => useRunStream(`stream_${status}`));
    await act(async () => {});
    await act(async () => {
      mocks.getHandlers()!.onError(Object.assign(new Error("temporary HTTP failure"), { status }));
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(result.current.status).toBe("closed");
    expect(result.current.error).toBeNull();
  });

});
