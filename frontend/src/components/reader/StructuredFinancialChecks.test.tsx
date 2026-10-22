import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { EvidenceChecksV1DTO, ResearchRecordV1DTO } from "../../api/contracts";
import saved from "../../test/fixtures/unified-research-v7.json";
import checks from "../../test/fixtures/structured-financial-checks-v3.json";
import { LocalEvidenceChecks } from "./ResearchRecordSection";

it("shows passed structured comparisons beside the unavailable complete cash bridge", () => {
  const inspect = vi.fn();
  const record: ResearchRecordV1DTO = { ...saved as ResearchRecordV1DTO, evidence_checks: checks as EvidenceChecksV1DTO };
  render(<LocalEvidenceChecks record={record} onInspect={inspect} />);
  expect(screen.getByText("利润与现金流同期比较 · 所需证据已核对")).toBeVisible();
  expect(screen.getByText("现金流桥核对 · 所需证据不足")).toBeVisible();
  const detail = screen.getByText("利润与现金流同期比较 · 所需证据已核对").closest("details")!;
  fireEvent.click(within(detail).getByText("利润与现金流同期比较 · 所需证据已核对"));
  expect(within(detail).getByText(/仅核对报表端点及其变化，不代表完整现金流调节桥/)).toBeVisible();
  expect(within(detail).getByText(/已有结构化财务核对，尚未与官方原表互证/)).toBeVisible();
  expect(within(detail).getByText(/2026-06-30 合并净利润：10 元/)).toBeVisible();
  expect(within(detail).queryByText(/structured_financial_comparison/)).toBeNull();
});
