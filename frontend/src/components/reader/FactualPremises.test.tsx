import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PremiseContext, PremiseLedger } from "./FactualPremises";
import { ExplainedText } from "./PlainExplanation";
import type { PremiseReceiptV1DTO } from "../../api/contracts";

const entry: PremiseReceiptV1DTO & { text: string } = {
  policy: "factual-premises-v1", status: "interpretation",
  text: "解释假设：收入扩张尚未转化为盈利",
  observations: [{
    observation_id: "o.revenue", kind: "comparison",
    text: "营业收入：本期较上年同期金额增加。",
    fact_ids: ["f.revenue"], evidence_ids: ["e.income"],
    anchor_id: "n.revenue.difference", limitations: ["数值关系不证明原因或持续性"],
  }],
  pending_questions: ["销售费用是否增加？"],
};

describe("factual premise delivery", () => {
  it("keeps pending premises visible beside the interpretation and source detail", () => {
    render(<PremiseContext.Provider value={[entry]}>
      <ExplainedText target="claim:test" text={entry.text}/>
    </PremiseContext.Provider>);
    expect(screen.getByText(entry.text)).toBeInTheDocument();
    expect(screen.getByText("销售费用是否增加？")).toBeInTheDocument();
    expect(screen.getByText("待验证前提 · 不作为已发生事实")).toBeInTheDocument();
    expect(screen.getByText(entry.observations[0].text)).toBeInTheDocument();
    expect(screen.getByText("e.income")).toBeInTheDocument();
    expect(screen.getByText(/解释的含义和因果尚未证实/)).toBeInTheDocument();
  });

  it("shows stage bindings without presenting them as a final conclusion", () => {
    render(<PremiseLedger entries={[entry]}/>);
    expect(screen.getByText("观察、解释与待验证前提")).toBeInTheDocument();
    expect(screen.getByText("销售费用是否增加？")).toBeInTheDocument();
    expect(screen.queryByText("事实已验证")).not.toBeInTheDocument();
  });

  it("does not attach new guarantees to a historical statement with no receipt", () => {
    render(<ExplainedText target="claim:legacy" text="旧报告原文"/>);
    expect(screen.getByText("旧报告原文")).toBeInTheDocument();
    expect(screen.queryByText(/已有观察与依据/)).not.toBeInTheDocument();
    expect(screen.queryByText(/待验证前提/)).not.toBeInTheDocument();
  });
});
