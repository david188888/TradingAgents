import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanionDTO } from "./contracts";
import { getCompanion } from "./client";

const response: CompanionDTO = {
  schema_version: 1,
  run_id: "run_companion",
  selection: { kind: "claim", id: "claim /? 中文" },
  summary: "摘要",
  actual_coverage: ["来源：年报"],
  conclusion_impact: "支持当前研究结论",
  next_validation: "下一期复核",
};

describe("getCompanion", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("encodes the public selection without interpolating it into the path", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      getCompanion("run_companion", { kind: "claim", id: "claim /? 中文" }),
    ).resolves.toEqual(response);

    const requestUrl = new URL(String(fetchMock.mock.calls[0]?.[0]), "http://localhost");
    expect(requestUrl.pathname).toBe("/api/runs/run_companion/reader/companion");
    expect(requestUrl.searchParams.get("kind")).toBe("claim");
    expect(requestUrl.searchParams.get("id")).toBe("claim /? 中文");
  });

  it("rejects an unsafe run id before calling fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");

    expect(() =>
      getCompanion("../other-run", { kind: "role", id: "market" }),
    ).toThrow(RangeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
