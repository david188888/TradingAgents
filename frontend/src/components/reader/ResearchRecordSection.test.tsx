import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import savedRecord from "../../../../shared_fixtures/research-record.json";
import type { ResearchAssessmentV1DTO, ResearchRecordResponseDTO } from "../../api/contracts";
import { ResearchRecordSection, SourceContent } from "./ResearchRecordSection";

const response = savedRecord as ResearchRecordResponseDTO;
if (response.state !== "ready") throw new Error("invalid fixture");
const record = response.record;
const assessment: ResearchAssessmentV1DTO = {
  schema_version: "research-assessment-v1",
  input_snapshot_id: record.snapshots[0].snapshot_id,
  research_question: "经营改善是否值得继续跟踪？",
  judgement: "改善有事实依据，但持续性仍待核查。",
  dimensions: [
    { dimension: "operating_quality", status: "conditional", judgement: "收入改善，持续性未确认", claim_ids: ["i1"], challenge_ids: ["c1"], limitations: [] },
    { dimension: "valuation", status: "unresolved", judgement: "无法判断估值", claim_ids: [], challenge_ids: [], limitations: ["未取得合格估值资料"] },
    { dimension: "market_context", status: "supported", judgement: "历史收益背景可复核", claim_ids: ["f1"], challenge_ids: [], limitations: [] },
  ],
  key_claim_ids: ["i1"],
  primary_challenge_id: "c1",
  next_check: "核对下一期收入分项和利润率。",
  challenge_assessments: [{ challenge_id: "c1", outcome: "unresolved", rationale: "条件核查不足以证明经营持续性" }],
  completeness: "partial",
  quality: "LOW_CONFIDENCE",
  forward_window_calendar_days: null,
  limitations: ["经营分项覆盖不足"],
};

describe("saved research records", () => {
  it("keeps a positive return quantile signed and isolates unavailable beta", () => {
    render(<ResearchRecordSection runId={record.run_id} response={response} loading={false} error={false} />);
    expect(screen.getByText("1.2%")).toBeVisible();
    expect(screen.getByText("暂不可用")).toBeVisible();
    expect(screen.getByText(/未取得符合口径的基准行情/)).toBeInTheDocument();
    expect(screen.getByText(/尚未执行独立工具验证/)).toBeInTheDocument();
    expect(screen.queryByText(/已验证/)).toBeNull();
    expect(screen.queryByRole("region", { name: "研究简报" })).toBeNull();
  });

  it("does not show another run's record even when the endpoint wrapper matches", () => {
    const wrong = { ...response, run_id: "new-run", record };
    const { container } = render(<ResearchRecordSection runId="new-run" response={wrong} loading={false} error={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("puts saved content before its locator and renders markup as text", () => {
    const evidence = { ...record.evidence[0], content: { ...record.evidence[0].content!, text: "<img src=x onerror=alert(1)>收入增长" } };
    const { container } = render(<SourceContent evidence={evidence} />);
    const text = container.textContent!;
    expect(text.indexOf("收入增长")).toBeLessThan(text.indexOf("经营概况"));
    expect(container.querySelector("img")).toBeNull();
  });

  it("never substitutes a source name for missing original content", () => {
    render(<SourceContent evidence={{ ...record.evidence[0], content: null }} />);
    expect(screen.getByText("来源内容未保存")).toBeInTheDocument();
    expect(screen.getByText(/无法展示原文/)).toBeInTheDocument();
  });

  it("limits a numeric result to its specified condition", () => {
    const verified = { ...response, record: { ...record, verifications: [{
      verification_id: "check", challenge_id: "challenge", input_snapshot_id: "v0", output_snapshot_id: "v1",
      method: "calculation" as const, status: "supports" as const, evidence_ids: ["derived"],
      executed_at: "2026-09-30T00:00:00Z", result: "指定条件满足",
      scope: "predicate_only" as const, hypothesis_id: "hypothesis", plan_sha256: "a".repeat(64),
      condition_role: "necessary" as const, condition_text: "同期收入增长超过 10%",
    }] } };
    render(<ResearchRecordSection runId={record.run_id} response={verified} loading={false} error={false} />);
    expect(screen.getByText("条件核查 · 支持")).toBeInTheDocument();
    expect(screen.getByText(/核查条件：同期收入增长超过 10%/)).toBeInTheDocument();
    expect(screen.getByText(/不证明整条假设，也不自动关闭挑战/)).toBeInTheDocument();
    expect(screen.queryByText(/验证执行 · 支持/)).toBeNull();
  });

  it("shows the native judgement, evidence, risk and next check before the quantitative background", () => {
    render(<ResearchRecordSection runId={record.run_id} response={{ ...response, record: { ...record, assessment } }} loading={false} error={false} />);
    const brief = screen.getByRole("region", { name: "研究简报" });
    expect(screen.getByText(assessment.judgement)).toBeVisible();
    expect(screen.getAllByText("推断 · 改善可能延续")[0]).toBeVisible();
    expect(screen.getAllByText("改善是否只来自一次性事项")[0]).toBeVisible();
    expect(screen.getByText(assessment.next_check)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("部分研究");
    const quantitative = screen.getByRole("region", { name: "量化摘要" });
    expect(brief.compareDocumentPosition(quantitative) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("1.2%")).toBeVisible();
    expect(screen.getByText(/共 1 项关键挑战尚未解决/)).toBeVisible();
    expect(screen.getByText(/关键挑战 · 尚未解决：条件核查不足以证明经营持续性/)).toBeVisible();
    expect(screen.queryByText(/展望 84/)).toBeNull();
  });

  it("traces an inferred key claim through its supporting fact to saved source content", () => {
    const { container } = render(<ResearchRecordSection runId={record.run_id} response={{ ...response, record: { ...record, assessment } }} loading={false} error={false} />);
    const keyClaim = container.querySelector('[aria-label="研究简报"] [data-claim="i1"]')!;
    expect(keyClaim.textContent).toContain("支撑事实：披露收入上升");
    expect(keyClaim.textContent).toContain("收入增长，但利润率下降。");
    expect(keyClaim.textContent!.indexOf("收入增长，但利润率下降。")).toBeLessThan(keyClaim.textContent!.indexOf("经营概况 · 第 8 页"));
    expect(screen.getByText("估值 · 待核查")).toBeInTheDocument();
    expect(screen.getByText("未取得合格估值资料")).toBeInTheDocument();
  });

  it("displays all critical challenge counts even when the primary challenge is less severe", () => {
    const secondary = { ...record.challenges[0], challenge_id: "c2", statement: "尚未确认的治理事项" };
    render(<ResearchRecordSection runId={record.run_id} response={{ ...response, record: { ...record, assessment, challenges: [{ ...record.challenges[0], severity: "minor" }, secondary] } }} loading={false} error={false} />);
    expect(screen.getByText(/共 1 项关键挑战尚未解决/)).toBeVisible();
    expect(screen.getByText("尚未确认的治理事项")).toBeInTheDocument();
  });

  it("keeps absent key evidence explicit and renders native model text safely", () => {
    const unsafe = { ...assessment, judgement: "<img src=x onerror=alert(1)>待核查", key_claim_ids: [], primary_challenge_id: null, forward_window_calendar_days: 84 as const };
    const { container } = render(<ResearchRecordSection runId={record.run_id} response={{ ...response, record: { ...record, mode: "catalyst_research", assessment: unsafe, challenges: [] } }} loading={false} error={false} />);
    expect(screen.getByText(unsafe.judgement)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("当前没有可展示的重点依据。")).toBeVisible();
    expect(screen.getByText(/不代表不存在风险/)).toBeVisible();
    expect(screen.getByText(/展望 84 个日历日/)).toBeVisible();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
