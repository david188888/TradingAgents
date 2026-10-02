import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import savedRecord from "../../../../shared_fixtures/research-record.json";
import type { ResearchRecordResponseDTO } from "../../api/contracts";
import { ResearchRecordSection, SourceContent } from "./ResearchRecordSection";

const response = savedRecord as ResearchRecordResponseDTO;
if (response.state !== "ready") throw new Error("invalid fixture");
const record = response.record;

describe("saved research records", () => {
  it("keeps a positive return quantile signed and isolates unavailable beta", () => {
    render(<ResearchRecordSection runId={record.run_id} response={response} loading={false} error={false} />);
    expect(screen.getByText("1.2%")).toBeVisible();
    expect(screen.getByText("暂不可用")).toBeVisible();
    expect(screen.getByText(/未取得符合口径的基准行情/)).toBeInTheDocument();
    expect(screen.getByText(/尚未执行独立工具验证/)).toBeInTheDocument();
    expect(screen.queryByText(/已验证/)).toBeNull();
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
});
