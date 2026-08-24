import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RoundCard, researchLanes, riskLanes } from "./RoundCard";
import type { ResearchRoundSummaryDTO, RiskRoundSummaryDTO } from "../../api/contracts";

const RESEARCH_ROUND: ResearchRoundSummaryDTO = {
  round_index: 2,
  topic: "营收预测分歧",
  summary: "多方看好服务收入，空方担忧硬件周期。",
  keywords: ["服务收入", "iPhone 周期", "中国市场"],
  bull_summary: "多方重申 15% 增长",
  bear_summary: "空方引用渠道调研",
  bull_estimated_conviction: 0.9,
  bear_estimated_conviction: 0.75,
};

const RISK_ROUND: RiskRoundSummaryDTO = {
  round_index: 1,
  topic: "尾部风险",
  summary: "三方对监管风险看法不一。",
  keywords: ["监管", "集中度"],
  aggressive_summary: "可控",
  neutral_summary: "观察",
  conservative_summary: "高危",
};

describe("RoundCard", () => {
  it("renders topic, summary, keywords and lanes", () => {
    render(
      <RoundCard
        roundIndex={RESEARCH_ROUND.round_index}
        topic={RESEARCH_ROUND.topic}
        summary={RESEARCH_ROUND.summary}
        keywords={RESEARCH_ROUND.keywords}
        lanes={researchLanes(RESEARCH_ROUND)}
      />,
    );
    expect(screen.getByText("第 2 轮")).toBeInTheDocument();
    expect(screen.getByText("营收预测分歧")).toBeInTheDocument();
    expect(screen.getByText(/服务收入，空方/)).toBeInTheDocument();
    expect(screen.getByText("iPhone 周期")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    // Research conviction must be marked as an LLM estimate, never a measurement.
    expect(screen.getAllByText("摘要估计")).toHaveLength(2);
  });

  it("renders an em dash for null conviction without an estimate marker", () => {
    render(
      <RoundCard
        roundIndex={RISK_ROUND.round_index}
        topic={RISK_ROUND.topic}
        summary={RISK_ROUND.summary}
        keywords={RISK_ROUND.keywords}
        lanes={riskLanes(RISK_ROUND, null)}
      />,
    );
    // Three lanes with null measured conviction all render "—".
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByText("摘要估计")).not.toBeInTheDocument();
  });

  it("does not render a toggle when there is no L3 detail", () => {
    render(
      <RoundCard roundIndex={1} topic="T" summary="S" keywords={[]} />,
    );
    expect(screen.queryByRole("button", { name: /展开详情/ })).not.toBeInTheDocument();
  });

  it("lazy-mounts L3 detail only after expanding", () => {
    render(
      <RoundCard
        roundIndex={1}
        topic="T"
        summary="S"
        keywords={[]}
        detail={<div>full-text-body</div>}
      />,
    );
    expect(screen.queryByText("full-text-body")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /展开详情/ }));
    expect(screen.getByText("full-text-body")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /收起详情/ }));
    expect(screen.queryByText("full-text-body")).not.toBeInTheDocument();
  });

  it("renders a placeholder topic when the LLM returns an empty string", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<RoundCard roundIndex={1} topic="" summary="S" keywords={[]} />);
    expect(screen.getByText("未命名主题")).toBeInTheDocument();
  });
});
