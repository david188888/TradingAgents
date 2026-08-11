import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReaderEvidenceRefDTO, ThesisDiffDTO } from "../../api/contracts";
import { ThesisDiffSection } from "./ThesisDiffSection";

const evidenceRefs: ReaderEvidenceRefDTO[] = [
  {
    ref_id: "public-ref-counter",
    source_label: "2026 半年报",
    resolution_status: "available",
  },
];

function diffFixture(overrides: Partial<ThesisDiffDTO> = {}): ThesisDiffDTO {
  return {
    schema_version: 1,
    run_id: "run-current",
    ticker: "000338.SZ",
    horizon: "medium",
    previous_run_id: "run-previous",
    baseline_completed_at: "2026-07-28T08:30:00Z",
    entries: [
      {
        claim_key: "market.price.trend.primary",
        diff_kind: "new",
        previous_claim_type: null,
        current_claim_type: "fact",
        previous_text: null,
        current_text: "出现新的价格趋势证据。",
        previous_confidence: null,
        current_confidence: 0.72,
        previous_lifecycle_status: null,
        current_lifecycle_status: "active",
        change_flags: [],
        counter_evidence_ref_ids: [],
      },
      {
        claim_key: "fundamentals.margin.trend.primary",
        diff_kind: "maintained",
        previous_claim_type: "inference",
        current_claim_type: "inference",
        previous_text: "利润率保持稳定。",
        current_text: "利润率韧性增强。",
        previous_confidence: 0.55,
        current_confidence: 0.68,
        previous_lifecycle_status: "active",
        current_lifecycle_status: "active",
        change_flags: ["text_changed", "evidence_changed", "confidence_changed"],
        counter_evidence_ref_ids: [],
      },
      {
        claim_key: "news.demand.outlook.primary",
        diff_kind: "invalidated",
        previous_claim_type: "inference",
        current_claim_type: "inference",
        previous_text: "需求将快速恢复。",
        current_text: "半年报反证了需求快速恢复。",
        previous_confidence: 0.7,
        current_confidence: 0.8,
        previous_lifecycle_status: "active",
        current_lifecycle_status: "invalidated",
        change_flags: ["text_changed", "evidence_changed", "status_changed"],
        counter_evidence_ref_ids: ["public-ref-counter", "unresolved-private-ref"],
      },
      {
        claim_key: "sentiment.channel.signal.primary",
        diff_kind: "unresolved",
        previous_claim_type: "fact",
        current_claim_type: "unknown",
        previous_text: "渠道情绪改善。",
        current_text: "渠道样本仍不足。",
        previous_confidence: 0.6,
        current_confidence: null,
        previous_lifecycle_status: "active",
        current_lifecycle_status: "active",
        change_flags: ["text_changed", "confidence_changed"],
        counter_evidence_ref_ids: [],
      },
      {
        claim_key: "market.volume.structure.primary",
        diff_kind: "not_reassessed",
        previous_claim_type: "fact",
        current_claim_type: null,
        previous_text: "成交结构偏向机构。",
        current_text: null,
        previous_confidence: 0.64,
        current_confidence: null,
        previous_lifecycle_status: "active",
        current_lifecycle_status: null,
        change_flags: [],
        counter_evidence_ref_ids: [],
      },
    ],
    ...overrides,
  };
}

describe("ThesisDiffSection", () => {
  it("renders five explicit states, change dimensions, and only public counter-evidence labels", () => {
    const wireDiff = {
      ...diffFixture(),
      current_research_case_artifact_id: "private-current-artifact-id",
      previous_research_case_artifact_id: "private-previous-artifact-id",
    } as ThesisDiffDTO;
    render(<ThesisDiffSection diff={wireDiff} evidenceRefs={evidenceRefs} />);

    const section = screen.getByRole("region", { name: "论点变化" });
    for (const label of ["新增", "延续", "已被反证", "仍待确认", "本轮未复核"]) {
      expect(within(section).getAllByText(label)).toHaveLength(2);
    }
    for (const flag of ["表述变化", "证据变化", "置信度变化", "状态变化"]) {
      expect(within(section).getAllByText(flag).length).toBeGreaterThan(0);
    }
    expect(within(section).getByText("反证来源：2026 半年报")).toBeInTheDocument();
    expect(section).not.toHaveTextContent("public-ref-counter");
    expect(section).not.toHaveTextContent("unresolved-private-ref");
    expect(section).not.toHaveTextContent("private-current-artifact-id");
    expect(section).not.toHaveTextContent("private-previous-artifact-id");
  });

  it("distinguishes a first baseline from an unavailable diff", () => {
    const { rerender } = render(
      <ThesisDiffSection
        diff={diffFixture({ previous_run_id: null, baseline_completed_at: null })}
        evidenceRefs={[]}
      />,
    );
    expect(screen.getByText("首次建立研究基线")).toBeInTheDocument();

    rerender(<ThesisDiffSection diff={null} evidenceRefs={[]} />);
    expect(screen.getByText("本轮未生成可比较的论点变化")).toBeInTheDocument();
    expect(screen.queryByText("首次建立研究基线")).not.toBeInTheDocument();
  });
});
