import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { DebateJourneyDTO } from "../../api/contracts";
import { DebateTimeline } from "./DebateTimeline";

const JOURNEY: DebateJourneyDTO = {
  stages: [
    { stage_id: "analysts", status: "completed", rounds: null },
    { stage_id: "evidence", status: "completed", rounds: null },
    { stage_id: "research", status: "completed", rounds: 5 },
    { stage_id: "trading", status: "completed", rounds: null },
    { stage_id: "risk", status: "completed", rounds: 3 },
    { stage_id: "portfolio", status: "completed", rounds: null },
  ],
  research_rating: "Buy",
  disagreement_count: 2,
  risk_consensus: { conviction: -0.3, disagreement: "tight", abstained_roles: [] },
};

describe("DebateTimeline", () => {
  it("renders six stages with measured round counts", () => {
    render(
      <DebateTimeline journey={JOURNEY} selectedStage={null} onStageToggle={vi.fn()} />,
    );

    expect(screen.getByText("分析师")).toBeInTheDocument();
    expect(screen.getByText("证据门")).toBeInTheDocument();
    expect(screen.getByText("研究辩论")).toBeInTheDocument();
    expect(screen.getByText("风险辩论")).toBeInTheDocument();
    expect(screen.getByText("5 轮")).toBeInTheDocument();
    expect(screen.getByText("3 轮")).toBeInTheDocument();
    expect(screen.getByText("2 项关键分歧")).toBeInTheDocument();
  });

  it("marks the selected stage and toggles on click", () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <DebateTimeline journey={JOURNEY} selectedStage="research" onStageToggle={onToggle} />,
    );

    const researchButton = screen.getByRole("button", { name: /研究辩论/ });
    expect(researchButton).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(researchButton);
    expect(onToggle).toHaveBeenCalledWith("research");

    rerender(
      <DebateTimeline journey={JOURNEY} selectedStage={null} onStageToggle={onToggle} />,
    );
    expect(researchButton).toHaveAttribute("aria-pressed", "false");
  });

  it("disables waiting stages and keeps completed stages clickable", () => {
    const partial: DebateJourneyDTO = {
      ...JOURNEY,
      stages: [
        { stage_id: "analysts", status: "completed", rounds: null },
        { stage_id: "evidence", status: "running", rounds: null },
        { stage_id: "research", status: "waiting", rounds: null },
        { stage_id: "trading", status: "waiting", rounds: null },
        { stage_id: "risk", status: "waiting", rounds: null },
        { stage_id: "portfolio", status: "waiting", rounds: null },
      ],
    };
    render(<DebateTimeline journey={partial} selectedStage={null} onStageToggle={vi.fn()} />);

    expect(screen.getByRole("button", { name: /研究辩论/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /分析师/ })).not.toBeDisabled();
  });
});
