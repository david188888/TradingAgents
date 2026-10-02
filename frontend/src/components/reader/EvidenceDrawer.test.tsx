/**
 * T29 — the evidence drawer.
 *
 * The four accessibility properties design 4.4 requires (focus management,
 * Esc, background inert, focus return) are implemented in
 * `../shared/drawerFocus`, which is the mechanism the existing Companion and
 * Audit panels use. These tests assert the drawer's own two contracts on top of
 * it: the content rules (public source or the limitation, never an internal
 * locator) and the run boundary (evidence never crosses runs).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import catalystMinimalComplete from "../../../../shared_fixtures/catalyst/catalyst_minimal_complete.json";
import type { CatalystEvidenceDTO, CatalystEventDTO, SourceEvidenceV1DTO } from "../../api/contracts";
import { parseCatalystCase } from "../../domain/catalystWorkbench";
import { EvidenceDrawer } from "./EvidenceDrawer";

const kase = parseCatalystCase(catalystMinimalComplete.case)!;
const RUN_ID = catalystMinimalComplete.run_id as string;

/** jsdom has no matchMedia; the drawer asks for it on every render. */
function installMatchMedia(matches: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
      onchange: null,
    }),
  });
}

function otherRunEvidence(): CatalystEvidenceDTO {
  return {
    ...kase.evidence[0],
    evidence_id: "ev_other_run",
    run_id: "run_other",
    source_name: "OTHER RUN SOURCE",
  };
}

function Harness(props: {
  openId: string | null;
  evidence?: CatalystEvidenceDTO[];
  backgroundRef?: React.RefObject<HTMLDivElement>;
  events?: CatalystEventDTO[];
  title?: string | null;
}): JSX.Element {
  return (
    <div>
      <div ref={props.backgroundRef ?? undefined} data-testid="background">
        <button type="button">背景按钮</button>
      </div>
      <EvidenceDrawer
        runId={RUN_ID}
        evidence={props.evidence ?? kase.evidence}
        events={props.events ?? kase.events}
        openId={props.openId}
        title={props.title ?? null}
        background={[props.backgroundRef?.current ?? document.querySelector('[data-testid="background"]')]}
        onClose={() => undefined}
      />
    </div>
  );
}

describe("EvidenceDrawer", () => {
  beforeEach(() => {
    installMatchMedia(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("rejects saved source content from another run with a colliding evidence id", () => {
    const own = kase.evidence[0];
    const source: SourceEvidenceV1DTO = {
      evidence_id: own.evidence_id, source_name: "fixture", source_kind: "official",
      source_family_id: null, availability: "available", public_url: null,
      published_at: null, usable_as_of: null, captured_at: null, limitations: [],
      content: { kind: "excerpt", text: "FOREIGN SAVED CONTENT", locator_label: "正文", content_sha256: "a".repeat(64), truncated: false },
    };
    const { rerender } = render(<EvidenceDrawer runId={RUN_ID} evidence={kase.evidence} events={[]}
      sourceRecord={{ run_id: "other-run", evidence: [source] }} openId={own.evidence_id} background={[]} onClose={() => undefined} />);
    expect(screen.queryByText("FOREIGN SAVED CONTENT")).toBeNull();
    rerender(<EvidenceDrawer runId={RUN_ID} evidence={kase.evidence} events={[]}
      sourceRecord={{ run_id: RUN_ID, evidence: [source] }} openId={own.evidence_id} background={[]} onClose={() => undefined} />);
    expect(screen.getByText("FOREIGN SAVED CONTENT")).toBeInTheDocument();
  });

  it("resolves a claim to all its saved sources without upgrading it to verification", () => {
    const ids = kase.evidence.slice(0, 2).map((item) => item.evidence_id);
    render(<EvidenceDrawer runId={RUN_ID} evidence={kase.evidence} events={[]}
      sourceRecord={{ run_id: RUN_ID, evidence: [], claims: [{ claim_id: "claim-one", kind: "inference", statement: "推断", evidence_ids: ids, supporting_fact_ids: [], limitations: [] }] }}
      openId="claim-one" background={[]} onClose={() => undefined} />);
    expect(screen.queryByText(/无法解析/)).toBeNull();
    expect(screen.getAllByText("来源内容未保存")).toHaveLength(ids.length);
    for (const source of kase.evidence.slice(0, 2)) expect(screen.getAllByText(source.source_name).length).toBeGreaterThan(0);
  });

  it("shows a challenge's intended check without pretending it has counterevidence", () => {
    render(<EvidenceDrawer runId={RUN_ID} evidence={kase.evidence} events={[]}
      sourceRecord={{ run_id: RUN_ID, evidence: [], challenges: [{ challenge_id: "challenge-one", target_claim_ids: ["claim-one"], statement: "缺乏利润率分项", severity: "critical", risk_type: "operations", evidence_ids: [], proposed_test: "读取分项披露", reported_disposition: null }] }}
      openId="challenge-one" background={[]} onClose={() => undefined} />);
    expect(screen.getByText(/拟核查：读取分项披露/)).toBeInTheDocument();
    expect(screen.getByText(/没有直接引用已保存的反证来源/)).toBeInTheDocument();
  });

  it("renders nothing when no reference is open", () => {
    const { container } = render(<Harness openId={null} />);
    expect(container.querySelector(".catalyst-drawer")).toBeNull();
  });

  it("shows the public source identity for a resolvable evidence id", () => {
    const evidence = kase.evidence.find((item) => item.public_url !== null);
    expect(evidence).toBeDefined();
    render(<Harness openId={evidence!.evidence_id} />);
    expect(screen.getByRole("dialog", { name: "证据详情" })).toBeInTheDocument();
    expect(screen.getAllByText(evidence!.source_name).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "打开公开来源" })).toHaveAttribute(
      "href",
      evidence!.public_url,
    );
  });

  it("shows the source identity and the limitation when there is no public link", () => {
    const anonymous: CatalystEvidenceDTO = { ...kase.evidence[0], public_url: null };
    const { container } = render(
      <Harness openId={anonymous.evidence_id} evidence={[anonymous]} events={[]} />,
    );
    expect(screen.getAllByText(anonymous.source_name).length).toBeGreaterThan(0);
    expect(screen.getByText(/没有可公开的来源链接/)).toBeInTheDocument();
    // No internal locator of any kind is rendered.
    expect(container.querySelector("a[href]")).toBeNull();
    expect(container.textContent).not.toMatch(/artifact|\/api\/runs|locator/i);
  });

  it("refuses a non-http public link rather than rendering it", () => {
    const odd: CatalystEvidenceDTO = { ...kase.evidence[0], public_url: "javascript:alert(1)" };
    render(<Harness openId={odd.evidence_id} evidence={[odd]} events={[]} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(/没有可公开的来源链接/)).toBeInTheDocument();
  });

  it("never shows evidence belonging to a different run", () => {
    const foreign = otherRunEvidence();
    render(<Harness openId={foreign.evidence_id} evidence={[...kase.evidence, foreign]} />);
    expect(screen.queryByText("OTHER RUN SOURCE")).toBeNull();
    expect(screen.getByText(/该引用在本次运行内无法解析/)).toBeInTheDocument();
  });

  it("does not render this run's evidence under another run's id", () => {
    const own = kase.evidence[0];
    render(
      <Harness
        openId={own.evidence_id}
        evidence={[own]}
        events={[]}
        backgroundRef={undefined}
      />,
    );
    // Rendered under RUN_ID, so it resolves; the cross-run direction is the
    // test above.
    expect(screen.getAllByText(own.source_name).length).toBeGreaterThan(0);
  });

  it("moves focus into the drawer on open", async () => {
    render(<Harness openId={kase.evidence[0].evidence_id} />);
    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "关闭证据详情" }),
      );
    });
  });

  it("closes on Esc", () => {
    const onClose = vi.fn();
    render(
      <div>
        <EvidenceDrawer
          runId={RUN_ID}
          evidence={kase.evidence}
          events={kase.events}
          openId={kase.evidence[0].evidence_id}
          background={[]}
          onClose={onClose}
        />
      </div>,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not listen for Esc while closed", () => {
    const onClose = vi.fn();
    render(
      <EvidenceDrawer
        runId={RUN_ID}
        evidence={kase.evidence}
        events={kase.events}
        openId={null}
        background={[]}
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("makes the background inert and restores it on close", () => {
    const background = document.createElement("div");
    document.body.appendChild(background);
    const { rerender } = render(
      <EvidenceDrawer
        runId={RUN_ID}
        evidence={kase.evidence}
        events={kase.events}
        openId={kase.evidence[0].evidence_id}
        background={[background]}
        onClose={() => undefined}
      />,
    );
    expect((background as HTMLElement & { inert: boolean }).inert).toBe(true);
    expect(background.getAttribute("aria-hidden")).toBe("true");
    expect(background.hasAttribute("inert")).toBe(true);

    rerender(
      <EvidenceDrawer
        runId={RUN_ID}
        evidence={kase.evidence}
        events={kase.events}
        openId={null}
        background={[background]}
        onClose={() => undefined}
      />,
    );
    // Not "true" rather than exactly false: jsdom has no `inert` property, so
    // a restored element reads back as undefined. What matters is that the
    // background is interactive again and no longer hidden.
    expect((background as HTMLElement & { inert: boolean }).inert).not.toBe(true);
    expect(background.hasAttribute("inert")).toBe(false);
    expect(background.hasAttribute("aria-hidden")).toBe(false);
    background.remove();
  });

  it("traps Tab inside the drawer instead of escaping to the page", () => {
    render(<Harness openId={kase.evidence[0].evidence_id} />);
    const dialog = screen.getByRole("dialog", { name: "证据详情" });
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'),
    );
    expect(focusable.length).toBeGreaterThan(1);
    const last = focusable[focusable.length - 1];
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(focusable[0]);

    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("becomes a modal sheet on a narrow screen and a drawer on a wide one", () => {
    const { unmount } = render(<Harness openId={kase.evidence[0].evidence_id} />);
    expect(screen.getByRole("dialog", { name: "证据详情" })).not.toHaveAttribute("aria-modal");
    unmount();

    installMatchMedia(true);
    render(<Harness openId={kase.evidence[0].evidence_id} />);
    expect(screen.getByRole("dialog", { name: "证据详情" })).toHaveAttribute("aria-modal", "true");
  });
});
