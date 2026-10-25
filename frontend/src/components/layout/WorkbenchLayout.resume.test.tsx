import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getRun, getRunView, listRecentRuns, resumeRun } from "../../api/client";
import { openRunStream } from "../../api/eventSource";
import { WorkbenchProvider, useWorkbenchStore } from "../../state/WorkbenchStore";
import { runSnapshot, runView } from "../../test/runFixtures";
import { WorkbenchLayout } from "./WorkbenchLayout";
vi.mock("../../api/client", () => ({ getRun: vi.fn(), getRunView: vi.fn(), listRecentRuns: vi.fn(), resumeRun: vi.fn() }));
vi.mock("../../api/eventSource", () => ({ openRunStream: vi.fn(() => ({ close: vi.fn() })) }));
vi.mock("../../hooks/useReaderProcess", () => ({ useReaderProcess: () => ({ response: null, error: false, retry: vi.fn() }), useReaderAgent: () => ({ response: null, error: false, retry: vi.fn() }) }));
vi.mock("../../hooks/useCatalyst", () => ({ useCatalyst: () => ({ state: null, loading: false, error: null, kase: null, stageStatus: null, stageCounts: null }) }));
vi.mock("../../hooks/useResearchRecord", () => ({ useResearchRecord: () => ({ response: null, loading: false, error: false, retry: vi.fn() }) }));
vi.mock("../controls/Controls", () => ({ Controls: () => null }));
vi.mock("../reader/ReaderSurface", () => ({ ReaderSurface: () => null }));
vi.mock("../reader/LegacyReader", () => ({ LegacyReader: () => null }));
vi.mock("../reader/AuditCenter", () => ({ AuditCenter: () => null }));
vi.mock("../inspector/Inspector", () => ({ Inspector: () => null }));
vi.mock("../status/SwarmStatusCard", () => ({ SwarmStatusCard: () => null }));
vi.mock("../workflow/WorkflowMap", () => ({ WorkflowMap: () => null }));
vi.mock("./RunDisclosure", () => ({ RunDisclosure: () => null }));
function Probe() {
  const store = useWorkbenchStore();
  return <><button onClick={() => store.selectRun("layout_resume")}>选择中断记录</button><output data-testid="run-status">{store.stream.state?.meta.status}</output></>;
}

describe("WorkbenchLayout resume integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listRecentRuns).mockResolvedValue({ schema_version: 1, items: [], next_cursor: null });
    vi.mocked(getRun).mockResolvedValue(runSnapshot("layout_resume", "interrupted"));
    const interrupted = runView("layout_resume"); interrupted.view.run.research_profile = "evidence_v1";
    vi.mocked(getRunView).mockResolvedValue(interrupted);
    vi.mocked(resumeRun).mockResolvedValue(runSnapshot("layout_resume"));
  });
  it("the resume button reconnects and replaces the interrupted same-ID projection", async () => {
    render(<WorkbenchProvider><Probe /><WorkbenchLayout /></WorkbenchProvider>);
    fireEvent.click(screen.getByRole("button", { name: "选择中断记录" }));
    await screen.findByRole("button", { name: "恢复研究" });
    await act(async () => vi.mocked(openRunStream).mock.calls.at(-1)![2].onClose?.());
    await waitFor(() => expect(getRun).toHaveBeenCalledTimes(2));
    const updated = runView("layout_resume"); updated.terminal = false; updated.view.run.status = "running"; updated.view.run.research_profile = "evidence_v1";
    vi.mocked(getRun).mockResolvedValue(runSnapshot("layout_resume"));
    vi.mocked(getRunView).mockResolvedValue(updated);
    fireEvent.click(screen.getByRole("button", { name: "恢复研究" }));
    await waitFor(() => expect(screen.getByTestId("run-status")).toHaveTextContent("running"));
    expect(openRunStream).toHaveBeenCalledTimes(2);
    expect(resumeRun).toHaveBeenCalledWith("layout_resume");
    expect(screen.queryByRole("button", { name: "恢复研究" })).not.toBeInTheDocument();
  });
});
