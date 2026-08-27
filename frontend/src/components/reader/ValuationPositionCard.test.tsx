import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ValuationAssessmentDTO } from "../../api/contracts";
import { ValuationPositionCard } from "./ValuationPositionCard";

const basePercentile = (label: string, percentile: number): ValuationAssessmentDTO["positions"][number] => ({
  window_label: label,
  percentile,
  sample_size: 700,
  excluded_nonpositive: 0,
  bucket: "lower_mid_band",
});

function assessment(
  overrides: Partial<ValuationAssessmentDTO> = {},
): ValuationAssessmentDTO {
  return {
    schema_version: "valuation-assessment-v1",
    assessment_id: "valuation:run-1:2026-08-20",
    run_id: "run-1",
    ticker: "600519.SH",
    as_of: "2026-08-20",
    created_at_note: "",
    current_price: 1500,
    total_market_cap_yi: 18800,
    positions: [basePercentile("pe_756d", 32)],
    week52_position: null,
    peer_relation: "not_assessable",
    anchor_outputs: [
      {
        anchor_id: "history_pe_band",
        method_label_zh: "自身历史市盈率区间",
        multiple_kind: "pe_ttm",
        status: "available",
        reason_code: null,
        earnings_base: { metric_id: "net_income", value_yi: 862, period: "2025-12-31" },
        multiple_low: 17.5,
        multiple_high: 32.5,
        implied_value_low_yi: 15085,
        implied_value_high_yi: 28015,
        per_share_low: 1203.59,
        per_share_high: 2235.91,
        assumptions: ["以最新已披露年度净利润为基数"],
        invalidation: "年报重大变化后失效。",
      },
      {
        anchor_id: "peer_pe_band",
        method_label_zh: "同行市盈率区间",
        multiple_kind: "pe_ttm",
        status: "unavailable",
        reason_code: "verified_peer_valuations_unavailable",
        earnings_base: null,
        multiple_low: null,
        multiple_high: null,
        implied_value_low_yi: null,
        implied_value_high_yi: null,
        per_share_low: null,
        per_share_high: null,
        assumptions: [],
        invalidation: null,
      },
    ],
    synthesis: {
      status: "available",
      reference_low_yi: 15085,
      reference_high_yi: 28015,
      per_share_low: 1203.59,
      per_share_high: 2235.91,
      contributing_anchor_ids: ["history_pe_band"],
      disagreement_note_zh: null,
      method_note_zh: "合成规则：history_pe_band（单锚，未做交叉验证）。",
    },
    verdict: {
      range_position: "within_range",
      deviation_pct: -1.2,
      overall_label_zh: "现价处于参考区间之内（位于区间中位附近 -1.2%）。",
      fact_notes_zh: ["现价位于自身 52 周收盘分布的第 88 百分位。"],
    },
    input_reasons: [],
    ...overrides,
  };
}

describe("ValuationPositionCard", () => {
  afterEach(cleanup);

  it("renders the headline verdict and reference interval band", () => {
    render(<ValuationPositionCard assessment={assessment()} />);
    expect(screen.getByText("估值定位")).toBeTruthy();
    expect(screen.getByText(/现价处于参考区间之内/)).toBeTruthy();
    const svg = document.querySelector(".reader-valuation__range-svg");
    expect(svg).not.toBeNull();
    expect(screen.getByText(/每股约 1203\.59–2235\.91 元/)).toBeTruthy();
  });

  it("shows unavailable reasons when the chain degrades", () => {
    render(
      <ValuationPositionCard
        assessment={assessment({
          verdict: {
            range_position: "unavailable",
            deviation_pct: null,
            overall_label_zh: "参考区间不可用，暂不能判断价格相对位置。",
            fact_notes_zh: [],
          },
          synthesis: {
            status: "unavailable",
            reference_low_yi: null,
            reference_high_yi: null,
            per_share_low: null,
            per_share_high: null,
            contributing_anchor_ids: ["history_pe_band"],
            disagreement_note_zh: "没有可用锚点，无法给出参考区间。",
            method_note_zh: "合成规则：全部锚点不可用时整体降级。",
          },
        })}
      />,
    );
    expect(screen.getByText("无法判断")).toBeTruthy();
    expect(screen.getByText(/没有可用锚点/)).toBeTruthy();
    // No range band when synthesis is unavailable.
    expect(document.querySelector(".reader-valuation__range-svg")).toBeNull();
  });

  it("renders percentile bars with Chinese bucket labels", () => {
    render(<ValuationPositionCard assessment={assessment()} />);
    expect(screen.getByText(/第 32 百分位 · 中低带/)).toBeTruthy();
  });

  it("keeps the research-reference disclaimer visible", () => {
    render(<ValuationPositionCard assessment={assessment()} />);
    expect(screen.getByText(/研究参考而非操作建议/)).toBeTruthy();
  });
});
