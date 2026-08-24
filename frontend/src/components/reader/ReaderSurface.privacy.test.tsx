import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReaderResponseDTO } from "../../api/contracts";
import { useReader } from "../../hooks/useReader";
import { ReaderSurface } from "./ReaderSurface";

vi.mock("../../hooks/useReader", () => ({ useReader: vi.fn() }));

const mockedUseReader = vi.mocked(useReader);

describe("ReaderSurface privacy", () => {
  beforeEach(() => {
    mockedUseReader.mockReset();
  });

  it("never copies unknown internal wire fields into the initial DOM", () => {
    const privateArtifact = "research-case-v2:" + "a".repeat(64);
    const privateLocator = "runs/private/raw-payload.json";
    const wireReader = {
      kind: "typed",
      schema_version: 2,
      run_id: "run-reader-privacy",
      mode: "company_research",
      ticker: "000338.SZ",
      horizon: "medium",
      as_of: "2026-08-10T00:00:00Z",
      availability: "partial",
      decision_eligibility: "none",
      evidence_verdict: "PASS",
      research_tilt: null,
      rating_confidence: null,
      claims: [],
      scenarios: null,
      catalysts: [],
      invalidation_conditions: [],
      review_plan: null,
      analyst_cards: [],
      data_quality: {
        level: "limited",
        degraded_capabilities: [],
        unavailable_capabilities: [],
        conflicts: [],
        coverage_ref_ids: [],
      },
      evidence_refs: [],
      coverage_refs: [],
      omissions: [],
      thesis_diff: {
        schema_version: 1,
        run_id: "run-reader-privacy",
        ticker: "000338.SZ",
        horizon: "medium",
        previous_run_id: null,
        baseline_completed_at: null,
        entries: [],
        current_research_case_artifact_id: privateArtifact,
        previous_research_case_artifact_id: privateArtifact,
      },
      audit_entry: {
        route: "reader",
        artifact_count: 2,
        tool_call_count: 1,
        degradation_count: 0,
        audit_refs: [privateArtifact],
      },
      locator: privateLocator,
      content_sha256: "b".repeat(64),
      raw: "private raw content",
    } as unknown as ReaderResponseDTO;
    mockedUseReader.mockReturnValue({ reader: wireReader, loading: false, error: null });

    const { container } = render(<ReaderSurface runId="run-reader-privacy" />);
    const initialDom = container.textContent ?? "";

    expect(initialDom).not.toContain(privateArtifact);
    expect(initialDom).not.toContain(privateLocator);
    expect(initialDom).not.toContain("private raw content");
    expect(initialDom).not.toContain("content_sha256");
    expect(initialDom).not.toContain("audit_refs");
  });
});
