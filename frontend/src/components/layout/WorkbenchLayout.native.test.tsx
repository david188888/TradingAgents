import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import savedRecord from "../../../../shared_fixtures/research-record.json";
import type { ResearchMode, ResearchRecordResponseDTO } from "../../api/contracts";
import { useCatalyst } from "../../hooks/useCatalyst";
import { useResearchRecord } from "../../hooks/useResearchRecord";
import { useRunHistory } from "../../hooks/useRunHistory";
import { createInitialState } from "../../state/runReducer";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { WorkbenchLayout } from "./WorkbenchLayout";

vi.mock("../../hooks/useRunHistory", () => ({ useRunHistory: vi.fn() }));
vi.mock("../../hooks/useCatalyst", () => ({ useCatalyst: vi.fn() }));
vi.mock("../../hooks/useResearchRecord", () => ({ useResearchRecord: vi.fn() }));
vi.mock("../../state/WorkbenchStore", () => ({ useWorkbenchStore: vi.fn() }));
vi.mock("../controls/Controls", () => ({ Controls: () => <div data-testid="existing-controls" /> }));
vi.mock("../history/RunHistory", () => ({ RunHistory: () => null }));
vi.mock("../inspector/Inspector", () => ({ Inspector: () => null }));
vi.mock("../reader/ReaderSurface", () => ({ ReaderSurface: () => <div data-testid="classic-reader" /> }));
vi.mock("../reader/LegacyReader", () => ({ LegacyReader: () => <div data-testid="legacy-reader" /> }));
vi.mock("../reader/CatalystCasePage", () => ({ CatalystCasePage: () => <div data-testid="catalyst-reader" /> }));
vi.mock("../reader/AuditCenter", () => ({ AuditCenter: ({ open }: { open: boolean }) => open ? <div data-testid="native-audit" /> : null }));

const RUN_ID = "run-record";
const stored = savedRecord as ResearchRecordResponseDTO;
if (stored.state !== "ready") throw new Error("invalid fixture");
const baseRecord = stored.record;

function nativeRecord(mode: ResearchMode): ResearchRecordResponseDTO {
  const dimensions = mode === "catalyst_research" ? ["operating_quality", "catalyst_delivery", "market_context"] as const :
    mode === "holding_review" ? ["holding_thesis", "operating_quality", "valuation", "market_context"] as const :
      ["operating_quality", "valuation", "market_context"] as const;
  return { state: "ready", schema_version: 1, run_id: RUN_ID, record: { ...baseRecord, mode, assessment: {
    schema_version: "research-assessment-v1", input_snapshot_id: baseRecord.snapshots[0].snapshot_id,
    research_question: "哪些经营事实值得继续核查？", judgement: "经营事实可复核，持续性仍待核查。",
    dimensions: dimensions.map((dimension) => ({ dimension, status: "unresolved", judgement: "资料不足", claim_ids: [], challenge_ids: [], limitations: ["覆盖不足"] })),
    key_claim_ids: ["f1"], primary_challenge_id: "c1", next_check: "核对收入分项和利润率。",
    challenge_assessments: [{ challenge_id: "c1", outcome: "unresolved", rationale: "条件核查不能关闭经济挑战" }],
    completeness: "partial", quality: "LOW_CONFIDENCE", forward_window_calendar_days: mode === "catalyst_research" ? 84 : null,
    limitations: [],
  } } };
}

function install(status = "completed", profileInView = true): void {
  const state = createInitialState();
  state.meta = { ...state.meta, run_id: RUN_ID, ticker: "600519.SS", research_profile: "evidence_v1", status: status as typeof state.meta.status };
  state.roles["native.evidence"] = { actor_id: "native.evidence", node_id: "evidence", team_id: "native", status: "completed" };
  vi.mocked(useWorkbenchStore).mockReturnValue({ run_id: RUN_ID, selectRun: vi.fn(), stream: { state, status: "closed", error: null },
    view: { loading: false, error: null, view: { terminal: true, view: { run: { run_id: RUN_ID, ticker: "600519.SS", status,
      ...(profileInView ? { research_profile: "evidence_v1" } : {}) }, brief: { value: { executive_summary: { text: "旧流程摘要不得作为原生结论" } } } } } },
  } as unknown as ReturnType<typeof useWorkbenchStore>);
}

describe("evidence_v1 owns its single native Reader", () => {
  beforeEach(() => {
    vi.mocked(useRunHistory).mockReturnValue({ runs: [], loading: false, error: null, refresh: vi.fn(), removeRun: vi.fn(), clearAll: vi.fn() });
    // An old contract read cannot override the producer profile.
    vi.mocked(useCatalyst).mockReturnValue({ state: { state: "ready" }, loading: false, error: null, kase: null,
      screen: null, stageStatus: null, stageDurations: null, stageCounts: null, uncommittedCandidates: 0 } as unknown as ReturnType<typeof useCatalyst>);
    vi.mocked(useResearchRecord).mockReturnValue({ response: nativeRecord("company_research"), loading: false, error: false });
    install();
  });

  it.each(["company_research", "catalyst_research", "holding_review"] as const)("renders only the native brief and quantitative background for %s", (mode) => {
    vi.mocked(useResearchRecord).mockReturnValue({ response: nativeRecord(mode), loading: false, error: false });
    const { container } = render(<WorkbenchLayout />);
    expect(screen.getByText("经营事实可复核，持续性仍待核查。")).toBeVisible();
    expect(screen.getByText("1.2%")).toBeVisible();
    expect(container.querySelectorAll("[data-main-summary]")).toHaveLength(1);
    expect(container.querySelector("[data-main-summary]")).toHaveAttribute("data-main-summary", "native_research");
    for (const id of ["classic-reader", "legacy-reader", "catalyst-reader"]) expect(screen.queryByTestId(id)).toBeNull();
    expect(container.textContent).not.toContain("旧流程摘要不得作为原生结论");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(vi.mocked(useCatalyst).mock.calls.at(-1)?.[0]).toBeNull();
  });

  it("keeps missing publication unavailable instead of falling back to a case summary", () => {
    vi.mocked(useResearchRecord).mockReturnValue({ response: { state: "unavailable", schema_version: 1, run_id: RUN_ID, reason_code: "not_published" }, loading: false, error: false });
    render(<WorkbenchLayout />);
    expect(screen.getByText("该运行未保存新版证据与计算记录。")).toBeVisible();
    expect(screen.queryByTestId("legacy-reader")).toBeNull();
    expect(screen.queryByTestId("catalyst-reader")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "打开审计中心" }));
    expect(screen.getByTestId("native-audit")).toBeInTheDocument();
  });

  it("routes from the projection profile even before the SSE snapshot arrives", () => {
    const current = vi.mocked(useWorkbenchStore).mock.results.at(-1)?.value;
    vi.mocked(useWorkbenchStore).mockReturnValue({ ...current, stream: { state: null, status: "connecting", error: null } });
    render(<WorkbenchLayout />);
    expect(screen.getByRole("region", { name: "研究简报" })).toBeInTheDocument();
    expect(screen.queryByTestId("legacy-reader")).toBeNull();
  });

  it("routes from same-run snapshot identity on an older run-view projection", () => {
    install("completed", false);
    render(<WorkbenchLayout />);
    expect(screen.getByRole("region", { name: "研究简报" })).toBeInTheDocument();
  });

  it("shows generic native stages while running without final or classic role claims", () => {
    install("running");
    vi.mocked(useResearchRecord).mockReturnValue({ response: null, loading: false, error: false });
    render(<WorkbenchLayout />);
    expect(screen.getByText("正在整理研究证据")).toBeVisible();
    expect(screen.getByText("证据冻结 · 已完成")).toBeVisible();
    expect(screen.queryByText("多方研究员")).toBeNull();
    expect(screen.queryByRole("region", { name: "研究简报" })).toBeNull();
    expect(vi.mocked(useResearchRecord).mock.calls.at(-1)?.[0]).toBeNull();
  });

  it("never shows an adapted or assessment-free record as a native completed judgement", () => {
    vi.mocked(useResearchRecord).mockReturnValue({ response: stored, loading: false, error: false });
    render(<WorkbenchLayout />);
    expect(screen.getByText(/未包含原生研究判断/)).toBeVisible();
    expect(screen.queryByRole("region", { name: "研究简报" })).toBeNull();
  });
});
