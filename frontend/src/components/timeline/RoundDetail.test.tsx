import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RoundDetail } from "./RoundDetail";
import type { LaneSpec } from "./RoundDetail";

const mockUseArtifact = vi.fn();
vi.mock("../../hooks/useArtifact", () => ({
  useArtifact: (...args: unknown[]) => mockUseArtifact(...args),
}));

const RESEARCH_LANES: LaneSpec[] = [
  { lane: "bull", actor_id: "researcher.bull", label: "多方分析师", tone: "bull", artifact_id: "data:bull" },
  { lane: "bear", actor_id: "researcher.bear", label: "空方分析师", tone: "bear", artifact_id: "data:bear" },
];

const ARTIFACTS: Record<string, ReturnType<typeof artifactResult>> = {};

function artifactResult(content: string | null, error: string | null = null) {
  return {
    content,
    loading: content === null && error === null,
    error,
    reload: vi.fn(),
  };
}

describe("RoundDetail", () => {
  beforeEach(() => {
    mockUseArtifact.mockReset();
    mockUseArtifact.mockImplementation((_runId: string, artifactId: string) => {
      if (Object.prototype.hasOwnProperty.call(ARTIFACTS, artifactId)) {
        return ARTIFACTS[artifactId];
      }
      return { content: null, loading: false, error: "missing artifact", reload: vi.fn() };
    });
  });

  it("renders two lane columns and extracts response text from each artifact", async () => {
    ARTIFACTS["data:bull"] = artifactResult(
      JSON.stringify({ investment_debate_state: { current_response: "多方全文：服务收入增 15%" } }),
    );
    ARTIFACTS["data:bear"] = artifactResult(
      JSON.stringify({ investment_debate_state: { current_response: "空方全文：估值偏高" } }),
    );

    render(<RoundDetail runId="run_x" lanes={RESEARCH_LANES} />);

    expect(screen.getByText("多方分析师")).toBeInTheDocument();
    expect(screen.getByText("空方分析师")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/服务收入增 15%/)).toBeInTheDocument();
      expect(screen.getByText(/估值偏高/)).toBeInTheDocument();
    });
  });

  it("renders three columns for a risk round with the three-column class", () => {
    const riskLanes: LaneSpec[] = [
      { lane: "aggressive", actor_id: "risk.aggressive", label: "激进方", tone: "bull", artifact_id: "data:a" },
      { lane: "neutral", actor_id: "risk.neutral", label: "中性方", tone: "neutral", artifact_id: "data:n" },
      { lane: "conservative", actor_id: "risk.conservative", label: "保守方", tone: "bear", artifact_id: "data:c" },
    ];
    for (const lane of riskLanes) ARTIFACTS[lane.artifact_id] = artifactResult(null);

    const { container } = render(<RoundDetail runId="run_x" lanes={riskLanes} />);
    expect(screen.getByText("激进方")).toBeInTheDocument();
    expect(screen.getByText("中性方")).toBeInTheDocument();
    expect(screen.getByText("保守方")).toBeInTheDocument();
    expect(container.querySelector(".round-detail-three")).not.toBeNull();
    expect(screen.getAllByText("读取发言中…")).toHaveLength(3);
    for (const lane of riskLanes) delete ARTIFACTS[lane.artifact_id];
  });

  it("shows an error message when an artifact fails to load", async () => {
    ARTIFACTS["data:bull"] = artifactResult(null, "network down");
    ARTIFACTS["data:bear"] = artifactResult(
      JSON.stringify({ investment_debate_state: { current_response: "ok" } }),
    );

    render(<RoundDetail runId="run_x" lanes={RESEARCH_LANES} />);
    await waitFor(() => {
      expect(screen.getByText(/无法读取发言：network down/)).toBeInTheDocument();
    });
  });
});
