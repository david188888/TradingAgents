import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { InsightReportDTO } from "../../api/contracts";
import { InsightReader } from "./InsightReader";
import { NativeResearchPage } from "./NativeResearchPage";

vi.mock("../../hooks/useReportExplanation", () => ({ useReportExplanation: () => ({response: null, error: false}) }));

vi.mock("../../hooks/useReaderProcess", () => ({
  useReaderProcess: () => ({ response: null, error: false, retry: vi.fn() }),
  useReaderAgent: () => ({ response: null, error: false, retry: vi.fn() }),
}));

const report: InsightReportDTO = {
  schema_version: "insight-research-v1", construction: "native", run_id: "run-a", ticker: "002130.SZ",
  mode: "company_research", analysis_date: "2026-10-28", gaps: ["unreviewed_insights"], stages: {},
  catalogs: { operating_quality: { snapshot_id: "snapshot-a", evidence: [], numbers: [], sources: [{
    evidence_id: "source-a", source_name: "已保存公告", source_kind: "official", source_family_id: null,
    availability: "available", public_url: "https://example.com/report", published_at: null,
    usable_as_of: "2026-10-01T00:00:00Z", captured_at: null, limitations: [],
    content: { kind: "excerpt", text: "原始披露支持片段", locator_label: "第十页", content_sha256: "a".repeat(64), truncated: false },
  }] } },
  insights: [{ insight_id: "insight-a", role: "operating_quality", index: 0, revision: 1, snapshot_id: "snapshot-a", catalog_id: "operating_quality",
    status: "accepted", proposal: { claim: "客户结构仍需核查", reasoning: "需要后续披露", limitations: "资料不完整", evidence_refs: ["E1"] },
    rendered: { claim: "客户结构仍需核查", reasoning: "需要后续披露", limitations: "资料不完整" },
    fact_ids: ["fact-a"], source_ids: ["source-a"], numeric_ids: [], issues: [] }],
  reviews: [], responses: [], synthesis: null, focus_question: null, focus_insights: [], superseded_ids: [], search_requests: {},
};

describe("Insight Reader", () => {
  it.each(["review", "response"])("exposes saved counterevidence from a %s", (kind) => {
    const record = structuredClone(report);
    const source = {...record.catalogs.operating_quality.sources[0], evidence_id: "counter-source",
      source_name: "反证公告", content: {...record.catalogs.operating_quality.sources[0].content!, text: "反证的原始支持片段"}};
    record.catalogs.operating_quality.sources.push(source);
    record.catalogs.operating_quality.evidence.push({ref: "E2", fact_id: "counter-fact", text: "反证事实摘要", source_ids: [source.evidence_id]});
    const note = {...record.insights[0], insight_id: "review-note", fact_ids: ["counter-fact"], source_ids: [source.evidence_id]};
    if (kind === "review") record.reviews.push({target_id: "insight-a", status: "challenged", concern: "依据存在冲突", reasoning: "核查反证", source_ids: note.source_ids, note});
    else record.responses.push({target_id: "insight-a", action: "maintain", reasoning: "已核查反证", source_ids: note.source_ids, replacement_id: null, note});
    render(<InsightReader record={record}/>);
    expect(screen.getByText("反证的原始支持片段")).toBeTruthy();
    expect(screen.getByText("E2：反证事实摘要")).toBeTruthy();
  });

  it("keeps findings and source locations without manufacturing a stance", () => {
    render(<InsightReader record={report}/>);
    expect(screen.getByText("客户结构仍需核查")).toBeTruthy();
    expect(screen.getByText(/暂未形成总体判断/)).toBeTruthy();
    expect(screen.getByText("原始披露支持片段")).toBeTruthy();
    expect(screen.getByText(/第十页/)).toBeTruthy();
    expect(screen.getByText(/部分观点尚未完成审阅/)).toBeTruthy();
    expect(screen.queryByText("中性")).toBeNull();
  });

  it("routes the new public contract from the maintained research page", () => {
    render(<NativeResearchPage runId="run-a" ticker={report.ticker} status="completed" state={null}
      response={{ state: "insight_ready", schema_version: 1, run_id: "run-a", record: report }} loading={false} error={false}
      onOpenAudit={vi.fn()} onCancel={vi.fn()} onRetry={vi.fn()} onResume={vi.fn()} onNewResearch={vi.fn()}/>);
    expect(screen.getByText("客户结构仍需核查")).toBeTruthy();
    expect(screen.queryByText(/没有合格的已发布研究记录/)).toBeNull();
  });
});
