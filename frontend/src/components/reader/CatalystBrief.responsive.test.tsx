/**
 * T32 — the first screen is readable without opening a detail, at every
 * required width.
 *
 * Design 4.6 requires the seven core rows to be readable at 1440x900 and
 * 1280x800 *without opening a detail*, and to keep a single column with no
 * horizontal scroll at 390x844 and at 200% zoom (functionally a 640 CSS-pixel
 * viewport). jsdom does not lay out a page or honour a viewport size, so a
 * pixel measurement here would be theatre: it would pass regardless of the
 * real CSS. What jsdom *can* verify, and what actually determines whether a
 * narrow viewport can show the rows without scrolling sideways, is structural:
 *
 *   - every row is mounted at the same time, none behind a disclosure widget
 *     that only "readable at 1440" would let slip in (this file); and
 *   - the stylesheet that ships to the browser has no rule that would force a
 *     column wider than the viewport, and uses the wrapping/shrink rules the
 *     component's own comments say it depends on (`catalyst.responsive.test.ts`,
 *     next to `catalyst.css`).
 *
 * Together these are the structural equivalent of "the reader scrolls down,
 * never sideways, and never clicks to reveal a row" — the property design 4.6
 * is actually protecting. Fixture wiring below mirrors `CatalystBrief.test.tsx`
 * exactly (same `toBrief`/`screenOf` shape) so this file states nothing about
 * the wire that the T28 tests do not already state.
 */
import { render, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import budgetFixture from "../../test/fixtures/catalyst-brief-budget.json";
import catalystMinimalComplete from "../../../../shared_fixtures/catalyst/catalyst_minimal_complete.json";
import type {
  CatalystBriefDTO,
  CatalystReadState,
  CatalystResearchPriority,
} from "../../api/contracts";
import {
  buildCatalystFirstScreen,
  catalystScreenState,
  parseCatalystCase,
} from "../../domain/catalystWorkbench";
import { CatalystBrief } from "./CatalystBrief";

interface BriefLineBody {
  text: string;
  event_ids?: string[];
  finding_ids?: string[];
  challenge_ids?: string[];
}

function toBrief(body: {
  kind: "ordinary" | "safety_overflow";
  judgement: string;
  priority: CatalystResearchPriority;
  primary_catalyst_event_id: string | null;
  primary_catalyst: BriefLineBody | null;
  key_evidence: BriefLineBody[];
  key_question: BriefLineBody;
  next_check: BriefLineBody;
  critical_limitations: BriefLineBody[];
  overflow_reason?: string;
}): CatalystBriefDTO {
  const line = (item: BriefLineBody) => ({
    text: item.text,
    event_ids: item.event_ids ?? [],
    finding_ids: item.finding_ids ?? [],
    challenge_ids: item.challenge_ids ?? [],
  });
  return {
    kind: body.kind,
    judgement: body.judgement,
    priority: body.priority,
    primary_catalyst_event_id: body.primary_catalyst_event_id,
    primary_catalyst: body.primary_catalyst === null ? null : line(body.primary_catalyst),
    key_evidence: body.key_evidence.map(line),
    key_question: line(body.key_question),
    next_check: line(body.next_check),
    critical_limitations: body.critical_limitations.map(line),
    overflow_reason: body.overflow_reason ?? null,
  };
}

const budgetCases = (
  budgetFixture as {
    cases: Array<{ name: string; body: Parameters<typeof toBrief>[0] }>;
  }
).cases;

const readyFixture = catalystMinimalComplete as unknown as CatalystReadState;
const RUN_ID = "run_responsive";

function screenOf(brief: CatalystBriefDTO) {
  const overflowing = brief.kind === "safety_overflow";
  const state = {
    ...(readyFixture as object),
    priority: brief.priority,
    completeness: overflowing ? "partial" : "complete",
    quality: overflowing ? "LOW_CONFIDENCE" : "PASS",
  } as unknown as CatalystReadState;
  return {
    screen: buildCatalystFirstScreen(brief, parseCatalystCase(catalystMinimalComplete.case)),
    state: catalystScreenState({
      run_status: "completed",
      state,
      completeness: overflowing ? "partial" : "complete",
      quality: overflowing ? "LOW_CONFIDENCE" : "PASS",
      profile: "catalyst_v1",
      error: null,
    }),
  };
}

function renderBrief(brief: CatalystBriefDTO, onOpenEvidence = vi.fn()) {
  const { screen: built, state } = screenOf(brief);
  return render(
    <CatalystBrief
      runId={RUN_ID}
      screen={built}
      state={state}
      asOf="2026-09-29"
      onOpenEvidence={onOpenEvidence}
    />,
  );
}

/** No row anywhere on the page sits behind a disclosure widget. */
function expectNoDisclosureWidgets(container: HTMLElement): void {
  expect(container.querySelector("details")).toBeNull();
  expect(container.querySelector("summary")).toBeNull();
  expect(container.querySelector("[aria-expanded]")).toBeNull();
  expect(container.querySelectorAll("[hidden]")).toHaveLength(0);
  expect(container.querySelectorAll('[aria-hidden="true"]')).toHaveLength(0);
}

describe("T32 — all seven rows are simultaneously readable, not gated by a detail", () => {
  it("mounts all seven rows with no hidden/collapsed wrapper on the ordinary path", () => {
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    const rows = container.querySelectorAll(".catalyst-row");
    expect(rows).toHaveLength(7);
    rows.forEach((row) => {
      expect(row.hasAttribute("hidden")).toBe(false);
      expect(row.getAttribute("aria-hidden")).toBeNull();
      expect(row.closest("details")).toBeNull();
    });
    expectNoDisclosureWidgets(container);
  });

  it("mounts all seven rows with no hidden/collapsed wrapper on the safety-overflow path too", () => {
    // The overflow path is the one design 4.3 is strictest about: it is
    // exactly the case where a lazy implementation would reach for a
    // "show more" collapse to fit a long limitation list into the layout.
    const brief = toBrief(budgetCases.find((c) => c.name === "safety_overflow")!.body);
    const { container } = renderBrief(brief);
    const rows = container.querySelectorAll(".catalyst-row");
    expect(rows).toHaveLength(7);
    rows.forEach((row) => {
      expect(row.hasAttribute("hidden")).toBe(false);
      expect(row.getAttribute("aria-hidden")).toBeNull();
    });
    expectNoDisclosureWidgets(container);
  });

  it("uses <section>/<h3> for every row, not an accordion or tab primitive", () => {
    // A reader at 1280x800 reads top to bottom; an accordion or tablist would
    // satisfy "readable without opening a detail" only for whichever panel is
    // already open. Every row is a plain, always-rendered section.
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    expect(container.querySelectorAll('[role="tab"]')).toHaveLength(0);
    expect(container.querySelectorAll('[role="tabpanel"]')).toHaveLength(0);
    const rows = Array.from(container.querySelectorAll(".catalyst-row"));
    expect(rows.every((row) => row.tagName === "SECTION")).toBe(true);
  });

  it("keeps the limitations list reachable inside its scroll region rather than counted away", () => {
    const brief = toBrief(budgetCases.find((c) => c.name === "safety_overflow")!.body);
    const { container } = renderBrief(brief);
    const region = within(container).getByRole("region", { name: "影响判断的限制（完整列表）" });
    // A scroll box (bounded height, `overflow-y: auto` in the stylesheet) is
    // not a disclosure widget: everything inside it is already in the DOM and
    // reachable by keyboard (`tabIndex=0`), just as at any other width.
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region.hasAttribute("hidden")).toBe(false);
  });
});

describe("T32 — the main container is a single column, not a width-gated grid", () => {
  it("has no inline width/style on the brief or its rows for JS to reflow at a breakpoint", () => {
    // A structural stand-in for "no JS-driven layout switch by viewport
    // width": the whole first screen is styled by the stylesheet's media
    // queries (asserted in catalyst.responsive.test.ts), never by an inline
    // style or a width computed in the component.
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    const root = container.querySelector(".catalyst-brief") as HTMLElement;
    expect(root.getAttribute("style")).toBeNull();
    container.querySelectorAll(".catalyst-row").forEach((row) => {
      expect((row as HTMLElement).getAttribute("style")).toBeNull();
    });
  });
});
